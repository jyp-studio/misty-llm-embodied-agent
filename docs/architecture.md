# Current architecture

The product boundary is `SocialAgentRuntime`.  A finite scenario and a future
live adapter both satisfy the same `InputSource` interface; neither the Demo
nor an acceptance test opens a ReAct Episode directly.

```text
ScenarioInputAdapter ─┐
                     ├─> SocialAgentRuntime / Attention Loop
future live adapter ─┘          │ one selected cue at a time
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

`ScenarioInputAdapter` currently supports ordered `ScheduledInput` wrappers
around text Explicit Requests with optional selected image evidence. Scheduling
stays in that adapter; the
`RuntimeInput` returned through `InputSource` carries no scenario-only clock
field. The adapter advances an injected clock, so the whole path is
deterministic and needs no network or hardware. `SocialAgentRuntime` consumes
one input at a time, waits for the resulting bounded Episode to close, and
only then reads another. Exhausting the finite source, runtime shutdown, the
ReAct Turn cap, and dependency failure all produce bounded endings.

The Episode Turn cap defaults to 12. It is an initial design value, not a
hardware measurement.

The Demo's Run button is itself an Explicit Request. Its typed Trigger Evidence
contains source, runtime-relative time, selected facts, uncertainty, transcript
and an optional bounded image. The first model Turn receives it before any
Observation. An uploaded image remains evidence for that deliberate request;
it is not an autonomously classified visual cue.

Each model Turn uses a provider-neutral representation of the native function-
calling protocol. The OpenAI adapter preserves assistant Tool call identity,
answers it with a matching `tool` result, disables parallel calls and rejects a
response containing more than one call. A short public Decision Note may be
recorded in the Journal; it is not private model reasoning and cannot carry
physical control parameters.

This is ticket 02's vertical slice, not the completed social system. Wake-word
detection, visual cue classification, cue queueing/handoff, Skills,
target-aware movement, and the live input adapter
remain future tickets in `.scratch/social-react-runtime/`.

The real-driver branch is marked with an asterisk because it has never run on
a Misty II and never will in this project.  Its request shapes have contract
tests; its hardware behaviour, latency, calibration, and reliability are
unverified.
