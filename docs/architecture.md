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
invented facts. Session binds this view to the Trigger Evidence track when the
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
ASR attempt without another wake; a pending wake remains Attention's. The
total listening budget also caps the ASR timeout. Decoded transcript queues
report dequeue age, explicitly not an observed capture age. This wiring is
tested with injected sources only, not a Misty microphone.

The Demo greeting and care cards offer checked-in synthetic WAV fixtures and
synthetic visual timelines. Each click reruns the selected local gate, then
uses scripted ASR/detector signals/model decisions and a simulated robot, so it
needs no API key or network. The page displays the audio stages or per-frame
visual gate facts, selected Evidence metadata, Episode, Tool effect and ending
derived from that run. The care card offers sustained face/posture signals and
a visual-versus-verbal conflict. In the latter, `new_speech` carries the
person's explicit statement after the first Tool, and the scripted next
response respects those words while acknowledging visual uncertainty. A
negative visual timeline states that no Episode opened and the model was not
called. Trigger Evidence reaches the model before any Observation. The
optional Live AI panel remains a separate hosted path.

Each model Turn uses a provider-neutral representation of the native function-
calling protocol. The OpenAI adapter preserves assistant Tool call identity,
answers it with a matching `tool` result, disables parallel calls and rejects a
response containing more than one call. A short public Decision Note may be
recorded in the Journal; it is not private model reasoning and cannot carry
physical control parameters.

The care card also offers `請協助我冷靜`: a timed text request, Skill activation,
optional reference reading, speak/listen, gentle head expression and `done`.
Its timed reply is consumed by `listen`, not inserted by the model script.
The decisions and speech remain authored fixtures, not recorded LLM outputs.
This verifies the current wiring, not autonomous model policy quality.

This is ticket 07's vertical slice, not the completed social system.
Person-aware handoff and target-aware movement remain future tickets
in `.scratch/social-react-runtime/`.

The real-driver branch is marked with an asterisk because it has never run on
a Misty II and never will in this project.  Its request shapes have contract
tests; its hardware behaviour, latency, calibration, and reliability are
unverified. The vendor AV composition now passes `AudioStream` through
`LiveInputAdapter`, but no microphone audio has ever been received from Misty;
the local wake threshold and both visual gate policies are supported only by
their synthetic fixtures. Care geometry thresholds are not validated as
emotion recognition and must not be represented as such.
