from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import logging
from pathlib import Path
from typing import Callable

from app.config import settings
from app.models import SessionLocal, Transcript, TranscriptSegment, Video

logger = logging.getLogger(__name__)


class TranscriptionCancelled(RuntimeError):
    """Raised when a caller cancels speech-to-text processing."""


@dataclass(frozen=True, slots=True)
class SpeechSegment:
    start: float
    end: float
    text: str
    confidence: float | None = None
    words: list[dict] | None = None


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    language: str
    text: str
    segments: list[SpeechSegment]
    model_name: str


class Transcriber(ABC):
    @abstractmethod
    def transcribe(
        self,
        media_path: str | Path,
        progress_callback: Callable[[int], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> TranscriptionResult:
        raise NotImplementedError


class MockTranscriber(Transcriber):
    def transcribe(
        self,
        media_path: str | Path,
        progress_callback: Callable[[int], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> TranscriptionResult:
        if is_cancelled and is_cancelled():
            raise TranscriptionCancelled("Transcription was cancelled")
        if progress_callback:
            progress_callback(100)
        name = Path(media_path).stem.replace("_", " ").replace("-", " ")
        text = f"Mock transcript for {name}."
        return TranscriptionResult(
            language="ru",
            text=text,
            segments=[SpeechSegment(start=0.0, end=3.0, text=text, confidence=1.0)],
            model_name="mock",
        )


class FasterWhisperTranscriber(Transcriber):
    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or settings.whisper_model
        self._model = None

    def _get_model(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError(
                "faster-whisper is not installed; install requirements-ai.txt"
            ) from exc
        self._model = WhisperModel(
            self.model_name,
            device=settings.whisper_device,
            compute_type=settings.whisper_compute_type,
            download_root=str(settings.cache_folder / "whisper"),
        )
        return self._model

    def transcribe(
        self,
        media_path: str | Path,
        progress_callback: Callable[[int], None] | None = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> TranscriptionResult:
        raw_segments, info = self._get_model().transcribe(
            str(media_path), vad_filter=True, word_timestamps=True
        )
        segments: list[SpeechSegment] = []
        for segment in raw_segments:
            if is_cancelled and is_cancelled():
                raise TranscriptionCancelled("Transcription was cancelled")
            words = [
                {
                    "start": word.start,
                    "end": word.end,
                    "text": word.word,
                    "probability": word.probability,
                }
                for word in (segment.words or [])
            ]
            segments.append(
                SpeechSegment(
                    start=float(segment.start),
                    end=float(segment.end),
                    text=segment.text.strip(),
                    confidence=None,
                    words=words,
                )
            )
            if progress_callback and getattr(info, "duration", 0):
                progress_callback(min(99, round(float(segment.end) / info.duration * 100)))
        if progress_callback:
            progress_callback(100)
        language_probability = float(getattr(info, "language_probability", 1.0))
        return TranscriptionResult(
            language=str(info.language) if language_probability >= 0.5 else "unknown",
            text=" ".join(item.text for item in segments),
            segments=segments,
            model_name=self.model_name,
        )


def get_transcriber() -> Transcriber:
    provider = settings.transcription_provider.strip().lower()
    if provider == "mock":
        return MockTranscriber()
    if provider in {"faster-whisper", "faster_whisper"}:
        return FasterWhisperTranscriber()
    raise ValueError(f"Unsupported TRANSCRIPTION_PROVIDER: {settings.transcription_provider}")


def transcribe_video(
    video_id: int,
    transcriber: Transcriber | None = None,
    progress_callback: Callable[[int], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> int:
    with SessionLocal() as session:
        video = session.get(Video, video_id)
        if video is None:
            raise ValueError(f"Video {video_id} does not exist")
        transcript = Transcript(video_id=video_id, status="processing")
        session.add(transcript)
        session.commit()
        session.refresh(transcript)
        transcript_id = transcript.id
        media_path = video.original_path

    try:
        if not Path(media_path).is_file():
            raise FileNotFoundError(f"Video file does not exist: {media_path}")
        result = (transcriber or get_transcriber()).transcribe(
            media_path, progress_callback, is_cancelled
        )
        with SessionLocal() as session:
            transcript = session.get(Transcript, transcript_id)
            if transcript is None:
                raise RuntimeError("Transcript record disappeared")
            transcript.language = result.language
            transcript.model_name = result.model_name
            transcript.text = result.text
            transcript.status = "ready"
            transcript.segments = [
                TranscriptSegment(
                    start_time=item.start,
                    end_time=item.end,
                    text=item.text,
                    confidence=item.confidence,
                    words_json=item.words,
                )
                for item in result.segments
            ]
            session.commit()
        return transcript_id
    except Exception as exc:
        logger.exception("Transcription failed for video %s", video_id)
        with SessionLocal() as session:
            transcript = session.get(Transcript, transcript_id)
            if transcript:
                transcript.status = "error"
                transcript.error_message = str(exc)[:2000]
                session.commit()
        raise
