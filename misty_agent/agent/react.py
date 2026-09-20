"""One Episode: a trigger in, a few decisions, and back to idle.

This is the file that makes the word "agent" honest. Until now the only
callers of the control layer were tests and measurement harnesses; from here
the model chooses, one Turn at a time, and the Journal records what it chose.

## The two properties worth more than the features

**Every Episode provably returns to idle.** `PLAN.md` §4 calls that the
strongest property this system has, and ReAct is the easiest way to lose it —
a loop that ends when the model says so ends when the model says so. The Turn
cap is therefore not a safety net bolted on the side: the loop is a bounded
`for`, and running out of Turns is one of the three ways an Episode ends
rather than an error. There is no `while True` here and no `break` that
depends on the model being reasonable.

**The model may stop on the first Turn, and nothing here special-cases that.**
Whether a Tool ends the Episode is a property the registry declares
(`PLAN.md` §15.9); this loop reads it and never compares a name. Self-termination
is what makes a ReAct loop a ReAct loop, so hard-coding it would be
disqualifying.

## Where each record comes from

The Journal is the deliverable, not a log. Everything the loop learns is
written through it, and `tests/goldens/` is five Journals this loop has to be
able to produce. The original four predate the loop; the fifth pins the later
closure decision that runtime failure is a named ending.

Three shapes are decided here rather than in a Tool:

**A refusal produces no Observation.** The rejection reason *is* what the
model reads next Turn, so recording an Observation beside it would be the
same fact twice (`PLAN.md` §15.4) — and there is no Snapshot worth taking,
because nothing happened.

**`done` produces no Observation either.** An Observation is what the model
reads to decide the next Turn, and after `done` there is no next Turn.

**The Snapshot is attached by the loop, not assembled by each Tool.** It is
the same three facts for all nine, so putting it in the Tools would be nine
copies of one thing.

## The narrow model interface

`Model` is the only new seam this milestone adds. Messages and Tool schemas
in, one Tool choice out — which is what lets a test script the model's answers
without mocking anybody's SDK. The list of messages is **one Episode's working
context** and is discarded with it. It is deliberately not a cross-Episode
memory or profile.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence

from misty_agent.agent.evidence import TriggerEvidence
from misty_agent.agent.handoff import HandoffNotice
from misty_agent.agent.journal import (
    DecisionNoted,
    ExecutionFailed,
    EpisodeFinished,
    EpisodeStarted,
    HandoffRequested,
    Journal,
    ModelCalled,
    Observation,
    Snapshot,
    SkillsAvailable,
    TargetBound,
    TurnStarted,
    snapshot_facts,
)
from misty_agent.agent.layering import mentions_control_parameter
from misty_agent.agent.persona import PERSONA
from misty_agent.agent.stop import NEVER_STOPS, Stop
from misty_agent.agent.tools import (
    Dispatched,
    ToolContext,
    ToolRegistry,
    dispatch,
)

@dataclass(frozen=True)
class Decision:
    """What the model came back with.

    Always a Tool call: "say nothing and stop" is `done`, so there is no
    second shape to handle and no way for the model to answer in a way the
    loop has to interpret.
    """

    tool: str
    args: Mapping[str, Any]
    tokens_in: int
    tokens_out: int
    tool_call_id: str = ""
    note: str = ""


class Model(Protocol):
    """The narrow seam. Nothing here knows what an HTTP request is."""

    def decide(
        self,
        working_context: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> Decision: ...


class Perception(Protocol):
    """The three cheap facts, however they are actually obtained."""

    def snapshot(self) -> Snapshot: ...


@dataclass(frozen=True)
class EpisodeOutcome:
    """How it ended, and the two counts that are not the same thing."""

    outcome: str
    turns: int
    steps: int
    boundary_respected: bool = False


def run_episode(
    evidence: TriggerEvidence,
    *,
    model: Model,
    registry: ToolRegistry,
    ctx: ToolContext,
    journal: Journal,
    perception: Perception,
    stop: Stop = NEVER_STOPS,
    instructions: str = PERSONA,
    at_turn_boundary: Optional[Callable[[], Optional[HandoffNotice]]] = None,
) -> EpisodeOutcome:
    """Run one Episode to completion and return how it ended.

    `at_turn_boundary` may return a `HandoffNotice`: someone else's Explicit
    Request is queued. It is recorded and shown to the model once; the loop
    never ends the Episode for it, the model does, by calling `done`.

    `journal` arrives already built, on the same clock as `ctx.clock`: the
    latency this loop measures and the timestamps the Journal writes have to
    come from one clock or they describe two different runs.
    """
    boundary = at_turn_boundary or (lambda: None)
    config = ctx.config
    clock = ctx.clock
    journal.record(EpisodeStarted, trigger=evidence.source.value)
    if ctx.target is not None:
        journal.record(
            TargetBound,
            track_reference=ctx.target.reference,
            source=ctx.target.source.value,
            state=ctx.target.state.value,
        )

    # What the model is shown, and only this. Everything in the list belongs
    # to this Episode and dies with it.
    working_context: List[Dict[str, Any]] = []
    # Who it is, then what it knows, then what just happened. On by default:
    # an Episode whose model has not been told what it is is not a
    # configuration anybody wants, so it has to be asked for rather than
    # remembered — `PLAN.md` §15.34 is a list of things that were built and
    # then never wired up.
    if instructions:
        working_context.append({"role": "system", "content": instructions})
    try:
        if ctx.skills is not None:
            available = ctx.skills.available()
            journal.record(SkillsAvailable, skills=available)
            working_context.append({
                "role": "system",
                "content": "Available Skills (name and description only): "
                + json.dumps(available, ensure_ascii=False),
            })
    except Exception as error:
        _record_failure_and_halt(journal, ctx.robot, "skills", error)
        journal.record(EpisodeFinished, outcome="error", turns=0, steps=0)
        return EpisodeOutcome(outcome="error", turns=0, steps=0)
    working_context.append(dict(evidence.model_message()))

    turns = 0
    steps = 0
    # The cap is the loop bound, not a check inside it. `turn_limit` is
    # therefore what happens when the `for` runs out, which is why it needs no
    # branch of its own and cannot be forgotten.
    outcome = "turn_limit"
    boundary_respected = False

    def handoff(turn: int) -> None:
        notice = boundary()
        if notice is None:
            return
        journal.record(
            HandoffRequested,
            turn=turn,
            cue_id=notice.cue_id,
            cue_kind=notice.cue_kind,
        )
        working_context.append(notice.model_message())

    for turn in range(1, config.max_turns_per_episode + 1):
        turns = turn
        journal.record(TurnStarted, turn=turn)

        began = clock.monotonic()
        try:
            decision = model.decide(tuple(working_context), registry.schemas())
        except Exception as error:
            _record_failure_and_halt(journal, ctx.robot, "model", error)
            outcome = "error"
            break
        journal.record(
            ModelCalled,
            turn=turn,
            latency_ms=int(round((clock.monotonic() - began) * 1000)),
            tokens_in=decision.tokens_in,
            tokens_out=decision.tokens_out,
        )
        tool_call_id = decision.tool_call_id or f"turn-{turn}-tool"
        try:
            if decision.note.strip():
                journal.record(
                    DecisionNoted,
                    turn=turn,
                    tool_call_id=tool_call_id,
                    note=decision.note.strip(),
                )
        except Exception as error:
            _record_failure_and_halt(journal, ctx.robot, "model", error)
            outcome = "error"
            break
        working_context.append(_asked_for(decision, tool_call_id))

        # Checked here as well as at the end of the Turn, and the two are not
        # the same check. This one refuses to *begin* a physical action after
        # someone has asked for everything to stop; the one below ends the
        # Episode once the action already running has returned.
        if stop.requested():
            outcome = "aborted"
            break

        try:
            dispatched = dispatch(
                registry, decision.tool, decision.args, ctx, journal, turn=turn
            )
        except Exception as error:
            _record_failure_and_halt(journal, ctx.robot, "tool", error)
            outcome = "error"
            break
        steps += dispatched.steps
        if dispatched.ends_episode:
            # An ending Tool that did something physical still owes the
            # Journal an account of it: `respect_boundary` halts the base,
            # and whether that halt was accepted is behaviour, which the
            # Journal is the only record of. `done` returns nothing, so its
            # Journal — and every golden built on it — is unchanged.
            if dispatched.result:
                try:
                    snapshot = perception.snapshot()
                    if ctx.target is not None:
                        snapshot = replace(snapshot, target=ctx.target.as_facts())
                    journal.record(
                        Observation,
                        turn=turn,
                        result=dispatched.result,
                        snapshot=snapshot,
                    )
                except Exception as error:
                    _record_failure_and_halt(journal, ctx.robot, "perception", error)
                    outcome = "error"
                    break
            boundary()
            boundary_respected = dispatched.boundary_respected
            outcome = "done"
            break

        if not dispatched.accepted:
            # The reason is the Observation, in the sense that matters: it is
            # what the model reads next Turn. Recording one as well would be
            # the same fact in two records.
            working_context.append(
                _refused(dispatched, tool_call_id)
            )
            handoff(turn)
            continue

        try:
            snapshot = perception.snapshot()
            if ctx.target is not None:
                snapshot = replace(snapshot, target=ctx.target.as_facts())
        except Exception as error:
            _record_failure_and_halt(journal, ctx.robot, "perception", error)
            outcome = "error"
            break
        try:
            observation = journal.record(
                Observation,
                turn=turn,
                result=dispatched.result,
                snapshot=snapshot,
            )
        except Exception as error:
            _record_failure_and_halt(journal, ctx.robot, "tool", error)
            outcome = "error"
            break
        working_context.append(_observed(observation, tool_call_id))
        handoff(turn)

        # The stop may have arrived while the Tool was running. Python cannot
        # interrupt a call that has not returned, so the Tool finished and its
        # Observation is recorded — discarding it would lose something the
        # robot really did. What it must not do is claim the work succeeded:
        # `tests/goldens/README.md` records that decision, and the aborted
        # golden reports `timeout` rather than `arrived`.
        if stop.requested():
            outcome = "aborted"
            break

    journal.record(EpisodeFinished, outcome=outcome, turns=turns, steps=steps)
    return EpisodeOutcome(
        outcome=outcome,
        turns=turns,
        steps=steps,
        boundary_respected=boundary_respected,
    )


def _asked_for(decision: Decision, tool_call_id: str) -> Dict[str, Any]:
    return {
        "role": "assistant",
        "content": decision.note,
        "tool_calls": [
            {
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": decision.tool,
                    "arguments": dict(decision.args),
                },
            }
        ],
    }


def _refused(dispatched: Dispatched, tool_call_id: str) -> Dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": {"refused": dispatched.reason},
    }


def _observed(
    observation: Observation, tool_call_id: str
) -> Dict[str, Any]:
    """The Observation the model reads, as JSON and only as JSON.

    `PLAN.md` §15.4 turned down putting a prose summary beside it: the same
    fact written twice is two things that can disagree, and the one the model
    actually attends to would be the one nobody checked.
    """
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": {
            "result": dict(observation.result),
            "snapshot": snapshot_facts(observation.snapshot),
        },
    }


def _error_message(error: Exception) -> str:
    """Keep diagnostics useful without teaching the model drive vocabulary."""
    message = str(error)
    if mentions_control_parameter(message) is not None:
        return "details withheld by the control-layer boundary"
    return message


def _record_failure_and_halt(
    journal: Journal, robot: Any, phase: str, error: Exception
) -> None:
    """Record one collaborator failure and make leaving motion best-effort."""
    journal.record(
        ExecutionFailed,
        phase=phase,
        error_type=type(error).__name__,
        message=_error_message(error),
    )
    try:
        robot.halt()
    except Exception:
        pass
