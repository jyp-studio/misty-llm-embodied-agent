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
class HazardState:
    """Whether the base may move, as of `observed_at` on the caller's clock.

    Not a Reading: that word is the distance measurement's. This is the
    safety state a checkpoint consults.

    `observed_at` is `None` only for a scenario assertion that is true by
    construction; a measured reading always carries its time, so staleness
    can be judged.
    """

    blocked: bool
    observed_at: Optional[float]
    uncertainty: Tuple[str, ...] = ()


#: The one caveat every simulated hazard state carries.
SIMULATED_HAZARD = "simulated hazard state, provided by the scenario, never sensed"


class HazardSource(Protocol):
    def latest_hazard(self) -> Optional[HazardState]: ...


class NoHazardSource:
    """No hazard signal exists: the controller must fail closed."""

    def latest_hazard(self) -> None:
        return None


class AlwaysClear:
    """A simulated scenario's assertion that nothing is in the way."""

    def latest_hazard(self) -> HazardState:
        return HazardState(
            blocked=False,
            observed_at=None,
            uncertainty=(SIMULATED_HAZARD,),
        )


NO_HAZARD_SOURCE = NoHazardSource()
ALWAYS_CLEAR = AlwaysClear()

__all__ = [
    "SIMULATED_HAZARD",
    "ALWAYS_CLEAR",
    "AlwaysClear",
    "HazardState",
    "HazardSource",
    "NO_HAZARD_SOURCE",
    "NoHazardSource",
]
