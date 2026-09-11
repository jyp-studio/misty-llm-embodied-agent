# Current architecture

The product boundary is `SocialAgentRuntime`.  A finite scenario and a future
live adapter both satisfy the same `InputSource` interface; neither the Demo
nor an acceptance test opens a ReAct Episode directly.

```text
ScenarioInputAdapter ─┐
                     ├─> SocialAgentRuntime / Attention Loop
future live adapter ─┘          │ one selected cue at a time
                                │ bounded priority queue while active
                                v
                         Session.episode()
                                │
                   typed Trigger Evidence
                                │ first Turn
                                v
          bounded ReAct + native Tool-call / Tool-result protocol
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
dependency failure all produce bounded endings. Shutdown asks the active
Episode to stop, drops every queued Cue with a typed shutdown reason, and stops
the input source without leaving a Runtime-owned thread. Runtime and Episode
failures also give every pending Cue a typed drop reason before stopping.

The Episode Turn cap defaults to 12. It is an initial design value, not a
hardware measurement.

The Demo's Run button is itself an Explicit Request. Its typed Trigger Evidence
contains source, runtime-relative time, selected facts, uncertainty, transcript
and an optional image that is strict base64 and capped at 8 MiB decoded. The
first model Turn receives it before any Observation. A completed runtime result
keeps only the selected image's media type, not its bytes. An uploaded image
remains evidence for that deliberate request; it is not an autonomously
classified visual cue.

Each model Turn uses a provider-neutral representation of the native function-
calling protocol. The OpenAI adapter preserves assistant Tool call identity,
answers it with a matching `tool` result, disables parallel calls and rejects a
response containing more than one call. A short public Decision Note may be
recorded in the Journal; it is not private model reasoning and cannot carry
physical control parameters.

This is ticket 03's vertical slice, not the completed social system. Wake-word
detection, visual cue classification, person-aware handoff, Skills,
target-aware movement, and the live input adapter
remain future tickets in `.scratch/social-react-runtime/`.

The real-driver branch is marked with an asterisk because it has never run on
a Misty II and never will in this project.  Its request shapes have contract
tests; its hardware behaviour, latency, calibration, and reliability are
unverified.
