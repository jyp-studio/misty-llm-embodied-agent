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

**Attention Loop**:
The continuous, low-cost watch for Interaction Cues while the agent is idle or
an Episode is active. It may open an Episode while idle; while active it only
manages queued Cues and never chooses the robot's response.
_Avoid_: perception phase, outer ReAct loop, monitor loop

**Trigger Evidence**:
The modality-specific evidence explaining why the Attention Loop opened an
Episode. It is available before the first Turn and is not a Snapshot.
_Avoid_: initial observation, trigger string, context

**Turn**:
One iteration of the ReAct loop — a single model decision and the tool call it
produces. Bounded by `max_turns_per_episode`.
_Avoid_: step, iteration, round

**Decision Note**:
A short, non-sensitive statement of what a Tool choice is intended to achieve.
It is public explanation, not the model's private reasoning or chain of thought.
_Avoid_: thought, reasoning trace, chain of thought, rationale

**Step**:
One commanded movement issued by the control layer. A single Turn may produce
many Steps.
_Avoid_: move, action, increment

**Tool**:
One typed, bounded capability the agent may invoke, declared to the model and
dispatched by the registry. Tools are the only way an Episode affects or reads
the world.
_Avoid_: function, action, command

**Skill**:
A reusable set of instructions that guides the agent in combining Tools toward
a goal. Loading a Skill does not create another agent loop or bypass Tool
validation and the control layer.
_Avoid_: tool, function, command

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
made of, and deliberately **not** the model's message list. Exchanges remain
available within their Episode, but are not retained as personal memory across
Episodes unless a future consent-based memory policy explicitly allows it.
_Avoid_: message, turn, history, conversation

### Social attention

**Interaction Cue**:
Evidence that a person may want or benefit from the robot's attention. It is
classified as an Explicit Request, Care Cue, or Social Invitation.
_Avoid_: anomaly, abnormality, unusual event

**Explicit Request**:
A deliberate attempt to engage the robot, such as addressing it by its wake
phrase or making an unambiguous request for help.
_Avoid_: command, wake event

**Care Cue**:
Evidence that a person may benefit from concern, without assuming that they
want help or physical proximity.
_Avoid_: abnormal emotion, distress diagnosis

**Social Invitation**:
Evidence that a person may welcome low-stakes social engagement, such as
looking toward the robot and waving or sustaining a smile.
_Avoid_: positive anomaly, help request

**Interaction Target**:
The one person an Episode is currently about. The target may be lost and
reacquired, but is never silently replaced by another visible person; its
anonymous identity expires with the Episode.
_Avoid_: face, user, nearest person, subject

**Cue Suppression**:
A short-lived refusal to reopen an Episode from the same anonymous person's
non-explicit cues after a decline or completed interaction. It is not personal
memory, and a new Explicit Request always bypasses it.
_Avoid_: ignore list, user cooldown, remembered refusal

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

### Verification

**Acceptance Scenario**:
One representative social situation used to inspect the agent's observable
decisions, Tool use, and outcome. It demonstrates intended capability without
being a benchmark or a unit test for one code path.
_Avoid_: benchmark, model test, unit test

### The screen

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
