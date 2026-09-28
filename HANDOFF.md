# HANDOFF: current state

Last updated: 2026-09-28 · branch `main`

This file covers where the work stands. The concise view of the system is
`docs/architecture.md`, the vocabulary is in `CONTEXT.md`, specifications live
under `.scratch/`, and `PLAN.md` records every decision and the reasons for it.

## Where the work stands

The project is published at `jyp-studio/misty-llm-embodied-agent`. `main` is
the current version and the repository's default branch. The earlier class
project is kept, unchanged, as the `v1` branch and the `v1-class-project` tag
(`PLAN.md` §16.68). The social runtime effort under
`.scratch/social-react-runtime/` is complete: all fifteen tickets are resolved
and the fifteen acceptance situations run in the default suite.

### The runtime

1. `SocialAgentRuntime` is the highest product seam for the command line, the
   demo and the acceptance tests. Text, audio and visual providers enter
   through one `InputSource` seam.
2. The Attention Loop turns input into Interaction Cues (Explicit Request,
   Social Invitation, Care Cue), queues them by priority, freshness and
   deduplication, and gives one bounded ReAct Episode at a time ownership of
   model context and robot effects.
3. The audio path gates locally on "Hey Misty" and "Hi Misty" before any
   hosted transcription. The visual gates form a Social Invitation from a
   sustained look and a wave, and an uncertain Care Cue from sustained
   observable face and posture geometry. Neither gate diagnoses emotion.
4. Typed Trigger Evidence reaches the first Turn. The hosted adapter uses the
   Responses API with reasoning set to `low`, keeps native tool call identity,
   rejects more than one call in a Turn, stores nothing with the provider, and
   passes encrypted reasoning items between the Turns of one Episode only.
5. Each Episode binds one anonymous Interaction Target. Another person's
   Explicit Request is queued and announced at a Turn boundary, and opens its
   own Episode after `done`. Social context is discarded with its Episode.
6. The Turn cap is twelve. Short public Decision Notes are typed Journal
   records; private reasoning is never requested or stored.

### Tools and control

7. Sixteen Tools are registered: `speak`, `listen`, `wait`, `approach`,
   `look_around`, `observe_target`, `inspect_scene`, `move_head`, `move_arms`,
   `change_led`, `display_image`, `play_audio`, `activate_skill`,
   `read_skill_resource`, `respect_boundary` and `done`.
8. `approach` takes one argument, `keep`, with the values `close` (60 cm, the
   default), `comfortable` (100 cm) and `far` (150 cm). The closed loop aligns
   the chassis, moves in bounded steps from fresh readings and stops at the
   first checkpoint that reports a stop request or a hazard. Readings without
   a bearing fail closed, which is what the live distance pipeline produces.
9. `wait(seconds)` keeps still for one to thirty seconds. Only a stop cuts it
   short; speech heard meanwhile arrives on the following Snapshot.
10. In text scenarios, `observe_target` and `inspect_scene` report the person
    where the scenario placed them, labelled as simulated, through
    `PlacedPersonPerception`. Visual fixtures still look through their gate.
11. Tools and the controller depend on one `Robot` interface. The real
    adapter maps behaviours to vendor requests and has never run on a robot;
    the simulated adapter holds pose, chest light, speech and distance.

### Boundaries

12. Misty follows the person's language, including a change of language
    partway through. For self-harm, medical danger or a request to be freed,
    the persona and the `emergency-boundaries` Skill keep it present, honest
    about its limits and pointing at local help. `respect_boundary` halts and
    ends the Episode, and the runtime then suppresses repeated non-explicit
    cues from the same anonymous track for a short time.
13. `tests/boundary_audit.py` reads spoken output for diagnosis, promises of
    safety and claims of contact. It runs over the scripted scenarios, every
    recorded demo run and, when selected, the live model suite.

### The demo

14. `python -m misty_agent --demo` serves a loopback page with fifteen
    recordings of `gpt-5.6-luna` from 2026-09-25, in five groups: noticing
    someone, talking, moving, care, and knowing its limits. Recordings are
    stored data in `misty_agent/demo/recordings/`; the playback is computed
    when a recording is served, so a presentation change never needs a paid
    re-recording.
15. The stage stands alone by default and the full conversation opens in a
    drawer on its right, which the page remembers. The plain telling hides
    the loop's bookkeeping and the hearing steps (wake, capture,
    transcription), keeps the step where a visual gate made up its mind, and
    shows each Decision Note as a thought cloud on a step of its own. Scene
    titles such as "Talking with B" are frames of their own. Status labels sit
    in the stage's top left, distance appears as a badge on the floor, and an
    action is drawn with the pose its Observation confirmed.
16. The recordings predate `PlacedPersonPerception`, so the `come-closer`
    recording still ends with "I can't see you right now". The fix will show
    in the next recording.
17. Three scripts exist for examples that are not on the demo yet:
    `back-off`, `timer` and `show-off`. Each has authored decisions and
    tests. They stay off the page until the body-language work.

## Verification

Always use `.venv`, never a bare `python3`:

```bash
.venv/bin/python -m pytest tests/ -q -rs
```

The default suite must make no hosted-model or network calls and must report
zero skips. MediaPipe needs a macOS OpenGL context, so a restricted shell can
fail those tests even with the correct environment; run the final suite
outside such a sandbox rather than accepting a partial pass.

To see the demo:

```bash
.venv/bin/python -m misty_agent --demo
```

To record the demo examples again (needs a key in `OPENAI_API_KEY` or
`OAI_CONFIG_LIST.json`, never in `.env`):

```bash
.venv/bin/python -m misty_agent.demo.record
```

## Evidence boundary

No Misty II has ever been available to this project, and none will be. The
wake path has run only with synthetic WAV files and the visual gates only
with synthetic frame timelines. Those timelines carry authored detector
signals (where a person stands, whether they look, where the hand is) over
plain drawn frames, so no face detector runs on them, and the one crop the
model receives in a visual example shows a grey rectangle rather than a
person. Scenario tests use fake clocks, authored model decisions and
simulated robot effects. The demo recordings are real model decisions over
the same simulated inputs, which makes them evidence about one model on one
day and nothing more. Physical behaviour, timing, calibration and reliability
are hardware-unverified, and passing the movement safety tests is not a
hardware safety certification.

Speaker attribution in the two-person example is scripted: there is no face
identity and no sound-source direction. Configured hosted services may receive
bounded Evidence for the current Episode; ephemeral storage does not mean no
external transfer occurs.

## Next ticket

There is no open ticket. The next piece of work is the body-language design
in `.scratch/body-language/spec.md`. Grill its open questions before writing
any code.

Two rules to preserve in anything built next. `Session.episode()` is an
internal one-Episode dependency: providers enter at `SocialAgentRuntime`
through the shared `InputSource` seam, and
`tests/test_acceptance_scenarios.py` fails if a second caller appears.
Built-in scenarios are run by `misty_agent.acceptance.run_fixture` and nothing
else, so the demo's recordings and the tests cannot drift apart.
