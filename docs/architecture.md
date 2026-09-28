# Current architecture

The product boundary is `SocialAgentRuntime`.  A finite scenario and a future
live adapter both satisfy the same `InputSource` interface; neither the Demo
nor an acceptance test opens a ReAct Episode directly.

```text
ScenarioInputAdapter ───┐
LiveInputAdapter ───────┼─> SocialAgentRuntime / Attention Loop
VisualInputAdapter ─────┘          │ one selected cue at a time
  ▲                              │
  │ typed input + audio records  │
AudioStream (bounded queues)     │
  │ VAD Segment                  │
local Hey/Hi Misty detector      │
  │ only after wake              │
bounded capture → hosted ASR ────┘
                                │ bounded priority queue while active
                                v
                         Session.episode()
                                │
                   typed Trigger Evidence
                                │ first Turn
                                v
          bounded ReAct + native Tool-call / Tool-result protocol
                       │       ├─ observe_target (cheap)
                       │       └─ inspect_scene (expensive)
                                │
                 simulated Misty / real drivers*
                                │
              typed Episode Journal + robot effects

SocialAgentRuntime ──> Attention/Cue records + Episode Journals
                                              │
                                              v
                                      Demo Storyboard replay
```

`ScenarioInputAdapter` supports ordered `ScheduledInput` wrappers around all
three Cue kinds. Scheduling stays in that adapter; the provider-independent
input carries no scenario-only clock field. An `InputArrival` reports how long
the input was waiting when the Runtime received it, rather than exporting an
absolute monotonic timestamp. Providers therefore do not need to share the
Runtime's clock domain. The scenario adapter advances an injected clock, so the
whole path is deterministic and needs no network or hardware.

`LiveInputAdapter` is the corresponding audio provider. `AudioStream` keeps
decoded blocks and VAD segments in fixed-capacity, latest-preserving queues.
PocketSphinx checks `Hey Misty` and `Hi Misty` locally; ambient segments that
do not match produce an observable `no_match` and never reach hosted ASR. A
match authorises one utterance, bounded by silence timeout and maximum
duration. Wake, capture, ASR, backlog and audio-pipeline outcomes are typed
Runtime records; only a non-empty transcript becomes Explicit Request Trigger
Evidence. Hosted ASR retries are disabled so its configured timeout remains the
upper bound for the one authorised attempt.

`VisualInputAdapter` is the temporal visual provider. Local detections carry
only normalized person bounds, camera-facing geometry, hand position,
observable eye/mouth/head geometry and confidence into an anonymous,
short-lived tracker. A Social Invitation needs sustained gaze plus hand motion
with a direction change; an empty frame, a passerby, or a single still frame
remains an observable negative gate result and never calls the model. A Care
Cue needs multiple frames of sustained observable geometry on the same track.
It may report narrowed eyes, an open mouth, a lowered head or raised mouth
corners; it never reports an emotion label or diagnosis. The gate chooses no
robot action for either cue. When it qualifies one, exactly one bounded JPEG
crop enters Trigger Evidence and the completed Runtime result discards its
bytes. MediaPipe extraction exists as a local, replaceable detector, but its
real-camera accuracy, thresholds, associations, latency, and all Misty II
behaviour are unverified; acceptance evidence uses synthetic temporal fixtures
and a simulated robot.

The Snapshot remains the same three cheap facts. A model that wants richer
visual information must explicitly call `observe_target` or `inspect_scene`.
Both return one typed result with cost, age, freshness, structured observable
facts and uncertainty. The first reads the cue's latest anonymous target
track; the second returns bounded selected-scene facts and is marked as the
expensive option. Neither Tool can move the robot or diagnose emotion. An
unavailable visual source returns a typed unavailable ending instead of
invented facts. A text scenario has no camera, but it places its person in
the simulated room and the Snapshot reports them from that placement, so its
Episodes look through `PlacedPersonPerception`: the person is reported where
the scenario placed them, labelled as a simulated placement rather than a
camera frame, and as unavailable once the placement is empty. Session binds this view to the Trigger Evidence track when the
Episode opens, so a later queued cue cannot silently replace it. If that track
is absent from the newest frame, its own last-seen time supplies the age and
the Tool reports unavailable.

While an Episode owns model and robot effects, the Runtime drains already-due
inputs only at safe Turn boundaries. It never starts a second Episode in
parallel and does not create a background task. The queue defaults to three
items and five seconds of freshness. Explicit Requests have priority 3, Care
Cues 2, and Social Invitations 1; equal priority is FIFO. A deduplication key
keeps the first equal-or-lower-priority Cue, while a higher-priority Cue with
the same key replaces it. At capacity, a higher-priority arrival displaces the
newest lowest-priority item; otherwise the arrival is dropped. Expired Cues
never open Episodes. Every enqueue, dequeue, dedupe, replacement and drop is a
typed runtime record.

Exhausting the finite source, runtime shutdown, the ReAct Turn cap, and
dependency failure all produce bounded endings. An abnormal audio terminal
produces its typed source record and a `runtime_error` ending. Shutdown asks the active
Episode to stop, drops every queued Cue with a typed shutdown reason, and stops
the input source without leaving a Runtime-owned thread. Runtime and Episode
failures also give every pending Cue a typed drop reason before stopping.

The Episode Turn cap defaults to 12. It is an initial design value, not a
hardware measurement.

`SkillCatalog` is separate from `ToolRegistry`. It validates local `SKILL.md`
YAML metadata using a safe loader, advertises only names/descriptions, and
loads instructions through typed `activate_skill`. `read_skill_resource`
reads one reference or UTF-8 text asset only after activation in the current
Episode. Files are bounded to 64 KiB; path escapes, symlinks, binary content,
missing resources and scripts are refused. No code is executed, fetched from
the network or given direct robot authority. A compliant new directory under
`misty_agent/skills/` is discoverable without changing the core or registry.
Invalid directories are omitted from discovery and explicitly refused if
activation is attempted. Non-text assets are not supported in this version.

Activation and resource contents return through matching native Tool results;
the same bounded ReAct loop decides what to do next. Activation permissions
and instructions live only in that Episode, including on error or abort.
The Journal records discovery and actual activation results. Storyboard
replay shows the active Skills at each Moment and clears them at the ending.

`listen` is an explicit active-perception Tool, not an enlarged Snapshot. Its
wait defaults to five seconds (`MISTY_LISTEN_TIMEOUT_S`, at most 30), with
injected clock and stop checks. It reports heard/silence/unavailable/error/
aborted, source, age, freshness and speaker uncertainty. The live audio
provider owns the same VAD queue: an explicit listen authorises one bounded
ASR attempt without another wake; a pending wake remains Attention's. Speech
that finishes between Turns, while the model is deciding, is drained by the
Attention wake gate and is not replayed to a later `listen`. The
total listening budget also caps the ASR timeout. Decoded transcript queues
report dequeue age, explicitly not an observed capture age. This wiring is
tested with injected sources only, not a Misty microphone.

The acceptance fixtures include checked-in synthetic WAV files and synthetic
visual timelines. Run through `run_fixture`, each reruns the selected local
gate, then uses scripted ASR/detector signals/model decisions and a simulated
robot, so it needs no API key or network; the scripted route
`/scenarios/<card>/run` serves that run with its audio stages or per-frame
visual gate facts, selected Evidence metadata, Episode, Tool effect and ending. The care card offers sustained face/posture signals and
a visual-versus-verbal conflict. In the latter, `new_speech` carries the
person's explicit statement after the first Tool, and the scripted next
response respects those words while acknowledging visual uncertainty. A
negative visual timeline states that no Episode opened and the model was not
called. Trigger Evidence reaches the model before any Observation.

The Demo page does not show those scripted runs. Its examples are
recordings: `python -m misty_agent.demo.record` runs a chosen subset of
the same fixtures with the configured hosted model making every decision,
and writes each run to `misty_agent/demo/recordings/` in the scripted
route's shape, labelled `recorded_model_run` with the model name and date.
The page offers fifteen of them in five groups (noticing someone, talking,
moving, care, knowing its limits), replays them without a key, and animates
the simulated Misty on an eye-level stage whose lines meet at its centre.
Misty and the person stand three-quarters to each other so both faces read,
and the gap between them follows the real distance without being to scale.
The person is an abstract figure whose face is drawn only from the fixture's
observable signals (looking, head lowered, mouth corners raised), never
inferred from what they say.

The server plays one list per run, `playback_of`, which keeps the runtime's
records in the order it wrote them and lets each Episode's Moments out as
time passes, so a run that never opened an Episode still has something to
show, and somebody speaking during one appears where they spoke. Each step
carries a plain sentence, whether it tells the story, and its voice: the
person's words, Misty's words, a model note, Misty's other actions, what came
back, what Misty sensed on its own, or a marker. That projection is applied
when a recording is served rather than when it is made, so the page can
change without re-running anything against a paid model.

The page then chooses the plain telling. It keeps the steps that tell the
story, leaves out how speech was heard (wake, capture, transcription), keeps
only the step where a visual gate made up its mind, gives each model note
that the next call carries a step of its own, and, when two people take
part, gives each conversation's opening a step of its own. Everything else
stays behind a developer switch. On the stage, speech appears in bubbles over
the speaker, a model note appears as a thought cloud, a marker or a
conversation's opening appears as a title across the stage, and a status
label in the top left says what Misty is doing or sensing. The distance is a
badge on the floor between them, a Skill appears as a card that rises and is
absorbed, a sound floats up as notes, and a `wait` counts down beside Misty's
head. An action is drawn with the pose its own Observation confirmed, so a
gesture appears on the step that made it and a failed call shows nothing. The
full conversation opens in a drawer beside the stage, and a strip of one icon
per step is the scrubber.

A recording is evidence about that model on that day, not a test: the
default suite checks the files' shape and runs the boundary audit over what
Misty said in them. The optional live panel is a separate hosted path that
plays on the same stage.

Each model Turn uses a provider-neutral representation of the native function-
calling protocol. The OpenAI adapter speaks it over the Responses API, which
is the endpoint that accepts function tools and reasoning together — Chat
Completions refuses the pair for the whole GPT-5.6 family, and a model doing
no reasoning chose to listen rather than answer. It preserves Tool call
identity, pairs each call with its `function_call_output`, disables parallel
calls, rejects a response containing more than one call, asks the provider to
store nothing, and reads only the public text as the Decision Note.

Because nothing is stored provider-side, a Turn's reasoning would be gone by
the next one, so it is requested encrypted and handed back up with the Turn
it belongs to. It travels in the working context, which is where a Turn's
history already lives and which is discarded with the Episode — so one
Episode cannot inherit another's — and never in the Journal, which is a
public record that private reasoning stays out of. A short public Decision Note may be
recorded in the Journal; it is not private model reasoning and cannot carry
physical control parameters.

The care card also offers `請協助我冷靜`: a timed text request, Skill activation,
optional reference reading, speak/listen, gentle head expression and `done`.
Its timed reply is consumed by `listen`, not inserted by the model script.
The decisions and speech remain authored fixtures, not recorded LLM outputs.
This verifies the current wiring, not autonomous model policy quality.

Each Episode binds one anonymous `InteractionTarget` from its Trigger
Evidence: the track reference the Attention Loop named, or none for speech
without a visual track. The visual gate keeps several candidate tracks, but
the Episode's active-perception view is fixed to that one reference, so a
closer, larger or newer face is reported as unavailable rather than as the
target. `observe_target` and `inspect_scene` update the target's
bound/visible/lost/reacquired state and return it; every Snapshot carries it
as a fourth fact; `approach` refuses a lost target with the controller's own
`lost_user` status and zero Steps. A new
Episode never inherits a target, and reacquisition requires the same
anonymous track within the tracker's TTL.

While an Episode runs, another person's Explicit Request is queued rather
than dropped or run in parallel. At the next Turn boundary the runtime hands
the loop a `HandoffNotice`, recorded as `handoff_requested` and shown to the
model once, asking it to close the Episode and call `done`. "Another person"
means a queued request on a different anonymous track than the active
target; an untracked request is assumed to be the current speaker and is not
announced, though it still opens its own Episode afterwards. The
runtime never ends an Episode for a handoff; bumper, e-stop and shutdown
still abort immediately. Queued requests keep their freshness bound and are
dropped as expired if the active Episode outlasts them.

The A→B fixture runs two anonymous actors through this path and renders
target binding, the queued request, the notice, the dequeue and both
Episodes in order. Speaker attribution there is part of the fixture: the
runtime has no sound-source direction and no face identity.

Tools and the approach controller depend on one `Robot` interface
(`misty_agent/robot/`): behaviours such as `move_head(pitch, roll, yaw)` or
`drive(...)` that return a typed `Effect`, never a status code or a vendor
parameter name. `RealMistyAdapter` turns each behaviour into the documented
Misty REST request over the existing command transport and is
hardware-unverified throughout. `SimulatedMistyAdapter` turns the same
behaviours into state: pose, chest light, last speech and sound, and the
distance the perception side measures, so driving changes the next Snapshot
and a refused behaviour reaches the Observation as `ok: false` and leaves
the storyboard's pose where it was. Neither adapter records what happened;
the Journal written by the ReAct loop and Tool dispatch is the only
behaviour record, and the Demo replays from it.

`approach` is the only movement Tool. Its one argument, `keep`, says how much
room to leave the current Interaction Target: `close` (the default, the
`target_distance_cm` the loop has always converged to), `comfortable` or
`far`, each a `Settings` field validated to widen in order. The model states
the intent and that choice, and nothing about how: the Tool copies the
settings with the chosen target and hands them to the same closed loop, which
comes closer or backs away as the reading requires.
A reading now carries a bearing beside its distance, timestamp and
uncertainty. The controller turns the chassis while the bearing exceeds
`align_tolerance_deg`, each turn bounded by `max_turn_deg` and divided by the
uncalibrated motion multiplier, then moves one bounded distance Step per
fresh reading until the arrival band. Head yaw is never read as alignment. A
reading with no bearing ends the call as `bearing_unavailable` before any
motion; the live distance pipeline reports none, so on hardware the Tool
fails closed. Stale readings, a vanished person, the alignment budget, the
Step cap, the deadline and a refused drive are distinct typed results, and
the Tool result carries every motion with the distance and bearing it was
planned from, plus the reading source's own caveats. The simulated adapter models the person in
relative polar coordinates with a chassis heading; its turning rate and
travel speed are simulation constants, never hardware measurements.

Movement has safety checkpoints (`misty_agent/control/safety.py`): before
the first motion, before each motion, and at `movement_poll_s` during it
with the last poll at its end, the controller asks whether a stop was requested and reads the
hazard source. A stop ends the call as `aborted` without another command,
since the stop's owner already halted the motors; a hazard halts them here
and ends the call as `blocked`; a missing reading, or one older than
`hazard_max_age_s`, is `hazard_unavailable` and the base does not move. A
real Session has no hazard source today, so its movement Tool fails closed at
the first checkpoint; the simulated world reports the scenario's own hazard
and departure timeline. Every result carries a short reason, and the Journal
keeps the intent, the completed motions, the reason and the Snapshot. These
are simulated checks of the control law's shape, not a hardware safety
certification.

`wait(seconds)` keeps the robot still for one to thirty whole seconds, for
example to time something the person asked for. It moves nothing, which is
why the model may choose its length, and it polls only the stop: the
microphone offers no way to look at speech without taking it, so anything
said meanwhile arrives on the Snapshot afterwards, and the thirty-second
ceiling bounds how long a changed mind can go unheard. The result reports
whether the wait elapsed or was stopped, and how long it actually lasted.

Model context is Episode-scoped. The current Trigger Evidence, native Tool
calls/results, Snapshots, later utterances and activated Skill instructions
remain available to later Turns in that Episode. `run_episode` then releases
that local list; `Session` owns no summary, extracted facts, exchanges or other
personal context that a later Episode could inherit. Interaction Target and
Skill permissions are also rebuilt per Episode. Cue lifecycle records retain
only run-local anonymous ids, priority, timing and queue size.

The in-memory Journal may feed the current Demo run, but its optional
`JsonlFile` subscriber redacts personal prose before writing. Lossless JSONL is
reserved for synthetic/provenance-labelled fixtures. Demo responses set
`Cache-Control: no-store`, retain no server-side run session, and never return
raw image/audio bytes. This persistent-storage policy is separate from hosted
processing: configured ASR/VLM/LLM providers may receive the bounded selected
Evidence needed for the current Episode.

An explicit request for space is not classified by Runtime text matching. The
model selects the typed `respect_boundary` Tool, which calls `Robot.halt()` and
ends the Episode with a boundary-respected outcome. Runtime may then retain one
anonymous track token plus an expiry: same-track Care/Social cues are observable
as suppressed, another anonymous track remains eligible, and an Explicit
Request removes the throttle and opens immediately. Expiry, shutdown and run
completion clear the state, and so does the visual gate reporting an empty
scene for `track_lost_after_s` — sustained, because the gate reports empty on
every frame with no detection and one of those is somebody turning away, not
leaving. Releasing early is how a person who asked for space gets pestered
again. No name, face embedding or cross-session identity is part of Cue
Suppression.

An Episode-ending Tool that did something physical records an Observation
before the Episode closes, so `respect_boundary`'s halt result is in the
Journal rather than lost with the Turn. `done` returns nothing and records
nothing, which is why the golden Journals are untouched.

Language and high-risk conversation are policy, not a matcher in the
response path. Following the person's language starts at transcription:
`asr_language` defaults to none, so the provider detects Chinese or English
rather than a fixed hint turning one into gibberish. The persona tells the
model to answer in the person's language and to follow a change of it
mid-Episode; the wake phrases stay
English, which says nothing about the conversation that follows. For
self-harm, medical danger or a request to be freed, the persona and the
`emergency-boundaries` Skill tell the model to stay in the conversation, say
plainly what it cannot do, and point at someone nearby or local emergency
services, while never naming a diagnosis, promising safety, claiming to have
contacted anyone or offering to lift or carry. Nothing inspects the
transcript for keywords and substitutes a fixed line; every effect still
goes through the same typed Tools.

Two of those boundaries are structural rather than advisory: no Tool can
reach anyone off the robot, so "I have called someone" cannot be true, and
`speak` takes only the words, with no recipient. The rest are guidance, and
guidance can be paraphrased around. What a real model actually does is
measured by the opt-in evaluation in `tests/test_llm_live.py`, which runs
the same audit as the offline tests and reports the result without gating on
it.

The spec's fifteen social situations are one declarative set in
`misty_agent/acceptance.py`. Each contract names the card and fixture that
runs it, whether an Episode may open at all, the runtime records it must
make observable, the Tools that would make the outcome unsafe or a boundary
breach, and whether the base may move. It deliberately fixes no wording and
no Tool order, because these situations have more than one reasonable
answer. `run_fixture` is the only way a built-in scenario runs: the
acceptance tests, the scripted route and the Demo's recorder all call it,
so a recording differs from the tested run only in who made the decisions.

That set is not a benchmark. There is no score, no leaderboard and no claim
of comparability with any published suite; every model decision in it is an
authored fixture. The Demo's recorded model runs are shown beside it, not
counted as part of it.

This completes the social-runtime effort in
`.scratch/social-react-runtime/`. What the system does not do is unchanged
by that: no hazard source reaches the real Session, no bearing has come from
a camera, and no line of this has run on a Misty II.

The real-driver branch is marked with an asterisk because it has never run on
a Misty II and never will in this project.  Its request shapes have contract
tests; its hardware behaviour, latency, calibration, and reliability are
unverified. The vendor AV composition now passes `AudioStream` through
`LiveInputAdapter`, but no microphone audio has ever been received from Misty;
the local wake threshold and both visual gate policies are supported only by
their synthetic fixtures. Care geometry thresholds are not validated as
emotion recognition and must not be represented as such.
