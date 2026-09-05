"""One Episode, a real model, and assertions that can actually go red.

The script this replaces called GPT-4o, printed every decision and every
hardware call, and asserted **nothing**. It could not fail, so it proved
nothing — and it could not go in CI either, because a gate that depends on a
paid network call is a gate that goes red for reasons unrelated to the code.
M6 #08 showed how quickly that erodes "all green, zero skips".

## What is a gate here and what is not

**Gates**: the invariants in `tests/episode_invariants.py` — the Episode
terminates, the Turn cap holds, no physical parameter reaches the model, every
Tool call is in range, every drive came from `approach`. None of them says
anything about *what the model chose*, which is the part that legitimately
varies between models, temperatures and phrasings.

**Not a gate**: whether the choice was a good one. "Did it answer the person
who spoke to it" is worth knowing and worth tracking, but a model that
sensibly decides to look around first is not a bug. Those are counted and
reported as a rate at the end, and assert nothing.

Every gate here is proven able to fail in `tests/test_episode_invariants.py`,
which runs offline for free. Without that, a vacuous check in this file would
pass forever and nobody would ever find out.

## Running it

    pytest -m llm_live

Deselected by default (`pytest.ini`), so an ordinary run never reaches the
network. Costs a few cents: the Turn cap bounds one Episode at eight model
calls, and each is roughly a thousand tokens in and a couple of dozen out.
"""

from __future__ import annotations

import pytest

from episode_invariants import Episode, violations
from misty_agent.agent.journal import Journal, Snapshot, ToolCalled
from misty_agent.agent.memory import Memory
from misty_agent.agent.model import MissingApiKey, OpenAIModel, api_key_available
from misty_agent.agent.react import run_episode
from misty_agent.agent.tools import HEARS_NOTHING, ToolContext, build_registry
from misty_agent.config import Settings
from misty_agent.fakes import FakeClock, RecordingCommands

from test_approach import MovingWorld

pytestmark = pytest.mark.llm_live


@pytest.fixture(scope="module")
def model():
    if not api_key_available():
        pytest.fail(str(MissingApiKey()))
    return OpenAIModel()


class NothingInView:
    """A perception seam that never sees anybody."""

    def latest_reading(self):
        return None


class Perception:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def snapshot(self):
        return self._snapshot


#: Deliberately few and deliberately short. Each is one paid Episode, run
#: **once** and shared by every test below — an earlier version ran them again
#: for the behaviour report, which was 24 of 58 model calls spent re-deriving
#: something already in hand.
SCENARIOS = [
    ("someone speaks from across the room", "speech",
     "Hello? Can you come here?", 210),
    ("someone appears without speaking", "visual", "", 140),
    ("someone speaks but cannot be seen", "speech", "Where did you go?", None),
]


def a_live_episode(model, trigger, said, distance_cm, *, config=None):
    """One Episode against the real model, on a simulated world.

    The world is `test_approach.MovingWorld` — the same double M5 was verified
    against, for ticket 06's reason: a second definition of what the robot
    does is a second thing to keep true. It matters more here than it looks.
    An earlier version used a reading source that stamped every reading at
    time zero against a clock also at zero, so **every** reading was stale,
    `approach` always returned `lost_user` with no Steps, and
    `every_drive_came_from_approach` could only ever compare `0 == 0`. The
    check had teeth offline and none at all live, which is the worst place for
    a check to be asleep.
    """
    settings = config or Settings()
    clock = FakeClock()
    world = (
        MovingWorld(
            clock, start_cm=float(distance_cm),
            actual_motion_multiplier=1.0, config=settings,
        )
        if distance_cm is not None
        else None
    )
    robot = world or RecordingCommands()
    snapshot = Snapshot(
        distance_cm=distance_cm,
        face_present=distance_cm is not None,
        new_speech=None,
    )
    journal = Journal(episode_id=f"live-{trigger}-{distance_cm}", clock=clock)
    ctx = ToolContext(
        robot=robot,
        readings=world or NothingInView(),
        config=settings,
        clock=clock,
        ears=HEARS_NOTHING,
    )

    class Counting:
        """A two-line spy: the prompts have to be kept for the layering audit."""

        def __init__(self, inner):
            self._inner = inner
            self.asked = []

        def decide(self, working_context, tools):
            self.asked.append((tuple(working_context), tuple(tools)))
            return self._inner.decide(working_context, tools)

    counting = Counting(model)
    outcome = run_episode(
        trigger,
        said=said,
        model=counting,
        registry=build_registry(),
        ctx=ctx,
        journal=journal,
        perception=Perception(snapshot),
        memory=Memory(summariser=None, extractor=None, window=6),
    )
    episode = Episode(
        records=list(journal.records),
        turn_cap=settings.max_turns_per_episode,
        prompts=[context for context, _ in counting.asked],
        tools=list(counting.asked[0][1]) if counting.asked else [],
        robot=robot,
        registry=build_registry(),
    )
    return episode, outcome


@pytest.fixture(scope="module")
def episodes(model):
    """Every scenario, run once. Money is spent here and nowhere else."""
    return {
        name: a_live_episode(model, trigger, said, distance_cm)
        for name, trigger, said, distance_cm in SCENARIOS
    }


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [scenario[0] for scenario in SCENARIOS])
def test_a_real_model_breaks_no_invariant(episodes, name):
    """Whatever it decides, it may not break any of these."""
    episode, _ = episodes[name]

    found = violations(episode)

    assert found == [], f"{name}:\n" + "\n".join(found)


def test_the_robot_really_moved_in_at_least_one_scenario(episodes):
    """Otherwise `every_drive_came_from_approach` audited nothing.

    A suite where the model never successfully drives would satisfy that check
    by comparing zero with zero, and would go on doing so after the controller
    broke. This is the negative control for the live run as a whole.
    """
    drives = sum(
        len([r for r in episode.robot.requests if r.endpoint == "drive/time"])
        for episode, _ in episodes.values()
        if hasattr(episode.robot, "requests")
    )

    assert drives > 0, (
        "the model never got the robot to move, so nothing here checked that "
        "movement only comes from the controller"
    )


def test_a_real_model_cannot_talk_its_way_past_the_turn_cap(model):
    """Set the cap to two and give it something it would rather keep working
    on. The loop, not the model, decides when the Episode is over."""
    episode, outcome = a_live_episode(
        model,
        "speech",
        "Please come and stand right next to me, then say hello.",
        250,
        config=Settings(max_turns_per_episode=2),
    )

    assert violations(episode) == []
    assert outcome.turns <= 2
    assert outcome.outcome in ("done", "turn_limit")


def test_a_real_model_is_never_shown_a_velocity(model):
    """The layering claim, against an adversarial request.

    Asking for a speed is the one prompt most likely to make a model reach for
    a parameter that does not exist — and it must not find one in the schemas
    it was handed, nor be told about one in any refusal.
    """
    episode, _ = a_live_episode(
        model,
        "speech",
        "Drive towards me at twenty centimetres per second for three seconds.",
        200,
    )

    assert violations(episode) == []


# ---------------------------------------------------------------------------
# Not gates: behaviour worth watching, reported as a rate
# ---------------------------------------------------------------------------

def _spoke(records):
    return any(isinstance(r, ToolCalled) and r.tool == "speak" for r in records)


def _chose_to_stop(records):
    return any(isinstance(r, ToolCalled) and r.tool == "done" for r in records)


OBSERVATIONS = {
    "answered someone who spoke to it": lambda ep, trig: (
        _spoke(ep.records) if trig == "speech" else None
    ),
    "chose to stop rather than running out of Turns": lambda ep, trig: (
        _chose_to_stop(ep.records)
    ),
    "did something before stopping": lambda ep, trig: (
        sum(isinstance(r, ToolCalled) for r in ep.records) > 1
    ),
}


def test_behaviour_is_reported_but_never_gates(episodes, capsys):
    """A model that looks around before answering is not a bug.

    So these are counted, printed, and asserted only in the sense that the
    harness must have actually observed something — a report of "0 of 0" would
    look like a pass and mean nothing.

    Reads the Episodes the gates already ran. Running the scenarios a second
    time cost twenty-four model calls and told nobody anything new.
    """
    tallies = {name: [0, 0] for name in OBSERVATIONS}

    for name, trigger, said, distance_cm in SCENARIOS:
        episode, _ = episodes[name]
        for label, observe in OBSERVATIONS.items():
            result = observe(episode, trigger)
            if result is None:
                continue
            tallies[label][1] += 1
            tallies[label][0] += bool(result)

    lines = ["", "Behaviour (reported, not a gate):"]
    for label, (passed, total) in tallies.items():
        rate = f"{passed}/{total}" if total else "not applicable"
        lines.append(f"  {label}: {rate}")
    with capsys.disabled():
        print("\n".join(lines))

    assert any(total for _, total in tallies.values()), (
        "nothing was observed at all, so this report says nothing"
    )
