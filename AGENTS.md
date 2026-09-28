# misty-embodied-agent

An LLM-driven embodied agent for the Misty II social robot, rebuilt from a
class project and published as open source. `main` is the current version;
the class project is kept as the `v1` branch.

**Read `HANDOFF.md` first** for where the work stands and what comes next,
then `docs/architecture.md` for the system as it is. `PLAN.md` is the full
decision record, written in Chinese and in the order decisions were made.
Code, tests and docs cite it by section (`§16.7`), so read the cited section
when you need the reason behind something, and keep its section numbers
stable.

The hard premise that shapes every technical choice: **there is no robot, and
there never will be.** Nothing here has run against hardware. Anything not
verified in simulation must say so.

## Running anything

**Use `.venv`. Never bare `python3`.**

```bash
.venv/bin/python -m pytest tests/ -q
```

`python3` on this machine resolves to a miniforge 3.10 install that has no
mediapipe and no opencv. The trap is that `python3 -m pytest tests/` still
reports green — the perception tests skip rather than fail, so a wrong
interpreter looks like a healthy one. **The tell is the skip count**: run with
`-rs`, and if anything reports "not importable — run under the project venv",
you are on the wrong interpreter. Under `.venv` nothing in `tests/` skips.

`.venv` is Python 3.11, matching the Docker target in `PLAN.md`, with the
dependencies actually installed.

If `.venv` is missing: `python3.11 -m venv .venv && .venv/bin/python -m pip
install --only-binary=:all: -r requirements.txt`. Run **one** pip process at a
time — two concurrent installs against the same venv deadlock silently.

## Agent skills

### Issue tracker

Issues and specs live as markdown under `.scratch/`, one directory per feature.
See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, used verbatim. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root.
See `docs/agents/domain.md`.
