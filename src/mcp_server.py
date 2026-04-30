"""MCP Server for Podcast Knowledge Agent.

Exposes podcast processing capabilities via Model Context Protocol (MCP),
allowing Claude Desktop, Claude Code, and other MCP-compatible AI tools
to directly call podcast knowledge extraction.

Usage:
    python -m src.mcp_server
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

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
from src.layers.memory.compressor import MemoryCompressor
from src.layers.output.assembler import OutputAssembler

server = Server("podcast-knowledge-agent")


def _get_resolver(platform: PlatformType):
    if platform == PlatformType.YOUTUBE:
        return YouTubeResolver()
    return GenericResolver()


async def _run_pipeline(url: str, transcript_only: bool = False, summary_only: bool = False) -> dict:
    """Run the full or partial pipeline and return results as dict."""
    config = get_config()
    config.ensure_data_dir()

    job_id = f"mcp-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    started_at = datetime.now(timezone.utc)

    # Stage 1: Resolve
    platform = detect_platform(url)
    resolver = _get_resolver(platform)
    resolved = await resolver.resolve(url)

    # Stage 2: Download audio
    extractor = AudioExtractor(data_dir=config.data_dir)
    extracted = await extractor.extract(resolved, job_id)

    # Stage 3: Chunk
    chunker = AudioChunker(max_chunk_duration=600, overlap_seconds=30)
    chunks = await chunker.chunk(extracted.file_path, extracted.duration_seconds)

    # Stage 4: Transcribe
    segments = await transcribe_chunks(chunks, config, language=None)

    # If only transcript requested, return early
    if transcript_only:
        paragraphs = []
        block_duration = 60
        current_block_start = 0
        current_texts = []

        for seg in segments:
            block_start = int(seg.start // block_duration) * block_duration
            if block_start != current_block_start and current_texts:
                m1, s1 = divmod(int(current_block_start), 60)
                m2, s2 = divmod(int(current_block_start + block_duration), 60)
                paragraphs.append({
                    "time": f"{m1:02d}:{s1:02d} - {m2:02d}:{s2:02d}",
                    "text": "".join(current_texts),
                })
                current_texts = []
                current_block_start = block_start
            current_texts.append(seg.text)

        if current_texts:
            m1, s1 = divmod(int(current_block_start), 60)
            m2, s2 = divmod(int(current_block_start + block_duration), 60)
            paragraphs.append({
                "time": f"{m1:02d}:{s1:02d} - {m2:02d}:{s2:02d}",
                "text": "".join(current_texts),
            })

        return {
            "title": resolved.title,
            "duration_seconds": extracted.duration_seconds,
            "segments_count": len(segments),
            "paragraphs": paragraphs,
        }

    # Stage 5: Summarize
    llm = LLMClient(
        model=config.llm_model,
        api_key=config.openrouter_api_key,
        base_url=config.openrouter_base_url,
    )
    summarizer = Summarizer(llm)
    full_text = " ".join(s.text for s in segments)
    summary = await summarizer.summarize(full_text, title=resolved.title)

    if summary_only:
        return {
            "title": summary.title,
            "one_line_summary": summary.one_line_summary,
            "executive_summary": summary.executive_summary,
            "key_topics": [{"topic": t.topic, "summary": t.summary} for t in summary.key_topics],
            "key_insights": summary.key_insights,
            "entities": [{"name": e.name, "type": e.type} for e in summary.entities],
        }

    # Stage 6: Memory compression
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

    # Stage 7: Assemble
    completed_at = datetime.now(timezone.utc)
    processing_info = ProcessingInfo(
        job_id=job_id,
        started_at=started_at.isoformat(),
        completed_at=completed_at.isoformat(),
        duration_seconds=(completed_at - started_at).total_seconds(),
        asr_model=f"faster-whisper/{config.whisper_model_size}",
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

    # Save to file
    output_path = config.data_dir / job_id / "result.json"
    assembler.save_to_file(result, output_path)

    return json.loads(result.model_dump_json())

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="process_podcast",
            description=(
                "Process a podcast/audio URL and extract structured knowledge including "
                "full transcript, AI-generated summary, key topics, insights, entities, "
                "and compressed agent memory blocks. Supports YouTube, RSS feeds, "
                "Xiaoyuzhou FM, and any URL with audio content."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The podcast or audio URL to process",
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="get_transcript",
            description=(
                "Download and transcribe a podcast/audio URL. Returns the transcript "
                "grouped into 1-minute paragraphs. Faster than full processing since "
                "it skips LLM summarization and memory compression."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The podcast or audio URL to transcribe",
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="get_summary",
            description=(
                "Process a podcast/audio URL and return only the structured summary "
                "including title, one-line summary, executive summary, key topics, "
                "insights, and entities. Skips memory compression."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The podcast or audio URL to summarize",
                    },
                },
                "required": ["url"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    url = arguments.get("url", "")
    if not url:
        return [TextContent(type="text", text="Error: 'url' parameter is required.")]

    try:
        if name == "process_podcast":
            result = await _run_pipeline(url)
        elif name == "get_transcript":
            result = await _run_pipeline(url, transcript_only=True)
        elif name == "get_summary":
            result = await _run_pipeline(url, summary_only=True)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        return [TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2),
        )]
    except Exception as e:
        return [TextContent(type="text", text=f"Error processing podcast: {e}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        init_options = server.create_initialization_options()
        await server.run(read_stream, write_stream, init_options)


if __name__ == "__main__":
    asyncio.run(main())
