# Perception latency — baseline

**Measured 2026-08-11** with the replay harness (`harness/`), against
`DirectPipeline`: the simplest possible consumer — read a frame, detect a face,
keep the answer. No buffering policy, no filtering, no sample window.

This is the floor the rewritten pipeline (`PLAN.md` M5) is measured against. It
is not a target to beat; it is the cost of doing nothing at all beyond
detecting, and anything the rewrite adds shows up as the difference.

## Conditions

| | |
|---|---|
| Machine | Apple M1 Pro, arm64, macOS (Metal GPU acceleration active) |
| Python | 3.11.3, project `.venv` |
| mediapipe | 0.10.21 (legacy `solutions.face_mesh`, tracking enabled) |
| Camera | `SyntheticCamera` at 30 fps, 640×480 |
| Sampling | 40 Hz |
| Script | `start 130cm, walk to 90cm over 1s, hold 1.5s, step to 69cm, hold 1.5s` |
| Runs | 5 |

**The machine matters more than anything else here.** `PLAN.md` §12.2 records
the plan assuming MediaPipe cost 30–50 ms per frame where it in fact costs 5;
that single figure decided whether defect A1 manifested at all. A latency
number without its host is not a result. The Docker image (`M8`) targets x86
without GPU acceleration and will not reproduce these numbers.

## Results

| | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| **Lag p95** | **42.5 ms** | **42.5 ms** | **42.5 ms** | **42.6 ms** | **42.5 ms** |
| Lag p50 | 39.7 | 17.5 | 17.6 | 42.5 | 40.4 |
| Lag by correlation | 25.6 | 25.4 | 25.5 | 48.6 | 48.3 |
| Consumer cost (median frame age) | 4.95 ms | 4.95 | 4.86 | 4.93 | 5.02 |
| Queue inversion point | 202 fps | 202 | 206 | 203 | 199 |
| p95 ÷ floor | 1.11 | 1.11 | 1.11 | 1.11 | 1.11 |

Measurable samples: ~40 of 161. The rest fall in the two holds and at the step,
where inversion has nothing to work with — see "what cannot be measured".

**p95 is the figure. p50 is not stable and should not be quoted.** It lands at
either ~17 ms or ~42 ms depending on the run — one sampling interval apart —
because whether the recorder polls before or after the pipeline has swapped in
its latest reading is a coin toss per sample, and the median follows whichever
side got more of them. p95 sits at the top of the distribution and is unmoved
by that split. The ticket asked for p50 alongside; it is here, with the caveat
that makes it readable.

Correlation is bimodal for the same reason and at half the scale, because it
fits one shift to the whole trace. It is a cross-check, not a second opinion.

### The model explains the measurement

```
frame period (1/30)      33.3 ms
detection cost            5.0 ms
                         --------
lag floor                38.3 ms
measured p95             42.5 ms      → 1.11 × floor
```

A reading cannot describe the world more recently than the frame it came from,
and cannot arrive before that frame has been looked at. The measurement sits
11% above that floor, which is the sampling and scheduling slack. **The
reference pipeline adds essentially nothing of its own** — which is what makes
it a usable baseline.

## The bound

`harness.latency.MAX_LAG_OVER_FLOOR = 2.0`, asserted in
`tests/test_latency_bound.py`.

Expressed as a multiple of the floor rather than in milliseconds, so it travels
between machines. A rewrite that doubles the pipeline's own overhead still
passes; one that queues frames, filters over a stale window, or fails to
invalidate after movement does not — those cost multiples of a frame period,
not fractions.

## An estimator bug, and why these numbers are the second set

The first version of `lag_samples` filtered candidate samples by local speed
alone and searched the whole trace for a matching instant. A step's local speed
is enormous, so samples straddling it passed the filter — and a distance that
occurs on both sides of a step has two crossings, so they matched the wrong
one. Fed a trace built with **exactly 40 ms** of lag, the estimator returned
values up to **+1537 ms**.

The published figures did not visibly contain that garbage, which is worse
rather than better: they were not right, they were unexamined. The fix confines
the search to a stretch with no discontinuity in it and treats a jump faster
than any human walk as "not measurable here" rather than "moving very fast".
`test_the_step_does_not_produce_wild_readings` replays that exact trajectory
with a known lag and fails if a reading comes back beyond 200 ms.

The numbers above are from after the fix. p95 moved from a wandering 43–90 ms
to a flat 42.5 ms across five runs.

## Queue growth

The buffer never grew during a solo run. That is **not** a property of the code: the buffer is
unbounded and has no backpressure whatsoever. It stayed empty because the
consumer costs 5 ms against a producer arriving every 33 ms — a ratio of 0.15.

The two costs cross at **≈200 fps**. Equivalently, the queue starts growing if
the consumer becomes ~6.6× slower. That is well within the range of a slower
host: `PLAN.md` §5 originally assumed 30–50 ms per frame, which is 6–10× what
was measured here, and at those figures the buffer grows without limit.

Under the **full test suite** it is a different story: with other tests running
MediaPipe on the same cores, the consumer slows enough that frames genuinely
queue. An assertion that the buffer stayed empty was tried and removed for
failing intermittently — which is not a flaky test so much as defect A1
happening in front of us.

**So defect A1 is real but conditional.** The correct claim is not "the queue
grows" but "nothing prevents the queue growing, and whether it does is a
property of the host rather than of the code". A system whose correctness
depends on the machine being fast enough is defective regardless of which
machine it is currently running on.

## What cannot be measured, and why

**Lag is undefined while nobody is moving.** Every recent instant matches a
constant reading equally well. 117 of the 161 samples fall in the holds and the
step for exactly this reason, and the estimator returns nothing there rather
than a number. This is not a limitation to work around — it is the mechanism by
which a stale reading stays invisible. A robot facing a stationary person cannot
tell whether its eyes are working.

**Readings are quantised to whole centimetres.** One reading pins the person no
better than `1 cm / speed`. The script walks at 40 cm/s, giving 25 ms — below
the 43 ms being measured, so the signal survives. An earlier version of the
script walked at 6.7 cm/s, where the quantum is 150 ms; the same pipeline
measured **−45 ms**, the noise having swallowed the signal whole. The walking
speed is part of the instrument, and it is recorded here for that reason.

**Segment A of the pipeline is not measured at all.** Everything above covers
the path from a frame entering the process to a reading coming out. Camera
exposure, on-robot encoding and RTSP over WiFi are upstream of the harness's
injection point and cannot be measured without hardware, which this project
does not have and will not get (`PLAN.md` §1). Ticket 08 sweeps
`sensor_transport_lag_s` to show how much of it the control law tolerates; that
sweep is a parameter study, not a measurement.
