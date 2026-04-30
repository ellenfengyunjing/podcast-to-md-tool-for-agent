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
    """Transcribe all chunks and merge into a single segment list with adjusted timestamps."""
    transcriber = get_transcriber(config)
    all_segments: list[TranscriptSegment] = []

    for chunk in chunks:
        chunk_segments = await transcriber.transcribe(chunk.file_path, language=language)

        # For OpenRouter ASR (no native timestamps), approximate timestamps
        # based on chunk position and duration
        for seg in chunk_segments:
            if seg.end == 0.0:
                # No timestamps from ASR - approximate using chunk boundaries
                adjusted = TranscriptSegment(
                    start=chunk.start_seconds,
                    end=chunk.end_seconds,
                    text=seg.text,
                    speaker=seg.speaker,
                )
            else:
                # Has timestamps (e.g., from local whisper) - offset by chunk start
                adjusted = TranscriptSegment(
                    start=seg.start + chunk.start_seconds,
                    end=seg.end + chunk.start_seconds,
                    text=seg.text,
                    speaker=seg.speaker,
                )
            all_segments.append(adjusted)

    # Deduplicate overlapping segments (for chunked audio with overlap)
    if len(chunks) > 1:
        all_segments = _deduplicate_overlaps(all_segments, chunks)

    all_segments.sort(key=lambda s: s.start)
    logger.info("transcription_complete", total_segments=len(all_segments))
    return all_segments


def _deduplicate_overlaps(
    segments: list[TranscriptSegment],
    chunks: list[AudioChunk],
) -> list[TranscriptSegment]:
    """Remove duplicate segments from overlapping chunk regions."""
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

    # For segments in overlap zones, keep only those from the chunk
    # where the segment falls in the middle (better context)
    deduplicated = []
    seen_texts = set()

    for seg in sorted(segments, key=lambda s: s.start):
        in_overlap = any(start <= seg.start <= end for start, end in overlap_zones)
        if in_overlap:
            key = (seg.text[:50], round(seg.start, 0))
            if key in seen_texts:
                continue
            seen_texts.add(key)

        deduplicated.append(seg)

    return deduplicated
