"""Local, host-side wake phrase detection over bounded PCM audio.

PocketSphinx runs entirely in this process.  Its result gates the hosted ASR
path: ambient speech is never sent to the external transcription provider.
The bundled English acoustic model is only verified here against synthetic
fixtures; it is not evidence of Misty microphone or real-room performance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol

import numpy as np


_DETECTOR_SAMPLE_RATE = 16_000
_FRAME_RATE = 100
_GRAMMAR = """\
#JSGF V1.0;
grammar misty_wake;
public <wake> = (hey | hi) misty;
"""


class WakePhrase(str, Enum):
    HEY_MISTY = "hey misty"
    HI_MISTY = "hi misty"


@dataclass(frozen=True)
class WakeMatch:
    """A matched phrase and where it ends in the caller's PCM."""

    phrase: WakePhrase
    confidence: float
    end_sample: int

    def __post_init__(self) -> None:
        if not isinstance(self.phrase, WakePhrase):
            raise TypeError("phrase must be a WakePhrase")
        if (
            not math.isfinite(self.confidence)
            or not 0.0 <= self.confidence <= 1.0
        ):
            raise ValueError("confidence must be finite and within [0, 1]")
        if self.end_sample < 0:
            raise ValueError("end_sample cannot be negative")


class WakeDetector(Protocol):
    def detect(
        self, pcm: np.ndarray, sample_rate: int
    ) -> Optional[WakeMatch]: ...


class PocketSphinxWakeDetector:
    """Speaker-independent local keyword spotting for the two wake phrases."""

    def __init__(self, *, minimum_confidence: float = 0.68) -> None:
        if not 0.0 < minimum_confidence <= 1.0:
            raise ValueError("minimum_confidence must be in (0, 1]")
        from pocketsphinx import Decoder

        self._minimum_confidence = minimum_confidence
        self._decoder = Decoder(
            samprate=_DETECTOR_SAMPLE_RATE,
            loglevel="ERROR",
        )
        self._decoder.add_jsgf_string("misty_wake", _GRAMMAR)
        self._decoder.activate_search("misty_wake")

    def detect(
        self, pcm: np.ndarray, sample_rate: int
    ) -> Optional[WakeMatch]:
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        source = np.asarray(pcm, dtype=np.float32).reshape(-1)
        if source.size == 0:
            return None
        detector_pcm = _resample(source, sample_rate, _DETECTOR_SAMPLE_RATE)
        raw = (
            np.clip(detector_pcm, -1.0, 1.0) * 32767.0
        ).astype("<i2").tobytes()

        self._decoder.start_utt()
        try:
            self._decoder.process_raw(raw, full_utt=True)
        finally:
            self._decoder.end_utt()
        hypothesis = self._decoder.hyp()
        if (
            hypothesis is None
            or hypothesis.score < self._minimum_confidence
        ):
            return None
        try:
            phrase = WakePhrase(hypothesis.hypstr.strip().lower())
        except ValueError:
            return None
        words = [
            word
            for word in self._decoder.seg()
            if word.word not in {"<s>", "</s>", "<sil>"}
        ]
        if not words:
            return None
        end_s = (words[-1].end_frame + 1) / _FRAME_RATE
        end_sample = min(source.size, round(end_s * sample_rate))
        return WakeMatch(
            phrase=phrase,
            confidence=float(hypothesis.score),
            end_sample=end_sample,
        )


def _resample(
    pcm: np.ndarray, source_rate: int, target_rate: int
) -> np.ndarray:
    if source_rate == target_rate:
        return pcm
    target_size = max(1, round(pcm.size * target_rate / source_rate))
    source_x = np.arange(pcm.size, dtype=np.float64)
    target_x = np.arange(target_size, dtype=np.float64) * (
        source_rate / target_rate
    )
    return np.interp(target_x, source_x, pcm).astype(np.float32)


__all__ = [
    "PocketSphinxWakeDetector",
    "WakeDetector",
    "WakeMatch",
    "WakePhrase",
]
