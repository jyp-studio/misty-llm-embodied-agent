"""One Robot interface, two adapters, one Tool and controller code path.

The real adapter turns behaviours into the vendor requests the contract
tests already pin, over the recording transport, without an address to send
them to. The simulated adapter turns the same behaviours into state that the
next Snapshot and Observation can see. Neither keeps a second event log: the
Journal is the record of what the agent did.
"""

from __future__ import annotations

from misty_agent.agent.evidence import EvidenceKind, TriggerEvidence
from misty_agent.agent.journal import Journal, Observation, ToolCalled
from misty_agent.agent.react import Decision, run_episode
from misty_agent.agent.storyboard import storyboard_of
from misty_agent.agent.tools import EXPRESSION_IMAGES, ToolContext, build_registry
from misty_agent.app import LivePerception
from misty_agent.config import Settings
from misty_agent.control.approach import ApproachStatus, approach
from misty_agent.fakes import FakeClock, RecordingCommands
from misty_agent.robot import Effect, RealMistyAdapter, RobotPose, SimulatedMistyAdapter
from misty_agent.scenarios import ScenarioModel


def test_the_real_adapter_emits_the_documented_vendor_requests_without_an_address():
    commands = RecordingCommands("10.0.0.5")
    robot = RealMistyAdapter(commands)

    assert robot.speak("hello") == Effect(ok=True)
    assert commands.last("tts/speak").body_without_defaults() == {"text": "hello"}
    robot.display_image("e_Joy.jpg")
    assert commands.last("images/display").body_without_defaults() == {"fileName": "e_Joy.jpg"}
    robot.move_arms(45.0, 90.0)
    assert commands.last("arms/set").body_without_defaults() == {
        "leftArmPosition": 45.0, "rightArmPosition": 90.0, "units": "degrees",
    }
    robot.move_head(-5.0, 0.0, 30.0)
    assert commands.last("head").body_without_defaults() == {
        "pitch": -5.0, "roll": 0.0, "yaw": 30.0, "units": "degrees",
    }
    robot.change_led(0, 128, 255)
    assert commands.last("led").body_without_defaults() == {"red": 0, "green": 128, "blue": 255}
    robot.play_audio("s_Awe.wav", 60)
    assert commands.last("audio/play").body_without_defaults() == {"fileName": "s_Awe.wav", "volume": 60}
    robot.drive(linear_percent=20, angular_percent=0, duration_ms=500, timeout_s=2.0)
    assert commands.last("drive/time").body_without_defaults() == {
        "linearVelocity": 20, "angularVelocity": 0, "timeMs": 500,
    }
    robot.halt()
    assert commands.endpoints[-1] == "halt"
    assert robot.commands is commands


def test_a_refused_vendor_request_is_a_failed_effect_not_an_exception():
    robot = RealMistyAdapter(RecordingCommands(fail_endpoints=["head"], failure_status=503))

    effect = robot.move_head(0.0, 0.0, 0.0)

    assert effect.ok is False
    assert "503" in effect.detail
    assert robot.speak("still fine").ok is True


def test_the_simulated_adapter_holds_pose_speech_and_the_world_it_drives_through():
    clock = FakeClock()
    robot = SimulatedMistyAdapter(clock, start_cm=150.0, config=Settings())

    assert robot.pose == RobotPose()
    assert robot.display_image("e_Joy.jpg").ok
    assert robot.change_led(255, 0, 0).ok
    assert robot.move_head(-5.0, 2.0, 30.0).ok
    assert robot.move_arms(45.0, 60.0).ok
    assert robot.pose == RobotPose(expression="e_Joy.jpg", led=(255, 0, 0), head=(-5.0, 2.0, 30.0), arms=(45.0, 60.0))
    assert robot.speak("你好").ok
    assert robot.speech == "你好"
    assert robot.play_audio("s_Awe.wav", 40).ok
    assert robot.sound == ("s_Awe.wav", 40)

    before = robot.latest_reading().distance_cm
    assert robot.drive(linear_percent=20, angular_percent=0, duration_ms=1000, timeout_s=1.0).ok
    moved = before - robot.latest_reading().distance_cm
    assert moved == Settings().cm_per_sec_at_percent
    assert robot.directions == [1]
    assert robot.closest_cm == robot.distance_cm
    assert robot.halt().ok and robot.halted


def test_a_simulated_failure_leaves_state_unchanged_and_an_empty_room_reads_nothing():
    clock = FakeClock()
    robot = SimulatedMistyAdapter(clock, start_cm=120.0, config=Settings(), failing=("move_head", "drive"))

    assert robot.move_head(0.0, 0.0, 45.0) == Effect(ok=False, detail="simulated move_head failure")
    assert robot.pose.head == (0.0, 0.0, 0.0)
    assert robot.drive(linear_percent=20, angular_percent=0, duration_ms=1000, timeout_s=1.0).ok is False
    assert robot.latest_reading().distance_cm == 120

    nobody = SimulatedMistyAdapter(clock, start_cm=None, config=Settings())
    assert nobody.latest_reading() is None
    assert nobody.drive(linear_percent=20, angular_percent=0, duration_ms=1000, timeout_s=1.0).ok
    assert nobody.latest_reading() is None


def test_the_controller_converges_in_the_simulated_world_and_reports_a_refused_drive():
    config = Settings()
    clock = FakeClock()
    world = SimulatedMistyAdapter(clock, start_cm=150.0, config=config)
    result = approach(world, world, config=config, clock=clock)
    assert result.status is ApproachStatus.ARRIVED
    assert world.closest_cm >= config.min_safe_distance_cm

    refused = SimulatedMistyAdapter(FakeClock(), start_cm=150.0, config=config, failing=("drive",))
    assert approach(refused, refused, config=config, clock=FakeClock()).status is ApproachStatus.DRIVE_ERROR


SCRIPT = (
    Decision("speak", {"text": "你好"}, 1, 1),
    Decision("display_image", {"expression": "happy"}, 1, 1),
    Decision("change_led", {"red": 0, "green": 200, "blue": 0}, 1, 1),
    Decision("move_head", {"pitch": -5, "roll": 0, "yaw": 20}, 1, 1),
    Decision("move_arms", {"left": 45, "right": 90}, 1, 1),
    Decision("done", {}, 1, 1),
)


def one_episode(robot, readings, clock):
    journal = Journal(episode_id="ep-adapter", clock=clock)
    outcome = run_episode(
        TriggerEvidence(source=EvidenceKind.SPEECH, observed_at_s=0.0, transcript="Hi Misty"),
        model=ScenarioModel(SCRIPT),
        registry=build_registry(),
        ctx=ToolContext(robot=robot, readings=readings, config=Settings(), clock=clock),
        journal=journal,
        perception=LivePerception(readings),
    )
    return outcome, journal


def test_the_same_scripted_episode_runs_on_both_adapters_through_one_tool_path():
    clock = FakeClock()
    simulated = SimulatedMistyAdapter(clock, start_cm=150.0, config=Settings())
    commands = RecordingCommands()
    real = RealMistyAdapter(commands)

    sim_outcome, sim_journal = one_episode(simulated, simulated, clock)
    real_outcome, real_journal = one_episode(real, simulated, FakeClock())

    assert sim_outcome == real_outcome
    strip = lambda journal: [
        (r.type, getattr(r, "tool", None), dict(getattr(r, "result", {})))
        for r in journal.records if isinstance(r, (ToolCalled, Observation))
    ]
    assert strip(sim_journal) == strip(real_journal)
    assert [r.result["ok"] for r in sim_journal.records if isinstance(r, Observation)] == [True] * 5
    assert commands.endpoints == ["tts/speak", "images/display", "led", "head", "arms/set"]

    # The storyboard keeps the model's word; the robot holds the asset it
    # was actually shown. Same pose, two vocabularies, one mapping.
    final = storyboard_of(sim_journal.records).moments[-1].robot
    assert simulated.pose == RobotPose(
        expression=EXPRESSION_IMAGES[final.expression],
        led=final.led, head=final.head, arms=final.arms,
    )
    assert simulated.speech == "你好"


def test_a_failed_simulated_effect_reaches_the_observation_and_the_storyboard_does_not_move():
    clock = FakeClock()
    robot = SimulatedMistyAdapter(clock, start_cm=150.0, config=Settings(), failing=("move_head",))

    outcome, journal = one_episode(robot, robot, clock)

    head = next(r for r in journal.records if isinstance(r, Observation) and r.turn == 4)
    assert head.result == {"ok": False, "detail": "simulated move_head failure"}
    assert outcome.outcome == "done"
    board = storyboard_of(journal.records)
    assert board.moments[-1].robot.head == (0.0, 0.0, 0.0)
    assert board.moments[-1].robot.arms == (45.0, 90.0)
    assert robot.pose.head == (0.0, 0.0, 0.0)


def test_the_demo_runs_on_the_simulated_adapter_and_its_end_state_matches_the_journal():
    import json
    from misty_agent.demo import answer

    run = json.loads(answer("POST", "/scenarios/crying-care/run", b'{"fixture":"calming-support"}').body)

    robot = run["robot"]
    assert "not a robot" in robot["provenance"]
    assert robot["speech"] == "好，我會尊重你的空間。"
    assert robot["halted"] is False
    final = run["episodes"][-1]["storyboard"]["moments"][-1]["robot"]
    assert robot["pose"]["head"] == final["head"] == [0.0, 8.0, 0.0]
    assert robot["pose"]["arms"] == final["arms"]
    assert robot["pose"]["led"] == final["led"]


def test_a_refused_scan_leaves_the_storyboard_head_where_it_was():
    """A `look_around` whose first turn is refused reports `ok: False` and
    `found_at_yaw: None`; the pose must not be recentred as if it had scanned."""
    clock = FakeClock()
    journal = Journal(episode_id="ep-scan", clock=clock)
    script = (
        Decision("move_head", {"pitch": 0, "roll": 0, "yaw": 20}, 1, 1),
        Decision("look_around", {}, 1, 1),
        Decision("done", {}, 1, 1),
    )

    class RefusesAfterOne(SimulatedMistyAdapter):
        def move_head(self, pitch_deg, roll_deg, yaw_deg):
            if self.pose.head != (0.0, 0.0, 0.0):
                return Effect(ok=False, detail="simulated move_head failure")
            return super().move_head(pitch_deg, roll_deg, yaw_deg)

    robot = RefusesAfterOne(clock, start_cm=None, config=Settings())
    run_episode(
        TriggerEvidence(source=EvidenceKind.SPEECH, observed_at_s=0.0, transcript="Hi"),
        model=ScenarioModel(script), registry=build_registry(),
        ctx=ToolContext(robot=robot, readings=None, config=Settings(), clock=clock),
        journal=journal, perception=LivePerception(robot),
    )
    scan = next(r for r in journal.records if isinstance(r, Observation) and r.turn == 2)
    assert scan.result["ok"] is False and scan.result["found_at_yaw"] is None
    assert storyboard_of(journal.records).moments[-1].robot.head == (0.0, 0.0, 20.0)
    assert robot.pose.head == (0.0, 0.0, 20.0)


def test_a_halt_the_robot_refuses_is_not_reported_as_halted():
    from misty_agent.agent.stop import EmergencyStop

    stop = EmergencyStop(Journal(episode_id="ep-halt"), RealMistyAdapter(
        RecordingCommands(fail_endpoints=["halt"], failure_status=500)
    ))
    assert stop.request("foot_bumper") is True
    assert stop.halted is False
