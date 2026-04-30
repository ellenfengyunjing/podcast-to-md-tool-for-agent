"""Groq Whisper API transcriber - extremely fast cloud ASR.

Groq's Whisper API processes audio at ~100x real-time speed,
provides word-level timestamps, punctuation, and supports 50+ languages.
Uses the standard OpenAI Whisper API format.

Requires: GROQ_API_KEY environment variable or config setting.
Free tier: 28,800 audio-seconds/day (~8 hours).
"""
import asyncio
from pathlib import Path

import httpx
import structlog

from src.api.v1.schemas.response import TranscriptSegment

logger = structlog.get_logger()

GROQ_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


class GroqWhisperTranscriber:
    """Transcribe audio using Groq's Whisper API (whisper-large-v3-turbo).

    Benefits over local faster-whisper:
    - ~100x faster (30min audio → ~10 seconds)
    - No local GPU/CPU load
    - Native punctuation and timestamps
    - Free tier: 28,800 seconds/day
    """

    def __init__(self, api_key: str, model: str = "whisper-large-v3-turbo"):
        self.api_key = api_key
        self.model = model

    async def transcribe(self, audio_path: Path, language: str | None = None) -> list[TranscriptSegment]:
        """Transcribe audio file via Groq Whisper API with timestamps."""
        # Build multipart form data
        form_data = {
            "model": self.model,
            "response_format": "verbose_json",
            "timestamp_granularities[]": "segment",
        }
        if language:
            form_data["language"] = language

        return await self._call_api(audio_path, form_data)

    async def _call_api(self, audio_path: Path, form_data: dict) -> list[TranscriptSegment]:
        """Make the actual API call to Groq."""
        file_size_mb = audio_path.stat().st_size / (1024 * 1024)
        logger.info("groq_whisper_start", path=str(audio_path), size_mb=f"{file_size_mb:.1f}")

        async with httpx.AsyncClient(timeout=300.0) as client:
            with open(audio_path, "rb") as f:
                files = {"file": (audio_path.name, f, "audio/wav")}
                response = await client.post(
                    GROQ_API_URL,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    data=form_data,
                    files=files,
                )

        if response.status_code != 200:
            error_text = response.text
            logger.error("groq_whisper_error", status=response.status_code, error=error_text)
            raise RuntimeError(f"Groq Whisper API error ({response.status_code}): {error_text}")

        data = response.json()
        segments = []

        # Parse verbose_json response with segment timestamps
        for seg in data.get("segments", []):
            segments.append(TranscriptSegment(
                start=seg["start"],
                end=seg["end"],
                text=seg["text"].strip(),
                speaker="SPEAKER_00",
            ))

        # Fallback: if no segments but has text, create single segment
        if not segments and data.get("text"):
            segments.append(TranscriptSegment(
                start=0.0,
                end=data.get("duration", 0.0),
                text=data["text"].strip(),
                speaker="SPEAKER_00",
            ))

        logger.info(
            "groq_whisper_transcribed",
            path=str(audio_path),
            segments=len(segments),
            language=data.get("language", "unknown"),
            duration=data.get("duration", 0),
        )
        return segments
