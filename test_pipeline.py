"""Quick end-to-end pipeline test — no Redis / Celery needed.

Run with:
    python test_pipeline.py "<podcast-url>"

What it does (all that's required is ``PKA_GROQ_API_KEY``):
  1. Resolves the URL (Apple Podcasts / Xiaoyuzhou / YouTube / RSS / generic)
  2. Downloads and converts the audio to 16kHz mono WAV
  3. Chunks into 10-minute slices and transcribes them in parallel via Groq
  4. Writes ``result.json`` (plain transcript + metadata) and
     ``transcript_readable.txt`` (1-minute paragraphs).

If ``PKA_LLM_API_KEY`` is also configured, the script additionally runs the
summary + memory compression pipeline and writes ``knowledge.json``.
"""
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
from src.layers.resolver.factory import detect_platform, resolve_podcast
from src.layers.audio.extractor import AudioExtractor
from src.layers.audio.chunker import AudioChunker
from src.layers.transcription.factory import transcribe_chunks
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

    print(f"[1/5] Resolving URL: {url}")
    platform = detect_platform(url)
    print(f"       Platform: {platform.value}")

    resolved = await resolve_podcast(url)
    print(f"       Title: {resolved.title}")
    print(f"       Duration: {resolved.duration_seconds}s")

    print(f"\n[2/5] Downloading & converting audio...")
    extractor = AudioExtractor(data_dir=config.data_dir)
    extracted = await extractor.extract(resolved, job_id)
    print(f"       Audio saved: {extracted.file_path}")
    print(
        f"       Duration: {extracted.duration_seconds:.1f}s, "
        f"Size: {extracted.file_size_bytes / 1e6:.1f}MB"
    )

    print(f"\n[3/5] Chunking audio...")
    chunker = AudioChunker(max_chunk_duration=600, overlap_seconds=30)
    chunks = await chunker.chunk(extracted.file_path, extracted.duration_seconds)
    print(f"       Chunks: {len(chunks)}")

    print(f"\n[4/5] Transcribing with Groq ({config.groq_model}) — chunks run in parallel...")
    segments = await transcribe_chunks(chunks, config, language=None)
    print(f"       Segments: {len(segments)}")
    full_text = " ".join(s.text for s in segments)
    print(f"       Word count: {_count_words(full_text)}")
    print(f"       Preview: {full_text[:100]}...")

    # Write a readable transcript (always — this is the core output)
    transcript_path = config.data_dir / job_id / "transcript_readable.txt"
    _save_readable_transcript(segments, resolved.title, transcript_path)

    # And a compact JSON transcript for agents to consume directly
    result_path = config.data_dir / job_id / "result.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    compact = {
        "source": {
            "url": resolved.original_url,
            "platform": resolved.platform.value,
            "title": resolved.title,
            "author": resolved.author,
            "duration_seconds": extracted.duration_seconds,
        },
        "transcript": {
            "full_text": full_text,
            "segments": [
                {"start": s.start, "end": s.end, "text": s.text, "speaker": s.speaker}
                for s in segments
            ],
        },
    }
    result_path.write_text(json.dumps(compact, ensure_ascii=False, indent=2), encoding="utf-8")

    if not config.llm_enabled:
        print(f"\n[5/5] Skipping summary: PKA_LLM_API_KEY not set.")
        print(f"       (The calling agent should summarize the transcript itself.)")
        print(f"\n{'='*60}")
        print(f"Done!")
        print(f"  Transcript JSON:      {result_path}")
        print(f"  Readable transcript:  {transcript_path}")
        print(f"{'='*60}")
        return

    # --- Optional: run the built-in LLM pipeline when a key is configured ---
    from src.layers.semantic.llm_client import LLMClient
    from src.layers.semantic.single_pass import SinglePassExtractor
    from src.layers.semantic.summarizer import Summarizer
    from src.layers.memory.compressor import MemoryCompressor

    print(f"\n[5/5] Running built-in LLM summary ({config.llm_model})...")
    llm = LLMClient(
        model=config.llm_model,
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
    )

    extractor = SinglePassExtractor(llm, token_budget=2000)
    if extractor.can_single_pass(full_text):
        print(f"       Mode: single-pass (one LLM call)")
        summary, memory = await extractor.extract(
            full_text=full_text,
            title=resolved.title,
            duration=extracted.duration_seconds,
            source_id=job_id,
            source_url=resolved.original_url,
        )
    else:
        print(f"       Mode: multi-step (transcript too long for single pass)")
        summarizer = Summarizer(llm)
        summary = await summarizer.summarize(full_text, title=resolved.title)
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

    completed_at = datetime.now(timezone.utc).isoformat()
    processing_info = ProcessingInfo(
        job_id=job_id,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=(
            datetime.fromisoformat(completed_at) - datetime.fromisoformat(started_at)
        ).total_seconds(),
        asr_model=f"groq/{config.groq_model}",
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
    knowledge_path = config.data_dir / job_id / "knowledge.json"
    assembler.save_to_file(result, knowledge_path)

    print(f"\n{'='*60}")
    print(f"Done!")
    print(f"  Transcript JSON:      {result_path}")
    print(f"  Readable transcript:  {transcript_path}")
    print(f"  Knowledge JSON:       {knowledge_path}")
    print(f"{'='*60}")
    print(f"\n--- Summary ---")
    print(f"Title: {summary.title}")
    print(f"One-line: {summary.one_line_summary}")
    print(f"Memory: {len(memory.memory_blocks)} blocks, {memory.total_tokens} tokens")


def _save_readable_transcript(segments, title: str, output_path: Path):
    """Save transcript grouped into 1-minute blocks with speaker labels."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    speakers = set(seg.speaker for seg in segments)
    multi_speaker = len(speakers) > 1

    lines = [f"# {title}", f"# Total segments: {len(segments)}"]
    if multi_speaker:
        lines.append(f"# Speakers: {', '.join(sorted(speakers))}")
    lines.append("")

    if not segments:
        output_path.write_text("No segments.", encoding="utf-8")
        return

    block_duration = 60
    current_block_start = 0
    current_block_texts: list[str] = []

    for seg in segments:
        block_index = int(seg.start // block_duration)
        block_start = block_index * block_duration

        if block_start != current_block_start and current_block_texts:
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
