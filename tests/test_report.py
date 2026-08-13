"""The report a reader sees, and the claims it is allowed to make.

`build_report` is pure — it takes a trace and a sweep and returns text — so
these tests run in milliseconds and need no media stack. The command that
records the trace is a thin wrapper around it, tested separately by being run.

Most of what is asserted here is about **honesty**, not arithmetic. The numbers
are already tested where they are computed. What this file guards is that the
report cannot present a swept parameter as a measurement, cannot omit the
machine it ran on, and cannot claim anything about hardware nobody has.
"""

from __future__ import annotations

import pytest

from harness.report import build_report
from harness.replay import Sample, Trace
from harness.robustness import sweep_transport_lag

HZ = 40.0


def walking_trace(lag_s: float = 0.04, *, machine: str = "test-machine") -> Trace:
    samples = []
    for i in range(160):
        t = i / HZ
        truth = 130.0 - 40.0 * t
        delayed = 130.0 - 40.0 * max(0.0, t - lag_s)
        samples.append(
            Sample(
                t=t,
                truth_cm=truth,
                reported_cm=int(delayed),
                backlog=0,
                frame_arrived_at=t,
                detected_at=t + 0.005,
            )
        )
    return Trace(
        samples=tuple(samples),
        trajectory="start 130cm, walk to 90cm over 1s",
        sample_hz=HZ,
        environment={"machine": machine, "python": "3.11.3", "platform": "test"},
    )


@pytest.fixture(scope="module")
def report():
    return build_report(
        [walking_trace(), walking_trace()],
        sweep_transport_lag([0.0, 0.5, 1.0, 1.5, 2.0]),
        pipeline="DirectPipeline",
    )


# ---------------------------------------------------------------------------
# The numbers the ticket asks for
# ---------------------------------------------------------------------------

def test_the_report_carries_every_figure_the_ticket_lists(report):
    text = report.to_markdown()

    for expected in ("p50", "p95", "buffer", "frame age", "converges"):
        assert expected in text.lower(), f"{expected!r} missing from the report"


def test_the_report_names_the_pipeline_it_measured(report):
    # Ticket 06 measures one pipeline; M5 will measure another against the same
    # bound. A report that does not say which is not comparable to anything.
    assert "DirectPipeline" in report.to_markdown()


def test_the_report_names_the_machine_it_ran_on(report):
    # PLAN.md §12.2: the same code measured an order of magnitude apart on two
    # machines. A latency figure without its host is not a result.
    assert "test-machine" in report.to_markdown()


def test_the_report_names_the_trajectory_that_produced_it(report):
    assert "130cm" in report.to_markdown()


# ---------------------------------------------------------------------------
# What it is allowed to claim
# ---------------------------------------------------------------------------

def test_the_sweep_is_never_presented_as_a_measurement(report):
    text = report.to_markdown().lower()

    assert "not a measurement" in text
    assert "sweep" in text


def test_segment_a_is_named_as_unmeasurable(report):
    text = report.to_markdown().lower()

    assert "rtsp" in text
    assert "hardware" in text


def test_every_claim_is_labelled_verified_or_not(report):
    # The ticket asks for these to be distinguished 逐條 — item by item, not as
    # one disclaimer at the bottom that a skimming reader skips.
    for claim in report.claims:
        assert claim.status in ("simulated", "unverified"), claim


def test_nothing_claims_to_have_run_on_a_robot(report):
    # PLAN.md §1: there is no robot and never will be. A report that implied
    # otherwise would be the single most damaging thing in the repository.
    assert not any(claim.status == "hardware" for claim in report.claims)
    assert "has ever run against a Misty II" in report.to_markdown()
    assert "No line of this project" in report.to_markdown()


def test_the_unverified_claims_say_what_would_settle_them(report):
    # An honest gap names its own test. "Unverified" alone reads as an excuse.
    for claim in report.claims:
        if claim.status == "unverified":
            assert claim.settled_by, f"{claim.what!r} says nothing about how to check it"


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------

def test_the_terminal_form_is_shorter_than_the_document(report):
    assert 0 < len(report.to_text()) < len(report.to_markdown())


def test_a_trace_with_no_measurable_lag_is_reported_rather_than_faked():
    still = Trace(
        samples=tuple(
            Sample(t=i / HZ, truth_cm=90.0, reported_cm=90, backlog=0)
            for i in range(80)
        ),
        trajectory="synthetic hold",
        sample_hz=HZ,
        environment={"machine": "test-machine"},
    )
    text = build_report(
        [still], sweep_transport_lag([0.0]), pipeline="DirectPipeline"
    ).to_markdown()

    assert "no measurable lag" in text.lower()


def test_the_document_is_markdown_a_reader_can_open(report):
    text = report.to_markdown()

    assert text.startswith("#")
    assert "|" in text  # at least one table
    assert text.endswith("\n")


def test_a_report_needs_at_least_one_trace():
    with pytest.raises(ValueError):
        build_report([], sweep_transport_lag([0.0]), pipeline="DirectPipeline")


def test_figures_that_vary_between_runs_are_shown_as_a_range():
    """The defect that made the first published artefact unreproducible.

    It was built from one replay, so buffer depth, frame age and the queue
    crossing were published as single values. A rerun disagreed with all three,
    and the crossing contradicted the baseline document the report points at.
    """
    quiet = walking_trace()
    busy = Trace(
        samples=tuple(
            Sample(s.t, s.truth_cm, s.reported_cm, backlog=4,
                   frame_arrived_at=s.t, detected_at=s.t + 0.02)
            for s in quiet.samples
        ),
        trajectory=quiet.trajectory,
        sample_hz=quiet.sample_hz,
        environment=quiet.environment,
    )
    text = build_report(
        [quiet, busy], sweep_transport_lag([0.0]), pipeline="DirectPipeline"
    ).to_markdown()

    assert "0–4" in text, "buffer depth should be shown as a range across runs"
    assert "run" in text.lower()


def test_p50_is_marked_as_not_quotable():
    # The baseline document's instruction is "should not be quoted", not
    # "is bimodal" — a reader who sees only the latter quotes it anyway.
    assert "do not quote this" in build_report(
        [walking_trace()], sweep_transport_lag([0.0]), pipeline="DirectPipeline"
    ).to_markdown().lower()


def test_every_unverified_boundary_in_the_plan_reaches_the_report():
    """Cross-check against PLAN.md §8, which is the canonical list.

    A boundary that is in the plan but not in the report is a boundary the
    reader is never told about, and this artefact is the only place most
    readers will look.
    """
    import pathlib

    plan = pathlib.Path(__file__).resolve().parent.parent / "PLAN.md"
    section = plan.read_text().split("## 8.")[1].split("## 9.")[0]
    listed = [line for line in section.splitlines() if line.startswith("- ")]

    report = build_report(
        [walking_trace()], sweep_transport_lag([0.0]), pipeline="DirectPipeline"
    )
    unverified = [c for c in report.claims if c.status == "unverified"]

    # Nine in the plan, eight here: it names the camera-to-process delay twice.
    assert len(listed) == 9
    assert len(unverified) == 8
    assert "listed twice" in report.to_markdown()
