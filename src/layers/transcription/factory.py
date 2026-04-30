import asyncio
from pathlib import Path

import structlog

from src.api.v1.schemas.response import TranscriptSegment
from src.config import AppConfig
from src.layers.audio.chunker import AudioChunk

logger = structlog.get_logger()


def get_transcriber(config: AppConfig):
    """Factory: return the appropriate transcriber based on config."""
    if config.asr_backend == "local":
        from src.layers.transcription.whisper_local import WhisperLocalTranscriber
        return WhisperLocalTranscriber(model_size=config.whisper_model_size)
    elif config.asr_backend == "groq":
        from src.layers.transcription.groq_whisper import GroqWhisperTranscriber
        if not config.groq_api_key:
            raise ValueError(
                "PKA_GROQ_API_KEY is required when asr_backend='groq'. "
                "Get a free key at https://console.groq.com"
            )
        return GroqWhisperTranscriber(api_key=config.groq_api_key)
    else:
        from src.layers.transcription.openrouter_asr import OpenRouterASRTranscriber
        return OpenRouterASRTranscriber(
            api_key=config.openrouter_api_key,
            base_url=config.openrouter_base_url,
            model=config.asr_model,
        )


async def transcribe_chunks(
    chunks: list[AudioChunk],
    config: AppConfig,
    language: str | None = None,
) -> list[TranscriptSegment]:
    """Transcribe all chunks and merge into a single segment list with adjusted timestamps.

    For API-based backends (groq, api), chunks are processed in parallel for speed.
    For local backend, chunks are processed sequentially (CPU-bound).
    """
    transcriber = get_transcriber(config)
    use_parallel = config.asr_backend in ("groq", "api")

    if use_parallel and len(chunks) > 1:
        all_segments = await _transcribe_parallel(transcriber, chunks, language)
    else:
        all_segments = await _transcribe_sequential(transcriber, chunks, language)

    # Deduplicate overlapping segments (for chunked audio with overlap)
    if len(chunks) > 1:
        all_segments = _deduplicate_overlaps(all_segments, chunks)

    all_segments.sort(key=lambda s: s.start)
    logger.info("transcription_complete", total_segments=len(all_segments))
    return all_segments


async def _transcribe_sequential(
    transcriber, chunks: list[AudioChunk], language: str | None
) -> list[TranscriptSegment]:
    """Transcribe chunks one by one (for CPU-bound local whisper)."""
    all_segments: list[TranscriptSegment] = []

    for chunk in chunks:
        chunk_segments = await transcriber.transcribe(chunk.file_path, language=language)
        all_segments.extend(_adjust_timestamps(chunk_segments, chunk))

    return all_segments


async def _transcribe_parallel(
    transcriber, chunks: list[AudioChunk], language: str | None
) -> list[TranscriptSegment]:
    """Transcribe chunks in parallel (for API-based backends)."""
    # Limit concurrency to avoid rate limits
    semaphore = asyncio.Semaphore(3)

    async def _transcribe_one(chunk: AudioChunk) -> list[TranscriptSegment]:
        async with semaphore:
            chunk_segments = await transcriber.transcribe(chunk.file_path, language=language)
            return _adjust_timestamps(chunk_segments, chunk)

    results = await asyncio.gather(*[_transcribe_one(c) for c in chunks])

    all_segments: list[TranscriptSegment] = []
    for segs in results:
        all_segments.extend(segs)
    return all_segments


def _adjust_timestamps(
    chunk_segments: list[TranscriptSegment], chunk: AudioChunk
) -> list[TranscriptSegment]:
    """Adjust segment timestamps based on chunk offset."""
    adjusted = []
    for seg in chunk_segments:
        if seg.end == 0.0:
            # No timestamps from ASR - approximate using chunk boundaries
            adjusted.append(TranscriptSegment(
                start=chunk.start_seconds,
                end=chunk.end_seconds,
                text=seg.text,
                speaker=seg.speaker,
            ))
        else:
            # Has timestamps (e.g., from local whisper or groq) - offset by chunk start
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
    """Remove duplicate segments from overlapping chunk regions.

    Uses timestamp proximity + text similarity to detect duplicates.
    """
    if len(chunks) <= 1:
        return segments

    # Build overlap zones
    overlap_zones = []
    for i in range(len(chunks) - 1):
        overlap_start = chunks[i + 1].start_seconds
        overlap_end = chunks[i].end_seconds
        if overlap_start < overlap_end:
            overlap_zones.append((overlap_start, overlap_end))

    if not overlap_zones:
        return segments

    # For segments in overlap zones, keep only first occurrence
    # Use rounded start time + text prefix as dedup key
    deduplicated = []
    seen_keys = set()

    for seg in sorted(segments, key=lambda s: s.start):
        in_overlap = any(start <= seg.start <= end for start, end in overlap_zones)
        if in_overlap:
            # Use first 30 chars (handles both short and long segments)
            text_key = seg.text[:30].strip()
            time_key = round(seg.start, -1)  # Round to nearest 10s
            key = (text_key, time_key)
            if key in seen_keys:
                continue
            seen_keys.add(key)

        deduplicated.append(seg)

    return deduplicated
