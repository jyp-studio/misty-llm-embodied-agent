# Coverage audit — the hardware-free simulation runner

> **Hand-written. Not generated, and no command reproduces it.** Everything
> else in this directory falls out of `python -m harness`; this does not. It is
> a reading of the test suite as it stood on 2026-08-20, and it goes stale the
> moment either suite changes.

## Why this exists

M6 deletes `test_sim.py`. Deleting tests on the strength of "those are covered
elsewhere" is deleting protection on trust, so this audit names the replacement
for every one of its 24 checks — or admits there isn't one.

Rule applied throughout: **a claim of coverage that cannot name a test is a
gap.** Every test named below was executed while this was being written and
passed. The suite stood at **272 passed, zero skips** under `.venv`.

## The "28 cases" discrepancy, settled

`README.md` claims 28 in three places, including a pasted transcript reading
`# Result: 28 passed, 0 failed`. `PLAN.md` repeats it. The runner prints 24.

| Commit | | Checks | Scenarios |
|---|---|---|---|
| `b753b42` | Initial public release | **28** | 10 |
| `8a8dee8` | M1 — AutoMisty removed | **24** | 9 |
| `65889ff` | M3 | 24 | 9 |
| `HEAD` | | 24 | 9 |

**The missing four are one scenario: `T10 AutoMisty termination semantics`**,
which asserted the exit-code and `ALLSET` conventions of the code-generation
loop. M1 excised AutoMisty and took T10 with it; nobody updated the prose.

So both documents were accurate when written and now describe a pre-M1 tree.
**The stale documents are `README.md` (three places) and `PLAN.md`'s
"migrate to pytest" line.** Nothing is missing from the runner, and no check
was ever lost silently. M6's deletion ticket corrects both.

## Scenario by scenario

Verdicts: **covered** (a named, passing test asserts the same property or a
stronger one) · **M7** (the behaviour is being replaced, not preserved) ·
**gap**.

### T1 — accurate calibration, user at 150 cm

| Check | Verdict | Where it lives now |
|---|---|---|
| reports arrived | covered | `test_with_no_lag_and_perfect_calibration_the_robot_arrives` |
| final distance within target ± tolerance | covered | same test, asserting the arrival band directly |
| safety floor respected | covered *a fortiori* | No test asserts the floor at exactly 1× travel. `test_the_two_x_counterexample_stays_outside_the_safety_floor` and `test_the_two_x_bound_is_not_luck_at_one_starting_distance` assert it at **2×**, and a robot that travels less than the bound cannot pass a robot that travels the bound. The 1× case is strictly inside the 2× case. |

The 1× floor entry is the one place this audit reasons rather than points. It
is recorded that way on purpose: the argument is sound, but it is an argument.

### T2 — calibration error +50 %

| Check | Verdict | Where it lives now |
|---|---|---|
| still stops | covered | `test_the_step_cap_is_never_exceeded_however_bad_the_lag` |
| no overshoot past the user (min > 20 cm) | covered, stronger | `test_the_two_x_counterexample_stays_outside_the_safety_floor` asserts ≥ 45 cm at 2×, not 20 cm at 1.5× |
| min ≥ floor − 15 cm | covered, stronger | same test, with **no** 15 cm slack, plus `test_public_approach_reserves_enough_headroom_for_two_x_motion` through the public seam |

The old checks bought their passes with slack (`− 5`, `− 10`, `− 15` cm below
the floor, varying by scenario). The replacements assert the floor itself.

### T3 — calibration error −40 %

| Check | Verdict | Where it lives now |
|---|---|---|
| still converges or stops safely | covered | `test_a_slow_robot_undershoots_rather_than_overshoots` |
| final distance reasonable | covered, stronger | same test asserts `converged`, which requires arrival **in band** and no floor breach along the way — the old check ran only `if res == "arrived"` and silently vanished otherwise |

### T4 — measurement noise ±8 cm

| Check | Verdict | Where it lives now |
|---|---|---|
| still stops under noise | **gap** | nothing in `tests/`, `harness/` or `misty_agent/` injects any measurement error |
| stays above floor − 10 cm | **gap** | as above |

**Gap 1.** This is the more serious of the two, because `approach()` aggregates
readings with a median and **the only reason that median exists is noise
rejection** — which nothing has ever exercised.

It is also the reason the old checks cannot simply be ported. Distance comes
from apparent face width through the pinhole relation, so a fixed pixel jitter
produces a centimetre error that grows with the **square** of distance. Under
the default constants (650 × 15 = 9750 px·cm), 1 px is 0.21 cm at the 45 cm
safety floor and 4.10 cm at 200 cm. A flat ±8 cm therefore demands ~38 px of
jitter at the floor — 17 % of the face's width, which cannot happen — while
supplying only ~2 px at 200 cm, where detection actually is shaky. **The model
is wrong in both directions at once, and wrong hardest exactly where the safety
conclusion is decided.**

Filled by tickets **03** (distance-dependent model, cross-checked against the
real detector) and **05** (the sweep and its report). Not ported.

### T5 — user lost mid-approach

| Check | Verdict | Where it lives now |
|---|---|---|
| reports `lost_user` | covered (different path) | `test_stale_in_band_readings_end_as_lost_user_without_motion` and `test_two_readings_must_be_fresh_at_the_same_decision_time` — both assert the status, both from **startup**, both with `steps == 0` |
| stops immediately after loss (drive calls == 2) | **gap** | nothing exercises loss *after* the robot has already moved |

**Gap 2 — found by this audit, not previously known.** Every `lost_user` test
in the suite loses the user before any motion. The mid-approach path is
different code: it runs after a movement has set an invalidation epoch, so
`_fresh_median` is filtering against that epoch rather than against an empty
history. PLAN §5 defect E was specifically about giving up too early on this
path, and the property T5 actually bought — **the loop stops issuing drive
commands once the user is gone** — is asserted nowhere.

Filled by ticket **06**, added as a consequence of this audit.

### T6 — user too close (40 cm), backs up

| Check | Verdict | Where it lives now |
|---|---|---|
| terminates | covered | `test_too_close_commands_one_bounded_backward_step_then_arrives` |
| distance increased (moved backward) | covered, stronger | same test asserts the actual command — `linearVelocity == -20`, one bounded step — rather than an after-the-fact world state |

### T7 — step cap

| Check | Verdict | Where it lives now |
|---|---|---|
| reports timeout | covered | `test_step_limit_returns_timeout_and_stops_issuing_commands` |
| drive calls ≤ 8 | covered, stronger | same test pins the count exactly against a lowered cap; `test_the_step_cap_is_never_exceeded_however_bad_the_lag` holds it across transport lags to 20 s |

### T8 — brain sanitisation

| Check | Verdict | Disposition |
|---|---|---|
| illegal values fall back to safe defaults | **M7** | |
| malformed JSON → no crash, all fields present | **M7** | |
| valid output passes through unchanged | **M7** | |

Not rebuilt in M6, and **not rebuilt in this form at all**. These test a hand
-rolled JSON parser over a free-text model reply. M7 moves to OpenAI function
calling, where structure is guaranteed model-side, so "sanitise malformed JSON"
stops being a requirement rather than moving to a new home. Porting it would
formalise a requirement that is about to be deleted.

What M7 *does* owe: that an out-of-range or unknown tool argument is rejected
rather than passed to the robot. That is the surviving half of T8, and it
belongs with the tool registry.

### T9 — memory folding and persistence

| Check | Verdict | Disposition |
|---|---|---|
| window size ≤ 10 | **M7** | |
| facts extracted | **M7** | |
| file persisted | **M7** | |
| facts survive reload | **M7** | |
| prompt block contains recent turns | **M7** | |

**Gap 3, deliberately incurred.** Unlike T8, this behaviour *is* meant to
survive — memory folding and fact persistence move out of the legacy script in
M7. Deleting these checks now leaves that logic with no executable coverage
between M6 and the point in M7 where it is re-homed.

This is accepted rather than avoided: the tests reach into the legacy script's
internals, and M7 rewrites those internals. Ticket 02 registers it in `PLAN.md` as
an M7 rebuild item so it cannot be lost by silence.

## Tally

| | Checks |
|---|---|
| Covered by a named passing test | 13 |
| Covered by a stronger assertion than the original | 5 of those 13 |
| Belongs to M7, not rebuilt in this form | 3 |
| Belongs to M7, rebuild owed | 5 |
| Gap, filled by tickets 03 / 05 | 2 |
| Gap, filled by ticket 06 | 1 |
| **Total** | **24** |

## What this audit does not claim

- **It does not claim the deleted tests and their replacements test the same
  code.** `test_sim.py` drives `approach_user()` in the legacy script; the
  replacements drive the M5 `approach()`. These are different implementations
  of the same intent. Deleting the runner therefore removes the **only**
  executable check on legacy `approach_user()` — intentional, since PLAN §12.3
  makes that file a read-only reference, but worth saying out loud.
- **It does not claim the replacements are better in every respect.** The old
  runner exercised one thing none of the replacements do: a full episode with
  brain, body and memory wired together. That integration is not preserved; it
  returns in M7 in ReAct form.
- **It does not establish anything about hardware.** No line of this project
  has ever run against a Misty II.
