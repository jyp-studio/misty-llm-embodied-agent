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
                 bounded ReAct + Tool Registry
                                │
                 simulated Misty / real drivers*
                                │
              typed Episode Journal + robot effects

SocialAgentRuntime ──> Attention/Cue records + Episode Journals
                                              │
                                              v
                                      Demo Storyboard replay
```

`ScenarioInputAdapter` currently supports ordered, timed text Explicit
Requests.  It advances an injected clock, so the whole path is deterministic
and needs no network or hardware.  `SocialAgentRuntime` consumes one input at
a time, waits for the resulting bounded Episode to close, and only then reads
another.  Exhausting the finite source, runtime shutdown, the ReAct Turn cap,
and dependency failure all produce bounded endings.

This is ticket 01's tracer bullet, not the completed social system.  Wake-word
detection, visual cue classification, first-Turn Trigger Evidence, cue
queueing/handoff, Skills, target-aware movement, and the live input adapter
remain future tickets in `.scratch/social-react-runtime/`.

The real-driver branch is marked with an asterisk because it has never run on
a Misty II and never will in this project.  Its request shapes have contract
tests; its hardware behaviour, latency, calibration, and reliability are
unverified.
