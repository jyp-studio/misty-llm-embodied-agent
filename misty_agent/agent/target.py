"""One Episode's anonymous Interaction Target.

The target is the anonymous track the Trigger Evidence named, or nothing at
all when the Evidence was speech with no visual track. It is short-lived: it
is created with the Episode, it cannot be replaced inside the Episode, and it
is not carried to the next one. It is a track token, never an identity.

State follows what the Episode actually observed. The model's own active
perception calls report whether the same track was in the latest frame; a
closer, larger or newer face is a different track and cannot update this.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from misty_agent.agent.evidence import EvidenceKind, TriggerEvidence
from misty_agent.perception.active import (
    ActivePerceptionEnding,
    ActivePerceptionResult,
)


class TargetState(str, Enum):
    #: No anonymous track was named: speech-only Evidence.
    UNOBSERVABLE = "unobservable"
    #: Bound from the Evidence and not yet re-observed by this Episode.
    BOUND = "bound"
    #: The same anonymous track was in the latest observed frame.
    VISIBLE = "visible"
    #: The track was not in the latest observed frame; it may come back.
    LOST = "lost"
    #: Seen again after a loss, on the same anonymous track only.
    REACQUIRED = "reacquired"


class InteractionTarget:
    """The one person this Episode is about, as an anonymous track token."""

    def __init__(
        self,
        reference: Optional[str],
        source: EvidenceKind,
        bound_at_s: float,
    ) -> None:
        self._reference = str(reference) if reference else None
        self._source = source
        self._bound_at_s = bound_at_s
        self._state = (
            TargetState.BOUND if self._reference else TargetState.UNOBSERVABLE
        )

    @classmethod
    def from_evidence(cls, evidence: TriggerEvidence) -> "InteractionTarget":
        return cls(
            evidence.facts.get("track_reference"),
            evidence.source,
            evidence.observed_at_s,
        )

    @property
    def reference(self) -> Optional[str]:
        return self._reference

    @property
    def source(self) -> EvidenceKind:
        return self._source

    @property
    def state(self) -> TargetState:
        return self._state

    def update_from(self, result: ActivePerceptionResult) -> TargetState:
        """Update lost/visible/reacquired from one active observation.

        An observation carrying another track's reference is a programming
        error, not a switch: the perception view is bound to this track, so
        the only way another reference arrives is a wiring mistake.
        """
        if self._reference is None:
            return self._state
        if result.ending is ActivePerceptionEnding.OBSERVED:
            reported = result.facts.get(
                "track_reference", result.facts.get("target_track_reference")
            )
            if reported is not None and str(reported) != self._reference:
                raise ValueError(
                    "an observation of another anonymous track cannot update "
                    "this Episode's Interaction Target"
                )
            self._state = (
                TargetState.REACQUIRED
                if self._state is TargetState.LOST
                else TargetState.VISIBLE
            )
        elif result.ending is ActivePerceptionEnding.UNAVAILABLE:
            self._state = TargetState.LOST
        return self._state

    def as_facts(self) -> Dict[str, Any]:
        return {
            "track_reference": self._reference,
            "state": self._state.value,
            "bound_at": self._bound_at_s,
        }


__all__ = ["InteractionTarget", "TargetState"]
