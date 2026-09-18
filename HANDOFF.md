# HANDOFF — current state

Last updated: 2026-09-18 · branch `refactor/react-agent`

Read `PLAN.md` first for the full decision history. The concise current system
view is `docs/architecture.md`; ubiquitous language is in `CONTEXT.md`; the
approved social-runtime effort lives under `.scratch/social-react-runtime/`.

## Where the work stands

Social runtime tickets 01–08 are implemented. `SocialAgentRuntime` is the
highest product seam for the CLI, local Demo, and acceptance coverage:

1. `ScenarioInputAdapter` feeds a timed text Explicit Request with an injected
   clock.
2. The Attention Loop records the cue and opens one bounded ReAct Episode.
3. Existing Tool dispatch affects the simulated Misty and produces the typed
   Episode Journal.
4. Runtime output carries both Attention/Cue records and Episode Journals.
5. The Demo presents three horizontal social scenarios. Greeting and care are
   runnable; their human-readable results derive from current runtime records
   and Journals. A-to-B remains a visibly locked ticket 08 preview.
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

Ticket 07 ends at `446be12`; ticket 08 is the current implementation.

## Verification

Always use `.venv`, never bare `python3`:

```bash
.venv/bin/python -m pytest tests/ -q -rs
```

The default suite must make no hosted-model or network calls and must report
zero skips. MediaPipe needs a macOS OpenGL context; a restricted shell can fail
those tests even with the correct virtual environment, so run the final suite
outside that sandbox rather than accepting partial green.

To inspect the no-key tracer bullet:

```bash
.venv/bin/python -m misty_agent --demo
```

Choose the greeting or care card, select a WAV or visual timeline, and
select `執行離線模擬`. The page is loopback-only and needs no API key. The
selected local gate, Runtime, Tool dispatch and Journal execute afresh; visual
detector signals, ASR transcripts and model decisions are explicitly scripted.

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

The current social runtime does not yet implement target-aware movement.
Handoff is target-aware only in the sense of anonymous track tokens; there is
no face identity and no sound-source direction, and the A→B card's speaker
attribution is scripted. The care path is supported only by synthetic
temporal frames and scripted model decisions; it is not validated emotion
recognition. The A-to-B card runs only scripted text actors; distance
readings used by `approach` are still not target-specific until ticket 10.

## Next ticket

Continue with `.scratch/social-react-runtime/issues/09-*.md`. Preserve the
architecture rule that
`Session.episode()` is an internal one-Episode dependency; providers enter at
`SocialAgentRuntime` through the shared `InputSource` seam.

## Local-work warning

At the time of this handoff, `.env.example`, `CONTEXT.md`, `architecture.svg`,
`docs/measurements/m4-harness-report.md`, `tests/conftest.py`,
`.scratch/social-react-runtime/`, and `docs/adr/` contained user-owned work
outside ticket 01. Do not overwrite or sweep those changes into an unrelated
commit.
