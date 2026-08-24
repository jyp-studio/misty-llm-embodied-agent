"""``python -m harness`` — record a replay, sweep the unknown, write it down.

The one command ticket 09 asks for. It does no analysis of its own: it wires a
camera to a pipeline, hands the trace and the sweep to
:func:`harness.report.build_report`, prints the short form and writes the long
one. Everything it could get wrong is tested elsewhere, in milliseconds,
without a camera.

    .venv/bin/python -m harness

Takes about as long as the trajectory it replays — real time, no virtual clock,
because MediaPipe's per-frame cost is part of what is being measured.
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from harness.report import PUBLISHED_RUNS

DEFAULT_FIXTURE = (
    pathlib.Path(__file__).resolve().parent.parent
    / "tests"
    / "fixtures"
    / "frontal_face_portrait.jpg"
)
DEFAULT_OUTPUT = (
    pathlib.Path(__file__).resolve().parent.parent
    / "docs"
    / "measurements"
    / "m5-approach-report.md"
)
#: The M6 findings go in their own file rather than into the M5 one. A report
#: that replaces its predecessor destroys the before-state its successor is
#: measured against — the reasoning PLAN.md §13.3 recorded when M5 declined to
#: overwrite M4's. One command still writes both, so nobody can end up holding
#: half of one run and half of another.
DEFAULT_NOISE_OUTPUT = (
    pathlib.Path(__file__).resolve().parent.parent
    / "docs"
    / "measurements"
    / "m6-noise-envelope-report.md"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m harness",
        description=(
            "Replay a scripted approach through the real perception pipeline, "
            "sweep the delay nobody can measure, and write down what happened."
        ),
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=DEFAULT_OUTPUT,
        help=(
            "where to write the markdown report. It is committed so that "
            "readers without mediapipe installed can still see the numbers."
        ),
    )
    parser.add_argument(
        "--noise-out",
        type=pathlib.Path,
        default=DEFAULT_NOISE_OUTPUT,
        help=(
            "where to write the reading-noise boundary curve. Written by the "
            "same invocation as --out so the two documents always describe "
            "the same run."
        ),
    )
    parser.add_argument(
        "--portrait",
        type=pathlib.Path,
        default=DEFAULT_FIXTURE,
        help="the photograph composited into every frame",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=PUBLISHED_RUNS,
        help=(
            "how many replays to average over. One is not enough: buffer "
            "depth, frame age and the queue crossing all vary between "
            "otherwise identical runs, and a single run published them as "
            "results once already."
        ),
    )
    parser.add_argument(
        "--sample-hz",
        type=float,
        default=40.0,
        help=(
            "how often to record. Sampling slower than the camera cannot "
            "resolve a lag shorter than one frame period."
        ),
    )
    args = parser.parse_args(argv)

    try:
        import cv2
    except ImportError:
        print(
            "mediapipe and opencv are needed to record a trace.\n"
            "Run under the project venv: .venv/bin/python -m harness\n"
            "The last recorded report is committed at "
            f"{DEFAULT_OUTPUT.relative_to(DEFAULT_OUTPUT.parent.parent.parent)}",
            file=sys.stderr,
        )
        return 1

    from harness.replay import default_replay
    from harness.report import build_noise_report, build_report
    from harness.robustness import (
        DEFAULT_SWEEP_START_CM,
        boundary_curve,
        default_sweep_lags,
        describe_lags,
        sweep_lag_and_jitter,
        sweep_transport_lag,
    )
    from misty_agent.config import settings as live_settings

    portrait = cv2.imread(str(args.portrait))
    if portrait is None:
        print(f"could not read {args.portrait}", file=sys.stderr)
        return 1

    traces = []
    for run in range(args.runs):
        print(
            f"replaying {run + 1}/{args.runs} (real time)...", file=sys.stderr
        )
        traces.append(default_replay(portrait, sample_hz=args.sample_hz))
    report = build_report(
        traces, sweep_transport_lag(), pipeline="DistancePipeline"
    )

    print("sweeping transport lag against detector jitter...", file=sys.stderr)
    noise = build_noise_report(
        boundary_curve(sweep_lag_and_jitter()),
        start_cm=DEFAULT_SWEEP_START_CM,
        multiplier=live_settings.max_actual_motion_multiplier,
        lag_span=describe_lags(default_sweep_lags()),
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report.to_markdown())
    args.noise_out.parent.mkdir(parents=True, exist_ok=True)
    args.noise_out.write_text(noise.to_markdown())

    print(report.to_text(), end="")
    print(noise.to_text(), end="")
    print(f"written to {args.out} and {args.noise_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
