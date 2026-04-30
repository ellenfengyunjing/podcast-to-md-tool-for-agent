from datetime import datetime, timezone
from pathlib import Path

import structlog

from src.api.v1.schemas.response import ProcessingInfo, TranscriptSegment
from src.config import AppConfig
from src.layers.audio.chunker import AudioChunker
from src.layers.audio.extractor import AudioExtractor
from src.layers.memory.compressor import MemoryCompressor
from src.layers.output.assembler import OutputAssembler
from src.layers.resolver.factory import ResolvedPodcast, PlatformType, detect_platform
from src.layers.resolver.rss import RSSResolver
from src.layers.resolver.youtube import YouTubeResolver
from src.layers.semantic.llm_client import LLMClient
from src.layers.semantic.summarizer import Summarizer
from src.layers.transcription.factory import transcribe_chunks

logger = structlog.get_logger()


class PipelineOrchestrator:
    """Orchestrate the full podcast processing pipeline."""

    def __init__(self, config: AppConfig, job_id: str, progress_callback=None):
        self.config = config
        self.job_id = job_id
        self.progress_callback = progress_callback

    async def run(self, url: str, request_params: dict) -> Path:
        """Execute the full pipeline and return the path to the result JSON."""
        started_at = datetime.now(timezone.utc)

        # --- Stage 1: Resolve ---
        await self._report_progress("resolving", 5)
        resolved = await self._resolve(url, request_params)
        logger.info("pipeline_resolved", title=resolved.title, platform=resolved.platform)

        # --- Stage 2: Download & Extract Audio ---
        await self._report_progress("downloading", 15)
        extractor = AudioExtractor(data_dir=self.config.data_dir)
        audio = await extractor.extract(resolved, self.job_id)

        # --- Stage 3: Chunk Audio ---
        chunker = AudioChunker()
        chunks = await chunker.chunk(audio.file_path, audio.duration_seconds)

        # --- Stage 4: Transcribe ---
        await self._report_progress("transcribing", 30)
        language_hint = request_params.get("language_hint") or resolved.language_hint
        segments = await transcribe_chunks(chunks, self.config, language=language_hint)
        logger.info("pipeline_transcribed", segments=len(segments))

        # --- Stage 5: LLM Summarization ---
        await self._report_progress("summarizing", 60)
        llm_model = request_params.get("llm_model") or self.config.llm_model
        llm = LLMClient(
            model=llm_model,
            api_key=self.config.openrouter_api_key,
            base_url=self.config.openrouter_base_url,
        )
        summarizer = Summarizer(llm=llm)

        full_text = " ".join(seg.text for seg in segments)
        summary = await summarizer.summarize(full_text, title=resolved.title)
        logger.info("pipeline_summarized", language=summary.language)

        # --- Stage 6: Agent Memory Compression ---
        await self._report_progress("compressing", 80)
        token_budget = request_params.get("agent_memory_token_budget", 2000)
        compressor = MemoryCompressor(llm=llm, token_budget=token_budget)
        agent_memory = await compressor.compress(
            segments=segments,
            source_id=self.job_id,
            source_title=resolved.title,
            source_url=resolved.original_url,
            total_duration=audio.duration_seconds,
            language=summary.language,
            summary_text=summary.executive_summary,
        )
        logger.info("pipeline_compressed", blocks=len(agent_memory.memory_blocks))

        # --- Stage 7: Assemble Output ---
        await self._report_progress("assembling", 95)
        completed_at = datetime.now(timezone.utc)
        processing_info = ProcessingInfo(
            job_id=self.job_id,
            started_at=started_at.isoformat(),
            completed_at=completed_at.isoformat(),
            duration_seconds=(completed_at - started_at).total_seconds(),
            asr_model=self.config.asr_model if self.config.asr_backend == "api" else f"faster-whisper-{self.config.whisper_model_size}",
            llm_model=llm_model,
        )

        assembler = OutputAssembler()
        knowledge = assembler.assemble(
            resolved=resolved,
            segments=segments,
            summary=summary,
            agent_memory=agent_memory,
            processing_info=processing_info,
        )

        # Save result
        output_path = self.config.data_dir / self.job_id / "result.json"
        assembler.save_to_file(knowledge, output_path)

        await self._report_progress("completed", 100)
        logger.info("pipeline_complete", job_id=self.job_id, output=str(output_path))
        return output_path

    async def _resolve(self, url: str, params: dict) -> ResolvedPodcast:
        platform = detect_platform(url)
        if platform == PlatformType.YOUTUBE:
            resolver = YouTubeResolver()
            return await resolver.resolve(url)
        else:
            resolver = RSSResolver()
            episode_index = params.get("episode_index", 0) or 0
            return await resolver.resolve(url, episode_index=episode_index)

    async def _report_progress(self, stage: str, percent: float):
        if self.progress_callback:
            await self.progress_callback(stage, percent)
