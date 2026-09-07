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
            temperature=self._temperature,
        )
        choice = response.choices[0].message
        calls = getattr(choice, "tool_calls", None) or []
        if not calls:
            raise ModelSaidNothing(
                "the model answered without calling a Tool, which "
                "tool_choice='required' is supposed to prevent"
            )
        call = calls[0]
        usage = getattr(response, "usage", None)
        return Decision(
            tool=call.function.name,
            args=_as_arguments(call.function.arguments),
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
        )


class ModelSaidNothing(RuntimeError):
    """The one shape the loop has no branch for."""


def _as_message(entry: Mapping[str, Any]) -> Dict[str, Any]:
    """One working-context entry as something the API will accept.

    The loop's entries carry structured content — an Observation is a mapping,
    because `PLAN.md` §15.4 refuses to put a prose summary beside it. The API
    wants a string, so the mapping is serialised here and nowhere else: this
    is a transport detail, and the loop should not be shaped by it.

    `role` is narrowed to what the API knows. The loop uses `tool` for both
    Observations and refusals, but a real `tool` message has to answer a
    specific `tool_call_id` — which the loop does not carry, deliberately,
    since its Journal is the record and not the transcript. They go over as
    `user` content, which is what they are from the model's side: the world
    answering back.
    """
    content = entry.get("content", "")
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False, sort_keys=True)
    role = entry.get("role", "user")
    return {"role": "system" if role == "system" else "user", "content": content}


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
