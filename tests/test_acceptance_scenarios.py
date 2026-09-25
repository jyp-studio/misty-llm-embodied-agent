"""The spec's fifteen situations, run end to end through the one seam.

Every case here enters at `SocialAgentRuntime` with timed inputs and comes
out as runtime records, Episode Journals and a simulated robot's state. That
is the spec's primary acceptance seam: a test that called `Session.episode`
directly would prove the ReAct loop and nothing about whether Misty decides
on its own to open an Episode at all.

The assertions are contracts, not scripts. Each one says whether an Episode
may open, what the runtime must make observable, which Tools would make the
outcome unsafe, and whether the base may move — and says nothing about
wording or Tool order, because a social situation has more than one
reasonable answer. `misty_agent/acceptance.py` holds them, and the Demo
reads the same list, so the page and these tests cannot drift.

None of this is a benchmark. There is no score and no leaderboard, every
model decision is an authored fixture rather than recorded output, and the
robot is simulated throughout.
"""

from __future__ import annotations

import pytest

from misty_agent.acceptance import (
    ACCEPTANCE_CONTRACTS,
    AcceptanceContract,
    contract_for,
    fixtures_of,
    run_fixture,
)
from boundary_audit import boundary_violations, spoken
from misty_agent.agent.journal import ToolCalled
from misty_agent.scenarios import DEMO_SCENARIOS, AcceptanceScenario


@pytest.fixture(scope="module")
def runs():
    """Every contract, run once. The fifteen are the expensive part."""
    return {
        contract.number: run_fixture(contract.card, contract.fixture)
        for contract in ACCEPTANCE_CONTRACTS
    }


def spoken_lines(run):
    return [
        line
        for episode in run.result.episodes
        for line in spoken(episode.journal.records)
    ]


def tools_called(run):
    return [
        record.tool
        for episode in run.result.episodes
        for record in episode.journal.records
        if isinstance(record, ToolCalled)
    ]


# ---------------------------------------------------------------------------
# The set itself
# ---------------------------------------------------------------------------

def test_all_fifteen_situations_are_covered_exactly_once():
    """The spec numbers fifteen; a gap here is a situation nobody runs."""
    numbers = [contract.number for contract in ACCEPTANCE_CONTRACTS]

    assert sorted(numbers) == list(range(1, 16))
    assert len(set(numbers)) == 15


def test_every_contract_names_a_fixture_that_exists():
    """The contract list and the scenario definitions are separate files;
    this is what stops a rename in one from quietly orphaning the other."""
    for contract in ACCEPTANCE_CONTRACTS:
        card = next(
            item for item in DEMO_SCENARIOS if item.name == contract.card
        )
        assert isinstance(card, AcceptanceScenario), contract.card
        keys = {fixture.key for fixture in fixtures_of(card)}
        assert contract.fixture in keys, f"{contract.card}/{contract.fixture}"


def test_every_tool_a_contract_names_is_a_tool_that_exists():
    """A typo in `forbidden_tools` forbids nothing and says nothing, and the
    contract goes on passing. The registry is the list of real names."""
    from misty_agent.agent.tools import build_registry

    registered = set(build_registry().names())
    for contract in ACCEPTANCE_CONTRACTS:
        named = set(contract.forbidden_tools) | set(contract.requires_tools)
        assert named <= registered, (
            f"scenario {contract.number} names "
            f"{sorted(named - registered)}, which no Tool is called"
        )


def test_the_demo_and_the_tests_read_the_same_contracts():
    """Not a copy on each side: the Demo looks contracts up by card and
    fixture out of the same tuple this file asserts on."""
    for contract in ACCEPTANCE_CONTRACTS:
        assert contract_for(contract.card, contract.fixture) is contract
    assert contract_for("greeting", "no-such-fixture") is None


# ---------------------------------------------------------------------------
# The fifteen
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "contract",
    ACCEPTANCE_CONTRACTS,
    ids=[f"{c.number:02d}-{c.fixture}" for c in ACCEPTANCE_CONTRACTS],
)
def test_the_situation_comes_out_inside_its_contract(contract: AcceptanceContract, runs):
    run = runs[contract.number]
    episodes = run.result.episodes
    called = tools_called(run)

    if contract.opens_episode:
        assert episodes, "nobody was answered"
        assert [episode.outcome.outcome for episode in episodes] == [
            contract.outcome
        ] * len(episodes)
        if contract.episodes is not None:
            assert len(episodes) == contract.episodes, (
                f"scenario {contract.number} opened {len(episodes)} Episodes, "
                f"not {contract.episodes}"
            )
        if contract.cue_kind is not None:
            detected = next(
                record for record in run.result.records
                if record.type == "cue_detected"
            )
            assert detected.cue_kind == contract.cue_kind
    else:
        # The strongest thing in this file: it left them alone.
        assert episodes == (), "it interrupted somebody who gave it no cue"
        assert called == []

    assert not set(contract.forbidden_tools) & set(called), (
        f"scenario {contract.number} used {sorted(set(contract.forbidden_tools) & set(called))}"
    )
    assert set(contract.requires_tools) <= set(called), (
        f"scenario {contract.number} never called "
        f"{sorted(set(contract.requires_tools) - set(called))}"
    )

    # Both halves of the observable story: the Attention Loop's own records
    # and the Journals of the Episodes it opened. A handoff notice lives in
    # the second, a queued cue in the first.
    types = {record.type for record in run.result.records} | {
        record.type
        for episode in run.result.episodes
        for record in episode.journal.records
    }
    assert set(contract.requires_records) <= types, (
        f"scenario {contract.number} never showed "
        f"{sorted(set(contract.requires_records) - types)}"
    )

    moved = bool(run.session.robot.directions or run.session.robot.rotations)
    assert moved is (not contract.stays_put), (
        f"scenario {contract.number} expected stays_put={contract.stays_put}"
    )
    assert run.session.robot.halted is contract.halts, (
        f"scenario {contract.number} expected halts={contract.halts}"
    )

    # True of every one of the fifteen, whatever else they do: Misty never
    # claims a diagnosis, a rescue, a promise of safety or that it contacted
    # anybody. The net is proven able to fire in `test_boundary_audit.py`.
    assert boundary_violations(spoken_lines(run)) == []


def test_the_quiet_situations_are_quiet_for_the_right_reason(runs):
    """A scenario that opened no Episode because the fixture was empty would
    satisfy the contract while proving nothing. The gate has to have looked
    at somebody and decided against interrupting them."""
    passerby = runs[2]
    visual = [
        record for record in passerby.result.records
        if record.type == "visual_attention"
    ]

    assert visual, "the visual gate never ran"
    assert any(record.facts.get("person_count", 0) > 0 for record in visual), (
        "nobody was ever in frame, so declining to interrupt means nothing"
    )
    assert passerby.result.episodes == ()


def test_a_contract_notices_when_a_situation_stops_satisfying_it(runs):
    """The contracts are only worth their assertions if they can fail.

    Rather than break a scenario, this asks the same questions of the wrong
    run: the quiet passer-by measured against the greeting's contract, and
    the greeting measured against the passer-by's.
    """
    greeting = next(c for c in ACCEPTANCE_CONTRACTS if c.number == 3)
    passerby = next(c for c in ACCEPTANCE_CONTRACTS if c.number == 2)

    # The passer-by run answers nobody, so the greeting's contract fails.
    assert not runs[2].result.episodes
    assert set(greeting.requires_tools) - set(tools_called(runs[2]))

    # The greeting run does answer, so the passer-by's contract fails: its
    # whole assertion is that no Episode opened, and one did.
    assert passerby.opens_episode is False
    assert runs[3].result.episodes, "the greeting answered nobody"


# ---------------------------------------------------------------------------
# The seam
# ---------------------------------------------------------------------------

def test_no_product_entry_point_bypasses_the_runtime():
    """`Session.episode` is an internal dependency of `SocialAgentRuntime`.
    A second caller in the package would be a product path that never went
    through the Attention Loop, which is the thing this effort added."""
    import pathlib
    import re

    package = pathlib.Path(__file__).resolve().parent.parent / "misty_agent"
    #: Calls, not the definition: `app.py` defines `Session.episode` and is
    #: watched like everything else. Excluding it by name would have exempted
    #: the CLI assembly, which is exactly where a bypass would appear.
    call = re.compile(r"(?<!def )\b\w+\.episode\(")
    callers = sorted(
        path.name
        for path in package.rglob("*.py")
        if call.search(path.read_text())
    )

    assert callers == ["runtime.py"], callers


# ---------------------------------------------------------------------------
# What the page tells a visitor
# ---------------------------------------------------------------------------

def test_the_scenario_listing_says_which_spec_situation_a_fixture_stands_for():
    """The number comes from the same tuple the tests assert against, so the
    listing cannot claim coverage the tests do not have."""
    import json

    from misty_agent.demo import answer

    listed = json.loads(answer("GET", "/scenarios").body)
    labelled = {
        (card["name"], fixture["key"]): fixture
        for card in listed
        for fixture in card.get("fixtures", [])
        if "spec_scenario" in fixture
    }

    assert len(labelled) == 15
    for contract in ACCEPTANCE_CONTRACTS:
        entry = labelled[(contract.card, contract.fixture)]
        assert entry["spec_scenario"] == contract.number
        assert entry["situation"] == contract.situation


def test_the_whole_contract_set_is_served_with_its_limits_attached():
    import json

    from misty_agent.demo import answer

    payload = json.loads(answer("GET", "/acceptance").body)

    assert [item["number"] for item in payload["scenarios"]] == list(range(1, 16))
    assert set(payload["provenance"]) == {
        "specification_fixture",
        "scripted_run",
        "recorded_model_run",
        "live_model_run",
    }
    assert "No Misty II" in payload["hardware_unverified"]
    assert "no leaderboard" in payload["not_a_benchmark"]


def test_a_run_says_which_of_the_four_things_it_is():
    import json

    from misty_agent.demo import answer
    from misty_agent.demo import HARDWARE_UNVERIFIED, PROVENANCE

    payload = json.loads(
        answer("POST", "/scenarios/greeting/run", b'{"fixture":"good-news"}').body
    )
    provenance = payload["execution"]["provenance"]

    assert provenance["kind"] == "scripted_run"
    assert provenance["kind_means"] == PROVENANCE["scripted_run"]
    assert provenance["hardware_unverified"] == HARDWARE_UNVERIFIED


def test_the_page_can_play_pause_restart_and_scrub_every_moment():
    """Ticket 15 asks for all four, over the whole run rather than the first
    Episode: the scrubber's range is every Moment the run produced."""
    page = answer_page()

    assert 'id="replayScrub"' in page and 'type="range"' in page
    assert 'id="replayRestart"' in page
    assert "function playReplay()" in page
    assert "function pauseReplay()" in page
    assert "function restartReplay()" in page
    assert "function showMoment(" in page
    # Scrubbing pauses rather than fighting the timer.
    assert 'byId("replayScrub").addEventListener("input"' in page
    assert "pauseReplay();" in page
    # Every Episode's Moments, not just the first.
    assert "run.episodes.flatMap" in page


def answer_page() -> str:
    from misty_agent.demo import answer

    return answer("GET", "/").body.decode("utf-8")


def test_the_page_shows_what_kind_of_run_it_was():
    """The labels have to reach a visitor, not only the JSON. A route nobody
    renders is a claim nobody can see. The spec numbers are not shown: the
    page is a showcase for visitors, and `/acceptance` still serves every
    contract with its number."""
    page = answer_page()

    assert 'id="provenanceBadge"' in page
    assert "provenance.recorded_on" in page
    assert "provenance.kind_means" in page
    assert "provenance.hardware_unverified" in page


def test_the_live_panel_labels_itself_too():
    """It is the one path that reaches a real model, so it is the one a
    visitor is most likely to mistake for evidence."""
    import json

    from misty_agent.demo import HARDWARE_UNVERIFIED, answer

    payload = json.loads(answer("POST", "/run", b'{"said":"hello"}').body)

    assert payload["provenance"]["kind"] == "live_model_run"
    assert payload["provenance"]["hardware_unverified"] == HARDWARE_UNVERIFIED


def test_a_supplied_model_replaces_the_authored_decisions_and_nothing_else():
    """How the Demo's recordings are made: same inputs, same simulated room,
    somebody else deciding. If the fixture's script leaked through, a
    "recorded model run" would be the script with a different label."""
    from misty_agent.agent.react import Decision

    asked = []

    class Decides:
        def decide(self, working_context, tools):
            asked.append(working_context)
            return Decision("done", {}, 1, 1, tool_call_id="call-own", note="Nothing to add.")

    run = run_fixture("greeting", "good-news", model=Decides())

    assert tools_called(run) == ["done"]
    assert asked, "the supplied model was never asked"
    assert "Misty, I just got accepted!" in str(asked[0])
