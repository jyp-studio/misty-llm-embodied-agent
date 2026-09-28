"""Typed results for model-selected perception Tools.

The cheap Snapshot stays fixed. Richer observation crosses this seam only
when the model asks for it, with cost, freshness and uncertainty attached.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping, Optional, Protocol, Tuple


class ActivePerceptionKind(str, Enum):
    TARGET_OBSERVATION = "target_observation"
    SCENE_INSPECTION = "scene_inspection"


class ActivePerceptionCost(str, Enum):
    CHEAP = "cheap"
    EXPENSIVE = "expensive"


class ActivePerceptionEnding(str, Enum):
    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ActivePerceptionResult:
    """One provider-neutral observation returned to the model."""

    kind: ActivePerceptionKind
    cost: ActivePerceptionCost
    ending: ActivePerceptionEnding
    age_s: float
    fresh_for_s: float
    facts: Mapping[str, Any] = field(default_factory=dict)
    uncertainty: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not math.isfinite(self.age_s) or self.age_s < 0:
            raise ValueError("active perception age must be finite and non-negative")
        if not math.isfinite(self.fresh_for_s) or self.fresh_for_s <= 0:
            raise ValueError("active perception freshness must be positive")
        if self.ending is ActivePerceptionEnding.OBSERVED and not self.facts:
            raise ValueError("an observed perception result needs typed facts")
        if self.ending is ActivePerceptionEnding.UNAVAILABLE and not self.uncertainty:
            raise ValueError("an unavailable perception result needs a reason")

    def as_tool_result(self) -> Mapping[str, Any]:
        return {
            "kind": self.kind.value,
            "cost": self.cost.value,
            "ending": self.ending.value,
            "age_s": round(self.age_s, 3),
            "fresh_for_s": self.fresh_for_s,
            "fresh": (
                self.ending is ActivePerceptionEnding.OBSERVED
                and self.age_s <= self.fresh_for_s
            ),
            "facts": dict(self.facts),
            "uncertainty": list(self.uncertainty),
        }


class ActivePerception(Protocol):
    def for_track(self, track_reference: object) -> "ActivePerception": ...

    def observe_target(self, *, now_s: float) -> ActivePerceptionResult: ...

    def inspect_scene(self, *, now_s: float) -> ActivePerceptionResult: ...


class NoActivePerception:
    """Null provider for sessions with no selected visual observation."""

    def for_track(self, track_reference: object) -> "NoActivePerception":
        return self

    def observe_target(self, *, now_s: float) -> ActivePerceptionResult:
        return self._unavailable(
            ActivePerceptionKind.TARGET_OBSERVATION,
            ActivePerceptionCost.CHEAP,
        )

    def inspect_scene(self, *, now_s: float) -> ActivePerceptionResult:
        return self._unavailable(
            ActivePerceptionKind.SCENE_INSPECTION,
            ActivePerceptionCost.EXPENSIVE,
        )

    @staticmethod
    def _unavailable(
        kind: ActivePerceptionKind,
        cost: ActivePerceptionCost,
    ) -> ActivePerceptionResult:
        return ActivePerceptionResult(
            kind=kind,
            cost=cost,
            ending=ActivePerceptionEnding.UNAVAILABLE,
            age_s=0.0,
            fresh_for_s=1.0,
            uncertainty=("no selected visual observation is available",),
        )


NO_ACTIVE_PERCEPTION = NoActivePerception()


#: Said with every look at a placed person, so nobody reads it as a camera.
SIMULATED_PLACEMENT = "simulated: where the scenario placed the person, not a camera frame"
#: Said when the placement is empty: they walked off, as a script can say.
SIMULATED_ABSENCE = "simulated: nobody is where the scenario placed them any more"


class PlacedPersonPerception:
    """Active perception for a scripted scenario that has no camera.

    The scenario placed its person in the simulated room, and the Snapshot
    already reports them from that placement; looking at them reports the
    same thing, labelled as a placement. Without this, a look answered
    "unavailable" and marked the target lost while the Snapshot beside it
    said they were right there.

    `reading` is the simulated world's latest distance reading, `None` once
    the placement is empty. It is a callable because the world is built with
    the Session this perception is handed to.
    """

    def __init__(
        self,
        reading: Callable[[], Optional[Any]],
        track_reference: Optional[object] = None,
    ) -> None:
        self._reading = reading
        self._reference = track_reference

    def for_track(self, track_reference: object) -> "PlacedPersonPerception":
        return PlacedPersonPerception(self._reading, track_reference)

    def observe_target(self, *, now_s: float) -> ActivePerceptionResult:
        return self._look(
            ActivePerceptionKind.TARGET_OBSERVATION, ActivePerceptionCost.CHEAP, now_s
        )

    def inspect_scene(self, *, now_s: float) -> ActivePerceptionResult:
        return self._look(
            ActivePerceptionKind.SCENE_INSPECTION, ActivePerceptionCost.EXPENSIVE, now_s
        )

    def _look(
        self, kind: ActivePerceptionKind, cost: ActivePerceptionCost, now_s: float
    ) -> ActivePerceptionResult:
        reading = self._reading()
        if reading is None:
            return ActivePerceptionResult(
                kind=kind,
                cost=cost,
                ending=ActivePerceptionEnding.UNAVAILABLE,
                age_s=0.0,
                fresh_for_s=1.0,
                uncertainty=(SIMULATED_ABSENCE,),
            )
        facts = {"person_count": 1, "distance_cm": reading.distance_cm}
        if reading.bearing_deg is not None:
            facts["bearing_deg"] = reading.bearing_deg
        if self._reference is not None:
            facts["track_reference"] = str(self._reference)
        return ActivePerceptionResult(
            kind=kind,
            cost=cost,
            ending=ActivePerceptionEnding.OBSERVED,
            age_s=max(0.0, now_s - reading.detected_at),
            fresh_for_s=1.0,
            facts=facts,
            uncertainty=(SIMULATED_PLACEMENT,),
        )


__all__ = [
    "ActivePerception",
    "ActivePerceptionCost",
    "ActivePerceptionEnding",
    "ActivePerceptionKind",
    "ActivePerceptionResult",
    "NO_ACTIVE_PERCEPTION",
    "PlacedPersonPerception",
    "SIMULATED_ABSENCE",
    "SIMULATED_PLACEMENT",
]
