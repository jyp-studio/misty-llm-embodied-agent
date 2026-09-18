"""The live suite's assertions, checked without spending anything.

`tests/test_llm_live.py` asserts these against a real model. That suite costs
money and cannot run in CI, so if a check in it were vacuous nobody would find
out — it would pass on every run and prove nothing, which is exactly the
"prints things for a human to read" problem ticket 11 exists to end.

So each check is exercised twice here: once against a scripted Episode that
should satisfy it, and once against an Episode deliberately broken in the one
way that check exists to catch. Every one of them can fail, and this file is
what says so.
"""

from __future__ import annotations

import dataclasses

import pytest

from episode_invariants import (
    CHECKS,
    every_drive_came_from_approach,
    FORBIDDEN_IN_PROMPT,
    Episode,
    violations,
)
from misty_agent.agent.journal import (
    EpisodeFinished,
    ModelCalled,
    Observation,
    Snapshot,
    ToolCalled,
    ToolRejected,
    TurnStarted,
)
from misty_agent.agent.tools import build_registry
from misty_agent.config import Settings

import test_react as offline


def an_episode(scenario=offline.ends_after_several_turns, **overrides):
    """A real scripted Episode, wrapped for the invariant checks."""
    _, journal, model = scenario()
    fields = dict(
        records=list(journal.records),
        turn_cap=Settings().max_turns_per_episode,
        prompts=[context for context, _ in model.asked],
        tools=list(model.asked[0][1]) if model.asked else [],
        registry=build_registry(),
    )
    fields.update(overrides)
    return Episode(**fields)


# ---------------------------------------------------------------------------
# The Episodes the offline suite already produces satisfy every check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,scenario", offline.GOLDEN_EPISODES)
def test_a_scripted_episode_breaks_no_invariant(name, scenario):
    found = violations(an_episode(scenario))

    assert found == [], "\n".join(found)


def test_the_aborted_episode_breaks_no_invariant():
    """An abort is still a well-formed Episode — that is the whole claim of
    ticket 08, restated in the language the live suite uses."""
    _, journal, model, _, world = offline.is_aborted()

    found = violations(
        Episode(
            records=list(journal.records),
            turn_cap=Settings().max_turns_per_episode,
            prompts=[context for context, _ in model.asked],
            tools=list(model.asked[0][1]),
            registry=build_registry(),
            robot=world,
        )
    )

    assert found == [], "\n".join(found)


# ---------------------------------------------------------------------------
# ...and every check can fail
# ---------------------------------------------------------------------------

def without_the_ending(episode):
    return dataclasses.replace(episode, records=list(episode.records)[:-1])


def with_a_turn_past_the_cap(episode):
    """Enough contiguous Turns to run past the cap.

    Contiguous on purpose. Appending a lone `turn=99` also breaks the
    *numbering* clause, and then either clause could be the one noticing —
    which is how a mutation that loosened the cap comparison to `> cap + 1`
    survived: the numbering clause was quietly covering for it.
    """
    records = list(episode.records)
    ending = records[-1]
    started = [r for r in records if isinstance(r, TurnStarted)]
    extra = [
        TurnStarted(t=ending.t, episode_id=ending.episode_id, turn=turn)
        for turn in range(len(started) + 1, episode.turn_cap + 2)
    ]
    return dataclasses.replace(episode, records=records[:-1] + extra + [ending])


def with_a_velocity_in_the_prompt(episode):
    poisoned = [
        list(prompt) + [{"role": "user", "content": {"linearVelocity": 20}}]
        for prompt in episode.prompts
    ]
    return dataclasses.replace(episode, prompts=poisoned)


def with_an_out_of_range_call(episode):
    records = list(episode.records)
    index = next(i for i, r in enumerate(records) if isinstance(r, ToolCalled))
    records[index] = ToolCalled(
        t=records[index].t,
        episode_id=records[index].episode_id,
        turn=records[index].turn,
        tool="move_head",
        args={"pitch": 999},
    )
    return dataclasses.replace(episode, records=records)


class DroveOnItsOwn:
    """A robot that moved without the Episode reporting a Step.

    Shaped like the simulated adapter: what it drove is its `directions`.
    """

    directions = [1, 1, 1]

    @classmethod
    def with_drives(cls, count):
        stub = cls()
        stub.directions = [1] * count
        return stub


def with_a_drive_nobody_reported(episode):
    return dataclasses.replace(episode, robot=DroveOnItsOwn())


def with_a_record_that_cannot_be_written(episode):
    records = list(episode.records)
    records[-1] = dataclasses.replace(records[-1], turns=object())
    return dataclasses.replace(episode, records=records)


def with_a_refusal_that_also_observed(episode):
    records = list(episode.records)
    refused = next(r for r in records if isinstance(r, ToolRejected))
    ending = records.pop()
    records.append(
        Observation(
            t=refused.t,
            episode_id=refused.episode_id,
            turn=refused.turn,
            result={"ok": True},
            snapshot=Snapshot(distance_cm=60, face_present=True, new_speech=None),
        )
    )
    records.append(ending)
    return dataclasses.replace(episode, records=records)


def a_snapshot_that_round_trips_into_something_else(episode):
    """Same number of records, different content coming back.

    `to_jsonl` will happily write a plain mapping where a `Snapshot` belongs;
    `from_jsonl` rebuilds it as a `Snapshot`, so the two Journals are the same
    length and not the same thing. Without a case like this, a round-trip
    check that only compared lengths would look fine.
    """
    records = list(episode.records)
    index = next(i for i, r in enumerate(records) if isinstance(r, Observation))
    records[index] = dataclasses.replace(
        records[index],
        snapshot={"distance_cm": 60, "face_present": True, "new_speech": None},
    )
    return dataclasses.replace(episode, records=records)


def without_a_start(episode):
    return dataclasses.replace(episode, records=list(episode.records)[1:])


def with_a_record_after_the_ending(episode):
    """A Turn that begins after the Episode has already finished.

    Numbered so it *continues* the sequence rather than jumping: a `turn=99`
    would also break the numbering clause, and then this case would not say
    which of the two checks was doing the noticing.
    """
    records = list(episode.records)
    ending = records[-1]
    following = max(
        (r.turn for r in records if isinstance(r, TurnStarted)), default=0
    ) + 1
    return dataclasses.replace(
        episode,
        records=records
        + [TurnStarted(t=ending.t, episode_id=ending.episode_id, turn=following)],
    )


def with_a_gap_in_the_turn_numbers(episode):
    """A skipped Turn number, still inside the cap.

    Shifting every Turn up by five would also push the highest past the cap,
    and then the cap clause is the one that fires — leaving the numbering
    clause never exercised, which is exactly what happened.
    """
    records = list(episode.records)
    started = [i for i, r in enumerate(records) if isinstance(r, TurnStarted)]
    assert len(started) >= 2, "this scenario needs at least two Turns"
    index = started[-1]
    records[index] = dataclasses.replace(
        records[index], turn=records[index].turn + 1
    )
    return dataclasses.replace(episode, records=records)


def with_more_model_calls_than_turns_allowed(episode):
    records = list(episode.records)
    call = next(r for r in records if isinstance(r, ModelCalled))
    extra = [dataclasses.replace(call) for _ in range(episode.turn_cap + 1)]
    return dataclasses.replace(episode, records=records[:-1] + extra + records[-1:])


def with_a_velocity_in_the_tool_schemas(episode):
    """The other half of the layering audit.

    A scan that only looked at the prompts would miss a Tool advertising a
    velocity in its own schema — which is the half the live velocity test
    depends on.
    """
    return dataclasses.replace(
        episode,
        tools=list(episode.tools)
        + [{"function": {"parameters": {"properties": {"linearVelocity": {}}}}}],
    )


def with_a_call_to_a_tool_that_does_not_exist(episode):
    records = list(episode.records)
    index = next(i for i, r in enumerate(records) if isinstance(r, ToolCalled))
    records[index] = dataclasses.replace(records[index], tool="teleport")
    return dataclasses.replace(episode, records=records)


#: One deliberate breakage per **clause**, not per check.
#:
#: Keyed by check alone, this map gave false assurance: five of the seven
#: checks test several independent things, and a single breakage per check
#: left the other clauses never shown failing. Six surviving mutations came
#: from exactly that. The key is the clause; the value says which check must
#: notice it.
BROKEN = {
    "no ending at all": (without_the_ending, "ends exactly once"),
    "no start at all": (without_a_start, "ends exactly once"),
    "a record after the ending": (
        with_a_record_after_the_ending, "ends exactly once"),
    "a Turn past the cap": (
        with_a_turn_past_the_cap, "stays within the Turn cap"),
    "a gap in the Turn numbers": (
        with_a_gap_in_the_turn_numbers, "stays within the Turn cap"),
    "more model calls than Turns allowed": (
        with_more_model_calls_than_turns_allowed, "stays within the Turn cap"),
    "a velocity in the prompt": (
        with_a_velocity_in_the_prompt,
        "no physical parameter reached the model"),
    "a velocity in the Tool schemas": (
        with_a_velocity_in_the_tool_schemas,
        "no physical parameter reached the model"),
    "an out-of-range argument": (
        with_an_out_of_range_call, "every Tool call was in range"),
    "a call to a Tool that does not exist": (
        with_a_call_to_a_tool_that_does_not_exist,
        "every Tool call was in range"),
    "a drive nobody reported": (
        with_a_drive_nobody_reported, "every drive came from approach"),
    "a record that cannot be written down": (
        with_a_record_that_cannot_be_written,
        "the Journal survives being written down"),
    "a record that comes back as something else": (
        a_snapshot_that_round_trips_into_something_else,
        "the Journal survives being written down"),
    "a refusal that also produced an Observation": (
        with_a_refusal_that_also_observed,
        "a refusal is never treated as success"),
}


def test_every_check_is_exercised_by_a_failing_case():
    """A guard against this file rotting.

    Adding a check to `CHECKS` without a case below would leave it never shown
    to fail, which is the state the whole file exists to prevent.
    """
    named = {name for name, _ in CHECKS}
    covered = {check for _, check in BROKEN.values()}

    assert named == covered, f"never shown failing: {sorted(named - covered)}"


@pytest.mark.parametrize("clause", sorted(BROKEN))
def test_the_check_notices_when_its_invariant_is_broken(clause):
    """Each clause, shown failing — and failing **only** the check it belongs
    to, so a breakage is attributed to the right invariant.

    The exclusivity matters: an earlier version asserted merely that *some*
    problem was reported, which a check that fired on everything would satisfy.
    """
    breakage, expected = BROKEN[clause]
    broken = breakage(an_episode(robot=None))

    found = violations(broken)

    assert found, f"{clause!r} went unnoticed"
    blamed = {problem.split(":", 1)[0] for problem in found}
    assert blamed == {expected}, f"{clause!r} was blamed on {sorted(blamed)}"


def test_the_audit_is_at_least_as_strict_as_the_guard():
    """An independent list is only worth having if it misses nothing.

    `FORBIDDEN_IN_PROMPT` is deliberately not imported from `layering.py` —
    it audits that guard, and sharing a definition would make them agree by
    construction. But the first hand-written version was *lossy*: `speed`,
    `driveSpeed`, `cmPerSec` and `driveDuration` all failed the guard and
    passed the audit, which is `PLAN.md` §10's two-copies-diverge happening
    inside the file whose job is to catch it. Independent, and provably no
    weaker.
    """
    from misty_agent.agent.layering import DRIVE_COMMANDS, RATE_STEMS

    missed = [
        name for name in RATE_STEMS + DRIVE_COMMANDS
        if not any(word in name for word in FORBIDDEN_IN_PROMPT)
    ]

    assert missed == [], f"the guard refuses these and the audit would not: {missed}"


@pytest.mark.parametrize(
    "spelling",
    ["linearVelocity", "linear_velocity", "driveSpeed", "cmPerSec",
     "driveDuration", "timeMs", "time_ms", "LINEAR-VELOCITY"],
)
def test_any_spelling_of_a_control_parameter_is_caught(spelling):
    """However it is written. The audit flattens before matching, because
    `cm_per_sec` and `cmPerSec` are the same word and Misty's own API uses
    the camel-case one.
    """
    episode = an_episode(robot=None)
    poisoned = dataclasses.replace(
        episode,
        prompts=[[{"role": "user", "content": {spelling: 20}}]],
    )

    assert any(
        problem.startswith("no physical parameter reached the model")
        for problem in violations(poisoned)
    ), spelling


# ---------------------------------------------------------------------------
# The live suite's own plumbing, exercised without paying for it
# ---------------------------------------------------------------------------

class ApproachesThenStops:
    """A stand-in that drives, speaks and stops — enough to exercise the
    harness the paid suite uses."""

    def decide(self, working_context, tools):
        from misty_agent.agent.react import Decision

        plan = ["approach", "speak", "done"]
        step = min(
            sum(1 for entry in working_context if entry.get("role") == "assistant"),
            len(plan) - 1,
        )
        tool = plan[step]
        return Decision(
            tool=tool,
            args={"text": "hello"} if tool == "speak" else {},
            tokens_in=900,
            tokens_out=15,
        )


def test_the_live_harness_produces_an_episode_that_passes_its_own_gates():
    """`tests/test_llm_live.py` costs money, so nobody runs it by accident —
    which means a broken harness there stays broken silently until somebody
    pays to find out.

    That is not hypothetical. An earlier version of `a_live_episode` handed
    `approach` readings stamped at time zero against a clock also at zero, so
    every reading was stale, the robot never moved, and the drive audit could
    only ever compare zero with zero. Nothing offline noticed, because nothing
    offline ran it. This does.
    """
    import test_llm_live as live

    episode, outcome = live.a_live_episode(
        ApproachesThenStops(), "speech", "come here", 210
    )

    assert violations(episode) == []
    assert outcome.outcome == "done"
    assert episode.robot.directions, "the harness cannot make the robot move, so its drive audit is idle"


def test_the_drive_audit_trusts_the_episodes_own_total():
    """`PLAN.md` §15.20 put the `"steps"` string in one place and gave
    everyone else a typed field.

    An audit that went back to `result["steps"]` would agree with the typed
    total on every well-formed Journal — so only a deliberately inconsistent
    one can tell the two apart, and without this the layering rule could be
    quietly undone with nothing turning red.
    """
    episode = an_episode(scenario=offline.ends_after_several_turns)
    records = list(episode.records)
    index = next(
        i for i, r in enumerate(records)
        if isinstance(r, Observation) and "result" in r.result
    )
    records[index] = dataclasses.replace(
        records[index], result={**records[index].result, "steps": 5}
    )

    inconsistent = dataclasses.replace(
        episode, records=records, robot=DroveOnItsOwn.with_drives(1)
    )

    assert every_drive_came_from_approach(inconsistent) == []
