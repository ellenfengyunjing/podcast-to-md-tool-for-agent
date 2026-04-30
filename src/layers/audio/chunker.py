from dataclasses import dataclass
from pathlib import Path

import structlog

from src.utils.audio_utils import split_audio

logger = structlog.get_logger()


@dataclass
class AudioChunk:
    chunk_index: int
    file_path: Path
    start_seconds: float
    end_seconds: float
    duration_seconds: float


class AudioChunker:
    """Split long audio into overlapping chunks for ASR processing."""

    def __init__(self, max_chunk_duration: int = 600, overlap_seconds: int = 30):
        self.max_chunk_duration = max_chunk_duration
        self.overlap_seconds = overlap_seconds

    async def chunk(self, audio_path: Path, total_duration: float) -> list[AudioChunk]:
        """Split audio into chunks. Returns single-element list if audio is short enough."""
        if total_duration <= self.max_chunk_duration:
            return [AudioChunk(
                chunk_index=0,
                file_path=audio_path,
                start_seconds=0.0,
                end_seconds=total_duration,
                duration_seconds=total_duration,
            )]

        chunks = []
        output_dir = audio_path.parent / "chunks"
        output_dir.mkdir(exist_ok=True)

        start = 0.0
        index = 0

        while start < total_duration:
            end = min(start + self.max_chunk_duration, total_duration)
            duration = end - start

            chunk_path = await split_audio(
                input_path=audio_path,
                output_dir=output_dir,
                start_seconds=start,
                duration_seconds=duration,
                chunk_index=index,
            )

            chunks.append(AudioChunk(
                chunk_index=index,
                file_path=chunk_path,
                start_seconds=start,
                end_seconds=end,
                duration_seconds=duration,
            ))

            # Advance with overlap
            start += self.max_chunk_duration - self.overlap_seconds
            index += 1

        logger.info("audio_chunked", total_chunks=len(chunks), total_duration=total_duration)
        return chunks
