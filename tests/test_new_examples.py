"""Three scripts for the Demo's next examples (PLAN.md §16.67).

Backing off when asked, timing three seconds, and putting on a little show:
each needed something the Tool set did not have or the persona never
mentioned. These run the authored decisions, the way every other script's
tests do; the Demo will play a hosted model's own run over the same inputs.
"""

from __future__ import annotations

import pytest

from boundary_audit import boundary_violations, spoken
from misty_agent.acceptance import run_fixture
from misty_agent.agent.journal import ToolCalled
from misty_agent.robot.interface import RobotPose


def records(run):
    return [record for episode in run.result.episodes for record in episode.journal.records]


def calls(run):
    return [record for record in records(run) if isinstance(record, ToolCalled)]


@pytest.mark.parametrize("key", ["back-off", "timer", "show-off"])
def test_each_runs_to_its_own_ending_and_stays_inside_the_boundaries(key):
    run = run_fixture("greeting", key)

    (episode,) = run.result.episodes
    assert episode.outcome.outcome == "done"
    assert boundary_violations(spoken(episode.journal.records)) == []


def test_asked_to_back_up_it_keeps_far_and_ends_up_further_away():
    run = run_fixture("greeting", "back-off")
    approaches = [call for call in calls(run) if call.tool == "approach"]

    assert [call.args for call in approaches] == [{"keep": "far"}]
    assert run.session.robot.distance_cm > 130


def test_asked_to_time_three_seconds_it_waits_three_seconds_before_saying_so():
    run = run_fixture("greeting", "timer")
    said = calls(run)
    wait = next(call for call in said if call.tool == "wait")
    after = said[said.index(wait) + 1]

    assert wait.args == {"seconds": 3}
    assert after.tool == "speak"
    assert after.t - wait.t >= 3.0


def test_asked_for_a_show_it_composes_one_out_of_its_body():
    run = run_fixture("greeting", "show-off")
    used = {call.tool for call in calls(run)}

    assert {"move_arms", "move_head", "change_led", "play_audio", "speak"} <= used
    # And it comes back to rest before it finishes.
    assert run.session.robot.pose.arms == RobotPose().arms
    assert run.session.robot.pose.head == RobotPose().head
