"""Turn local temporal visual signals into Social Invitation inputs.

The gate observes only person bounds, camera-facing geometry and hand motion.
It does not infer emotion and it never chooses a robot response. Raw frames
stay inside this provider; only the one crop selected when a temporal cue
qualifies can cross into Trigger Evidence.

The deterministic fixtures exercise tracking and temporal gating. MediaPipe
signal extraction is available for local frames, but no real camera or Misty
II has verified its accuracy, latency, association policy, or thresholds.
"""

from __future__ import annotations

import base64
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Optional, Protocol, Sequence, Tuple

import numpy as np

from misty_agent.agent.evidence import SelectedImageEvidence
from misty_agent.perception.active import (
    ActivePerceptionCost,
    ActivePerceptionEnding,
    ActivePerceptionKind,
    ActivePerceptionResult,
)
from misty_agent.runtime import (
    AnonymousTrackReference,
    CueKind,
    InputArrival,
    VisualAttentionNotice,
    VisualAttentionOutcome,
    VisualCue,
)


@dataclass(frozen=True)
class NormalizedPoint:
    """One finite image point in normalized zero-to-one coordinates."""

    x: float
    y: float

    def __post_init__(self) -> None:
        if not all(
            math.isfinite(value) and 0 <= value <= 1
            for value in (self.x, self.y)
        ):
            raise ValueError("normalized image point must stay in [0, 1]")


@dataclass(frozen=True)
class BoundingBox:
    """A normalized image rectangle owned by one local detection."""

    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.width, self.height)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("visual bounds must be finite")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("visual bounds must have positive dimensions")
        if (
            self.x < 0
            or self.y < 0
            or self.x + self.width > 1
            or self.y + self.height > 1
        ):
            raise ValueError("visual bounds must stay inside the image")

    @property
    def center(self) -> NormalizedPoint:
        return NormalizedPoint(
            self.x + self.width / 2,
            self.y + self.height / 2,
        )


@dataclass(frozen=True)
class ObservablePersonGeometry:
    """Observable boolean geometry, with no inferred emotion label."""

    eyes_narrowed: bool = False
    mouth_open: bool = False
    head_lowered: bool = False
    mouth_corners_raised: bool = False

    @property
    def signal_count(self) -> int:
        return sum(self.as_facts().values())

    def as_facts(self) -> dict[str, bool]:
        return {
            "eyes_narrowed": self.eyes_narrowed,
            "mouth_open": self.mouth_open,
            "head_lowered": self.head_lowered,
            "mouth_corners_raised": self.mouth_corners_raised,
        }

    def describe(self) -> str:
        labels = {
            "eyes_narrowed": "narrowed eyes",
            "mouth_open": "an open mouth",
            "head_lowered": "a lowered head",
            "mouth_corners_raised": "raised mouth corners",
        }
        return ", ".join(
            label for name, label in labels.items() if self.as_facts()[name]
        )


NO_OBSERVABLE_GEOMETRY = ObservablePersonGeometry()


@dataclass(frozen=True)
class LocalVisualDetection:
    """Observable, local-only signals for one anonymous person in one frame."""

    bounds: BoundingBox
    confidence: float
    looking: bool
    hand_center: Optional[NormalizedPoint] = None
    geometry: ObservablePersonGeometry = NO_OBSERVABLE_GEOMETRY

    def __post_init__(self) -> None:
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("visual confidence must be between zero and one")
        if self.hand_center is not None and not isinstance(
            self.hand_center, NormalizedPoint
        ):
            raise TypeError("hand center must be a NormalizedPoint")
        if not isinstance(self.geometry, ObservablePersonGeometry):
            raise TypeError("visual geometry must be ObservablePersonGeometry")


@dataclass(frozen=True)
class _MeshSignal:
    center: NormalizedPoint
    looking: bool
    geometry: ObservablePersonGeometry


@dataclass(frozen=True)
class ScheduledVisualFrame:
    """One fixture frame and when it becomes observable to the adapter."""

    at_s: float
    image: np.ndarray
    detections: Tuple[LocalVisualDetection, ...]

    def __post_init__(self) -> None:
        if not math.isfinite(self.at_s) or self.at_s < 0:
            raise ValueError("visual fixture time must be finite and non-negative")
        if self.image.ndim != 3 or self.image.shape[2] != 3:
            raise ValueError("visual fixture image must be HxWx3 BGR")


@dataclass(frozen=True)
class VisualFrameArrival:
    """One decoded frame plus its portable age at the provider boundary."""

    age_s: float
    frame_index: int
    image: np.ndarray
    detections: Tuple[LocalVisualDetection, ...]

    def __post_init__(self) -> None:
        if not math.isfinite(self.age_s) or self.age_s < 0:
            raise ValueError("visual frame age must be finite and non-negative")
        if self.frame_index < 0:
            raise ValueError("visual frame index cannot be negative")
        if self.image.ndim != 3 or self.image.shape[2] != 3:
            raise ValueError("visual frame image must be HxWx3 BGR")


class VisualFrameSource(Protocol):
    """The bounded frame lifecycle consumed by ``VisualInputAdapter``."""

    def start(self) -> None: ...

    def read_frame(self, timeout: float) -> Optional[VisualFrameArrival]: ...

    @property
    def exhausted(self) -> bool: ...

    def stop(self) -> None: ...


@dataclass(frozen=True)
class VisualGatePolicy:
    """Simulation-backed thresholds; none are real-camera measurements."""

    minimum_confidence: float = 0.60
    minimum_gaze_s: float = 0.60
    minimum_wave_span: float = 0.25
    minimum_direction_changes: int = 1
    gesture_window_s: float = 0.8
    track_max_jump: float = 0.25
    track_ttl_s: float = 1.0
    max_tracks: int = 4
    evidence_max_side_px: int = 320
    cue_freshness_s: float = 2.0
    minimum_care_s: float = 0.4
    minimum_care_frames: int = 3

    def __post_init__(self) -> None:
        if not 0 <= self.minimum_confidence <= 1:
            raise ValueError("visual minimum confidence must be in [0, 1]")
        if self.minimum_gaze_s <= 0 or self.minimum_wave_span <= 0:
            raise ValueError("visual temporal thresholds must be positive")
        if self.minimum_direction_changes < 1:
            raise ValueError("a wave needs at least one direction change")
        if (
            self.gesture_window_s <= 0
            or self.track_max_jump <= 0
            or self.track_ttl_s <= 0
        ):
            raise ValueError("visual tracking bounds must be positive")
        if self.max_tracks <= 0 or self.evidence_max_side_px <= 0:
            raise ValueError("visual capacities must be positive")
        if self.cue_freshness_s <= 0:
            raise ValueError("visual cue freshness must be positive")
        if self.minimum_care_s <= 0 or self.minimum_care_frames < 2:
            raise ValueError("visual care evidence must be temporal")


@dataclass
class _Track:
    reference: AnonymousTrackReference
    center: NormalizedPoint
    last_seen_at: float
    gaze_started_at: Optional[float] = None
    observed_frames: int = 0
    gaze_frames: int = 0
    gaze_confidence_sum: float = 0.0
    hand_samples: Deque[Tuple[float, float]] = field(
        default_factory=lambda: deque(maxlen=8)
    )
    invitation_emitted: bool = False
    care_started_at: Optional[float] = None
    care_frames: int = 0
    care_confidence_sum: float = 0.0
    care_emitted: bool = False
    latest_detection: Optional[LocalVisualDetection] = None
    latest_frame_index: int = -1


@dataclass(frozen=True)
class _ObservedInput:
    item: VisualAttentionNotice | VisualCue
    observed_at: float


class LocalVisualGate:
    """Track anonymous detections and qualify temporal gaze-plus-wave cues."""

    def __init__(self, policy: VisualGatePolicy = VisualGatePolicy()) -> None:
        self._policy = policy
        self._tracks: list[_Track] = []
        self._next_track = 1
        self._latest_frame_index: Optional[int] = None
        self._latest_person_count = 0

    def observe(
        self,
        *,
        observed_at: float,
        frame_index: int,
        image: np.ndarray,
        detections: Sequence[LocalVisualDetection],
    ) -> Tuple[Tuple[VisualAttentionNotice, ...], Optional[VisualCue]]:
        if not math.isfinite(observed_at) or observed_at < 0:
            raise ValueError("visual observation time must be non-negative")
        if frame_index < 0:
            raise ValueError("visual frame index cannot be negative")
        if image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("visual gate image must be HxWx3 BGR")
        self._tracks = [
            track
            for track in self._tracks
            if observed_at - track.last_seen_at <= self._policy.track_ttl_s
        ]
        self._latest_frame_index = frame_index
        self._latest_person_count = len(detections)
        if not detections:
            return (
                (
                    VisualAttentionNotice(
                        frame_index=frame_index,
                        outcome=VisualAttentionOutcome.EMPTY,
                        facts={"person_count": 0},
                    ),
                ),
                None,
            )

        assignments = self._assign(detections, observed_at)
        notices = []
        selected_cue = None
        for detection, track in assignments:
            track.center = detection.bounds.center
            track.last_seen_at = observed_at
            track.observed_frames += 1
            track.latest_detection = detection
            track.latest_frame_index = frame_index
            care_signals = detection.geometry.signal_count
            if care_signals >= 2:
                if track.care_started_at is None:
                    track.care_started_at = observed_at
                    track.care_frames = 0
                    track.care_confidence_sum = 0.0
                track.care_frames += 1
                track.care_confidence_sum += detection.confidence
            else:
                track.care_started_at = None
                track.care_frames = 0
                track.care_confidence_sum = 0.0

            if not detection.looking:
                track.gaze_started_at = None
                track.gaze_frames = 0
                track.gaze_confidence_sum = 0.0
                track.hand_samples.clear()
                outcome = VisualAttentionOutcome.NOT_LOOKING
            else:
                if track.gaze_started_at is None:
                    track.gaze_started_at = observed_at
                    track.gaze_frames = 0
                    track.gaze_confidence_sum = 0.0
                track.gaze_frames += 1
                track.gaze_confidence_sum += detection.confidence
                while (
                    track.hand_samples
                    and observed_at - track.hand_samples[0][0]
                    > self._policy.gesture_window_s
                ):
                    track.hand_samples.popleft()
                if detection.hand_center is not None:
                    track.hand_samples.append(
                        (observed_at, detection.hand_center.x)
                    )
                outcome = self._progress(track, detection)

            if self._care_qualified(track):
                outcome = VisualAttentionOutcome.CARE_QUALIFIED
            elif care_signals >= 2:
                outcome = VisualAttentionOutcome.CARE_PROGRESS

            facts = self._facts(track, detection, len(detections))
            notices.append(
                VisualAttentionNotice(
                    frame_index=frame_index,
                    outcome=outcome,
                    track_reference=track.reference,
                    facts=facts,
                )
            )
            if outcome in (
                VisualAttentionOutcome.QUALIFIED,
                VisualAttentionOutcome.CARE_QUALIFIED,
            ) and selected_cue is None:
                care = outcome is VisualAttentionOutcome.CARE_QUALIFIED
                if care:
                    track.care_emitted = True
                else:
                    track.invitation_emitted = True
                selected_cue = VisualCue(
                    description=(
                        "anonymous person sustained observable "
                        + detection.geometry.describe()
                        if care
                        else "anonymous person sustained gaze toward Misty and waved"
                    ),
                    track_reference=track.reference,
                    confidence=round(
                        (
                            track.care_confidence_sum / track.care_frames
                            if care
                            else track.gaze_confidence_sum / track.gaze_frames
                        ),
                        3,
                    ),
                    facts=(
                        {
                            **detection.geometry.as_facts(),
                            "signal_duration_s": facts["care_duration_s"],
                            "observed_frames": track.care_frames,
                            "selected_frame_index": frame_index,
                            "person_count": len(detections),
                        }
                        if care
                        else {
                        "looking": True,
                        "wave_observed": True,
                        "gaze_duration_s": facts["gaze_duration_s"],
                        "wave_span": facts["wave_span"],
                        "direction_changes": facts["direction_changes"],
                        "observed_frames": track.observed_frames,
                        "selected_frame_index": frame_index,
                        "person_count": len(detections),
                        }
                    ),
                    uncertainty=(
                        (
                            "observable facial geometry does not establish "
                            "an emotion or a wish for help"
                            if care
                            else "local visual gate is verified only with "
                            "synthetic temporal fixtures"
                        ),
                        "anonymous tracking is not person identification",
                    ),
                    selected_image=_selected_crop(
                        image,
                        detection,
                        max_side_px=self._policy.evidence_max_side_px,
                    ),
                    deduplication_key=(
                        f"visual:{track.reference}:care"
                        if care
                        else f"visual:{track.reference}:invitation"
                    ),
                    cue_kind=(
                        CueKind.CARE_CUE if care else CueKind.SOCIAL_INVITATION
                    ),
                    fresh_for_s=self._policy.cue_freshness_s,
                )
        return tuple(notices), selected_cue

    def for_track(self, track_reference: object) -> "_TrackPerception":
        """Bind active perception to one Episode's Trigger Evidence track."""
        reference = (
            AnonymousTrackReference(track_reference)
            if isinstance(track_reference, str)
            else None
        )
        return _TrackPerception(self, reference)

    def _observe_track(
        self,
        *,
        reference: Optional[AnonymousTrackReference],
        now_s: float,
        kind: ActivePerceptionKind,
        cost: ActivePerceptionCost,
    ) -> ActivePerceptionResult:
        """Build one current observation from state this gate owns."""
        track = next(
            (item for item in self._tracks if item.reference == reference),
            None,
        )
        detection = track.latest_detection if track is not None else None
        age_s = 0.0 if track is None else now_s - track.last_seen_at
        if age_s < -1e-9:
            raise ValueError("active visual observation cannot be in the future")
        if (
            detection is None
            or track is None
            or track.latest_frame_index != self._latest_frame_index
        ):
            return ActivePerceptionResult(
                kind=kind,
                cost=cost,
                ending=ActivePerceptionEnding.UNAVAILABLE,
                age_s=max(0.0, age_s),
                fresh_for_s=self._policy.cue_freshness_s,
                uncertainty=(
                    "the Episode's anonymous visual track is not in the latest frame",
                ),
            )

        common = {
            "looking": detection.looking,
            **detection.geometry.as_facts(),
        }
        if kind is ActivePerceptionKind.TARGET_OBSERVATION:
            facts = {
                "track_reference": str(track.reference),
                "visible": True,
                "confidence": round(detection.confidence, 3),
                **common,
            }
            uncertainty = (
                "local geometry is not an emotion diagnosis",
                "anonymous tracking is not person identification",
            )
        else:
            facts = {
                "target_track_reference": str(track.reference),
                "target_visible": True,
                "person_count": self._latest_person_count,
                "selected_frame_index": track.latest_frame_index,
                **common,
            }
            uncertainty = (
                "scene inspection is bounded to the latest selected frame",
                "visible geometry cannot establish a person's feelings",
            )
        return ActivePerceptionResult(
            kind=kind,
            cost=cost,
            ending=ActivePerceptionEnding.OBSERVED,
            age_s=max(0.0, age_s),
            fresh_for_s=self._policy.cue_freshness_s,
            facts=facts,
            uncertainty=uncertainty,
        )

    def _care_qualified(self, track: _Track) -> bool:
        if track.care_started_at is None or track.care_frames == 0:
            return False
        return (
            not track.care_emitted
            and track.care_frames >= self._policy.minimum_care_frames
            and track.last_seen_at - track.care_started_at
            >= self._policy.minimum_care_s
            and track.care_confidence_sum / track.care_frames
            >= self._policy.minimum_confidence
        )

    def _assign(
        self,
        detections: Sequence[LocalVisualDetection],
        observed_at: float,
    ) -> Tuple[Tuple[LocalVisualDetection, _Track], ...]:
        unmatched_detections = set(range(len(detections)))
        assigned: dict[int, _Track] = {}
        for detection_index, track_index in _nearest_pairs(
            tuple(detection.bounds.center for detection in detections),
            tuple(track.center for track in self._tracks),
            maximum_distance=self._policy.track_max_jump,
        ):
            assigned[detection_index] = self._tracks[track_index]
            unmatched_detections.remove(detection_index)

        for detection_index in sorted(unmatched_detections):
            if len(self._tracks) >= self._policy.max_tracks:
                continue
            detection = detections[detection_index]
            track = _Track(
                reference=AnonymousTrackReference(
                    f"anon-{self._next_track}"
                ),
                center=detection.bounds.center,
                last_seen_at=observed_at,
            )
            self._next_track += 1
            self._tracks.append(track)
            assigned[detection_index] = track
        return tuple(
            (detections[index], assigned[index])
            for index in sorted(assigned)
        )

    def _progress(
        self, track: _Track, detection: LocalVisualDetection
    ) -> VisualAttentionOutcome:
        assert track.gaze_started_at is not None
        hand_x = tuple(value for _, value in track.hand_samples)
        gaze_duration = track.last_seen_at - track.gaze_started_at
        span = _span(hand_x)
        changes = _direction_changes(hand_x)
        average_confidence = (
            track.gaze_confidence_sum / track.gaze_frames
        )
        qualified = (
            not track.invitation_emitted
            and detection.hand_center is not None
            and average_confidence >= self._policy.minimum_confidence
            and gaze_duration >= self._policy.minimum_gaze_s
            and span >= self._policy.minimum_wave_span
            and changes >= self._policy.minimum_direction_changes
        )
        if qualified:
            return VisualAttentionOutcome.QUALIFIED
        if len(hand_x) >= 2 and span > 0:
            return VisualAttentionOutcome.WAVE_PROGRESS
        return VisualAttentionOutcome.TRACKING

    @staticmethod
    def _facts(
        track: _Track,
        detection: LocalVisualDetection,
        person_count: int,
    ) -> dict:
        gaze_duration = (
            0.0
            if track.gaze_started_at is None
            else track.last_seen_at - track.gaze_started_at
        )
        hand_x = tuple(value for _, value in track.hand_samples)
        return {
            "person_count": person_count,
            "looking": detection.looking,
            "hand_visible": detection.hand_center is not None,
            "confidence": round(detection.confidence, 3),
            "gaze_duration_s": round(gaze_duration, 3),
            "wave_span": round(_span(hand_x), 3),
            "direction_changes": _direction_changes(hand_x),
            **detection.geometry.as_facts(),
            "care_duration_s": round(
                0.0
                if track.care_started_at is None
                else track.last_seen_at - track.care_started_at,
                3,
            ),
        }


class _TrackPerception:
    """Active-perception view fixed to one Episode's anonymous track."""

    def __init__(
        self,
        gate: LocalVisualGate,
        reference: Optional[AnonymousTrackReference],
    ) -> None:
        self._gate = gate
        self._reference = reference

    def for_track(self, track_reference: object) -> "_TrackPerception":
        return self._gate.for_track(track_reference)

    def observe_target(self, *, now_s: float) -> ActivePerceptionResult:
        return self._observe(
            now_s=now_s,
            kind=ActivePerceptionKind.TARGET_OBSERVATION,
            cost=ActivePerceptionCost.CHEAP,
        )

    def inspect_scene(self, *, now_s: float) -> ActivePerceptionResult:
        return self._observe(
            now_s=now_s,
            kind=ActivePerceptionKind.SCENE_INSPECTION,
            cost=ActivePerceptionCost.EXPENSIVE,
        )

    def _observe(
        self,
        *,
        now_s: float,
        kind: ActivePerceptionKind,
        cost: ActivePerceptionCost,
    ) -> ActivePerceptionResult:
        return self._gate._observe_track(
            reference=self._reference,
            now_s=now_s,
            kind=kind,
            cost=cost,
        )


class VisualInputAdapter:
    """Expose local visual gate outcomes through Runtime's InputSource seam."""

    def __init__(
        self,
        *,
        frames: VisualFrameSource,
        clock,
        gate: Optional[LocalVisualGate] = None,
        maximum_frames_per_drain: int = 8,
    ) -> None:
        if maximum_frames_per_drain <= 0:
            raise ValueError("visual drain bound must be positive")
        self._frames = frames
        self._clock = clock
        self._gate = gate or LocalVisualGate()
        self._maximum_frames_per_drain = maximum_frames_per_drain
        self._ready: Deque[_ObservedInput] = deque()
        self._started = False
        self._stopped = False

    def start(self) -> None:
        if self._started:
            raise RuntimeError("this visual input adapter has already started")
        self._started = True
        self._frames.start()

    def read(self) -> Optional[InputArrival]:
        self._require_running()
        while not self._stopped:
            if self._ready:
                return self._take_ready()
            frame = self._frames.read_frame(timeout=0.05)
            if frame is not None:
                self._process(frame)
                continue
            if self._frames.exhausted:
                return None
        return None

    def read_available(self) -> Tuple[InputArrival, ...]:
        self._require_running()
        for _ in range(self._maximum_frames_per_drain):
            frame = self._frames.read_frame(timeout=0.0)
            if frame is None:
                break
            self._process(frame)
        return tuple(self._take_ready() for _ in range(len(self._ready)))

    def stop(self) -> None:
        self._stopped = True
        self._frames.stop()

    @property
    def exhausted(self) -> bool:
        return self._frames.exhausted and not self._ready

    def _require_running(self) -> None:
        if not self._started or self._stopped:
            raise RuntimeError("visual input adapter is not running")

    def _process(self, frame: VisualFrameArrival) -> None:
        observed_at = self._clock.monotonic() - frame.age_s
        if observed_at < -1e-9:
            raise ValueError("visual frame predates this adapter")
        notices, cue = self._gate.observe(
            observed_at=observed_at,
            frame_index=frame.frame_index,
            image=frame.image,
            detections=frame.detections,
        )
        for notice in notices:
            self._ready.append(_ObservedInput(notice, observed_at))
        if cue is not None:
            self._ready.append(_ObservedInput(cue, observed_at))

    def _take_ready(self) -> InputArrival:
        observed = self._ready.popleft()
        age_s = self._clock.monotonic() - observed.observed_at
        if age_s < -1e-9:
            raise ValueError("visual observation cannot be in the future")
        return InputArrival(age_s=max(0.0, age_s), input=observed.item)


class VisualFixtureSource:
    """Finite temporal frames driven by the same injected Runtime clock."""

    def __init__(self, clock, frames: Tuple[ScheduledVisualFrame, ...]) -> None:
        if any(
            later.at_s < earlier.at_s
            for earlier, later in zip(frames, frames[1:])
        ):
            raise ValueError("visual fixture frames must be ordered by time")
        self._clock = clock
        self._frames = frames
        self._index = 0
        self._started_at: Optional[float] = None
        self._stopped = False

    def start(self) -> None:
        if self._started_at is not None:
            raise RuntimeError("this visual fixture source has already started")
        self._started_at = self._clock.monotonic()

    def read_frame(self, timeout: float) -> Optional[VisualFrameArrival]:
        if self._started_at is None or self._stopped:
            raise RuntimeError("visual fixture source is not running")
        if timeout < 0:
            raise ValueError("visual read timeout cannot be negative")
        next_due = self._next_due()
        if next_due is None:
            return None
        scheduled, due_at = next_due
        wait_s = max(0.0, due_at - self._clock.monotonic())
        if wait_s > timeout:
            if timeout:
                self._clock.sleep(timeout)
            return None
        if wait_s:
            self._clock.sleep(wait_s)
        self._index += 1
        return VisualFrameArrival(
            age_s=max(0.0, self._clock.monotonic() - due_at),
            frame_index=self._index - 1,
            image=scheduled.image,
            detections=scheduled.detections,
        )

    @property
    def exhausted(self) -> bool:
        return self._started_at is not None and self._index >= len(self._frames)

    def stop(self) -> None:
        self._stopped = True

    def _next_due(self) -> Optional[Tuple[ScheduledVisualFrame, float]]:
        if self._index >= len(self._frames):
            return None
        assert self._started_at is not None
        scheduled = self._frames[self._index]
        return scheduled, self._started_at + scheduled.at_s


class MediaPipeVisualDetector:
    """Extract multi-face gaze and hand signals locally from one BGR frame.

    Face/hand association is nearest-centre geometry, not identity. It is a
    replaceable signal extractor for local use and remains real-camera-
    unverified in this no-hardware project.
    """

    def __init__(self, *, max_people: int = 4) -> None:
        import mediapipe as mp

        self._face_detection = mp.solutions.face_detection.FaceDetection(
            model_selection=0,
            min_detection_confidence=0.5,
        )
        self._face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=max_people,
            refine_landmarks=False,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=max_people,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

    def detect(self, image: np.ndarray) -> Tuple[LocalVisualDetection, ...]:
        import cv2

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        faces = self._face_detection.process(rgb).detections or ()
        meshes = self._face_mesh.process(rgb).multi_face_landmarks or ()
        hands = self._hands.process(rgb).multi_hand_landmarks or ()
        mesh_signals = [_mesh_signal(mesh) for mesh in meshes]
        hand_points = [
            NormalizedPoint(hand.landmark[0].x, hand.landmark[0].y)
            for hand in hands
        ]
        face_signals = []
        for face in faces:
            relative = face.location_data.relative_bounding_box
            bounds = _clamped_box(
                relative.xmin,
                relative.ymin,
                relative.width,
                relative.height,
            )
            face_signals.append((bounds, float(face.score[0])))
        centers = tuple(bounds.center for bounds, _ in face_signals)
        meshes_by_face = {
            face_index: mesh_signals[mesh_index]
            for face_index, mesh_index in _nearest_pairs(
                centers,
                tuple(item.center for item in mesh_signals),
                maximum_distance=0.5,
            )
        }
        hands_by_face = {
            face_index: hand_points[hand_index]
            for face_index, hand_index in _nearest_pairs(
                centers,
                tuple(hand_points),
                maximum_distance=0.75,
            )
        }
        detections = []
        for face_index, (bounds, confidence) in enumerate(face_signals):
            mesh = meshes_by_face.get(face_index)
            detections.append(
                LocalVisualDetection(
                    bounds=bounds,
                    confidence=confidence,
                    looking=(mesh.looking if mesh is not None else False),
                    hand_center=hands_by_face.get(face_index),
                    geometry=(
                        mesh.geometry
                        if mesh is not None
                        else NO_OBSERVABLE_GEOMETRY
                    ),
                )
            )
        return tuple(detections)

    def close(self) -> None:
        self._hands.close()
        self._face_mesh.close()
        self._face_detection.close()

    def __enter__(self) -> "MediaPipeVisualDetector":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def _mesh_signal(mesh) -> _MeshSignal:
    landmarks = mesh.landmark
    left = landmarks[234]
    right = landmarks[454]
    nose = landmarks[1]
    face_width = abs(right.x - left.x)
    center = NormalizedPoint(
        (left.x + right.x) / 2,
        (left.y + right.y) / 2,
    )
    if face_width == 0:
        return _MeshSignal(center, False, NO_OBSERVABLE_GEOMETRY)
    offset_ratio = abs(nose.x - center.x) / face_width
    left_eye_open = abs(landmarks[159].y - landmarks[145].y) / face_width
    right_eye_open = abs(landmarks[386].y - landmarks[374].y) / face_width
    mouth_open_ratio = abs(landmarks[13].y - landmarks[14].y) / face_width
    eyes_y = (
        landmarks[33].y + landmarks[263].y
    ) / 2
    nose_below_eyes = (nose.y - eyes_y) / face_width
    corners_y = (landmarks[61].y + landmarks[291].y) / 2
    mouth_center_y = (landmarks[13].y + landmarks[14].y) / 2
    # Geometry thresholds are deliberately local and conservative. They are
    # supported only by synthetic detector-boundary fixtures, not calibrated
    # emotion labels or claims about a real camera.
    return _MeshSignal(
        center=center,
        looking=offset_ratio < 0.25,
        geometry=ObservablePersonGeometry(
            eyes_narrowed=(left_eye_open + right_eye_open) / 2 < 0.035,
            mouth_open=mouth_open_ratio > 0.04,
            head_lowered=nose_below_eyes > 0.42,
            mouth_corners_raised=(
                (mouth_center_y - corners_y) / face_width > 0.015
            ),
        ),
    )


def _clamped_box(x: float, y: float, width: float, height: float) -> BoundingBox:
    left = min(1.0, max(0.0, x))
    top = min(1.0, max(0.0, y))
    right = min(1.0, max(left + 1e-6, x + width))
    bottom = min(1.0, max(top + 1e-6, y + height))
    return BoundingBox(left, top, right - left, bottom - top)


def _selected_crop(
    image: np.ndarray,
    detection: LocalVisualDetection,
    *,
    max_side_px: int,
) -> SelectedImageEvidence:
    import cv2

    height, width = image.shape[:2]
    box = detection.bounds
    xs = [box.x, box.x + box.width]
    ys = [box.y, box.y + box.height]
    if detection.hand_center is not None:
        xs.append(detection.hand_center.x)
        ys.append(detection.hand_center.y)
    pad = 0.05
    x1 = max(0, int((min(xs) - pad) * width))
    y1 = max(0, int((min(ys) - pad) * height))
    x2 = min(width, max(x1 + 1, int((max(xs) + pad) * width)))
    y2 = min(height, max(y1 + 1, int((max(ys) + pad) * height)))
    crop = image[y1:y2, x1:x2]
    scale = min(1.0, max_side_px / max(crop.shape[:2]))
    if scale < 1:
        crop = cv2.resize(
            crop,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA,
        )
    ok, encoded = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        raise ValueError("selected visual evidence could not be encoded")
    return SelectedImageEvidence(
        media_type="image/jpeg",
        data_base64=base64.b64encode(encoded.tobytes()).decode("ascii"),
    )


def _span(values: Sequence[float]) -> float:
    return 0.0 if len(values) < 2 else max(values) - min(values)


def _direction_changes(values: Sequence[float]) -> int:
    signs = []
    for left, right in zip(values, tuple(values)[1:]):
        delta = right - left
        if abs(delta) > 1e-6:
            signs.append(1 if delta > 0 else -1)
    return sum(left != right for left, right in zip(signs, signs[1:]))


def _distance(left: NormalizedPoint, right: NormalizedPoint) -> float:
    return math.hypot(left.x - right.x, left.y - right.y)


def _nearest_pairs(
    left: Sequence[NormalizedPoint],
    right: Sequence[NormalizedPoint],
    *,
    maximum_distance: float,
) -> Tuple[Tuple[int, int], ...]:
    """Greedily pair nearest points once, independent of input ordering."""
    unmatched_left = set(range(len(left)))
    unmatched_right = set(range(len(right)))
    pairs = sorted(
        (
            (_distance(left_point, right_point), left_index, right_index)
            for left_index, left_point in enumerate(left)
            for right_index, right_point in enumerate(right)
        ),
        key=lambda item: item[0],
    )
    selected = []
    for distance, left_index, right_index in pairs:
        if distance > maximum_distance:
            break
        if left_index not in unmatched_left or right_index not in unmatched_right:
            continue
        unmatched_left.remove(left_index)
        unmatched_right.remove(right_index)
        selected.append((left_index, right_index))
    return tuple(selected)


__all__ = [
    "BoundingBox",
    "LocalVisualDetection",
    "LocalVisualGate",
    "MediaPipeVisualDetector",
    "NormalizedPoint",
    "ObservablePersonGeometry",
    "ScheduledVisualFrame",
    "VisualFixtureSource",
    "VisualFrameArrival",
    "VisualFrameSource",
    "VisualGatePolicy",
    "VisualInputAdapter",
]
