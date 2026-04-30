import asyncio
import base64
from pathlib import Path

import structlog
from openai import AsyncOpenAI

from src.api.v1.schemas.response import TranscriptSegment

logger = structlog.get_logger()

TRANSCRIPTION_PROMPT = """You are a professional transcription engine. Transcribe the audio accurately and completely.

Rules:
- Output ONLY the transcribed text, nothing else
- Preserve the original language (do not translate)
- Include punctuation
- If there are multiple speakers, start each speaker's turn on a new line with a dash (-)
- Do not add any commentary, headers, or formatting beyond the transcription"""


class OpenRouterASRTranscriber:
    """Transcribe audio using an audio-capable model via OpenRouter chat completions."""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.model = model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers={
                "HTTP-Referer": "https://github.com/podcast-knowledge-agent",
                "X-Title": "Podcast Knowledge Agent",
            },
        )

    async def transcribe(self, audio_path: Path, language: str | None = None) -> list[TranscriptSegment]:
        """Transcribe audio by sending it as base64 in a chat completion request."""
        # Read and encode audio
        audio_bytes = audio_path.read_bytes()
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        # Determine MIME type
        suffix = audio_path.suffix.lower()
        mime_map = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".ogg": "audio/ogg"}
        mime_type = mime_map.get(suffix, "audio/wav")

        # Build prompt
        prompt = TRANSCRIPTION_PROMPT
        if language:
            prompt += f"\n- The audio language is: {language}"

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": audio_b64,
                            "format": suffix.lstrip("."),
                        },
                    },
                ],
            }
        ]

        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=4096,
            temperature=0.0,
        )

        text = response.choices[0].message.content.strip()
        logger.info("openrouter_asr_complete", model=self.model, text_length=len(text))

        # Convert raw text into segments
        # Since chat completions don't provide timestamps, we create a single segment
        # Timestamps will be approximated based on chunk position in the pipeline
        if not text:
            return []

        return [TranscriptSegment(
            start=0.0,
            end=0.0,  # Will be filled by chunk offset in factory
            text=text,
            speaker="SPEAKER_00",
        )]
