"""The one file in the package that knows OpenAI exists, tested without it.

`OpenAIModel` is the only production code the live suite exercises and the
offline suite otherwise would not — which would make it the least-tested thing
in the project while also being the thing standing between a real model and
the ReAct loop. The SDK is not mocked: the adapter takes a client, so a stand
-in object is all it needs.
"""

from __future__ import annotations

import json

import pytest

from misty_agent.agent.model import (
    API_KEY_FILE,
    API_KEY_VARIABLE,
    MissingApiKey,
    ModelProtocolError,
    ModelSaidNothing,
    OpenAIModel,
    _as_arguments,
    _as_message,
    api_key_available,
)


class FakeCompletions:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class FakeClient:
    def __init__(self, response):
        self.chat = type("Chat", (), {"completions": FakeCompletions(response)})()


def a_response(
    tool="done",
    arguments="{}",
    prompt=800,
    completion=12,
    calls=True,
    call_id="call-provider-1",
    note="Finish this bounded interaction.",
):
    function = type("Function", (), {"name": tool, "arguments": arguments})()
    call = type("Call", (), {"id": call_id, "function": function})()
    message = type(
        "Message", (), {"content": note, "tool_calls": [call] if calls else []}
    )()
    choice = type("Choice", (), {"message": message})()
    usage = type("Usage", (), {"prompt_tokens": prompt, "completion_tokens": completion})()
    return type("Response", (), {"choices": [choice], "usage": usage})()


def a_model(response=None):
    client = FakeClient(response or a_response())
    return OpenAIModel(client=client), client


# ---------------------------------------------------------------------------
# What comes back
# ---------------------------------------------------------------------------

def test_a_tool_call_becomes_a_decision():
    model, _ = a_model(a_response(tool="speak", arguments='{"text": "hello"}'))

    decision = model.decide([{"role": "user", "content": {"trigger": "speech"}}], [])

    assert decision.tool == "speak"
    assert decision.args == {"text": "hello"}
    assert decision.tool_call_id == "call-provider-1"
    assert decision.note == "Finish this bounded interaction."


def test_the_token_counts_come_from_the_response():
    """`model_called` records them, and four goldens carry them — a decision
    that invented its own would make the Journal a work of fiction."""
    model, _ = a_model(a_response(prompt=1234, completion=56))

    decision = model.decide([], [])

    assert decision.tokens_in == 1234
    assert decision.tokens_out == 56


def test_a_response_with_no_tool_call_is_an_error_not_a_guess():
    """`tool_choice='required'` is supposed to prevent it. If it happens
    anyway, the loop has no branch for it and inventing one here would be a
    second place that decides what the robot does."""
    model, _ = a_model(a_response(calls=False))

    with pytest.raises(ModelSaidNothing):
        model.decide([], [])


def test_multiple_tool_calls_are_rejected_instead_of_silently_truncated():
    response = a_response()
    first = response.choices[0].message.tool_calls[0]
    response.choices[0].message.tool_calls = [first, first]
    model, _ = a_model(response)

    with pytest.raises(ModelProtocolError, match="2 Tool calls"):
        model.decide([], [])


@pytest.mark.parametrize(
    "written",
    [
        "Decision Note: I will wave.",
        "decision note - I will wave.",
        "**Decision Note:** I will wave.",
        "Decision Note：I will wave.",
    ],
)
def test_a_note_the_model_titled_itself_is_not_labelled_twice(written):
    """The Journal already calls this a decision note. A model that heads its
    own text the same way made the CLI print "decision note, Decision Note:
    ..." — seen on gpt-5.6-luna's first live run."""
    model, _ = a_model(a_response(note=written))

    assert model.decide([], []).note == "I will wave."


def test_a_note_that_merely_mentions_decisions_is_kept_whole():
    model, _ = a_model(a_response(note="My decision: note the time, then wave."))

    assert model.decide([], []).note == "My decision: note the time, then wave."


def test_a_decision_note_cannot_expand_into_a_reasoning_transcript():
    from misty_agent.agent.journal import MAX_DECISION_NOTE_CHARS

    model, _ = a_model(a_response(note="x" * (MAX_DECISION_NOTE_CHARS + 1)))

    with pytest.raises(ModelProtocolError, match="Decision Note"):
        model.decide([], [])


# ---------------------------------------------------------------------------
# What goes out
# ---------------------------------------------------------------------------

def test_the_model_is_required_to_choose_a_tool():
    model, client = a_model()

    model.decide([], [{"type": "function", "function": {"name": "done"}}])

    assert client.chat.completions.calls[0]["tool_choice"] == "required"


def test_parallel_tool_calls_are_disabled_at_the_provider_boundary():
    model, client = a_model()

    model.decide([], [])

    assert client.chat.completions.calls[0]["parallel_tool_calls"] is False


def test_the_tool_schemas_are_passed_through_untouched():
    """They are generated from the argument types (`PLAN.md` §15.2). An
    adapter that rewrote them would be a second schema."""
    schemas = [{"type": "function", "function": {"name": "done", "parameters": {}}}]
    model, client = a_model()

    model.decide([], schemas)

    assert client.chat.completions.calls[0]["tools"] == schemas


def test_structured_content_is_serialised_rather_than_stringified():
    """The loop hands over mappings because `PLAN.md` §15.4 refuses a prose
    summary beside them. `str(dict)` would send Python's repr — single quotes
    and `None` — which is not JSON and not what the model was trained on.
    """
    message = _as_message(
        {
            "role": "tool",
            "tool_call_id": "call-one",
            "content": {"result": {"ok": True}, "n": None},
        }
    )

    assert json.loads(message["content"]) == {"result": {"ok": True}, "n": None}


def test_a_string_content_is_left_alone():
    assert _as_message({"role": "system", "content": "remember this"})[
        "content"
    ] == "remember this"


def test_native_assistant_and_tool_roles_keep_their_call_identity():
    assistant = _as_message(
        {
            "role": "assistant",
            "content": "Acknowledge the greeting.",
            "tool_calls": [
                {
                    "id": "call-one",
                    "type": "function",
                    "function": {
                        "name": "speak",
                        "arguments": {"text": "hello"},
                    },
                }
            ],
        }
    )
    tool_result = _as_message(
        {
            "role": "tool",
            "tool_call_id": "call-one",
            "content": {"result": {"ok": True}},
        }
    )

    assert _as_message({"role": "system", "content": "x"})["role"] == "system"
    assert assistant == {
        "role": "assistant",
        "content": "Acknowledge the greeting.",
        "tool_calls": [
            {
                "id": "call-one",
                "type": "function",
                "function": {
                    "name": "speak",
                    "arguments": '{"text": "hello"}',
                },
            }
        ],
    }
    assert tool_result == {
        "role": "tool",
        "tool_call_id": "call-one",
        "content": '{"result": {"ok": true}}',
    }


def test_provider_neutral_image_evidence_becomes_openai_image_content():
    message = _as_message(
        {
            "role": "user",
            "content": [
                {"type": "text", "text": {"face_present": True}},
                {
                    "type": "image",
                    "media_type": "image/png",
                    "data_base64": "cGljdHVyZQ==",
                },
            ],
        }
    )

    assert message == {
        "role": "user",
        "content": [
            {"type": "text", "text": '{"face_present": true}'},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64,cGljdHVyZQ=="},
            },
        ],
    }


# ---------------------------------------------------------------------------
# Malformed arguments reach `dispatch`, which already knows what to do
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", ["", "not json", "[1, 2]", "null", None])
def test_arguments_that_are_not_an_object_become_an_empty_one(raw):
    """Refused by `dispatch` with a reason the model reads next Turn, rather
    than raising here and ending the Episode over something the loop already
    has a designed answer for (`PLAN.md` §14.6)."""
    assert _as_arguments(raw) == {}


def test_well_formed_arguments_survive():
    """The negative control: returning `{}` always would satisfy the test
    above and silently drop every argument the model ever sent."""
    assert _as_arguments('{"pitch": 10}') == {"pitch": 10}


# ---------------------------------------------------------------------------
# No key
# ---------------------------------------------------------------------------

def test_the_missing_key_message_says_how_to_provide_one():
    """Not a stack trace from inside somebody's SDK — the person reading it is
    being told what to do about it.

    And told the thing that *works*. The first version said "put it in the
    project's .env file", which does not: `Settings` reads `.env` for
    `MISTY_`-prefixed fields and never exports anything to the environment,
    and `.env.example` says in so many words not to put a key there. This
    test asserted `".env" in message` and so locked the wrong advice in.
    """
    message = str(MissingApiKey())

    assert API_KEY_VARIABLE in message
    assert f"export {API_KEY_VARIABLE}=" in message
    assert "runs without one" in message


def test_the_missing_key_message_names_both_channels_that_work():
    """The mirror of the test below, and the defect that outlived it.

    That one keeps a channel which does *not* work out of the message. This
    one keeps a channel which does *in*: `README.md` and `.env.example` have
    both promised `OAI_CONFIG_LIST.json` since before the rewrite, and
    `app.load_api_key` is what keeps that promise — proven by
    `tests/test_app.py::test_a_key_from_the_file_is_put_where_the_sdk_will_look`.
    Until M8 #04 the message named only `export`, so the person most in need
    of the advice was told half of it.
    """
    message = str(MissingApiKey())

    assert f"export {API_KEY_VARIABLE}=" in message
    assert API_KEY_FILE in message


def test_the_missing_key_message_does_not_send_anyone_to_dot_env():
    """`.env.example`: "Do not put your OpenAI key here"."""
    message = str(MissingApiKey())

    assert "Not the project's .env" in message


def test_dot_env_really_does_not_supply_the_key(tmp_path, monkeypatch):
    """The claim the message makes, checked rather than asserted.

    If `Settings` ever did export to the environment, the message would be
    wrong again and nothing else here would notice.
    """
    monkeypatch.delenv(API_KEY_VARIABLE, raising=False)
    (tmp_path / ".env").write_text(f"{API_KEY_VARIABLE}=sk-not-a-real-key\n")
    monkeypatch.chdir(tmp_path)

    from misty_agent.config import Settings

    Settings()

    assert not api_key_available()


def test_no_key_is_needed_when_a_client_is_supplied(monkeypatch):
    """Every offline test in the project depends on this."""
    monkeypatch.delenv(API_KEY_VARIABLE, raising=False)
    model, _ = a_model()

    assert model.decide([], []).tool == "done"


def test_a_missing_key_is_noticed_before_the_network(monkeypatch):
    monkeypatch.delenv(API_KEY_VARIABLE, raising=False)

    with pytest.raises(MissingApiKey):
        OpenAIModel().decide([], [])


def test_a_blank_key_counts_as_missing(monkeypatch):
    monkeypatch.setenv(API_KEY_VARIABLE, "   ")

    assert not api_key_available()


# ---------------------------------------------------------------------------
# Settings that are declared must actually reach the API
# ---------------------------------------------------------------------------
#
# `PLAN.md` §10 #4: "宣告了卻沒接線比字面值更糟——它看起來可調，實際不可調."
# Both of these are `Settings` fields the adapter reads at construction, and
# both were untested until a mutation deleted them from the request and
# nothing went red.

def test_the_configured_model_is_the_one_that_is_asked():
    model, client = a_model()
    model._model = "gpt-4o-mini"

    model.decide([], [])

    assert client.chat.completions.calls[0]["model"] == "gpt-4o-mini"


def test_the_model_comes_from_settings_by_default():
    from misty_agent.config import settings

    model, client = a_model()

    model.decide([], [])

    assert client.chat.completions.calls[0]["model"] == settings.llm_model


def test_the_default_model_is_gpt_5_6_luna():
    from misty_agent.config import Settings

    assert Settings().llm_model == "gpt-5.6-luna"


def test_no_temperature_is_sent_unless_one_is_configured():
    """GPT-5-family reasoning models reject a custom temperature, so sending
    the old default of 0.5 would fail every Turn. Nothing is sent unless a
    temperature is configured on purpose."""
    model, client = a_model()

    model.decide([], [])

    assert "temperature" not in client.chat.completions.calls[0]


def test_a_configured_temperature_is_still_sent():
    """For a model that does accept one. A temperature nobody sends is the
    `llm_temperature` defect §10 #4 already made this project pay for once."""
    model, client = a_model()
    model._temperature = 0.25

    model.decide([], [])

    assert client.chat.completions.calls[0]["temperature"] == 0.25


def test_reasoning_effort_none_is_sent_by_default():
    """Chat Completions refuses function tools alongside any other reasoning
    effort for the GPT-5.6 family; `none` is the documented way to keep the
    tools on this endpoint."""
    model, client = a_model()

    model.decide([], [])

    assert client.chat.completions.calls[0]["reasoning_effort"] == "none"


def test_reasoning_effort_values_outside_the_documented_set_are_refused():
    import pytest
    from pydantic import ValidationError

    from misty_agent.config import Settings

    with pytest.raises(ValidationError):
        Settings(llm_reasoning_effort="extreme")
    assert Settings(llm_reasoning_effort="low").llm_reasoning_effort == "low"


def test_an_explicit_temperature_of_zero_is_honoured():
    """`temperature or settings...` would silently replace 0.0 with the
    default — and 0.0 is the value anyone reaching for reproducibility picks.
    """
    model, client = OpenAIModel(client=FakeClient(a_response()), temperature=0.0), None

    model.decide([], [])

    assert model._temperature == 0.0
