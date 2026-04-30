from pathlib import Path

import structlog

from src.api.v1.schemas.response import TranscriptSegment

logger = structlog.get_logger()


class WhisperLocalTranscriber:
    """Transcribe audio using faster-whisper (CPU mode)."""

    def __init__(self, model_size: str = "base", device: str = "cpu", compute_type: str = "int8"):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _get_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError:
                raise RuntimeError(
                    "faster-whisper is not installed. "
                    "Install with: pip install faster-whisper"
                )
            self._model = WhisperModel(
                self.model_size,
                device=self.device,
                compute_type=self.compute_type,
            )
        return self._model

    async def transcribe(self, audio_path: Path, language: str | None = None) -> list[TranscriptSegment]:
        import asyncio

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, lambda: self._transcribe_sync(audio_path, language)
        )
        return result

    def _transcribe_sync(self, audio_path: Path, language: str | None) -> list[TranscriptSegment]:
        model = self._get_model()

        kwargs = {"beam_size": 5, "word_timestamps": False}
        if language:
            kwargs["language"] = language

        segments_gen, info = model.transcribe(str(audio_path), **kwargs)

        segments = []
        for seg in segments_gen:
            segments.append(TranscriptSegment(
                start=seg.start,
                end=seg.end,
                text=seg.text.strip(),
                speaker="SPEAKER_00",
            ))

        logger.info(
            "whisper_local_transcribed",
            path=str(audio_path),
            segments=len(segments),
            language=info.language,
            duration=info.duration,
        )
        return segments
