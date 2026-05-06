"""Transcription orchestration.

The project now uses Groq Whisper API exclusively: it is free (8h/day),
~100x real-time, and removes the biggest bottleneck in the original pipeline.
No local models, no GPU, no waiting for downloads.
"""
import asyncio

import structlog

from src.api.v1.schemas.response import TranscriptSegment
from src.config import AppConfig
from src.layers.audio.chunker import AudioChunk
from src.layers.transcription.groq_whisper import GroqWhisperTranscriber

logger = structlog.get_logger()

# Groq rate limit for free tier is generous; 3 in-flight requests is a safe default.
_MAX_CONCURRENT_REQUESTS = 3


def get_transcriber(config: AppConfig) -> GroqWhisperTranscriber:
    """Return a Groq Whisper transcriber. Requires ``PKA_GROQ_API_KEY``."""
    if not config.groq_api_key:
        raise ValueError(
            "PKA_GROQ_API_KEY is required. Get a free key at https://console.groq.com "
            "(free tier: ~8h of audio/day, no credit card needed)."
        )
    return GroqWhisperTranscriber(api_key=config.groq_api_key, model=config.groq_model)


async def transcribe_chunks(
    chunks: list[AudioChunk],
    config: AppConfig,
    language: str | None = None,
) -> list[TranscriptSegment]:
    """Transcribe all audio chunks in parallel and merge into one segment list."""
    transcriber = get_transcriber(config)

    if len(chunks) <= 1:
        segments = await transcriber.transcribe(chunks[0].file_path, language=language)
        all_segments = _adjust_timestamps(segments, chunks[0])
    else:
        all_segments = await _transcribe_parallel(transcriber, chunks, language)
        all_segments = _deduplicate_overlaps(all_segments, chunks)

    all_segments.sort(key=lambda s: s.start)
    logger.info("transcription_complete", total_segments=len(all_segments))
    return all_segments


async def _transcribe_parallel(
    transcriber: GroqWhisperTranscriber,
    chunks: list[AudioChunk],
    language: str | None,
) -> list[TranscriptSegment]:
    """Transcribe chunks concurrently while respecting Groq's rate limits."""
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_REQUESTS)

    async def _transcribe_one(chunk: AudioChunk) -> list[TranscriptSegment]:
        async with semaphore:
            segments = await transcriber.transcribe(chunk.file_path, language=language)
            return _adjust_timestamps(segments, chunk)

    results = await asyncio.gather(*[_transcribe_one(c) for c in chunks])
    all_segments: list[TranscriptSegment] = []
    for segs in results:
        all_segments.extend(segs)
    return all_segments


def _adjust_timestamps(
    chunk_segments: list[TranscriptSegment], chunk: AudioChunk
) -> list[TranscriptSegment]:
    """Offset segment timestamps by chunk start time."""
    adjusted = []
    for seg in chunk_segments:
        if seg.end == 0.0:
            adjusted.append(TranscriptSegment(
                start=chunk.start_seconds,
                end=chunk.end_seconds,
                text=seg.text,
                speaker=seg.speaker,
            ))
        else:
            adjusted.append(TranscriptSegment(
                start=seg.start + chunk.start_seconds,
                end=seg.end + chunk.start_seconds,
                text=seg.text,
                speaker=seg.speaker,
            ))
    return adjusted


def _deduplicate_overlaps(
    segments: list[TranscriptSegment],
    chunks: list[AudioChunk],
) -> list[TranscriptSegment]:
    """Remove duplicate segments produced by overlapping chunk regions."""
    overlap_zones = []
    for i in range(len(chunks) - 1):
        overlap_start = chunks[i + 1].start_seconds
        overlap_end = chunks[i].end_seconds
        if overlap_start < overlap_end:
            overlap_zones.append((overlap_start, overlap_end))

    if not overlap_zones:
        return segments

    deduplicated = []
    seen_keys = set()

    for seg in sorted(segments, key=lambda s: s.start):
        in_overlap = any(start <= seg.start <= end for start, end in overlap_zones)
        if in_overlap:
            text_key = seg.text[:30].strip()
            time_key = round(seg.start, -1)
            key = (text_key, time_key)
            if key in seen_keys:
                continue
            seen_keys.add(key)

        deduplicated.append(seg)

    return deduplicated
