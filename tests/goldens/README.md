# Golden Journals

One file per way an Episode can end. Each is a Journal that ticket 07's ReAct
loop must be able to produce.

**The original four were written before the loop existed.** That is the point
of them, and `git log` is the evidence: they are derived from
`.scratch/m7-react-and-journal/spec.md`, not from whatever the implementation
turned out to do. The fifth was added when M7 #13 introduced runtime `error`
as a named outcome; it pins that closure path while leaving all four original
files byte-for-byte unchanged.

## The rule

> **If the implementation cannot produce one of these, changing which side
> gives way is a decision, and it goes in `PLAN.md`.**

Quietly editing a golden so the code passes is the failure this whole
arrangement exists to prevent. Editing one is allowed; editing one without
saying so is not.

**It has been invoked five times**, across tickets 04 to 08:

| What | Which side gave way |
|---|---|
| The refusal wording for an out-of-range angle | the implementation (§15.7) |
| `t`: the hand-written 2 ms bookkeeping gaps | the goldens (§15.21) |
| `look_around`'s result gaining `found_at_yaw` | the goldens (§15.22) |
| The turn cap rising from 5 to 8 | the goldens (§15.19) |
| `t` again, for the aborted file, in ticket 08 | the golden (§15.24) |

All four files are now on the timing rule below. The aborted one came last
because only ticket 08 can produce a `stop_requested`, and retiming a golden
nobody can yet regenerate would have been a change nobody could check.

Ticket 03 wrote sixty assertions about these files' *content*, and
fifty-nine held across those edits. **That is a weaker check than it sounds**
and it is not what verified them: every `t` assertion in `test_goldens.py` is
relational — time never goes backwards, the ending follows the stop — so a
wholesale retiming passes it by construction, and nothing there looks at a
`look_around` result at all. What actually checked the edits was a
field-by-field diff against the committed originals (`PLAN.md` §15.21).

## How the timestamps work

> **`t` advances only when something really waits** — a model call, or a Tool
> that sleeps. Records the loop writes in between share a timestamp, because
> under an injected clock no time has passed between them.

So every `t` here can be recomputed by hand from the file's own numbers: add
each `model_called.latency_ms` and each Tool's own waiting to the Turn it
belongs to. `tests/test_react.py::test_every_timestamp_follows_from_a_real_wait`
checks the rule rather than trusting it.

The earlier version of these files charged a plausible-looking 2 ms to each
record and 4 ms to starting a Turn. Nothing reproduces that: the `Clock` the
spec specifies advances on `sleep` and dispatch does not sleep, so those gaps
are zero in any deterministic run. §15.21 has the full argument, including
what this costs — "byte-for-byte comparable" is now "equal in structure and
every non-timing field, with `t` following a rule you can check on paper".

## The five

| File | Ends because | `outcome` |
|---|---|---|
| `episode_ends_on_the_first_turn.jsonl` | the model chose to stop immediately | `done` |
| `episode_ends_after_several_turns.jsonl` | the model chose to stop after composing an action out of several Tools | `done` |
| `episode_hits_the_turn_limit.jsonl` | the model never chose to stop and the cap did it | `turn_limit` |
| `episode_is_aborted.jsonl` | someone pressed the foot bumper | `aborted` |
| `episode_fails_during_model_call.jsonl` | the model collaborator raised before returning a decision | `error` |

**Five files, four outcomes.** Ending on the first Turn and ending after
several are both the model choosing to stop; they are separate files because
they are separate *paths* through the loop, not separate endings.

The error file was added by M7 #13 after `error` became a named outcome. The
original four still predate the loop and remain byte-for-byte unchanged; the
fifth closes the spec's requirement that every current outcome has a golden.

## Decisions these files pin

Reading them is how you find out what the loop is supposed to do. Three
choices are visible only here:

**`done` produces a `tool_called` but no `observation`.** An Observation is
what the model reads to decide the next Turn. After `done` there is no next
Turn, so recording one would be recording something nobody reads.

**The turn limit lets the last Turn finish.** The cap stops a *sixth* Turn
from starting; it does not cut the fifth short. So the limit file has five
complete Turns and then the ending.

**An abort does not discard work already done, but neither does it claim the
work succeeded.** The stop arrives from another thread part way through a Tool
call, and Python cannot interrupt a call that has not returned. So the Tool
finishes and its Observation is recorded — but the bumper has halted the
motors, so what it reports is `timeout`, not `arrived`. An `arrived` after a
stop would say the robot completed a drive it was forbidden to finish.

The gap between `stop_requested` and `episode_finished` is the interrupt
latency, which is exactly why those are two records rather than one
(`PLAN.md` §15.3).

That last one is the least certain of the three. It is what ticket 08 will
have to confirm, and if it turns out otherwise, this file changes **and
`PLAN.md` says why**.

## What else these files pin

`episode_hits_the_turn_limit.jsonl` runs to eight Turns, not five, because
the cap is eight — derived in `PLAN.md` §15.19 from the longest gesture the
script this replaces could perform, since §4 claims composition replaces it.
Its `look_around` results carry `found_at_yaw`, which is §15.22.

`episode_ends_after_several_turns.jsonl` carries a **refused Tool call** and a
Tool that **did not succeed** — the model asks for an angle the type will not
allow, and later an `approach` that ends in `lost_user`. Without those, ticket
04's rejection path and ticket 07's failure branch would have nothing to be
checked against, and the spec asks for both.

Every number in these files follows from something. `estimated_speech_ms` is
`PLAN.md` §4's estimator (`words / 2.2 + 0.5`, capped at 12 s) and nothing
else — §15.4 records that Misty's TTS returns no timing at all, so an invented
figure would be a number from nowhere in a file whose whole claim is to be
derived. `steps` is the sum of the drives that actually happened. A model
call takes exactly the latency it reports. The turn-limit file stops at the
configured cap rather than at a hard-coded five. Each of those is asserted, so
a golden cannot be quietly replaced with one that merely looks plausible.
