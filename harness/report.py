"""The harness's findings, written for someone who will not run it.

Tickets 04–08 produce numbers for assertions. This turns them into a document,
because two of the four things PLAN.md §6 asks the harness to deliver — a demo
that runs, and evidence about defect A — are worth nothing to a reader who
cannot see them. Nobody installs MediaPipe to look at a latency figure, so the
generated document is committed and the numbers are legible without the stack
that produced them.

``build_report`` is pure: a trace and a sweep in, text out. The command that
records the trace lives in ``harness.__main__`` and does nothing else, so the
report's content can be tested in milliseconds without a camera.

## The line this document must not cross

There is no Misty II, there never will be (PLAN.md §1), and **no line of this
project has ever run against one**. A report that let a reader believe
otherwise would be the most damaging artefact in the repository — worse than a
bug, because a bug is eventually found.

So every claim carries one of four evidence statuses:

``measured``                process-local measurement against a synthetic
                            camera, using real pixels, detector, threads, and
                            clock — but no robot or network.
``parameter_sweep``         deterministic exploration of an unknown input;
                            explicitly not a measurement of that input.
``conditional_simulation``  a software guarantee whose calibration and lag
                            assumptions are stated beside it.
``unverified``              not established here, with the experiment that
                            would settle it.

There is deliberately no fifth status meaning "confirmed on hardware". Adding
one is not a small change; it would need a robot.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

from harness.diagnostics import Diagnostics, diagnose
from harness.latency import (
    LagReport,
    MAX_LAG_OVER_FLOOR,
    ThroughputReport,
    estimate_lag,
    throughput,
)
from harness.replay import Trace
from harness.robustness import (
    ApproachOutcome,
    BoundaryCurve,
    RobustnessEnvelope,
    envelope,
)

CAMERA_FPS = 30.0

#: How many replays the published report is built from.
#:
#: One is not enough, and the first version of this report proved it: the
#: committed artefact showed a buffer depth of 1, a frame age p95 of 4.0 ms and
#: a crossing at 280 fps, none of which reproduced on a rerun — and the 280 fps
#: contradicted the ≈200 fps in the baseline document it points at. Those
#: quantities are noisy; the lag p95 is not. Reporting a range makes the
#: difference visible instead of presenting one sample of noise as a result.
PUBLISHED_RUNS = 3


def _range(values: Sequence[float], unit: str, places: int = 1) -> str:
    """A figure and its spread across runs, so noise cannot pass for a result."""
    lo, hi = min(values), max(values)
    if abs(hi - lo) < 10 ** -places:
        return f"{lo:.{places}f} {unit}"
    return f"{lo:.{places}f}–{hi:.{places}f} {unit}"


@dataclass(frozen=True)
class Claim:
    """One thing the project either has shown or has not.

    ``settled_by`` is required on anything unverified. "Unverified" on its own
    reads as an excuse; naming the experiment that would settle it turns the
    same sentence into a plan.
    """

    what: str
    status: str
    detail: str
    settled_by: str = ""

    def __post_init__(self) -> None:
        if self.status not in (
            "measured",
            "parameter_sweep",
            "conditional_simulation",
            "unverified",
        ):
            raise ValueError(f"unknown claim status {self.status!r}")
        if self.status == "unverified" and not self.settled_by:
            raise ValueError(f"unverified claim {self.what!r} needs settled_by")


@dataclass(frozen=True)
class Report:
    """Everything the harness found, and what it is worth."""

    lag: LagReport
    diagnostics: Diagnostics
    rates: Optional[ThroughputReport]
    limits: RobustnessEnvelope
    pipeline: str
    trajectory: str
    environment: Dict[str, Any]
    claims: Tuple[Claim, ...]
    #: Every run the report was built from. The headline figures come from the
    #: first; the spread across all of them is printed beside each, because
    #: some of these quantities are stable and some are not.
    runs: Tuple["RunFigures", ...] = ()

    # ---------- rendering ----------

    def to_text(self) -> str:
        """The short form, for a terminal."""
        lines = [
            f"perception harness — {self.pipeline} on "
            f"{self.environment.get('machine', 'an unrecorded machine')}",
            f"  {self.lag.summary()}",
            f"  {self.diagnostics.summary()}",
        ]
        if self.rates is not None:
            lines.append(f"  {self.rates.summary()}")
        lines.append(f"  {self.limits.summary()}")
        lines.append("  no line of this project has ever run against a Misty II")
        return "\n".join(lines) + "\n"

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "# M5 approach backend — evidence",
                "",
                _preamble(self),
                _headline_table(self),
                _claims_table(self),
                _segments(),
                _pointers(),
            ]
        ).rstrip("\n") + "\n"


@dataclass(frozen=True)
class RunFigures:
    """The handful of numbers that vary between otherwise identical runs."""

    lag_p95_s: Optional[float]
    backlog_max: int
    frame_age_p95_s: Optional[float]
    consumer_cost_s: Optional[float]
    inversion_fps: Optional[float]
    lag_floor_s: Optional[float]


def build_report(
    traces: Sequence[Trace],
    sweep: Sequence[ApproachOutcome],
    *,
    pipeline: str,
    producer_fps: float = CAMERA_FPS,
) -> Report:
    """Assemble the findings from one or more replays and one sweep.

    Several replays, because the first published version of this report was
    built from one and did not reproduce. Headline figures are taken from the
    first run and the spread across all of them printed alongside — a reader
    can then see for themselves which numbers are results and which are noise.
    """
    if not traces:
        raise ValueError("a report needs at least one trace")

    first = traces[0]
    lag = estimate_lag(first)
    rates = throughput(first, producer_fps=producer_fps)
    runs = []
    for trace in traces:
        run_lag = estimate_lag(trace)
        run_rates = throughput(trace, producer_fps=producer_fps)
        runs.append(
            RunFigures(
                lag_p95_s=run_lag.p95_s,
                backlog_max=diagnose(trace).backlog_max,
                frame_age_p95_s=diagnose(trace).frame_age_p95_s,
                consumer_cost_s=run_rates.consumer_cost_s if run_rates else None,
                inversion_fps=run_rates.inversion_fps if run_rates else None,
                lag_floor_s=run_rates.lag_floor_s if run_rates else None,
            )
        )

    return Report(
        lag=lag,
        diagnostics=diagnose(first),
        rates=rates,
        limits=envelope(sweep),
        pipeline=pipeline,
        trajectory=first.trajectory,
        environment=dict(first.environment),
        claims=_claims(lag, rates, envelope(sweep), runs),
        runs=tuple(runs),
    )


# ---------------------------------------------------------------------------
# The claims
# ---------------------------------------------------------------------------

def _claims(
    lag: LagReport,
    rates: Optional[ThroughputReport],
    limits: RobustnessEnvelope,
    runs: Sequence["RunFigures"] = (),
) -> Tuple[Claim, ...]:
    # The same figure the headline table shows, spread and all. Quoting the
    # first run's p95 here while the table showed the range across runs left
    # the document contradicting itself — "43-44 ms" above, "p95 43ms" below.
    spread = [run.lag_p95_s for run in runs if run.lag_p95_s is not None]
    if lag.p95_s is None:
        lag_figure = "no measurable lag in this trace"
    elif spread:
        lag_figure = f"p95 {_range([value * 1000 for value in spread], 'ms', 0)}"
    else:
        lag_figure = f"p95 {lag.p95_s * 1000:.0f}ms"
    multiplier = (
        limits.outcomes[0].actual_motion_multiplier if limits.outcomes else None
    )
    multiplier_text = "unrecorded" if multiplier is None else f"{multiplier:.1f}"
    safe_lag_text = (
        "no swept transport lag"
        if limits.largest_converging_lag_s is None
        else f"transport lag through {limits.largest_converging_lag_s:.2f}s"
    )
    silent_failures = [
        outcome
        for outcome in limits.outcomes
        if outcome.outcome == "arrived" and not outcome.converged
    ]
    return (
        Claim(
            "Distance readings lag reality, and by how much",
            "measured",
            f"{lag_figure}, against a synthetic camera at {CAMERA_FPS:.0f} fps "
            f"with the production DistancePipeline and real detector in the "
            f"loop. This is a process-local measurement only.",
        ),
        Claim(
            "The process-local frame buffer keeps only the latest value",
            "measured",
            (
                "Its backlog is bounded at one frame; a slower consumer "
                "replaces old frames and exposes the replacement count. "
                "This says nothing about OpenCV or RTSP internal buffers."
                if rates is not None
                else "Depth could not be characterised because no frame ever "
                "arrived to an empty buffer — which is itself the symptom, not "
                "a missing measurement."
            ),
        ),
        Claim(
            "Transport-lag convergence and failure boundary",
            "parameter_sweep",
            limits.summary(),
        ),
        Claim(
            "Safety inside the explicit drive-calibration assumption",
            "conditional_simulation",
            f"With `max_actual_motion_multiplier={multiplier_text}` and a "
            f"monotone maximum excursion no greater than that multiple of "
            f"each command, public `approach()` truth-audits as arrived for "
            f"{safe_lag_text}, without crossing the configured floor. This "
            f"is a conditional simulation guarantee, not hardware evidence; "
            f"behaviour beyond that multiplier is unknown.",
        ),
        Claim(
            "Public status is compared with simulator truth",
            "parameter_sweep",
            (
                f"{len(silent_failures)} swept row(s) reported `arrived` while "
                f"truth was outside the arrival band or below the floor; the "
                f"report classifies those rows by truth instead of presenting "
                f"them as success."
            ),
        ),
        Claim(
            "Camera-to-process delay on a real robot (segment A)",
            "unverified",
            "Exposure, on-robot encoding and RTSP over WiFi are upstream of "
            "where the harness injects frames. Swept, never measured. This is "
            "`PLAN.md` §8's `SENSOR_TRANSPORT_LAG_S` and its \"RTSP "
            "端到端延遲\" — one quantity, listed twice.",
            settled_by="Timestamping a frame at the robot and again on arrival, "
            "which needs a Misty II on a network.",
        ),
        Claim(
            "Travel speed at the commanded drive percentage",
            "unverified",
            "`cm_per_sec_at_percent` and "
            "`max_actual_motion_multiplier` are UNCALIBRATED assumptions. The "
            "conditional simulation covers a monotone maximum excursion up to "
            "the stated multiplier; transient overshoot and behaviour beyond "
            "it remain unknown.",
            settled_by="drive_time(linearVelocity=20, timeMs=2000) on a real "
            "robot, then measuring the distance covered.",
        ),
        Claim(
            "Camera focal constant",
            "unverified",
            "`focal_length` sets the distance estimate's scale. Every "
            "centimetre figure here is relative to it.",
            settled_by="Standing at a measured 100cm and scaling by "
            "actual / reported.",
        ),
        Claim(
            "The driver layer's HTTP and WebSocket requests are accepted",
            "unverified",
            "M3's contract tests prove the request format matches "
            "docs.mistyrobotics.com. They cannot prove the robot obeys.",
            settled_by="Sending them to a Misty II and observing the response.",
        ),
        Claim(
            "The motors turn at all at the commanded percentage",
            "unverified",
            "`drive_percent` is 20% of maximum. Whether that clears the motor "
            "deadband is unknown; the robot may simply not move.",
            settled_by="Issuing a drive at 20% and watching whether anything "
            "happens.",
        ),
        Claim(
            "Speech is recognised through Misty's microphone",
            "unverified",
            "The ASR adapter is tested against its own interface. Recognition "
            "rate against Misty's microphone in a room with noise in it is "
            "untouched.",
            settled_by="Speaking to a Misty II and reading the transcripts.",
        ),
        Claim(
            "What happens when a drive command arrives mid-motion",
            "unverified",
            "The approach loop waits `post_step_settle_s` and assumes the "
            "previous motion finished. Misty's actual behaviour if it has not "
            "is undocumented and untested.",
            settled_by="Issuing overlapping drive_time calls on a real robot.",
        ),
        Claim(
            "The robot ever approached anyone",
            "unverified",
            "Neither legacy `approach_user()` nor public `approach()` has ever "
            "executed on hardware. The public demo the project came from "
            "produced `movement: \"stay\"`.",
            settled_by="Running an episode on a Misty II.",
        ),
    )


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _preamble(report: Report) -> str:
    machine = report.environment.get("machine", "an unrecorded machine")
    platform = report.environment.get("platform", "")
    python = report.environment.get("python", "")
    recorded = report.environment.get("recorded_at", "")
    return (
        f"Generated by `python -m harness`. **No line of this project has ever "
        f"run against a Misty II**, and none ever will — the hardware is not "
        f"available and that is a fixed premise, not a temporary gap "
        f"(`PLAN.md` §1).\n"
        f"Neither `approach_user()` nor public `approach()` has run on "
        f"hardware.\n"
        f"\n"
        f"| | |\n"
        f"|---|---|\n"
        f"| Pipeline measured | `{report.pipeline}` |\n"
        f"| Trajectory | `{report.trajectory}` |\n"
        f"| Machine | {machine} {platform} |\n"
        f"| Python | {python} |\n"
        f"| Recorded | {recorded} |\n"
        f"\n"
        f"The machine is not decoration. `PLAN.md` §12.2 records the same code "
        f"measured an order of magnitude apart on two hosts, and that single "
        f"difference decided whether a defect appeared at all.\n"
    )


def _headline_table(report: Report) -> str:
    lag = report.lag
    diag = report.diagnostics
    rows = [
        "## What was measured",
        "",
        f"Figures below span **{len(report.runs) or 1} run"
        f"{'s' if len(report.runs) != 1 else ''}** of the same script. Where a "
        f"range is shown, that quantity varies between otherwise identical "
        f"runs — the spread is part of the result, not a rounding artefact.",
        "",
        "| | |",
        "|---|---|",
    ]
    runs = report.runs
    if lag.p95_s is None:
        rows.append("| Reading lag | no measurable lag in this trace |")
    else:
        spread = [r.lag_p95_s for r in runs if r.lag_p95_s is not None]
        rows.append(
            f"| Reading lag, p95 | **{_range([v * 1000 for v in spread], 'ms', 0)}** |"
            if spread
            else f"| Reading lag, p95 | **{lag.p95_s * 1000:.0f} ms** |"
        )
        rows.append(
            f"| Reading lag, p50 | {lag.p50_s * 1000:.0f} ms — **do not quote "
            f"this**: it is bimodal and flips between runs "
            f"(`m4-latency-baseline.md`) |"
        )
    if lag.resolution_s is not None:
        rows.append(
            f"| Finest lag this trajectory could resolve | "
            f"{lag.resolution_s * 1000:.0f} ms |"
        )
    rows.append(
        f"| Buffer depth, maximum | "
        f"{_range([float(r.backlog_max) for r in runs], '', 0) if runs else diag.backlog_max}"
        f" |"
    )
    rows.append(
        f"| Buffer still filling at the end | "
        f"{'yes' if diag.backlog_is_growing else 'no'} |"
    )
    ages = [r.frame_age_p95_s for r in runs if r.frame_age_p95_s is not None]
    if ages:
        rows.append(
            f"| Frame age at detection, p95 | {_range([a * 1000 for a in ages], 'ms')} |"
        )
    if report.rates is not None:
        rows.append(
            f"| Consumer vs producer | {report.rates.consumer_cost_s * 1000:.1f} ms "
            f"vs {report.rates.producer_interval_s * 1000:.1f} ms "
            f"(ratio {report.rates.ratio:.2f}) |"
        )
        crossings = [r.inversion_fps for r in runs if r.inversion_fps is not None]
        rows.append(
            f"| Buffer starts growing above | "
            f"{_range(crossings, 'fps', 0) if crossings else f'{report.rates.inversion_fps:.0f} fps'}"
            f" |"
        )
        observed_lags = [
            run.lag_p95_s for run in runs if run.lag_p95_s is not None
        ]
        allowed_lags = [
            run.lag_floor_s * MAX_LAG_OVER_FLOOR
            for run in runs
            if run.lag_floor_s is not None
        ]
        if observed_lags and allowed_lags:
            bound_passed = max(observed_lags) <= min(allowed_lags)
            rows.append(
                f"| Process-local latency bound | **"
                f"{'PASS' if bound_passed else 'FAIL'}** — worst p95 "
                f"{max(observed_lags) * 1000:.0f} ms vs tightest "
                f"{MAX_LAG_OVER_FLOOR:g}x-floor bound "
                f"{min(allowed_lags) * 1000:.0f} ms |"
            )
        else:
            rows.append(
                "| Process-local latency bound | not evaluable: this trace "
                "contained no measurable lag |"
            )
    rows.append("")
    rows.append("## What was swept")
    rows.append("")
    rows.append(
        "The transport lag below is an unknown parameter, not a measured "
        "sensor value."
    )
    rows.append("")
    rows.append(f"**Robustness envelope.** {report.limits.summary()}")
    rows.append("")
    return "\n".join(rows)


def _claims_table(report: Report) -> str:
    rows = [
        "## What this does and does not establish",
        "",
        "Item by item, because a single disclaimer at the bottom is a "
        "disclaimer a reader skips.",
        "",
        "The unverified rows cover every item on `PLAN.md` §8's list. That "
        "list has ten entries and this table has "
        f"{sum(1 for c in report.claims if c.status == 'unverified')}: §8 names "
        "the camera-to-process delay twice — once as "
        "`SENSOR_TRANSPORT_LAG_S` and once as \"RTSP 端到端延遲\" — and they "
        "are the same quantity. It also lists `CM_PER_SEC_AT_PERCENT` and "
        "`MAX_ACTUAL_MOTION_MULTIPLIER` separately; this report groups them "
        "into one drive-calibration claim while naming both assumptions.",
        "",
        "| Claim | Status | |",
        "|---|---|---|",
    ]
    labels = {
        "measured": "process-local measurement",
        "parameter_sweep": "parameter sweep",
        "conditional_simulation": "conditional simulation",
        "unverified": "**UNVERIFIED**",
    }
    for claim in report.claims:
        mark = labels[claim.status]
        detail = claim.detail
        if claim.settled_by:
            detail += f" *Would be settled by: {claim.settled_by}*"
        rows.append(f"| {claim.what} | {mark} | {detail} |")
    rows.append("")
    return "\n".join(rows)


def _segments() -> str:
    return (
        "## Why half the path cannot be measured\n"
        "\n"
        "```\n"
        "[truth] ─ exposure → encode → RTSP over WiFi ─▶ [in process] ─ buffer/detect ─▶ [reading]\n"
        "        └──────── segment A: needs hardware ───┘  └──────── segment B: measured here ────┘\n"
        "```\n"
        "\n"
        "The harness injects frames exactly where RTSP would deliver them, so "
        "segment B is covered end to end with the real detector running on "
        "real pixels. Segment A is upstream of that point and needs a robot on "
        "a network to observe at all.\n"
        "\n"
        "It is therefore **swept, not measured**: the report above says how "
        "large it would have to be before the controller stops converging, "
        "which is the strongest statement available without hardware. It is "
        "not a claim about how large it actually is.\n"
        "\n"
        "This is the same line M3 drew around the driver layer: the contract "
        "tests prove the requests match the published API, and prove nothing "
        "about whether the robot obeys them.\n"
    )


def _pointers() -> str:
    return (
        "## Where the workings are\n"
        "\n"
        "| | |\n"
        "|---|---|\n"
        "| Latency, and how the bound was derived | "
        "`docs/measurements/m4-latency-baseline.md` |\n"
        "| Pre-rewrite robustness comparison | "
        "`docs/measurements/m4-transport-lag-sweep.md` |\n"
        "| Defects, decisions and retractions | `PLAN.md` §5, §12 |\n"
        "| The harness itself | `harness/` |\n"
    )


# ---------------------------------------------------------------------------
# M6: what detector wobble does to the transport-lag envelope
#
# Written as a separate document rather than a section of the M5 one, for the
# same reason M5 did not overwrite M4's (PLAN.md §13.3): a report that
# replaces its predecessor destroys the before-state its successor is measured
# against.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NoiseReport:
    """The boundary curve, and the several things it is careful not to say."""

    curve: BoundaryCurve
    seeds: Tuple[int, ...]
    #: The limits the curve table cannot show by itself. Carried rather than
    #: inferred, so the document cannot quietly describe a different sweep
    #: from the one that ran.
    start_cm: float
    multiplier: float
    lag_span: str

    def to_text(self) -> str:
        return (
            "reading-noise sweep — lag x jitter\n"
            f"  {self.curve.summary()}\n"
            "  no line of this project has ever run against a Misty II\n"
        )

    def to_markdown(self) -> str:
        return "\n".join(
            [
                "# M6 reading noise — boundary curve",
                "",
                _noise_preamble(self),
                _noise_curve_table(self),
                _noise_failure_modes(self),
                _noise_limits(),
            ]
        ).rstrip("\n") + "\n"


def build_noise_report(
    curve: BoundaryCurve,
    *,
    start_cm: float = 130.0,
    multiplier: float = 2.0,
    lag_span: str = "0.00 to 3.00 in steps of 0.05",
) -> NoiseReport:
    """Assemble the document. Pure: a curve in, text out."""
    return NoiseReport(
        curve=curve,
        seeds=tuple(sorted({seed for row in curve.rows for seed in row.seeds})),
        start_cm=start_cm,
        multiplier=multiplier,
        lag_span=lag_span,
    )


def _noise_preamble(report: NoiseReport) -> str:
    jitters = ", ".join(f"{row.jitter_px:g}" for row in report.curve.rows)
    return (
        f"Generated by `python -m harness`. **No line of this project has "
        f"ever run against a Misty II**, and none ever will — the hardware is "
        f"not available and that is a fixed premise (`PLAN.md` §1).\n"
        f"\n"
        f"Both axes swept here are **UNCALIBRATED**. `sensor_transport_lag_s` "
        f"has never been measured; neither has detector jitter, which is "
        f"expressed in pixels of apparent face width because that is where "
        f"the error actually lives — a fixed pixel wobble costs centimetres "
        f"in proportion to the *square* of distance (`PLAN.md` §14.4).\n"
        f"\n"
        f"| | |\n"
        f"|---|---|\n"
        f"| Jitter levels swept, px | {jitters} |\n"
        f"| Transport lag swept, s | {report.lag_span} |\n"
        f"| Noise realisations per point | {len(report.seeds)} "
        f"(seeds {', '.join(str(seed) for seed in report.seeds)}) |\n"
        f"| Start distance | {report.start_cm:g} cm — **one**, not a range |\n"
        f"| Travel multiplier | **{report.multiplier:g}x only** — the "
        f"configured `max_actual_motion_multiplier`, itself UNCALIBRATED |\n"
        f"\n"
        f"The last two rows are limits, not settings. Everything below "
        f"describes one start distance at one travel multiplier; nothing here "
        f"licenses reading it as the controller's behaviour in general.\n"
        f"\n"
        f"**This is a parameter sweep, not a measurement.** Every figure below "
        f"answers \"what would happen if the delay and the wobble were X?\" — "
        f"and neither X has ever been observed.\n"
    )


def _noise_curve_table(report: NoiseReport) -> str:
    rows = [
        "## The curve",
        "",
        "One line per jitter level, not one per grid point. Two dimensions is "
        "the shape of the experiment; the question it answers is single, and "
        "a surface printed in full is a table nobody reads.",
        "",
        "`worst seed` is the headline: a controller is only as robust as its "
        "unlucky draw. `best seed` is beside it so the spread stays visible "
        "instead of being averaged away.",
        "",
        "| Jitter | Envelope, worst seed | best seed | Seeds disagree | First failure |",
        "|---|---|---|---|---|",
    ]
    for row in report.curve.rows:
        worst = (
            "converged nowhere"
            if row.largest_converging_lag_s is None
            else f"{row.largest_converging_lag_s:.2f}s"
        )
        best = (
            "—"
            if row.best_case_lag_s is None
            else f"{row.best_case_lag_s:.2f}s"
        )
        failure = (
            "none swept"
            if row.first_failing_lag_s is None
            else f"{row.first_failing_lag_s:.2f}s ({row.failure_mode})"
        )
        rows.append(
            f"| {row.jitter_px:g} px | **{worst}** | {best} | "
            f"{'yes' if row.seeds_disagree else 'no'} | {failure} |"
        )
    rows.append("")
    ragged = [row for row in report.curve.rows if row.convergence_is_not_monotone]
    if ragged:
        rows.append(
            f"⚠️ At {', '.join(f'{row.jitter_px:g}px' for row in ragged)} the "
            f"sweep converged again at a larger lag than one it had already "
            f"failed at. The envelope column stops at the first failure "
            f"regardless, which is the safe reading — but the surface is not a "
            f"staircase, and no row of it may be inferred from its neighbours."
        )
    else:
        rows.append(
            "Convergence was monotone in lag at every jitter level: each "
            "column failed once and stayed failed. That is worth stating "
            "rather than assuming, because `PLAN.md` §14.8 found the "
            "neighbouring parameter behaving otherwise."
        )
    rows.append("")
    rows.append(f"**Envelope.** {report.curve.summary()}")
    rows.append("")
    return "\n".join(rows)


def _noise_failure_modes(report: NoiseReport) -> str:
    breaching = sum(row.floor_breaching_rows for row in report.curve.rows)
    diverging = sum(row.non_converging_rows for row in report.curve.rows)
    reversing = sum(row.reversing_rows for row in report.curve.rows)
    inside = sum(
        row.reversing_rows_inside_envelope for row in report.curve.rows
    )

    if reversing == 0:
        reversal = (
            "**No swept row reversed direction at all.** That is a silence, "
            "not a pass: the counter has been shown to work against runs that "
            "do reverse (M6 #04), so an empty column here means this sweep "
            "never entered the regime that produces one."
        )
    elif inside == 0:
        reversal = (
            f"{reversing} row(s) reversed direction, and **every one of them "
            f"was already failing** on another axis. Reversal is therefore a "
            f"symptom *at this travel multiplier* rather than a mode of its "
            f"own — and that qualifier is load-bearing: `PLAN.md` §14.8 "
            f"measured twelve reversing lags at 1.5x travel and none at all "
            f"at the 2.0x swept here. If a converging run ever reverses, this "
            f"line changes and the finding is new."
        )
    else:
        reversal = (
            f"{reversing} row(s) reversed direction, **{inside} of them while "
            f"still converging** — a run the other two axes call a success. "
            f"That is the case reversal was counted separately to catch."
        )

    swept = sum(row.rows_swept for row in report.curve.rows)
    return "\n".join(
        [
            "## The three failure modes, counted apart",
            "",
            "They are not the same event and each can hide the others. M6 #04 "
            "found the worst floor breach in its table reversing zero times "
            "and still reporting `arrived`.",
            "",
            f"**Read the denominator first.** The lag axis is swept to 3s on "
            f"purpose, which is several times past where the controller stops "
            f"converging, so most of the {swept} rows failing is the shape of "
            f"the experiment and not a finding. The column that carries "
            f"information is the last one.",
            "",
            "| Mode | Rows | Inside the envelope |",
            "|---|---|---|",
            f"| Crossed the safety floor | {breaching} of {swept} | none "
            f"possible — a run that crossed the floor is not a converging run "
            f"by definition |",
            f"| Did not converge | {diverging} of {swept} | — |",
            f"| Reversed direction | {reversing} of {swept} | **{inside}** |",
            "",
            reversal,
            "",
        ]
    )


def _noise_limits() -> str:
    return (
        "## What this does and does not establish\n"
        "\n"
        "| Claim | Status | |\n"
        "|---|---|---|\n"
        "| Where the envelope sits under wobble | parameter sweep | Both axes "
        "are UNCALIBRATED. No test asserts where this lands, and none may: "
        "`PLAN.md` §14.2 reserves thresholds for Measurements. |\n"
        "| The noise model matches the real detector | process-local "
        "measurement | Asserted, at several distances, against real pixels "
        "and real MediaPipe — see `tests/test_robustness.py`. That one *is* a "
        "Measurement, which is why it carries a threshold. |\n"
        "| How much wobble a Misty II's camera actually has | **UNVERIFIED** "
        "| Never measured. *Would be settled by: pointing the robot at a "
        "stationary person and recording the spread of reported distances.* |\n"
        "\n"
        "### Two things the grid could hide\n"
        "\n"
        "**Rows cannot be interpolated, and neither can the axis this sweep "
        "holds fixed.** `PLAN.md` §14.8 measured reversal as non-monotone in "
        "the travel multiplier: 1.5x reverses where 2.0x does not. A smaller "
        "multiplier is *not* a milder case, so the single multiplier swept "
        "here cannot stand in for the ones either side of it, and nothing "
        "licenses reading between two rows of this table.\n"
        "\n"
        "**Failure bands can be narrower than they look.** The same section "
        "found one 0.55s wide. This sweep steps the lag axis at 0.05s, which "
        "resolves that; a coarser grid would step over it and report the next "
        "failure as the first, which is exactly what M4 #08 did once.\n"
        "\n"
        "### The band-edge artefact is not in this table\n"
        "\n"
        "`PLAN.md` §14.9 records starts where public `arrived` and simulator "
        "truth disagree by a fraction of a centimetre, in the direction away "
        "from the subject, because the reading truncates to whole "
        "centimetres. Those recur every 70cm of start distance and this sweep "
        "runs from one fixed start, so none appear here. They are a "
        "quantisation artefact and would not be safety failures if they did.\n"
    )
