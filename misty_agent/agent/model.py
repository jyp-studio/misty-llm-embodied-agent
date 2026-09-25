"""The real model, behind the same narrow interface the tests script.

`misty_agent/agent/react.py` defines `Model` as one method: messages and Tool
schemas in, one Tool choice out. Everything above this file is written against
that protocol, which is what lets the whole ReAct loop be tested without an
API key, a network, or anybody's SDK mocked.

This is the only file in the package that knows OpenAI exists.

## Why the Responses API and not Chat Completions

Chat Completions refuses function tools alongside any reasoning at all for
the GPT-5.6 family — `reasoning_effort` must be `none`, which the provider
says in the 400 itself: *"To use function tools, use /v1/responses or set
reasoning_effort to 'none'."* A model doing no reasoning is not a detail: the
first recorded Demo runs had it load a Skill and then `listen` eleven times
at somebody who had said they were trapped, without answering them once.

So the request is a Responses call, `store=False` because what people say to
this robot is not something to leave on a provider's disk as a side effect,
and the whole working context goes up each Turn — the loop already holds it,
and nothing here depends on the provider remembering the last Turn.

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
import re
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


#: A heading the model sometimes writes in front of its note. The Journal
#: already labels the note, so keeping this printed it twice.
_OWN_LABEL = re.compile(r"^[*_\s]*decision\s+note[*_\s]*[:：\-–—][*_\s]*", re.IGNORECASE)


def _without_own_label(note: str) -> str:
    return _OWN_LABEL.sub("", note.strip(), count=1).strip()


class OpenAIModel:
    """One model call per Turn, and the token counts the Journal records."""

    def __init__(
        self,
        client: Optional[Any] = None,
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        reasoning_effort: Optional[str] = None,
    ) -> None:
        self._client = client
        self._model = model or settings.llm_model
        self._temperature = (
            settings.llm_temperature if temperature is None else temperature
        )
        self._reasoning_effort = (
            settings.llm_reasoning_effort
            if reasoning_effort is None
            else reasoning_effort
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
        # A temperature only when one is configured: reasoning models reject
        # a custom one, so the default is to send nothing. `none` is not an
        # effort the provider takes either — it is the parameter's absence.
        optional: Dict[str, Any] = {}
        if self._temperature is not None:
            optional["temperature"] = self._temperature
        if self._reasoning_effort != "none":
            optional["reasoning"] = {"effort": self._reasoning_effort}
            # Nothing is stored provider-side, so reasoning would be gone by
            # the next Turn unless it comes back sealed and goes up again.
            optional["include"] = ["reasoning.encrypted_content"]
        items: list = []
        for entry in working_context:
            items.extend(_as_input_items(entry))
        response = self._connection().responses.create(
            model=self._model,
            input=items,
            tools=[_as_tool(schema) for schema in tools],
            tool_choice="required",
            parallel_tool_calls=False,
            store=False,
            **optional,
        )
        output = list(getattr(response, "output", None) or [])
        calls = [item for item in output if _kind(item) == "function_call"]
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
        call_id = str(getattr(call, "call_id", "") or "")
        if not call_id:
            raise ModelProtocolError("the provider Tool call has no identity")
        usage = getattr(response, "usage", None)
        note = _without_own_label(_said_by(output))
        if len(note) > MAX_DECISION_NOTE_CHARS:
            raise ModelProtocolError(
                f"Decision Note exceeds {MAX_DECISION_NOTE_CHARS} characters"
            )
        return Decision(
            provider_items=_sealed_reasoning(output),
            tool=getattr(call, "name", ""),
            args=_as_arguments(getattr(call, "arguments", "")),
            tokens_in=getattr(usage, "input_tokens", 0) or 0,
            tokens_out=getattr(usage, "output_tokens", 0) or 0,
            tool_call_id=call_id,
            note=note,
        )


class ModelSaidNothing(RuntimeError):
    """The one shape the loop has no branch for."""


class ModelProtocolError(RuntimeError):
    """The provider returned a shape that cannot represent one Turn."""


def _kind(item: Any) -> str:
    """An output item's type, whether it arrived as an object or a mapping."""
    if isinstance(item, Mapping):
        return str(item.get("type") or "")
    return str(getattr(item, "type", "") or "")


def _said_by(output: Sequence[Any]) -> str:
    """The public text of the Turn: the Decision Note, and nothing else.

    Reasoning items are deliberately not read. The Journal is a public record
    (`PLAN.md` §4), and a summary of private reasoning copied into it is the
    thing the Decision Note exists instead of.
    """
    said = []
    for item in output:
        if _kind(item) != "message":
            continue
        for part in getattr(item, "content", None) or []:
            if _kind(part) == "output_text":
                said.append(str(getattr(part, "text", "") or ""))
    return " ".join(text for text in said if text).strip()


def _sealed_reasoning(output: Sequence[Any]) -> tuple:
    """This Turn's reasoning, exactly as much of it as can be handed back.

    Only the identity and the sealed blob: a summary is prose about the
    model's private reasoning, and nothing in this project keeps that. The
    field itself is still required on the way back — a reasoning item
    without it is a 400 — so it goes back empty, which is also what comes
    back when no summary was asked for.
    """
    carried = []
    for item in output:
        if _kind(item) != "reasoning":
            continue
        sealed = getattr(item, "encrypted_content", None)
        if not sealed:
            continue
        carried.append(
            {
                "type": "reasoning",
                "id": str(getattr(item, "id", "") or ""),
                "summary": [],
                "encrypted_content": str(sealed),
            }
        )
    return tuple(carried)


def _as_tool(schema: Mapping[str, Any]) -> Dict[str, Any]:
    """One registry schema in the shape this endpoint reads.

    The same three fields, one level flatter. Copied rather than edited: the
    schemas come from the argument types (`PLAN.md` §15.2), and an adapter
    that rewrote a description would be a second schema.
    """
    function = schema.get("function")
    if not isinstance(function, Mapping):
        raise ModelProtocolError("a Tool schema has no function")
    return {"type": "function", **{str(k): v for k, v in function.items()}}


def _as_input_items(entry: Mapping[str, Any]) -> list:
    """Translate provider-neutral context without changing its protocol.

    A list, because one entry is not always one item: an assistant Turn is
    what it said *and* the call it made, which this endpoint keeps apart.
    """
    role = str(entry.get("role") or "")
    if role == "assistant":
        # Its reasoning first, then what it said, then the call it made:
        # the order the provider reads a Turn in.
        items = [dict(item) for item in entry.get("provider_items", ())]
        said = str(entry.get("content") or "")
        if said:
            items.append({"role": "assistant", "content": said})
        for call in entry.get("tool_calls", ()):
            function = call.get("function", {})
            arguments = function.get("arguments", {})
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments, ensure_ascii=False)
            call_id = str(call.get("id") or "")
            if not call_id:
                raise ModelProtocolError("a Tool call has no identity")
            items.append(
                {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": function.get("name"),
                    "arguments": arguments,
                }
            )
        return items

    if role == "tool":
        call_id = str(entry.get("tool_call_id") or "")
        if not call_id:
            raise ModelProtocolError("a Tool result has no tool_call_id")
        content = entry.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, sort_keys=True)
        return [
            {
                "type": "function_call_output",
                "call_id": call_id,
                "output": content,
            }
        ]

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
                parts.append({"type": "input_text", "text": text})
            elif part.get("type") == "image":
                media_type = part.get("media_type", "")
                data = part.get("data_base64", "")
                parts.append(
                    {
                        "type": "input_image",
                        "image_url": f"data:{media_type};base64,{data}",
                    }
                )
            else:
                raise ModelProtocolError(
                    f"unknown model content part {part.get('type')!r}"
                )
        return [{"role": "user", "content": parts}]
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False, sort_keys=True)
    return [{"role": role, "content": content}]


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
