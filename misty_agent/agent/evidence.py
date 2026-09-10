"""Typed, provider-neutral evidence that opens one Episode."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Tuple


#: Enough for a deliberately selected frame while keeping the first Turn
#: bounded independently of whichever InputSource produced it.
MAX_SELECTED_IMAGE_BYTES = 8 * 1024 * 1024


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
        try:
            decoded_size = len(
                base64.b64decode(self.data_base64, validate=True)
            )
        except (binascii.Error, ValueError) as error:
            raise ValueError(
                "selected image evidence must be strict base64"
            ) from error
        if decoded_size > MAX_SELECTED_IMAGE_BYTES:
            raise ValueError(
                "selected image evidence is too large: "
                f"{decoded_size} bytes exceeds {MAX_SELECTED_IMAGE_BYTES}"
            )


@dataclass(frozen=True)
class TriggerEvidenceSummary:
    """Completed-run evidence metadata with ephemeral image bytes removed."""

    source: EvidenceKind
    observed_at_s: float
    facts: Mapping[str, Any]
    transcript: str
    uncertainty: Tuple[str, ...]
    selected_image_media_type: Optional[str]

    @classmethod
    def from_evidence(
        cls, evidence: "TriggerEvidence"
    ) -> "TriggerEvidenceSummary":
        selected = evidence.selected_image
        return cls(
            source=evidence.source,
            observed_at_s=evidence.observed_at_s,
            facts=dict(evidence.facts),
            transcript=evidence.transcript,
            uncertainty=tuple(evidence.uncertainty),
            selected_image_media_type=(
                selected.media_type if selected is not None else None
            ),
        )


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


__all__ = [
    "EvidenceKind",
    "MAX_SELECTED_IMAGE_BYTES",
    "SelectedImageEvidence",
    "TriggerEvidence",
    "TriggerEvidenceSummary",
]
