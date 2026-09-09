# HANDOFF — current state

Last updated: 2026-09-09 · branch `refactor/react-agent`

Read `PLAN.md` first for the full decision history. The concise current system
view is `docs/architecture.md`; ubiquitous language is in `CONTEXT.md`; the
approved social-runtime effort lives under `.scratch/social-react-runtime/`.

## Where the work stands

Social runtime ticket 01 is implemented. `SocialAgentRuntime` is now the
highest product seam for the CLI, local Demo, and acceptance coverage. Its
first tracer bullet is deliberately narrow:

1. `ScenarioInputAdapter` feeds a timed text Explicit Request with an injected
   clock.
2. The Attention Loop records the cue and opens one bounded ReAct Episode.
3. Existing Tool dispatch affects the simulated Misty and produces the typed
   Episode Journal.
4. Runtime output carries both Attention/Cue records and Episode Journals.
5. The Demo presents three horizontal social scenarios: greeting, a scripted
   crying Care Cue, and a scripted A-to-B handoff. Each card uses a shared
   acceptance declaration, displays its runtime trace, and replays the
   completed Journal.
6. Offline scenario execution is visually and mechanically separate from the
   optional Live AI panel, so the no-key path no longer looks blocked by a
   hosted-model requirement.

The implementation commit is `7bd0a02`; review hardening starts at `1ac7b31`,
and the current HEAD includes the follow-up resolution check.

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

Choose one of the three illustrated cards and select `執行離線模擬`. The page
is loopback-only; all three card runs are deterministic and need no API key.

## Evidence boundary

There is no Misty II available to this project, and there never will be. The
new path has run only with `ScenarioInputAdapter`, fake clocks, scripted model
decisions, and simulated robot effects. Retained real-driver code has request
contract tests only; physical behaviour, timing, calibration, and safety are
hardware-unverified.

The initial social runtime does not yet implement wake detection, visual cue
classification, Trigger Evidence beyond the explicit input, cue queues,
identity-aware handoff, Skills, target-aware movement, or a live input adapter.
The crying and A-to-B cards inject their Care Cue/person labels; they are UI
acceptance stories, not evidence that those recognizers exist. Those are
separate vertical tickets rather than implied capabilities.

## Next ticket

Continue with `.scratch/social-react-runtime/issues/02-*.md` only after ticket
01's two-axis review commit is present. Preserve the architecture rule that
`Session.episode()` is an internal one-Episode dependency; new behaviour is
accepted at `SocialAgentRuntime` through `ScenarioInputAdapter`.

## Local-work warning

At the time of this handoff, `.env.example`, `CONTEXT.md`, `architecture.svg`,
`docs/measurements/m4-harness-report.md`, `tests/conftest.py`,
`.scratch/social-react-runtime/`, and `docs/adr/` contained user-owned work
outside ticket 01. Do not overwrite or sweep those changes into an unrelated
commit.
