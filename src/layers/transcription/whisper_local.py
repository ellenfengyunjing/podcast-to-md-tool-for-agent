from pathlib import Path

import structlog

from src.api.v1.schemas.response import TranscriptSegment

logger = structlog.get_logger()

# Initial prompt to guide punctuation for Chinese/multilingual content
PUNCTUATION_PROMPT_ZH = (
    "以下是一段播客对话的转录文本，请注意添加标点符号。"
    "你好，欢迎收听本期节目。今天我们来聊一聊人工智能的发展趋势，"
    "以及它对我们日常生活的影响。"
)
PUNCTUATION_PROMPT_EN = (
    "The following is a podcast transcript. "
    "Hello, welcome to today's episode. We'll be discussing the latest trends "
    "in artificial intelligence and their impact on our daily lives."
)


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

        # Use initial_prompt to guide punctuation generation
        initial_prompt = PUNCTUATION_PROMPT_ZH
        if language and language.startswith("en"):
            initial_prompt = PUNCTUATION_PROMPT_EN

        kwargs = {
            "beam_size": 5,
            "word_timestamps": False,
            "initial_prompt": initial_prompt,
            "vad_filter": True,
            "vad_parameters": {"min_silence_duration_ms": 500},
        }
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
