# HANDOFF — current state

Last updated: 2026-09-10 · branch `refactor/react-agent`

Read `PLAN.md` first for the full decision history. The concise current system
view is `docs/architecture.md`; ubiquitous language is in `CONTEXT.md`; the
approved social-runtime effort lives under `.scratch/social-react-runtime/`.

## Where the work stands

Social runtime tickets 01 and 02 are implemented. `SocialAgentRuntime` is the
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

Ticket 01's completed follow-up is `b749d6b`; ticket 02 is the current HEAD.

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

Choose the greeting card and select `執行離線模擬`. The page is loopback-only;
the run is deterministic and needs no API key. Its input and model decisions
are predefined, while Runtime, Tool dispatch and Journal execute afresh.

## Evidence boundary

There is no Misty II available to this project, and there never will be. The
new path has run only with `ScenarioInputAdapter`, fake clocks, scripted model
decisions, and simulated robot effects. Retained real-driver code has request
contract tests only; physical behaviour, timing, calibration, and safety are
hardware-unverified.

The current social runtime does not yet implement wake detection, visual cue
classification, cue queues,
identity-aware handoff, Skills, target-aware movement, or a live input adapter.
The crying and A-to-B cards are roadmap previews only. They do not inject a
Care Cue or person labels and cannot be run until their corresponding vertical
tickets implement the capability.

## Next ticket

Continue with `.scratch/social-react-runtime/issues/03-*.md`. Preserve the
architecture rule that
`Session.episode()` is an internal one-Episode dependency; new behaviour is
accepted at `SocialAgentRuntime` through `ScenarioInputAdapter`.

## Local-work warning

At the time of this handoff, `.env.example`, `CONTEXT.md`, `architecture.svg`,
`docs/measurements/m4-harness-report.md`, `tests/conftest.py`,
`.scratch/social-react-runtime/`, and `docs/adr/` contained user-owned work
outside ticket 01. Do not overwrite or sweep those changes into an unrelated
commit.
