# Golden Journals

One file per way an Episode can end. Each is a Journal that ticket 07's ReAct
loop must be able to produce.

**These were written before the loop existed.** That is the point of them, and
`git log` is the evidence: they are derived from
`.scratch/m7-react-and-journal/spec.md`, not from whatever the implementation
turned out to do. A schema written alongside its only producer ends up
describing the producer, and the assertions built on it end up agreeing with
the code by construction.

## The rule

> **If the implementation cannot produce one of these, changing which side
> gives way is a decision, and it goes in `PLAN.md`.**

Quietly editing a golden so the code passes is the failure this whole
arrangement exists to prevent. Editing one is allowed; editing one without
saying so is not.

## The four

| File | Ends because | `outcome` |
|---|---|---|
| `episode_ends_on_the_first_turn.jsonl` | the model chose to stop immediately | `done` |
| `episode_ends_after_several_turns.jsonl` | the model chose to stop after composing an action out of several Tools | `done` |
| `episode_hits_the_turn_limit.jsonl` | the model never chose to stop and the cap did it | `turn_limit` |
| `episode_is_aborted.jsonl` | someone pressed the foot bumper | `aborted` |

**Four files, three outcomes.** Ending on the first Turn and ending after
several are both the model choosing to stop; they are separate files because
they are separate *paths* through the loop, not separate endings.

## Decisions these files pin

Reading them is how you find out what the loop is supposed to do. Three
choices are visible only here:

**`done` produces a `tool_called` but no `observation`.** An Observation is
what the model reads to decide the next Turn. After `done` there is no next
Turn, so recording one would be recording something nobody reads.

**The turn limit lets the last Turn finish.** The cap stops a *sixth* Turn
from starting; it does not cut the fifth short. So the limit file has five
complete Turns and then the ending.

**An abort does not discard work already done.** The stop arrives from another
thread part way through a Tool call, and Python cannot interrupt a call that
has not returned. So the Tool completes, its Observation is recorded, and only
then does the Episode end — with `outcome="aborted"`. The gap between
`stop_requested` and `episode_finished` is the interrupt latency, which is
exactly why those are two records rather than one (`PLAN.md` §15.3).

That last one is the least certain of the three. It is what ticket 08 will
have to confirm, and if it turns out otherwise, this file changes **and
`PLAN.md` says why**.
