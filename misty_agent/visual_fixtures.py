"""Synthetic temporal visual scenarios shared by acceptance tests and Demo.

These frames contain pre-authored local detector signals. They exercise the
tracking and gating implementation; they are not camera or hardware evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np

from misty_agent.visual_input import (
    BoundingBox,
    LocalVisualDetection,
    NormalizedPoint,
    ScheduledVisualFrame,
)


@dataclass(frozen=True)
class VisualFixture:
    """One finite synthetic frame timeline offered by acceptance and Demo."""

    key: str
    label: str
    frames: Tuple[ScheduledVisualFrame, ...]

    def __post_init__(self) -> None:
        if not self.key or not self.label or not self.frames:
            raise ValueError("a visual fixture needs a key, label, and frames")


def _detection(
    *,
    x: float,
    looking: bool,
    hand_x: Optional[float] = None,
    confidence: float = 0.92,
) -> LocalVisualDetection:
    return LocalVisualDetection(
        bounds=BoundingBox(x=x, y=0.2, width=0.2, height=0.4),
        confidence=confidence,
        looking=looking,
        hand_center=(
            NormalizedPoint(hand_x, 0.35)
            if hand_x is not None
            else None
        ),
    )


def _frame(
    at_s: float, *detections: LocalVisualDetection
) -> ScheduledVisualFrame:
    """Draw a plain scene so a selected evidence crop is inspectable."""
    image = np.full((120, 160, 3), 245, dtype=np.uint8)
    for detection in detections:
        left = int(detection.bounds.x * image.shape[1])
        top = int(detection.bounds.y * image.shape[0])
        right = int(
            (detection.bounds.x + detection.bounds.width) * image.shape[1]
        )
        bottom = int(
            (detection.bounds.y + detection.bounds.height) * image.shape[0]
        )
        image[top:bottom, left:right] = (205, 197, 187)
        if detection.hand_center is not None:
            hand_x = int(detection.hand_center.x * image.shape[1])
            hand_y = int(detection.hand_center.y * image.shape[0])
            image[
                max(0, hand_y - 3):hand_y + 4,
                max(0, hand_x - 3):hand_x + 4,
            ] = (130, 116, 102)
    return ScheduledVisualFrame(at_s, image, tuple(detections))


def _gaze_wave_frames(
    *, two_people: bool = False
) -> Tuple[ScheduledVisualFrame, ...]:
    frames = []
    for index, hand_x in enumerate((0.10, 0.55, 0.12, 0.58)):
        waving = _detection(
            x=0.15 + (0.01 if index % 2 else 0.0),
            looking=True,
            hand_x=hand_x,
        )
        passerby = _detection(x=0.70, looking=False, confidence=0.82)
        detections = (
            (passerby, waving)
            if two_people and index % 2
            else ((waving, passerby) if two_people else (waving,))
        )
        frames.append(_frame(index * 0.2, *detections))
    return tuple(frames)


VISUAL_FIXTURES: Tuple[VisualFixture, ...] = (
    VisualFixture(
        "visual-empty-room",
        "空房間（不互動）",
        tuple(_frame(at_s) for at_s in (0.0, 0.3, 0.6)),
    ),
    VisualFixture(
        "visual-passerby",
        "路過但沒有看向 Misty（不互動）",
        tuple(
            _frame(at_s, _detection(x=x, looking=False))
            for at_s, x in ((0.0, 0.05), (0.3, 0.25), (0.6, 0.45))
        ),
    ),
    VisualFixture(
        "visual-gaze-wave",
        "持續看向 Misty 並揮手",
        _gaze_wave_frames(),
    ),
    VisualFixture(
        "visual-two-people",
        "兩人入鏡，其中一人持續揮手",
        _gaze_wave_frames(two_people=True),
    ),
)


def visual_fixture(key: str) -> VisualFixture:
    """Return one named fixture without duplicating its temporal facts."""
    found = next((item for item in VISUAL_FIXTURES if item.key == key), None)
    if found is None:
        raise KeyError(key)
    return found


__all__ = ["VISUAL_FIXTURES", "VisualFixture", "visual_fixture"]
