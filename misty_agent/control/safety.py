"""The safety state a movement checkpoint reads, and the two null sources.

A hazard reading says whether the base may move right now, when that was
known, and what the source cannot vouch for. The controller treats a missing
or stale reading exactly like a hazard: it does not move. That is the spec's
"fail closed" for real hardware, where today no hazard signal reaches this
process at all, so `NO_HAZARD_SOURCE` is what a real Session gets.

`ALWAYS_CLEAR` is for simulation only. A scenario that uses it is asserting
"nothing is in the way" as a fact about its own world, the way it asserts
where the person stands; it is never a measurement, and production wiring
must not reach for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, Tuple


@dataclass(frozen=True)
class HazardReading:
    """Whether the base may move, as of `observed_at` on the caller's clock.

    `observed_at` is `None` only for a scenario assertion that is true by
    construction; a measured reading always carries its time, so staleness
    can be judged.
    """

    blocked: bool
    observed_at: Optional[float]
    uncertainty: Tuple[str, ...] = ()


class HazardSource(Protocol):
    def latest_hazard(self) -> Optional[HazardReading]: ...


class NoHazardSource:
    """No hazard signal exists: the controller must fail closed."""

    def latest_hazard(self) -> None:
        return None


class AlwaysClear:
    """A simulated scenario's assertion that nothing is in the way."""

    def latest_hazard(self) -> HazardReading:
        return HazardReading(
            blocked=False,
            observed_at=None,
            uncertainty=("simulated: the scenario asserts a clear path",),
        )


NO_HAZARD_SOURCE = NoHazardSource()
ALWAYS_CLEAR = AlwaysClear()

__all__ = [
    "ALWAYS_CLEAR",
    "AlwaysClear",
    "HazardReading",
    "HazardSource",
    "NO_HAZARD_SOURCE",
    "NoHazardSource",
]
