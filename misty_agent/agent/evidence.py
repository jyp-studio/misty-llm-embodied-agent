"""Typed, provider-neutral evidence that opens one Episode."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Tuple


class EvidenceKind(str, Enum):
    """Where selected Trigger Evidence came from."""

    SPEECH = "speech"
    VISUAL = "visual"


@dataclass(frozen=True)
class SelectedImageEvidence:
    """One bounded image selected for the first model Turn."""

    media_type: str
    data_base64: str

    def __post_init__(self) -> None:
        if not self.media_type.startswith("image/"):
            raise ValueError("selected image evidence needs an image media type")
        if not self.data_base64:
            raise ValueError("selected image evidence cannot be empty")


@dataclass(frozen=True)
class TriggerEvidence:
    """Why the Attention Loop opened an Episode, before its first Turn."""

    source: EvidenceKind
    observed_at_s: float
    facts: Mapping[str, Any] = field(default_factory=dict)
    transcript: str = ""
    uncertainty: Tuple[str, ...] = ()
    selected_image: Optional[SelectedImageEvidence] = None

    def __post_init__(self) -> None:
        if self.observed_at_s < 0:
            raise ValueError("Trigger Evidence cannot predate the runtime")

    def model_message(self) -> Mapping[str, Any]:
        """Return provider-neutral text and image content for one Turn."""
        content = [
            {
                "type": "text",
                "text": {
                    "trigger_evidence": {
                        "source": self.source.value,
                        "observed_at_s": self.observed_at_s,
                        "facts": dict(self.facts),
                        "transcript": self.transcript,
                        "uncertainty": list(self.uncertainty),
                    }
                },
            }
        ]
        if self.selected_image is not None:
            content.append(
                {
                    "type": "image",
                    "media_type": self.selected_image.media_type,
                    "data_base64": self.selected_image.data_base64,
                }
            )
        return {"role": "user", "content": content}


def legacy_evidence(trigger: str, said: str) -> TriggerEvidence:
    """Keep direct Episode callers working while Runtime owns the new seam."""
    return TriggerEvidence(
        source=EvidenceKind(trigger),
        observed_at_s=0.0,
        facts={},
        transcript=said,
    )


__all__ = [
    "EvidenceKind",
    "SelectedImageEvidence",
    "TriggerEvidence",
    "legacy_evidence",
]
