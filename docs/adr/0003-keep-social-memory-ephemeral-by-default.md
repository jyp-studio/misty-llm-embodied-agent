# Keep social memory ephemeral by default

An Episode may retain its Interaction Target and Exchanges while it runs, but
the first version will not persist raw real-user audio or video, personally
identifying transcripts, target identity, or personal memory across Episodes.
Only short-lived anonymous Cue Suppression survives an Episode boundary, and
an Explicit Request bypasses it; richer memory requires a future explicit
consent policy.

## Consequences

- `run_episode` owns one local model message list. Trigger Evidence, Tool calls,
  matching results, Snapshots and activated Skill instructions remain available
  to later Turns in that Episode, then become unreachable when it returns.
- `Session` has no memory dependency and the former summary/fact/exchange store
  is removed. A second Episode cannot opt back into that path accidentally.
- The in-memory Journal and current Demo response may contain the current run's
  bounded transcript. `JsonlFile` redacts personal prose at the persistence
  boundary, and Demo responses use `Cache-Control: no-store`.
- Hosted ASR/VLM/LLM may still receive the bounded Evidence needed for the
  current decision. External transmission and persistent retention are
  separate policies; this ADR restricts the latter, not the former.
- Checked-in synthetic or licensed fixtures remain allowed when their
  provenance labels make clear that they are not real-user payloads.
- A boundary-respected Episode may create one run-local suppression entry with
  only an anonymous track token and expiry. Care/Social cues on that track are
  throttled; a new Explicit Request bypasses it. Expiry, track disappearance,
  shutdown and run completion clear the entry.
