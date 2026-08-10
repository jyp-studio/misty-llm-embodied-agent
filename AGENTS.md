# misty-embodied-agent

An LLM-driven embodied agent for the Misty II social robot, being refactored
from a class project into a portfolio piece.

**Read `PLAN.md` first.** It is the full specification and decision record, and
it is self-contained — a fresh session needs no other context. `HANDOFF.md`
covers only "where the work stands right now".

The hard premise that shapes every technical choice: **there is no robot, and
there never will be.** Nothing here has run against hardware. Anything not
verified in simulation must say so.

## Agent skills

### Issue tracker

Issues and specs live as markdown under `.scratch/`, one directory per feature.
See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical roles, used verbatim. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root.
See `docs/agents/domain.md`.
