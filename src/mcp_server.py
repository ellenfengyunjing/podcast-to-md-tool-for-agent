"""MCP Server for Podcast Knowledge Agent.

Exposes podcast transcription via the Model Context Protocol (MCP) so
Claude Code, OpenClaw, Codex, Claude Desktop and other MCP-compatible
agents can call it directly.

Primary tool: ``transcribe_podcast``.
    - Input:  any podcast / audio URL (Apple Podcasts, Xiaoyuzhou,
              YouTube, generic RSS, direct MP3 link).
    - Output: structured transcript (full text + 1-minute paragraphs
              + timestamped segments + metadata). The calling agent
              then uses its *own* LLM to summarize / analyze / edit.

Secondary tool (optional, only registered when ``PKA_LLM_API_KEY`` is
set): ``extract_knowledge`` — the original full pipeline that also
returns LLM summary + compressed agent memory blocks. This is useful
for non-agent callers (scripts, cron jobs) that need a self-contained
pipeline.

Run with:  python -m src.mcp_server
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Ensure project root is importable when launched as ``python -m src.mcp_server``
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import get_config
from src.layers.resolver.factory import resolve_podcast
from src.layers.audio.extractor import AudioExtractor
from src.layers.audio.chunker import AudioChunker
from src.layers.transcription.factory import transcribe_chunks

server = Server("podcast-knowledge-agent")

# --- Tool schemas -----------------------------------------------------------

_URL_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": (
                "Podcast or audio URL. Supported: Apple Podcasts "
                "(podcasts.apple.com/.../id...), Xiaoyuzhou FM "
                "(xiaoyuzhoufm.com/episode/...), YouTube, any RSS feed, "
                "or a direct audio URL (MP3/M4A/WAV)."
            ),
        },
        "language": {
            "type": "string",
            "description": (
                "Optional language hint (ISO-639-1, e.g. 'zh', 'en'). "
                "Leave empty for auto-detection."
            ),
        },
    },
    "required": ["url"],
}


# --- Shared transcription path ---------------------------------------------

async def _transcribe(url: str, language: str | None) -> dict:
    """Resolve → download → chunk → transcribe. Return an agent-friendly dict."""
    config = get_config()
    config.ensure_data_dir()

    job_id = f"mcp-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    started_at = datetime.now(timezone.utc)

    # 1. Resolve the URL to audio metadata
    resolved = await resolve_podcast(url)

    # 2. Download + convert to 16kHz mono WAV
    extractor = AudioExtractor(data_dir=config.data_dir)
    extracted = await extractor.extract(resolved, job_id)

    # 3. Chunk into 10-minute slices with 30s overlap
    chunker = AudioChunker(max_chunk_duration=600, overlap_seconds=30)
    chunks = await chunker.chunk(extracted.file_path, extracted.duration_seconds)

    # 4. Transcribe (Groq Whisper, runs chunks in parallel)
    segments = await transcribe_chunks(
        chunks, config, language=language or resolved.language_hint
    )

    completed_at = datetime.now(timezone.utc)

    # Build 1-minute paragraph view — easier for agents to read & edit
    paragraphs = _group_by_minute(segments)
    full_text = " ".join(s.text for s in segments)

    result = {
        "job_id": job_id,
        "source": {
            "url": resolved.original_url,
            "platform": resolved.platform.value,
            "title": resolved.title,
            "author": resolved.author,
            "duration_seconds": extracted.duration_seconds,
            "published_at": resolved.published_at,
            "thumbnail_url": resolved.thumbnail_url,
            "description": resolved.description,
        },
        "transcript": {
            "full_text": full_text,
            "paragraphs": paragraphs,
            "segments": [
                {
                    "start": round(s.start, 2),
                    "end": round(s.end, 2),
                    "text": s.text,
                    "speaker": s.speaker,
                }
                for s in segments
            ],
            "segment_count": len(segments),
        },
        "processing": {
            "asr_model": f"groq/{config.groq_model}",
            "started_at": started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "elapsed_seconds": round((completed_at - started_at).total_seconds(), 2),
        },
    }

    # Persist alongside the WAV for later inspection / re-use
    output_path = config.data_dir / job_id / "transcript.json"
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    result["output_path"] = str(output_path)
    return result


def _group_by_minute(segments) -> list[dict]:
    """Group segments into 1-minute paragraphs for easier downstream use."""
    if not segments:
        return []

    block_duration = 60
    paragraphs: list[dict] = []
    current_block = 0
    current_texts: list[str] = []
    current_start = 0.0
    current_end = 0.0

    for seg in segments:
        block_idx = int(seg.start // block_duration)
        if block_idx != current_block and current_texts:
            paragraphs.append(_format_paragraph(current_block, current_texts))
            current_texts = []
            current_block = block_idx
            current_start = seg.start
        current_texts.append(seg.text)
        current_end = seg.end

    if current_texts:
        paragraphs.append(_format_paragraph(current_block, current_texts))
    return paragraphs


def _format_paragraph(block_idx: int, texts: list[str]) -> dict:
    block_start = block_idx * 60
    block_end = block_start + 60
    m1, s1 = divmod(block_start, 60)
    m2, s2 = divmod(block_end, 60)
    return {
        "time_range": f"{m1:02d}:{s1:02d} - {m2:02d}:{s2:02d}",
        "time_start": float(block_start),
        "time_end": float(block_end),
        "text": "".join(texts).strip(),
    }


# --- Optional: full knowledge extraction (requires PKA_LLM_API_KEY) --------

async def _extract_knowledge(url: str, language: str | None) -> dict:
    """Transcribe + run built-in LLM summary and memory compression."""
    config = get_config()
    if not config.llm_enabled:
        raise RuntimeError(
            "extract_knowledge requires PKA_LLM_API_KEY to be set. "
            "If you are calling from an AI agent, use transcribe_podcast "
            "instead and let the agent summarize the transcript itself."
        )

    # Lazy imports: only needed when the caller opted into the LLM flow.
    from src.layers.semantic.llm_client import LLMClient
    from src.layers.semantic.single_pass import SinglePassExtractor
    from src.layers.semantic.summarizer import Summarizer
    from src.layers.memory.compressor import MemoryCompressor
    from src.layers.output.assembler import OutputAssembler
    from src.api.v1.schemas.response import ProcessingInfo

    # Reuse the transcription result
    base = await _transcribe(url, language)
    segments_data = base["transcript"]["segments"]

    # Rebuild TranscriptSegment objects (assembler expects them)
    from src.api.v1.schemas.response import TranscriptSegment
    segments = [
        TranscriptSegment(
            start=s["start"], end=s["end"], text=s["text"], speaker=s["speaker"]
        )
        for s in segments_data
    ]

    llm = LLMClient(
        model=config.llm_model,
        api_key=config.llm_api_key,
        base_url=config.llm_base_url,
    )
    full_text = base["transcript"]["full_text"]
    title = base["source"]["title"]
    duration = base["source"]["duration_seconds"]
    source_url = base["source"]["url"]

    single_pass = SinglePassExtractor(llm, token_budget=2000)
    if single_pass.can_single_pass(full_text):
        summary, memory = await single_pass.extract(
            full_text=full_text,
            title=title,
            duration=duration,
            source_id=base["job_id"],
            source_url=source_url,
        )
    else:
        summarizer = Summarizer(llm)
        summary = await summarizer.summarize(full_text, title=title)
        compressor = MemoryCompressor(llm, token_budget=2000)
        memory = await compressor.compress(
            segments=segments,
            source_id=base["job_id"],
            source_title=title,
            source_url=source_url,
            total_duration=duration,
            language=summary.language,
            summary_text=summary.executive_summary,
        )

    # Build the full PodcastKnowledge envelope
    from src.layers.resolver.factory import ResolvedPodcast, PlatformType
    resolved = ResolvedPodcast(
        platform=PlatformType(base["source"]["platform"]),
        original_url=source_url,
        audio_url="",  # already downloaded
        title=title,
        description=base["source"].get("description"),
        duration_seconds=duration,
        published_at=base["source"].get("published_at"),
        author=base["source"].get("author"),
        thumbnail_url=base["source"].get("thumbnail_url"),
    )
    processing = ProcessingInfo(
        job_id=base["job_id"],
        started_at=base["processing"]["started_at"],
        completed_at=datetime.now(timezone.utc).isoformat(),
        duration_seconds=base["processing"]["elapsed_seconds"],
        asr_model=base["processing"]["asr_model"],
        llm_model=config.llm_model,
    )
    assembler = OutputAssembler()
    knowledge = assembler.assemble(
        resolved=resolved,
        segments=segments,
        summary=summary,
        agent_memory=memory,
        processing_info=processing,
    )
    output_path = config.data_dir / base["job_id"] / "knowledge.json"
    assembler.save_to_file(knowledge, output_path)

    result = json.loads(knowledge.model_dump_json())
    result["output_path"] = str(output_path)
    return result


# --- MCP wiring -------------------------------------------------------------

@server.list_tools()
async def list_tools() -> list[Tool]:
    tools: list[Tool] = [
        Tool(
            name="transcribe_podcast",
            description=(
                "Transcribe a podcast/audio URL to structured text. The preferred "
                "tool for AI agents: returns the full transcript, 1-minute "
                "paragraphs (easy to quote/edit), timestamped segments, and "
                "episode metadata. Your own model then handles summarization "
                "or any downstream analysis.\n\n"
                "Supported sources:\n"
                "- Apple Podcasts (podcasts.apple.com/.../id...)\n"
                "- Xiaoyuzhou FM (小宇宙, xiaoyuzhoufm.com/episode/...)\n"
                "- YouTube (youtube.com, youtu.be)\n"
                "- Generic RSS / Atom feeds\n"
                "- Direct audio URLs (MP3/M4A/WAV/OGG)"
            ),
            inputSchema=_URL_INPUT_SCHEMA,
        ),
    ]

    # Only expose the LLM-dependent tool when a key is configured.
    if get_config().llm_enabled:
        tools.append(
            Tool(
                name="extract_knowledge",
                description=(
                    "Full self-contained pipeline: transcribe + built-in LLM "
                    "summary + compressed agent-memory blocks. Only use this "
                    "when you are NOT calling from an agent (e.g. a cron job "
                    "or CLI script) — agents should prefer transcribe_podcast "
                    "and run their own summarization."
                ),
                inputSchema=_URL_INPUT_SCHEMA,
            )
        )

    return tools


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    url = (arguments or {}).get("url", "").strip()
    language = (arguments or {}).get("language") or None

    if not url:
        return [TextContent(type="text", text="Error: 'url' parameter is required.")]

    try:
        if name == "transcribe_podcast":
            result = await _transcribe(url, language)
        elif name == "extract_knowledge":
            result = await _extract_knowledge(url, language)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        return [TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2),
        )]
    except Exception as exc:  # noqa: BLE001 — surface full error to the agent
        return [TextContent(type="text", text=f"Error: {exc}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)


if __name__ == "__main__":
    asyncio.run(main())
