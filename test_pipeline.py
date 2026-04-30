"""Quick end-to-end pipeline test - no Redis/Celery needed."""
import asyncio
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Fix Windows terminal encoding for Chinese output
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

from src.config import get_config
from src.api.v1.schemas.response import ProcessingInfo
from src.layers.resolver.factory import detect_platform, PlatformType
from src.layers.resolver.youtube import YouTubeResolver
from src.layers.resolver.generic import GenericResolver
from src.layers.audio.extractor import AudioExtractor
from src.layers.audio.chunker import AudioChunker
from src.layers.transcription.factory import transcribe_chunks
from src.layers.semantic.llm_client import LLMClient
from src.layers.semantic.summarizer import Summarizer
from src.layers.semantic.single_pass import SinglePassExtractor
from src.layers.memory.compressor import MemoryCompressor
from src.layers.output.assembler import OutputAssembler, _count_words


def format_time(seconds: float) -> str:
    """Format seconds as MM:SS."""
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


async def main(url: str):
    config = get_config()
    config.ensure_data_dir()
    job_id = "test-run"
    started_at = datetime.now(timezone.utc).isoformat()

    print(f"[1/7] Resolving URL: {url}")
    platform = detect_platform(url)
    print(f"       Platform: {platform.value}")

    if platform == PlatformType.YOUTUBE:
        resolver = YouTubeResolver()
    else:
        resolver = GenericResolver()

    resolved = await resolver.resolve(url)
    print(f"       Title: {resolved.title}")
    print(f"       Duration: {resolved.duration_seconds}s")

    print(f"\n[2/7] Downloading & converting audio...")
    extractor = AudioExtractor(data_dir=config.data_dir)
    extracted = await extractor.extract(resolved, job_id)
    print(f"       Audio saved: {extracted.file_path}")
    print(f"       Duration: {extracted.duration_seconds:.1f}s, Size: {extracted.file_size_bytes / 1e6:.1f}MB")

    print(f"\n[3/7] Chunking audio...")
    chunker = AudioChunker(max_chunk_duration=600, overlap_seconds=30)
    chunks = await chunker.chunk(extracted.file_path, extracted.duration_seconds)
    print(f"       Chunks: {len(chunks)}")

    print(f"\n[4/7] Transcribing with {config.asr_backend} backend...")
    if config.asr_backend == "local":
        print(f"       Model: faster-whisper/{config.whisper_model_size}")
        print(f"       (First run will download the model)")
    elif config.asr_backend == "groq":
        print(f"       Model: Groq whisper-large-v3-turbo (cloud, fast)")
    else:
        print(f"       Model: {config.asr_model} (OpenRouter)")
    segments = await transcribe_chunks(chunks, config, language=None)
    print(f"       Segments: {len(segments)}")
    full_text = " ".join(s.text for s in segments)
    print(f"       Word count: {_count_words(full_text)}")
    print(f"       Preview: {full_text[:100]}...")

    print(f"\n[5/7] Generating summary with LLM ({config.llm_model})...")
    llm = LLMClient(
        model=config.llm_model,
        api_key=config.openrouter_api_key,
        base_url=config.openrouter_base_url,
    )

    # Try single-pass extraction (1 LLM call instead of 8)
    extractor = SinglePassExtractor(llm, token_budget=2000)
    if extractor.can_single_pass(full_text):
        print(f"       Mode: single-pass (transcript fits in one call)")
        summary, memory = await extractor.extract(
            full_text=full_text,
            title=resolved.title,
            duration=extracted.duration_seconds,
            source_id=job_id,
            source_url=resolved.original_url,
        )
        print(f"       Title: {summary.title}")
        print(f"       One-line: {summary.one_line_summary}")
        print(f"\n[6/7] Memory extracted in single pass...")
        print(f"       Memory blocks: {len(memory.memory_blocks)}")
        print(f"       Total tokens: {memory.total_tokens}")
        print(f"       Compression ratio: {memory.compression_ratio}")
    else:
        print(f"       Mode: multi-step (transcript too long for single pass)")
        summarizer = Summarizer(llm)
        summary = await summarizer.summarize(full_text, title=resolved.title)
        print(f"       Title: {summary.title}")
        print(f"       One-line: {summary.one_line_summary}")

        print(f"\n[6/7] Compressing to agent memory...")
        compressor = MemoryCompressor(llm, token_budget=2000)
        memory = await compressor.compress(
            segments=segments,
            source_id=job_id,
            source_title=resolved.title,
            source_url=resolved.original_url,
            total_duration=extracted.duration_seconds,
            language=summary.language,
            summary_text=summary.executive_summary,
        )
        print(f"       Memory blocks: {len(memory.memory_blocks)}")
        print(f"       Total tokens: {memory.total_tokens}")
        print(f"       Compression ratio: {memory.compression_ratio}")

    print(f"\n[7/7] Assembling final output...")
    completed_at = datetime.now(timezone.utc).isoformat()
    processing_info = ProcessingInfo(
        job_id=job_id,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=(datetime.fromisoformat(completed_at) - datetime.fromisoformat(started_at)).total_seconds(),
        asr_model=f"faster-whisper/{config.whisper_model_size}" if config.asr_backend == "local"
        else f"groq/whisper-large-v3-turbo" if config.asr_backend == "groq"
        else config.asr_model,
        llm_model=config.llm_model,
    )
    assembler = OutputAssembler()
    result = assembler.assemble(
        resolved=resolved,
        segments=segments,
        summary=summary,
        agent_memory=memory,
        processing_info=processing_info,
    )

    # Save result JSON
    output_path = config.data_dir / job_id / "result.json"
    assembler.save_to_file(result, output_path)

    # Save readable transcript grouped by 1-minute blocks
    transcript_path = config.data_dir / job_id / "transcript_readable.txt"
    _save_readable_transcript(segments, resolved.title, transcript_path)

    print(f"\n{'='*60}")
    print(f"Done!")
    print(f"  Result JSON:          {output_path}")
    print(f"  Readable transcript:  {transcript_path}")
    print(f"{'='*60}")

    print(f"\n--- Summary ---")
    print(f"Title: {summary.title}")
    print(f"One-line: {summary.one_line_summary}")
    print(f"Transcript: {result.transcript.word_count} words, {len(segments)} segments")
    print(f"Memory: {len(memory.memory_blocks)} blocks, {memory.total_tokens} tokens")
    print(f"Topics: {[t.topic for t in summary.key_topics[:5]]}")


def _save_readable_transcript(segments, title: str, output_path: Path):
    """Save transcript grouped into 1-minute blocks with speaker labels."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Detect multiple speakers
    speakers = set(seg.speaker for seg in segments)
    multi_speaker = len(speakers) > 1

    lines = []
    lines.append(f"# {title}")
    lines.append(f"# Total segments: {len(segments)}")
    if multi_speaker:
        lines.append(f"# Speakers: {', '.join(sorted(speakers))}")
    lines.append("")

    if not segments:
        output_path.write_text("No segments.", encoding="utf-8")
        return

    # Group segments into 1-minute blocks
    block_duration = 60  # seconds
    current_block_start = 0
    current_block_texts = []

    for seg in segments:
        block_index = int(seg.start // block_duration)
        block_start = block_index * block_duration

        if block_start != current_block_start and current_block_texts:
            # Write previous block
            block_end = current_block_start + block_duration
            time_label = f"[{format_time(current_block_start)} - {format_time(block_end)}]"
            lines.append(f"## {time_label}")
            lines.append("")
            lines.append("".join(current_block_texts))
            lines.append("")
            current_block_texts = []
            current_block_start = block_start

        if multi_speaker:
            current_block_texts.append(f"[{seg.speaker}] {seg.text}\n")
        else:
            current_block_texts.append(seg.text)

    # Write last block
    if current_block_texts:
        block_end = current_block_start + block_duration
        time_label = f"[{format_time(current_block_start)} - {format_time(block_end)}]"
        lines.append(f"## {time_label}")
        lines.append("")
        lines.append("".join(current_block_texts))
        lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://www.xiaoyuzhoufm.com/episode/69f231defbed7ba941222e98"
    asyncio.run(main(url))
