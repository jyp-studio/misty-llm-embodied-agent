"""The real model, behind the same narrow interface the tests script.

`misty_agent/agent/react.py` defines `Model` as one method: messages and Tool
schemas in, one Tool choice out. Everything above this file is written against
that protocol, which is what lets the whole ReAct loop be tested without an
API key, a network, or anybody's SDK mocked.

This is the only file in the package that knows OpenAI exists.

## Why it always returns a Tool call

`tool_choice="required"`. The loop's `Decision` has no "the model said some
words" shape, and giving it one would mean a second path through every Turn
for an answer nobody acts on — "say nothing and stop" is already `done`.
Requiring a Tool keeps the loop's contract to one case.

## What it does not do

No retries, no repair of malformed arguments, no fallback model. A Tool call
the registry refuses becomes a `tool_rejected` record and the model gets
another Turn to do better — that is `dispatch`'s job and it is already tested
(`PLAN.md` §14.6). Adding a second place that fixes up model output would put
the same rule in two files.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Mapping, Optional, Sequence

from misty_agent.agent.journal import MAX_DECISION_NOTE_CHARS
from misty_agent.agent.react import Decision
from misty_agent.config import settings

#: The environment variable the OpenAI SDK reads, named here so the failure
#: message can say it rather than making someone go and find out.
API_KEY_VARIABLE = "OPENAI_API_KEY"

#: The other channel, and the reason it is a constant rather than a word in a
#: sentence: `README.md` and `.env.example` both promise this file works, and
#: `app.load_api_key` is what keeps that promise. A message naming the file as
#: prose would go stale the day the file is renamed, silently, in the one
#: paragraph a new reader depends on.
API_KEY_FILE = "OAI_CONFIG_LIST.json"


class MissingApiKey(RuntimeError):
    """Raised with instructions rather than a stack trace from inside a SDK."""

    def __init__(self) -> None:
        super().__init__(
            f"no {API_KEY_VARIABLE} in the environment, so there is nothing "
            f"to ask. Either run `export {API_KEY_VARIABLE}=sk-...` in this "
            f"shell, or put the key in {API_KEY_FILE} (copy "
            f"{API_KEY_FILE}.example) — an entry point reads that file and "
            f"exports it for you. "
            f"Not the project's .env file: that is read by `Settings` for "
            f"MISTY_-prefixed fields only and is never exported to the "
            f"environment, which is why .env.example says not to put a key "
            f"there. Everything except the live suite runs without one."
        )


def api_key_available() -> bool:
    return bool(os.environ.get(API_KEY_VARIABLE, "").strip())


class OpenAIModel:
    """One model call per Turn, and the token counts the Journal records."""

    def __init__(
        self,
        client: Optional[Any] = None,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> None:
        self._client = client
        self._model = model or settings.llm_model
        self._temperature = (
            settings.llm_temperature if temperature is None else temperature
        )

    def _connection(self) -> Any:
        if self._client is not None:
            return self._client
        if not api_key_available():
            raise MissingApiKey()
        from openai import OpenAI

        self._client = OpenAI()
        return self._client

    def decide(
        self,
        working_context: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> Decision:
        response = self._connection().chat.completions.create(
            model=self._model,
            messages=[_as_message(entry) for entry in working_context],
            tools=list(tools),
            tool_choice="required",
            parallel_tool_calls=False,
            temperature=self._temperature,
        )
        choice = response.choices[0].message
        calls = getattr(choice, "tool_calls", None) or []
        if not calls:
            raise ModelSaidNothing(
                "the model answered without calling a Tool, which "
                "tool_choice='required' is supposed to prevent"
            )
        if len(calls) != 1:
            raise ModelProtocolError(
                f"the provider returned {len(calls)} Tool calls for one Turn"
            )
        call = calls[0]
        call_id = getattr(call, "id", "") or ""
        if not call_id:
            raise ModelProtocolError("the provider Tool call has no identity")
        usage = getattr(response, "usage", None)
        note = str(getattr(choice, "content", "") or "").strip()
        if len(note) > MAX_DECISION_NOTE_CHARS:
            raise ModelProtocolError(
                f"Decision Note exceeds {MAX_DECISION_NOTE_CHARS} characters"
            )
        return Decision(
            tool=call.function.name,
            args=_as_arguments(call.function.arguments),
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            tool_call_id=call_id,
            note=note,
        )


class ModelSaidNothing(RuntimeError):
    """The one shape the loop has no branch for."""


class ModelProtocolError(RuntimeError):
    """The provider returned a shape that cannot represent one Turn."""


def _as_message(entry: Mapping[str, Any]) -> Dict[str, Any]:
    """Translate provider-neutral context without changing its protocol."""
    role = str(entry.get("role") or "")
    if role == "assistant":
        calls = []
        for call in entry.get("tool_calls", ()):
            function = call.get("function", {})
            arguments = function.get("arguments", {})
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments, ensure_ascii=False)
            calls.append(
                {
                    "id": call.get("id"),
                    "type": "function",
                    "function": {
                        "name": function.get("name"),
                        "arguments": arguments,
                    },
                }
            )
        return {
            "role": "assistant",
            "content": str(entry.get("content") or ""),
            "tool_calls": calls,
        }

    if role == "tool":
        call_id = str(entry.get("tool_call_id") or "")
        if not call_id:
            raise ModelProtocolError("a Tool result has no tool_call_id")
        content = entry.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, sort_keys=True)
        return {
            "role": "tool",
            "tool_call_id": call_id,
            "content": content,
        }

    if role not in ("system", "user"):
        raise ModelProtocolError(f"{role!r} is not a model message role")
    content = entry.get("content", "")
    if role == "user" and isinstance(content, (list, tuple)):
        parts = []
        for part in content:
            if part.get("type") == "text":
                text = part.get("text", "")
                if not isinstance(text, str):
                    text = json.dumps(text, ensure_ascii=False, sort_keys=True)
                parts.append({"type": "text", "text": text})
            elif part.get("type") == "image":
                media_type = part.get("media_type", "")
                data = part.get("data_base64", "")
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{data}"
                        },
                    }
                )
            else:
                raise ModelProtocolError(
                    f"unknown model content part {part.get('type')!r}"
                )
        return {"role": "user", "content": parts}
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False, sort_keys=True)
    return {"role": role, "content": content}


def _as_arguments(raw: Any) -> Dict[str, Any]:
    """Whatever came back, as a mapping — without repairing it.

    Malformed JSON becomes an empty mapping rather than an exception, so the
    call reaches `dispatch` and is refused there with a reason the model can
    read on its next Turn. Raising here would end the Episode over something
    the loop already has a designed answer for.
    """
    if isinstance(raw, Mapping):
        return dict(raw)
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
