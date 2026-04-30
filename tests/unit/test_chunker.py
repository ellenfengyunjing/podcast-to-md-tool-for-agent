import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from src.layers.audio.chunker import AudioChunker


class TestAudioChunker:
    @pytest.fixture
    def chunker(self):
        return AudioChunker(max_chunk_duration=600, overlap_seconds=30)

    @pytest.mark.asyncio
    async def test_short_audio_no_chunking(self, chunker, tmp_path):
        """Audio shorter than max_chunk_duration should not be split."""
        audio_path = tmp_path / "short.wav"
        audio_path.touch()

        chunks = await chunker.chunk(audio_path, total_duration=300.0)

        assert len(chunks) == 1
        assert chunks[0].file_path == audio_path
        assert chunks[0].start_seconds == 0.0
        assert chunks[0].end_seconds == 300.0

    @pytest.mark.asyncio
    async def test_long_audio_chunking(self, chunker, tmp_path):
        """Audio longer than max_chunk_duration should be split with overlap."""
        audio_path = tmp_path / "long.wav"
        audio_path.touch()
        chunks_dir = tmp_path / "chunks"
        chunks_dir.mkdir()

        with patch("src.layers.audio.chunker.split_audio") as mock_split:
            # Mock split_audio to return a fake path
            async def fake_split(input_path, output_dir, start_seconds, duration_seconds, chunk_index):
                p = output_dir / f"chunk_{chunk_index:04d}.wav"
                p.touch()
                return p

            mock_split.side_effect = fake_split

            chunks = await chunker.chunk(audio_path, total_duration=1500.0)

        # 1500s with 600s chunks and 30s overlap: ceil(1500 / 570) = 3 chunks
        assert len(chunks) >= 3
        assert chunks[0].start_seconds == 0.0
        assert chunks[1].start_seconds == 570.0  # 600 - 30 overlap

    @pytest.mark.asyncio
    async def test_exact_boundary(self, chunker, tmp_path):
        """Audio exactly at max_chunk_duration should not be split."""
        audio_path = tmp_path / "exact.wav"
        audio_path.touch()

        chunks = await chunker.chunk(audio_path, total_duration=600.0)

        assert len(chunks) == 1
