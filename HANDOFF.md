# HANDOFF — current state

Last updated: 2026-09-13 · branch `refactor/react-agent`

Read `PLAN.md` first for the full decision history. The concise current system
view is `docs/architecture.md`; ubiquitous language is in `CONTEXT.md`; the
approved social-runtime effort lives under `.scratch/social-react-runtime/`.

## Where the work stands

Social runtime tickets 01–05 are implemented. `SocialAgentRuntime` is the
highest product seam for the CLI, local Demo, and acceptance coverage:

1. `ScenarioInputAdapter` feeds a timed text Explicit Request with an injected
   clock.
2. The Attention Loop records the cue and opens one bounded ReAct Episode.
3. Existing Tool dispatch affects the simulated Misty and produces the typed
   Episode Journal.
4. Runtime output carries both Attention/Cue records and Episode Journals.
5. The Demo presents three horizontal social scenarios. Greeting is the only
   runnable card; its human-readable result is derived from the current
   runtime records and Journal. Crying and A-to-B are visibly locked previews
   for tickets 06 and 08, with no executable scripted substitute.
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

Ticket 04 ends at `8af7ba6`; ticket 05 is the current implementation.

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

Choose the greeting card, select a Hey/Hi Misty WAV or a visual timeline, and
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

The current social runtime does not yet implement Care Cue classification,
identity-aware handoff, Skills, or target-aware movement.
The crying and A-to-B cards are roadmap previews only. They do not inject a
Care Cue or person labels and cannot be run until their corresponding vertical
tickets implement the capability.

## Next ticket

Continue with `.scratch/social-react-runtime/issues/06-*.md`. Preserve the
architecture rule that
`Session.episode()` is an internal one-Episode dependency; providers enter at
`SocialAgentRuntime` through the shared `InputSource` seam.

## Local-work warning

At the time of this handoff, `.env.example`, `CONTEXT.md`, `architecture.svg`,
`docs/measurements/m4-harness-report.md`, `tests/conftest.py`,
`.scratch/social-react-runtime/`, and `docs/adr/` contained user-owned work
outside ticket 01. Do not overwrite or sweep those changes into an unrelated
commit.
