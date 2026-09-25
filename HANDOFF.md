# HANDOFF — current state

Last updated: 2026-09-20 · branch `refactor/react-agent`

Read `PLAN.md` first for the full decision history. The concise current system
view is `docs/architecture.md`; ubiquitous language is in `CONTEXT.md`; the
approved social-runtime effort lives under `.scratch/social-react-runtime/`.

## Where the work stands

Social runtime tickets 01–15 are implemented, and the effort is complete. `SocialAgentRuntime` is the
highest product seam for the CLI, local Demo, and acceptance coverage:

1. `ScenarioInputAdapter` feeds a timed text Explicit Request with an injected
   clock.
2. The Attention Loop records the cue and opens one bounded ReAct Episode.
3. Existing Tool dispatch affects the simulated Misty and produces the typed
   Episode Journal.
4. Runtime output carries both Attention/Cue records and Episode Journals.
5. The Demo presents three runnable horizontal social scenarios whose
   human-readable results derive from current runtime records and Journals.
6. Offline scenario execution is visually and mechanically separate from the
   optional Live AI panel, so the no-key path no longer looks blocked by a
   hosted-model requirement.
7. Typed Trigger Evidence reaches the first Turn with source, time, facts,
   transcript, uncertainty and an optional selected image, before any Snapshot.
8. Model context preserves native assistant Tool calls and matching `tool`
   results. The OpenAI adapter disables parallel calls and rejects multiple
   calls rather than silently dropping extras.
9. Short public Decision Notes are typed Journal records and Demo Moments; no
   private reasoning or chain-of-thought is requested or stored.
10. Selected image evidence is strict base64, capped at 8 MiB decoded, and
    removed from completed runtime results; only its media type remains.
11. Active Episodes drain Cues at Turn boundaries into a bounded priority,
    freshness and deduplication queue; there is still only one Episode owner.
12. `LiveInputAdapter` locally gates VAD segments on Hey/Hi Misty, captures one
    bounded utterance, and invokes hosted ASR only after a wake match.
13. Audio block/segment queues have fixed capacities; wake, capture, ASR,
    backlog and audio-pipeline endings are typed Runtime records. Hosted ASR
    retries are disabled so one configured timeout remains one total bound.
14. The greeting Demo selects checked-in synthetic WAV fixtures and shows the
    current wake → capture → ASR → Episode → simulated effect → ending path.
15. `VisualInputAdapter` turns local, anonymous detections across a bounded
   temporal fixture into typed frame outcomes. Sustained gaze plus a wave may
   form Social Invitation Evidence; empty rooms, passersby and interrupted
   gaze remain quiet without calling the model.
16. A qualifying visual cue carries one selected JPEG crop into the first
   multimodal Turn. Raw periodic frames do not cross that boundary, and the
   completed Runtime result discards the crop bytes.
17. The greeting Demo also selects four synthetic visual timelines and shows
   frame-by-frame gate facts, selected Evidence metadata, the scripted model
   decision, simulated response, or the reason no Episode opened.
18. Sustained observable eye, mouth and head geometry on one anonymous track
   can form an uncertain Care Cue. The gate emits no emotion diagnosis and
   chooses no response Tool.
19. `observe_target` and `inspect_scene` expose cheap and expensive typed
   active-perception results with freshness and uncertainty; neither moves the
   robot.
20. The care Demo provides two synthetic timelines: sustained care-relevant
   geometry and a visual/verbal conflict where explicit words take priority.
   Both show Evidence, Decision Note, selected Tool, Observation and ending.

21. Local Skills expose metadata first, then typed activation/reference reads.
    Loaded guidance and permissions are scoped to one Episode, never scripts.
22. The care card's calming-support variant runs speak/listen/head expression
    with timed scripted speech and shows Skill state during Journal replay.
23. Bounded listen has explicit silence/unavailable/error/aborted results;
    live audio wiring shares the VAD owner and caps one ASR attempt.
24. Each Episode binds one anonymous Interaction Target from its Trigger
    Evidence. Perception Tools report and update visible/lost/reacquired on
    that track only; a closer or newer face is never a silent switch, and
    `approach` refuses a lost target. Snapshots carry the target as a fourth
    fact.
25. During an Episode, another person's Explicit Request is queued and the
    model is told once at a Turn boundary. The Episode ends when the model
    calls `done`; the queued request then opens its own Episode with its own
    target. Stale queued requests expire; bumper/e-stop still abort at once.
26. The A→B Demo card runs two scripted anonymous actors and shows target
    binding, the queued request, the handoff notice, the dequeue and both
    Episodes. Speaker attribution in that card is scripted, not localised.
27. Tools and the approach controller depend on one `Robot` interface that
    returns a typed `Effect`. `RealMistyAdapter` maps behaviours to vendor
    requests (hardware-unverified); `SimulatedMistyAdapter` holds pose, chest
    light, last speech and the measured distance, so a refused behaviour
    reaches the Observation and the storyboard as `ok: false` and no move.
    There is no recording robot; the Journal is the only behaviour record.
28. `approach` is target-aware: a reading carries distance, bearing,
    timestamp and uncertainty; the controller turns the chassis until the
    bearing is within tolerance, then closes by bounded Steps, each planned
    from a fresh reading. Head yaw plays no part. Readings without a bearing
    fail closed as `bearing_unavailable`, which is what the live distance
    pipeline produces today. Stale readings, the alignment budget, the Step
    cap and the wall-clock deadline are separate typed results, and the Tool
    result carries every motion with the reading it was planned from. The simulated adapter has a
    chassis heading and a relative-polar person; every turning and travel
    constant is a simulated or hardware-unverified value.
29. The greeting card's "過來陪我" script shows alignment, each Step with the
    distance and bearing it was planned from, the chassis heading and the
    untouched head yaw.
30. Every movement checkpoint, before the first motion, before each motion
    and at a fixed poll during it ending exactly at its end, asks whether a stop was
    requested and whether the hazard source says the base may move. A stop
    ends the call as `aborted` with no further command; a hazard halts the
    motors and ends it as `blocked`; a missing or stale hazard reading is
    `hazard_unavailable`, which is every real call today because no hazard
    signal reaches this process. Every result carries a reason the model can
    act on. The simulated world provides the scenario's hazard and departure
    timeline; the greeting card has a target-lost and a hazard case.
31. One Episode's local working context retains its Trigger Evidence, native
    Tool calls/results, Snapshots, later utterances and activated Skill
    instructions. `Session` and `run_episode` expose no cross-Episode memory
    injection point; the old summary/fact/exchange store was removed.
32. The optional `JsonlFile` keeps typed control-flow evidence but redacts
    Decision Notes, spoken Tool text, listened transcript, Snapshot speech and
    failure prose. Lossless `to_jsonl` remains for explicitly synthetic,
    provenance-labelled fixtures.
33. Demo responses are `no-store`. The A→B card labels the context retained
    inside A's Episode and the reset before B; it is still a freshly executed
    scripted simulation, not a real model or robot run.
34. `respect_boundary` is a typed model Tool: it halts the Robot and ends the
    Episode with `boundary_respected=True`. The persona tells the model to stop
    questions and avoid further approach after an explicit request for space;
    no transcript keyword matcher chooses the response.
35. `SocialAgentRuntime` then keeps only an anonymous track token and expiry.
    Same-track Care/Social cues receive typed `cue_suppressed` records;
    another track remains eligible, and a new Explicit Request records a
    bypass and opens immediately. TTL expiry, an empty visual scene, shutdown
    and run completion clear the state.
36. The care card's `respect-boundary` fixture shows the acknowledgement,
    controller halt, suppression countdown, suppressed cue and explicit
    bypass. Every decision and utterance is scripted and the robot is simulated.

37. The persona tells the model to answer in the person's language and to
    follow a change of language mid-Episode. The wake phrases stay English:
    `Hey Misty` and `Hi Misty`, with no Chinese one added.
38. For self-harm, medical danger or a request to be freed, the persona and
    an `emergency-boundaries` Skill tell the model to stay, say what it
    cannot do, and point at someone nearby or local emergency services —
    never a diagnosis, a promise of safety, a claim of having contacted
    anyone, or an offer of physical rescue. No Tool can reach off the robot,
    so the contact claim cannot be true whatever is said.
39. The care card has a Chinese high-risk case and an English rescue-limits
    case. `tests/boundary_audit.py` reads spoken output as properties and is
    proven able to fire offline; `tests/test_llm_live.py` runs the same audit
    against a real model and reports it, deselected by default.

40. The spec's fifteen situations are one declarative set in
    `misty_agent/acceptance.py`: each names the card and fixture it runs,
    whether an Episode may open, the records it must make observable, the
    Tools that would make it unsafe, and whether the base may move. The
    acceptance tests, the scripted `/scenarios/<card>/run` route and the
    Demo's recorder call the same `run_fixture`.
41. The Demo labels what a visitor is looking at — specification fixture,
    scripted run, recorded model run or live-model run — and every one of
    them carries the hardware-unverified note. Replay plays, pauses,
    restarts and scrubs across every Moment of every Episode in the run.
42. `tests/test_documentation_contract.py` pins one job per document and
    fails on a claim the code has retired.
43. The Demo page is in English and shows sixteen recorded hosted-model runs
    (`misty_agent/demo/recordings/`, made by
    `python -m misty_agent.demo.record`) instead of scripted runs. An
    animated simulated Misty draws each Tool call: speech bubble and mouth,
    arms, head, face, chest LED, wheels and approach distance, listening,
    scanning and Skill loading. The live panel plays on the same stage.
    Recording needs a key and costs a little; the suite never records.

Ticket 14 ends at `ab22bf5`; ticket 15 is the current implementation.

## Verification

Always use `.venv`, never bare `python3`:

```bash
.venv/bin/python -m pytest tests/ -q -rs
```

The default suite must make no hosted-model or network calls and must report
zero skips. MediaPipe needs a macOS OpenGL context; a restricted shell can fail
those tests even with the correct virtual environment, so run the final suite
outside that sandbox rather than accepting partial green.

To see the Demo:

```bash
.venv/bin/python -m misty_agent --demo
```

Pick a group and an example; it replays a recorded hosted-model run on the
animated simulated robot. The page is loopback-only and needs no API key.
To re-record the examples against the configured model (needs a key):

```bash
.venv/bin/python -m misty_agent.demo.record
```

## Evidence boundary

There is no Misty II available to this project, and there never will be. The
wake path has run only with synthetic WAV files. The visual invitation path has
run only with synthetic frame timelines and scripted local detections. Both use
fake clocks, scripted model decisions, and simulated robot effects. MediaPipe
is a local detector implementation but has not validated the temporal gate
against a real camera. The vendor audio composition is wired to the same
`LiveInputAdapter`, but it has never received Misty audio. Physical behaviour,
timing, threshold calibration, association accuracy, and reliability are
hardware-unverified.

Handoff is target-aware only in the sense of anonymous track tokens; there is
no face identity and no sound-source direction, and the A→B card's speaker
attribution is scripted. Target-aware approach and its safety checkpoints
are verified only against the simulated relative-polar world with
scenario-provided hazard state: no bearing and no hazard signal has ever come
from a Misty II, so the live path fails closed at the first checkpoint, and
passing these tests is not a hardware safety certification. The care path is
supported only by synthetic temporal frames and scripted model decisions; it
is not validated emotion recognition. The A-to-B card runs only scripted text
actors. A vendor hazard subscription for the real Session does not exist yet.

Configured hosted ASR/VLM/LLM may receive bounded selected Evidence for the
current Episode; ephemeral storage does not mean no external transfer occurs.
No real-user media or transcript is written by the Demo.

## Next ticket

The social-runtime effort under `.scratch/social-react-runtime/` is
finished: all fifteen tickets are resolved and the fifteen acceptance
situations run in the default suite. `PLAN.md` §7 holds what comes after it.

Two rules to preserve in anything built next. `Session.episode()` is an
internal one-Episode dependency: providers enter at `SocialAgentRuntime`
through the shared `InputSource` seam, and
`tests/test_acceptance_scenarios.py` fails if a second caller appears.
Built-in scenarios are run by `misty_agent.acceptance.run_fixture` and
nothing else, so the Demo's recordings and the tests cannot drift apart.

## Local-work warning

At the time of this handoff, `.env.example`, `CONTEXT.md`, `architecture.svg`,
`docs/measurements/m4-harness-report.md`, `tests/conftest.py`,
`.scratch/social-react-runtime/`, and `docs/adr/` contained user-owned work
outside ticket 01. Do not overwrite or sweep those changes into an unrelated
commit.
