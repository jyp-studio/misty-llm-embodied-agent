# Misty Embodied Agent

**An LLM agent for Misty II that notices social cues, gathers information and
chooses its next action.**

Misty Embodied Agent connects continuous attention with a bounded ReAct loop.
The runtime selects cues from speech and vision, then gives the model room to
observe, respond and adapt as an interaction unfolds. A separate controller
handles movement, while a structured record makes each decision and its
outcome available for inspection.

The repository provides a working prototype and an experimental testbed for
extending these capabilities. Its original goal was to give a robot the
initiative to notice and engage with its surroundings. The current focus is
social interaction, with reusable interfaces for perception, models and robot
behaviour.

[Demo](#demo) · [Architecture](#architecture) · [Research directions](#research-directions)
· [Getting started](#getting-started) · [Validation](#validation) · [Scope](#scope)

<p align="center">
  <img src="assets/demo-calming-support.gif" width="900" alt="Misty responds to a request for help calming down, loads a Skill, listens to the person's choice and changes its expression.">
</p>

<p align="center"><em>A recorded interaction: Misty loads a Skill, offers a
choice, listens and adapts its response.</em></p>

## Demo

The local demo presents 15 recordings of `gpt-5.6-luna` made on September 25, 2026. The examples cover starting conversations, responding to visual cues,
approaching a person, offering support and respecting a request for space.

Start with **“Please help me calm down”** to follow a complete interaction.
Text examples begin after the wake phrase: in a real room the person would
first say “Hey Misty”. The “Hey Misty” example runs that step through the
local wake detector.
The stage shows speech, gestures, observations and public Decision Notes.
Open the conversation panel to read the exchange, or use **Try it live** to
send your own message to the model.

After [installing the project](#getting-started), launch the demo:

```bash
.venv/bin/python -m misty_agent --demo
```

Playback runs locally without an API key. The live panel uses the key
configured below and incurs API charges.

## Architecture

<p align="center">
  <a href="assets/architecture.svg"><img src="assets/architecture.svg" width="100%" alt="System architecture in two panels. (a) A continuous stream of audio and camera frames passes through a voice gate and a visual gate, which form cues; the cue queue orders them by priority, and the selected cue's Trigger Evidence e opens an episode. (b) In the episode, the LLM policy reads Skills on demand and chooses one action per turn, stated as intent; a safety controller sets speed and duration; the observation, with a Snapshot of distance, face and speech, returns to the policy for the next turn. Frames from the demo show Misty loading a Skill, asking what kind of company the person wants, and hearing the reply."></a>
</p>

**Attention determines when to engage.** Local wake detection and temporal
visual gates produce three kinds of cue: Explicit Request, Social Invitation
and Care Cue. The runtime orders cues by priority and freshness, removes
duplicates and gives one episode at a time control of the robot. A sustained
look and wave can open an interaction; a passing person can be left alone.

**The model chooses its next step.** Each turn permits one typed tool call.
The agent can speak, listen, inspect its target or scene, choose an expression,
request movement or finish. Tool results and fresh snapshots inform the next
decision. The default limit is 12 turns. Local Skills supply instructions and
reference material on demand, with access limited to the current episode.

**The controller turns intent into motion.** The model selects a distance
category when requesting `approach`. The controller handles chassis
alignment, bounded movement steps and fresh distance readings, with checks
for stop requests and hazards. Velocity and drive duration remain inside
the control layer.

**Records make the behaviour inspectable.** Attention records explain cue
selection, and the typed Journal captures tool calls, observations, outcomes
and public Decision Notes. Episode context is discarded when the interaction
ends. Optional persistent Journals redact personal prose.

## Research directions

The testbed supports experiments in three areas:

- **Interaction initiation.** Compare policies for selecting social cues,
  including their response delay, missed invitations and unnecessary model
  calls.
- **Active perception.** Study when the agent chooses to listen or inspect
  before acting, and measure the effect on decisions, latency and API cost.
- **Adaptive action.** Examine how an agent changes its behaviour when a
  person moves, new information arrives or an action fails.

Experiments can reuse the input scenarios, substitute a model or policy and
inspect the resulting Journals. The motion harness also supports parameter
sweeps over sensing delay, measurement noise and calibration assumptions.

## Getting started

Use **Python 3.11** to create the environment and install the dependencies:

```bash
git clone https://github.com/jyp-studio/misty-llm-embodied-agent.git
cd misty-llm-embodied-agent
python3.11 -m venv .venv
.venv/bin/python -m pip install --only-binary=:all: -r requirements.txt
.venv/bin/python -m misty_agent --demo
```

To run a new interaction, set `OPENAI_API_KEY` or create the configuration
file:

```bash
cp OAI_CONFIG_LIST.json.example OAI_CONFIG_LIST.json
```

Replace the placeholder key in that file, then run:

```bash
.venv/bin/python -m misty_agent --said "Misty, hello"
```

The CLI, live demo panel and recorder share this configuration. The key file
is ignored by Git. Runtime settings belong in `.env`; available settings
are listed in [.env.example](.env.example).

## Validation

The default suite runs offline:

```bash
.venv/bin/python -m pytest tests/ -q -rs
```

Always use `.venv/bin/python` and check that the suite reports zero skips.
Missing MediaPipe or OpenCV dependencies can otherwise cause perception
tests to be skipped.

| Coverage                                                   | Evidence                                                                                                                    |
| ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Cue selection, expiry, interruptions and social boundaries | [15 acceptance contracts](misty_agent/acceptance.py) and [scenario tests](tests/test_acceptance_scenarios.py)               |
| Episode limits, tool arguments and control boundaries      | [Invariant tests](tests/test_episode_invariants.py) and the [live model suite](tests/test_llm_live.py)                      |
| Face perception, reading freshness and movement            | [Perception tests](tests/test_perception_face.py), [replay harness](harness/) and [measurement reports](docs/measurements/) |
| Misty REST requests and WebSocket events                   | [Driver contract tests](tests/test_drivers_contract.py)                                                                     |
| Recorded interactions                                      | [Dated recordings](misty_agent/demo/recordings/) and [recording checks](tests/test_demo_recordings.py)                      |

With an API key configured, run the model tests or record new demo examples:

```bash
.venv/bin/python -m pytest -m llm_live
.venv/bin/python -m misty_agent.demo.record
```

Both commands call the hosted model and incur API charges.

## Scope

This project continues a class project that ran on a Misty II (see
[Provenance](#provenance-and-license)). The robot stayed with the course, so
this rebuild concentrates on what software can establish without it: the
attention runtime, the bounded agent loop, the control layer and the
evidence behind each.

**No Misty II has been available since the course, and none will be.**
Robot behaviour is evaluated in simulation. The demo combines scripted
inputs with recorded model decisions; offline acceptance tests use authored
decisions. Wake tests use synthetic audio, visual cue tests use authored
signals over drawn frames, and speaker attribution is scripted. Separate
perception tests run MediaPipe on image fixtures. These sources establish
software behaviour under declared assumptions. Comparative model benchmarks
and user studies remain future work.

Physical behaviour, calibration, latency and safety are unverified. The
`--robot <IP>` adapter has contract tests, but its movement path currently
lacks a hazard source and camera bearing and therefore refuses movement.
The [motion report](docs/measurements/m5-approach-report.md) documents the
assumptions and failure cases. Room mapping and autonomous navigation remain
outside the current implementation.

Configured hosted services may receive selected audio, images or text during
an interaction. Discarding local episode context does not prevent this
external processing.

## Extend the project

| Area                        | Entry points                                                                                                              |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Attention and cue policy    | [Runtime](misty_agent/runtime.py), [visual input](misty_agent/visual_input.py), [audio input](misty_agent/audio_input.py) |
| Model and observation tools | [Agent](misty_agent/agent/), [perception](misty_agent/perception/)                                                        |
| Behaviour instructions      | [Local Skills](misty_agent/skills/)                                                                                       |
| Motion and robot adapters   | [Control](misty_agent/control/), [robot interface](misty_agent/robot/)                                                    |
| Repeatable experiments      | [Scenarios](misty_agent/scenarios.py), [acceptance runner](misty_agent/acceptance.py), [harness](harness/)                |

[The architecture note](docs/architecture.md) describes the interfaces and
failure paths. [HANDOFF.md](HANDOFF.md) records the current state and next work.
[PLAN.md](PLAN.md) preserves the decision history. The next planned extension
is richer body language during speech, listening and model deliberation;
its open design decisions are in the [body language spec](.scratch/body-language/spec.md).

## Provenance and license

The original class project is preserved on the
[`v1` branch](https://github.com/jyp-studio/misty-llm-embodied-agent/tree/v1)
and at the `v1-class-project` tag under its original academic research
license. The current version is licensed under [Apache 2.0](LICENSE).
[NOTICE](NOTICE) attributes the retained Misty SDK code.

Misty II and its REST API are products of Misty Robotics. The project uses
MediaPipe for face perception, PocketSphinx for local wake detection and
OpenAI adapters for hosted speech and language services.
