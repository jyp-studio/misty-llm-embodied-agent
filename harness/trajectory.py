"""Where the person is, at any instant of a replay.

A trajectory is the harness's ground truth: a pure function from elapsed
seconds to distance in centimetres, built up from named segments. It touches
no camera, no detector and no clock, so it stays reproducible while everything
measured around it does not — which is the asymmetry the whole harness rests
on.

Three kinds of segment, chosen because they expose different things:

``walk``  the person approaches at a steady pace. The reading falls behind by
          however long the pipeline takes, and the faster they walk the larger
          the error that lag turns into.
``hold``  nobody moves. The control group: a stale reading and a fresh one are
          indistinguishable here, which is why the lag went unnoticed for so
          long — a robot facing a stationary person looks like it is working.
``step``  the distance changes between one frame and the next, because the
          robot drove forward. Nothing about the person changed; the whole
          jump is the robot's own motion, and every sample taken before it is
          now describing a world that no longer exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Tuple

SegmentKind = Literal["walk", "hold", "step"]


def _positive(distance_cm: float) -> float:
    if distance_cm <= 0:
        raise ValueError(f"distance must be positive, got {distance_cm}")
    return float(distance_cm)


@dataclass(frozen=True)
class Segment:
    """One stretch of the script.

    ``duration_s`` is zero for a step, which is what makes it a step: the
    distance changes without any time passing.
    """

    kind: SegmentKind
    start_cm: float
    end_cm: float
    duration_s: float

    def describe(self) -> str:
        if self.kind == "walk":
            return f"walk to {self.end_cm:g}cm over {self.duration_s:g}s"
        if self.kind == "hold":
            return f"hold {self.duration_s:g}s"
        return f"step to {self.end_cm:g}cm"

    def distance_at(self, elapsed_s: float) -> float:
        if self.duration_s <= 0:
            return self.end_cm
        fraction = min(1.0, elapsed_s / self.duration_s)
        return self.start_cm + (self.end_cm - self.start_cm) * fraction


@dataclass(frozen=True)
class Trajectory:
    """A script for the person in front of the robot.

    Built declaratively and immutably — each method returns a new trajectory,
    so a script can be extended without disturbing one already recorded
    against:

    ```python
    Trajectory.starting_at(130.0).walk_to(90.0, over=6.0).hold(2.0).step_to(65.0)
    ```

    ``distance_at`` is total over the replay: before the script has finished it
    interpolates, and after it has, the person stays where they ended. Negative
    time is an error rather than a clamp — it means the caller's clock and the
    replay's disagree about when the replay started, and silently returning the
    opening position would hide that.
    """

    start_cm: float
    segments: Tuple[Segment, ...] = ()

    # ---------- building ----------

    @classmethod
    def starting_at(cls, distance_cm: float) -> "Trajectory":
        return cls(start_cm=_positive(distance_cm))

    def walk_to(self, distance_cm: float, *, over: float) -> "Trajectory":
        """The person walks to ``distance_cm``, arriving after ``over`` seconds."""
        if over <= 0:
            raise ValueError(
                f"a walk takes time; use step_to for an instant change (got {over})"
            )
        return self._append("walk", _positive(distance_cm), over)

    def hold(self, seconds: float) -> "Trajectory":
        """Nobody moves for ``seconds``."""
        if seconds <= 0:
            raise ValueError(f"a hold takes time, got {seconds}")
        return self._append("hold", self.final_cm, seconds)

    def step_to(self, distance_cm: float) -> "Trajectory":
        """The distance changes instantly — the robot moved, not the person."""
        return self._append("step", _positive(distance_cm), 0.0)

    def _append(
        self, kind: SegmentKind, end_cm: float, duration_s: float
    ) -> "Trajectory":
        segment = Segment(kind, self.final_cm, end_cm, duration_s)
        return Trajectory(start_cm=self.start_cm, segments=self.segments + (segment,))

    # ---------- reading ----------

    @property
    def duration_s(self) -> float:
        return sum(segment.duration_s for segment in self.segments)

    @property
    def final_cm(self) -> float:
        return self.segments[-1].end_cm if self.segments else self.start_cm

    def distance_at(self, elapsed_s: float) -> float:
        """Where the person is ``elapsed_s`` into the replay."""
        if elapsed_s < 0:
            raise ValueError(f"replay time cannot be negative, got {elapsed_s}")

        remaining = elapsed_s
        for segment in self.segments:
            if remaining < segment.duration_s:
                return segment.distance_at(remaining)
            remaining -= segment.duration_s
        return self.final_cm

    def describe(self) -> str:
        """One line naming what was replayed.

        A latency figure without the script that produced it cannot be
        reproduced, so 06 and 09 record this next to their numbers.
        """
        opening = f"start {self.start_cm:g}cm"
        if not self.segments:
            return opening
        return ", ".join([opening, *(s.describe() for s in self.segments)])


#: The script the harness replays by default.
#:
#: **Starts at 130 cm rather than the 150 cm the milestone spec sketched, but
#: not for the reason first recorded.** The original argument — that the
#: fixture's far-field bias would warp the correlation — was wrong: PLAN.md
#: §12.5's error figures were taken with a *fresh detector per distance*, and
#: the harness feeds one detector a continuous sequence. Measured that way,
#: 120–155 cm all read within 1.3%, with no distance-varying drift.
#:
#: What survives is smaller and real: **the first frame of a replay is always
#: cold**, with nothing for tracking to work from, and cold-start error grows
#: with distance (130 cm cold reads 132; 160 cm cold reads 170). Opening
#: closer keeps that one frame honest. Nothing is lost by it — the controller
#: commands a forward step above 72 cm and its arrival band is 48–72 cm, so
#: 130 → 69 already spans everything the control law does.
#:
#: The step is 90 → 69 cm because that is what the control law actually
#: commands at 90 cm: ``plan_step(90)`` returns 21 cm at the default gain.
#: ``test_trajectory.py`` pins the two together, so a change to the control law
#: shows up here rather than leaving the script quietly unrealistic.
APPROACH_HOLD_STEP = (
    Trajectory.starting_at(130.0)
    .walk_to(90.0, over=6.0)  # ~6.7 cm/s, an unhurried walk
    .hold(2.0)
    .step_to(69.0)
    .hold(2.0)
)
