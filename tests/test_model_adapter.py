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
    API_KEY_VARIABLE,
    MissingApiKey,
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


def a_response(tool="done", arguments="{}", prompt=800, completion=12, calls=True):
    function = type("Function", (), {"name": tool, "arguments": arguments})()
    call = type("Call", (), {"function": function})()
    message = type("Message", (), {"tool_calls": [call] if calls else []})()
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


# ---------------------------------------------------------------------------
# What goes out
# ---------------------------------------------------------------------------

def test_the_model_is_required_to_choose_a_tool():
    model, client = a_model()

    model.decide([], [{"type": "function", "function": {"name": "done"}}])

    assert client.chat.completions.calls[0]["tool_choice"] == "required"


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
        {"role": "tool", "content": {"result": {"ok": True}, "n": None}}
    )

    assert json.loads(message["content"]) == {"result": {"ok": True}, "n": None}


def test_a_string_content_is_left_alone():
    assert _as_message({"role": "system", "content": "remember this"})[
        "content"
    ] == "remember this"


def test_the_system_role_survives_and_everything_else_becomes_user():
    """The loop's `tool` role is not the API's `tool` role — that one has to
    answer a specific `tool_call_id`, which the loop deliberately does not
    carry. Sending it as such would be rejected by the API."""
    assert _as_message({"role": "system", "content": "x"})["role"] == "system"
    assert _as_message({"role": "tool", "content": "x"})["role"] == "user"
    assert _as_message({"role": "assistant", "content": "x"})["role"] == "user"


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


def test_the_configured_temperature_is_the_one_that_is_sent():
    """A temperature nobody sends is the `llm_temperature` defect §10 #4
    already made this project pay for once."""
    model, client = a_model()
    model._temperature = 0.25

    model.decide([], [])

    assert client.chat.completions.calls[0]["temperature"] == 0.25


def test_the_temperature_comes_from_settings_by_default():
    from misty_agent.config import settings

    model, client = a_model()

    model.decide([], [])

    assert client.chat.completions.calls[0]["temperature"] == settings.llm_temperature


def test_an_explicit_temperature_of_zero_is_honoured():
    """`temperature or settings...` would silently replace 0.0 with the
    default — and 0.0 is the value anyone reaching for reproducibility picks.
    """
    model, client = OpenAIModel(client=FakeClient(a_response()), temperature=0.0), None

    model.decide([], [])

    assert model._temperature == 0.0
