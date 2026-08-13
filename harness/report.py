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

So every claim carries a status, and there are only two of them:

``simulated``   measured, in software, against a synthetic camera. Real
                MediaPipe on real pixels, real threads, real clock — but no
                robot and no network.
``unverified``  not established by anything here, with a note saying what
                would settle it.

There is deliberately no third status meaning "confirmed on hardware". Adding
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
from harness.robustness import ApproachOutcome, RobustnessEnvelope, envelope

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
    status: str  # "simulated" | "unverified"
    detail: str
    settled_by: str = ""

    def __post_init__(self) -> None:
        if self.status not in ("simulated", "unverified"):
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
                "# Perception harness — findings",
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
        claims=_claims(lag, rates, envelope(sweep)),
        runs=tuple(runs),
    )


# ---------------------------------------------------------------------------
# The claims
# ---------------------------------------------------------------------------

def _claims(
    lag: LagReport,
    rates: Optional[ThroughputReport],
    limits: RobustnessEnvelope,
) -> Tuple[Claim, ...]:
    lag_figure = (
        "no measurable lag in this trace"
        if lag.p95_s is None
        else f"p95 {lag.p95_s * 1000:.0f}ms"
    )
    return (
        Claim(
            "Distance readings lag reality, and by how much",
            "simulated",
            f"{lag_figure}, against a synthetic camera at {CAMERA_FPS:.0f} fps "
            f"with the real detector in the loop.",
        ),
        Claim(
            "The process-local frame buffer keeps only the latest value",
            "simulated",
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
            "The approach controller converges under a stale reading, up to a point",
            "simulated",
            limits.summary(),
        ),
        Claim(
            "The controller reports success even when it has failed",
            "simulated",
            "Every row of the sweep returns `arrived`, including rows that end "
            "inside the safety floor. It judges arrival from the same stale "
            "reading it steers by.",
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
            "`cm_per_sec_at_percent` is an assumption. The sweep shows a robot "
            "travelling twice as far as commanded walks through the safety "
            "floor.",
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
            "`approach_user()` has never executed on hardware. The public demo "
            "the project came from produced `movement: \"stay\"`.",
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
        rows.append(
            f"| Lag bound for the rewrite | {MAX_LAG_OVER_FLOOR:g} x the lag "
            f"floor, recomputed per run (~{report.rates.lag_floor_s * 1000:.0f} ms "
            f"here) rather than pinned, so it travels between machines |"
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
        "list has nine entries and this table has "
        f"{sum(1 for c in report.claims if c.status == 'unverified')}: §8 names "
        "the camera-to-process delay twice — once as "
        "`SENSOR_TRANSPORT_LAG_S` and once as \"RTSP 端到端延遲\" — and they "
        "are the same quantity.",
        "",
        "| Claim | Status | |",
        "|---|---|---|",
    ]
    for claim in report.claims:
        mark = "simulated" if claim.status == "simulated" else "**UNVERIFIED**"
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
        "| The robustness sweep in full | "
        "`docs/measurements/m4-transport-lag-sweep.md` |\n"
        "| Defects, decisions and retractions | `PLAN.md` §5, §12 |\n"
        "| The harness itself | `harness/` |\n"
    )
