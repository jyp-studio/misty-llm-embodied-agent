# Transport lag — robustness sweep

> **This is a parameter sweep, not a measurement.** Every number below answers
> "what would happen if the camera-to-process delay were X?" — and X has never
> been measured, because measuring it needs a Misty II on a network and this
> project has neither and will have neither (`PLAN.md` §1). Nothing here is
> evidence about how the real robot behaves.

Produced 2026-08-11 by `harness/robustness.py`.

## What is being swept, and why

```
[truth] ─ exposure → encode → RTSP over WiFi ─▶ [in process] ─ buffer/detect ─▶ [reading]
        └────── segment A: swept here ────────┘  └──── segment B: 43 ms, measured ────┘
```

`settings.sensor_transport_lag_s` has carried an `UNCALIBRATED` marker since M2
with nothing reading it. This is what reads it. The measured 43 ms of segment B
is added to every swept value, so the axis below is total staleness by way of
an assumed segment A.

The controller is **called, not modelled** — `plan_step` from
`misty_agent.control.step_policy`, the same function the robot runs. `PLAN.md`
§10 records a hand-derived closed form of that logic which was wrong and passed
its tests anyway.

## Results

Approach from 130 cm, perfect calibration, default settings (target 60 cm,
tolerance ±12, safety floor 45, step cap 8).

Swept at **0.05 s** resolution from 0 to 3 s — 61 points. The grid spacing is
part of the result: see "an earlier, coarser sweep got this wrong" below.

| Assumed segment A | Outcome | Steps | Final | Converged |
|---|---|---|---|---|
| 0.00 – 0.75 s | arrived | 2 | 70.5 | ✓ *(identical throughout)* |
| 0.80 s | arrived | 2 | 70.2 | ✓ *(first row that differs)* |
| 1.00 s | arrived | 2 | 67.0 | ✓ |
| 1.50 s | arrived | 3 | 48.8 | ✓ |
| **1.55 s** | arrived | 3 | 48.1 | ✓ *(last converging)* |
| **1.60 s** | arrived | 3 | **47.4** | ✗ **overshoot** — outside the band, floor intact |
| 1.70 s | arrived | 3 | 46.0 | ✗ overshoot |
| **1.75 s** | arrived | 3 | **44.6** | ✗ **collision** — first breach of the 45 cm floor |
| 2.00 s | arrived | 3 | 41.1 | ✗ collision |
| 2.50 s | arrived | 3 | 35.5 | ✗ collision |

**Envelope: converges up to 1.55 s; first fails at 1.60 s by overshoot; first
breaches the safety floor at 1.75 s. Located to ±0.05 s by the grid.**

### Why 0.80 s is the threshold where anything changes at all

Not the control cycle — `post_step_settle_s`, exactly. Every row below 0.80 s
is identical to three significant figures, and 0.80 s is the first that is not.

After a drive the robot waits `post_step_settle_s` = 0.8 s before looking
again. A delay shorter than that reaches back only into the settle, when the
robot was already stationary at its new position, so the reading is stale but
*correct*. A delay longer than it reaches back into the drive, when the person
was further away — and the controller then commands a step sized for a distance
it has already covered.

That is not the controller being clever. It is the settle time accidentally
buying the tolerance, and it means the robustness scales with how long the
robot dawdles rather than with anything designed. Halve `post_step_settle_s`
to make the robot feel responsive and the envelope halves with it.

### An earlier, coarser sweep got this wrong

The first version of this table stepped 1.5 → 2.0 s and reported "fails at
2.0 s by **collision**". Both halves are wrong. The first failure is at 1.60 s
and it is an **overshoot** — the robot ends outside the arrival band with the
safety floor still intact. The skipped band 1.60–1.70 s contains an entire
failure mode, and the spec asked about that mode by name
(「震盪?超衝?步數用盡?」).

`envelope()` now reports the grid spacing alongside the boundary, because a
boundary read off a coarse grid is not merely imprecise — it can name the wrong
failure.

## The finding that matters more than the envelope

**Every row says `arrived`.** At 2.0 s the robot ends at 41.1 cm — four
centimetres inside a floor it is forbidden to cross — and reports success. Push
the assumed lag further and the model puts the robot *behind* the person
(−34.5 cm at 7.5 s), though those rows are the model talking rather than a
finding: a real camera cannot report a negative distance and contact happens
at zero. The claim stands on the rows that are physical.

It cannot do otherwise. It decides it has arrived by comparing a reading
against the arrival band, and the reading is as stale as everything else. A
sufficiently delayed reading eventually lands in the band while the truth is
somewhere else entirely, and the loop exits satisfied.

So the failure mode is not oscillation, and not exhausting the step cap. It is
**silent**. There is no value of `sensor_transport_lag_s` at which this
controller notices something is wrong, which is the strongest argument in this
milestone for the rewrite (`PLAN.md` §12.3) doing something the current design
does not: bounding reading age at the point of decision rather than trusting
whatever the estimator last produced.

The step cap does hold throughout — the episode always terminates, which
`PLAN.md` §4 calls the system's strongest property. It terminates having failed.

## Calibration error, separately

The same simulator with `speed_error = 2.0` (a robot travelling twice as far as
commanded) and no lag at all:

| Start | Closest | Breached floor |
|---|---|---|
| 130 cm | 60.0 | no |
| 120 cm | 50.0 | no |
| 110 cm | 40.0 | **yes** |
| 100 cm | **44.0** | **yes** |
| 90 cm | 48.0 | no |

`PLAN.md` §5-B records "實速為校準值 2 倍時模擬會突破 45cm 至 44.0". The 100 cm
row reproduces **44.0** exactly, from a simulator written months later and
independently of the one that produced that figure.

Whether the floor is breached depends on where the approach started, because a
doubled first step can happen to land inside the arrival band. Defect B is not
conditional — the floor clamps the commanded distance and never the travelled
one — but whether it *shows* is.

## What this sweep does not cover

- **The controller under review reads a median, not one sample.**
  `get_distance` takes the median of a window of recent samples and refuses to
  answer with fewer than two — defect A3, and staleness this model does not
  have. The delay line matches the *reference* pipeline ticket 06 measured, so
  every figure here **understates** the current controller's exposure.
- **MediaPipe is not in the loop.** Perception is modelled as a delay line with
  centimetre quantisation, which is what ticket 06 measured the reference
  pipeline to be. Running the real detector through eight control steps per configuration
  would take minutes per sweep and would not be deterministic. Defensible is not
  identical, and this is the gap.
- **The person does not move.** Every row is a stationary subject. A person
  walking while the robot approaches would change the closing rate and is worth
  a second sweep.
- **Detection dropouts are absent.** Beyond ~195 cm the real detector finds
  nothing (`PLAN.md` §12.5); the model always reports.
