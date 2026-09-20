"""Speech-to-text, behind a one-method interface.

The project used to run ``openai-whisper`` locally, which dragged in torch
(~800 MB installed) to transcribe a few seconds of speech per episode. This
module replaces it with a hosted transcription call and keeps the seam so the
choice stays reversible: anything with a ``transcribe`` method will do.

Two adapters exist today — :class:`OpenAITranscriber` for real runs and
``tests`` supply a recording stand-in — which is what makes the seam worth
having rather than a layer of indirection around a single implementation.

Note the sample rate is passed through rather than resampled. The old pipeline
resampled 44.1 kHz to 16 kHz with librosa before feeding Whisper; the hosted
API accepts the native rate, so that dependency (and the aliasing risk of
decimating without a low-pass filter) is gone.
"""

from __future__ import annotations

import io
import logging
import wave
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Protocol, Tuple, runtime_checkable

import numpy as np

from misty_agent.config import settings

log = logging.getLogger(__name__)


class TranscriptionEnding(str, Enum):
    """The bounded ways a hosted transcription attempt can finish."""

    TRANSCRIBED = "transcribed"
    EMPTY = "empty"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass(frozen=True)
class Transcription:
    """Text plus an observable ending for one bounded ASR attempt."""

    text: str
    ending: TranscriptionEnding
    error_type: Optional[str] = None

    def __post_init__(self) -> None:
        text = self.text.strip()
        object.__setattr__(self, "text", text)
        if self.ending is TranscriptionEnding.TRANSCRIBED and not text:
            raise ValueError("a transcribed ending requires non-empty text")
        if self.ending is not TranscriptionEnding.TRANSCRIBED and text:
            raise ValueError("a non-transcribed ending cannot carry text")


@runtime_checkable
class Transcriber(Protocol):
    """Turns a block of audio into text.

    Everything a caller must know:

    * ``pcm`` is mono float32 in [-1.0, 1.0]; ``sample_rate`` is its rate in Hz.
    * Returns the transcript, stripped. Returns ``""`` when nothing was
      recognised — silence and failure are not distinguished, because the
      caller's response to both is the same.
    * Never raises. A transport failure is logged and reported as ``""``.
    * May block for the length of a network round trip. Call it off the thread
      that reads audio.
    """

    def transcribe(self, pcm: np.ndarray, sample_rate: int) -> str: ...


def pcm_to_wav(pcm: np.ndarray, sample_rate: int) -> bytes:
    """Encode mono float32 samples as a 16-bit PCM WAV container.

    Samples outside [-1.0, 1.0] are clipped rather than allowed to wrap, which
    would turn a loud noise into a burst of white noise.
    """
    clipped = np.clip(np.asarray(pcm, dtype=np.float32), -1.0, 1.0)
    samples = (clipped * 32767.0).astype("<i2")

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate))
        wav.writeframes(samples.tobytes())
    return buffer.getvalue()


def wav_to_pcm(data: bytes) -> Tuple[np.ndarray, int]:
    """Decode a 16-bit PCM WAV into the mono float32 `transcribe` expects.

    The inverse of `pcm_to_wav`, and here rather than in the caller because
    this is where the encoding is already known. M8 #10 needs it: a browser
    hands over a file, and the transcriber takes samples.

    Only 16-bit PCM, which is what `wave` can read without help and what a
    browser records. Anything else is refused by name rather than decoded
    into noise. Extra channels are averaged rather than dropped, so a stereo
    recording of one person does not lose whichever side they sat on.
    """
    with wave.open(io.BytesIO(data), "rb") as source:
        if source.getsampwidth() != 2:
            raise ValueError(
                f"{source.getsampwidth() * 8}-bit audio: this reads 16-bit "
                f"PCM WAV, which is what a browser records"
            )
        channels = source.getnchannels()
        rate = source.getframerate()
        frames = source.readframes(source.getnframes())

    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


class OpenAITranscriber:
    """Hosted transcription. Satisfies :class:`Transcriber`.

    ``ignored_phrases`` drops transcripts containing any of a small set of
    strings. It exists because local Whisper reliably hallucinated "thank you"
    over near-silence, and the behaviour is preserved here rather than dropped
    silently. It is a workaround with a real cost — a user who says "thanks"
    is not heard — so it is configuration, visible and removable, rather than
    a literal buried in a driver.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = settings.asr_model,
        language: Optional[str] = settings.asr_language,
        ignored_phrases: tuple[str, ...] = settings.asr_ignored_phrases,
    ) -> None:
        from openai import OpenAI

        # One configured timeout is one total provider attempt. The SDK's
        # default retries would otherwise multiply that upper bound.
        self._client = OpenAI(api_key=api_key, max_retries=0)
        self._model = model
        self._language = language
        self._ignored_phrases = tuple(p.lower() for p in ignored_phrases)

    def transcribe(self, pcm: np.ndarray, sample_rate: int) -> str:
        return self.transcribe_bounded(
            pcm, sample_rate, timeout_s=None
        ).text

    def transcribe_bounded(
        self,
        pcm: np.ndarray,
        sample_rate: int,
        *,
        timeout_s: Optional[float],
    ) -> Transcription:
        """Transcribe once, with a provider timeout and typed ending."""
        try:
            audio = pcm_to_wav(pcm, sample_rate)
            client = (
                self._client.with_options(
                    timeout=timeout_s,
                    max_retries=0,
                )
                if timeout_s is not None
                else self._client
            )
            # Omitted rather than sent as null when there is no hint: the
            # provider detects the language itself, which is what a
            # bilingual deployment needs.
            hint = {"language": self._language} if self._language else {}
            response = client.audio.transcriptions.create(
                model=self._model,
                file=("utterance.wav", audio, "audio/wav"),
                **hint,
            )
            text = (response.text or "").strip()
        except Exception as exc:
            log.warning("transcription failed: %s", exc)
            ending = (
                TranscriptionEnding.TIMEOUT
                if _is_timeout(exc)
                else TranscriptionEnding.ERROR
            )
            return Transcription(
                text="", ending=ending, error_type=type(exc).__name__
            )

        lowered = text.lower()
        if any(phrase in lowered for phrase in self._ignored_phrases):
            log.debug("dropping transcript matching an ignored phrase: %r", text)
            text = ""
        return Transcription(
            text=text,
            ending=(
                TranscriptionEnding.TRANSCRIBED
                if text
                else TranscriptionEnding.EMPTY
            ),
        )


def _is_timeout(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    try:
        from openai import APITimeoutError
    except ImportError:  # pragma: no cover - OpenAI is a core dependency
        return False
    return isinstance(exc, APITimeoutError)
