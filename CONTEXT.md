# misty-embodied-agent

An LLM-driven ReAct agent for the Misty II social robot. This glossary fixes
the words the project uses for its own concepts, because several of them
collide with each other and with the vendor's vocabulary.

`PLAN.md` holds the decisions and the evidence. This file holds only the
language, and no implementation detail.

## Language

### The agent loop

**Episode**:
One run from an external trigger until the agent is idle again, guaranteed to
terminate in bounded time. Its internal phases are not part of the definition.
_Avoid_: session, conversation, interaction, cycle

**Turn**:
One iteration of the ReAct loop — a single model decision and the tool call it
produces. Bounded by `max_turns_per_episode`.
_Avoid_: step, iteration, round

**Step**:
One commanded movement issued by the control layer. A single Turn may produce
many Steps.
_Avoid_: move, action, increment

**Tool**:
One capability the agent may invoke, declared to the model and dispatched by
the registry. A Tool is the agent's whole vocabulary of action — anything it
cannot do through one, it cannot do.
_Avoid_: skill, function, action, command

**Observation**:
What comes back to the model after a Tool runs: that Tool's own result,
plus a Snapshot. One per Turn.
_Avoid_: result, feedback, response

**Snapshot**:
The three cheap perception facts attached to every Observation — how far away
the subject is, whether they are visible, and whether anything new was heard.
Cheap is definitional: a Snapshot costs no extra model call and no extra
waiting, which is why it can ride along on every Turn.
_Avoid_: perception data, state, context

**Journal**:
The agent's own typed record of what happened during an Episode. Renderers and
tests are subscribers to it; it is never a channel the robot pushes into.
_Avoid_: event stream, event log, trace, telemetry

**Event**:
A signal Misty pushes to us over its websocket — bump sensors, touch, faces.
The vendor's word, kept for the vendor's concept only. An Event may be recorded
as a Journal entry, but the two are not the same thing.
_Avoid_: robot event, sensor event, notification

**Exchange**:
One thing the subject said and what the robot said back. The unit memory is
made of, and deliberately **not** the model's message list — that list is one
Episode's working context and is discarded with it, while Exchanges outlive
the Episode they came from.
_Avoid_: message, turn, history, conversation

### Perception and measurement

**Reading**:
One distance measurement carrying the moment its frame entered this process and
the moment detection finished. It never carries camera exposure time, which is
not observable without hardware.
_Avoid_: sample, measurement, observation, distance

**Trace**:
Everything one harness replay produced, together with the conditions it ran
under. A measurement artefact, not a record of agent behaviour.
_Avoid_: recording, log, run

**Trajectory**:
A script of ground-truth distance over time, used to drive a replay. A pure
function of time, decided before the replay runs.
_Avoid_: path, route, course

**Measurement**:
A number obtained by observing this process running real code on real inputs.
Only Measurements carry thresholds the code must pass.
_Avoid_: benchmark, metric, reading

**Sweep**:
A deterministic exploration of a parameter nobody has measured and nobody can
measure without hardware. A Sweep is reported, never asserted against.
_Avoid_: test, benchmark, experiment

**Envelope**:
The boundary a Sweep locates — the parameter value at which the controller
stops converging, together with how precisely the grid pinned it down.
_Avoid_: limit, threshold, bound, margin

**Storyboard**:
One Journal arranged for a screen: an ordered sequence of Moments, plus how
the Episode began and ended. Derived and never authored — a pure function of a
Journal, decided in Python so that what a page shows is something a test can
reach.
_Avoid_: view, view model, render, timeline, UI state

**Moment**:
One record of a Journal, ready to draw: what it says, what kind of moment it
is, the fields behind the sentence, and the whole robot as it stood just
after. Its unit is one record, not one Turn.
_Avoid_: frame, entry, item, event
