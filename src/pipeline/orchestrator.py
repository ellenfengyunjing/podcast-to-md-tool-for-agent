from datetime import datetime, timezone
from pathlib import Path

import structlog

from src.api.v1.schemas.response import ProcessingInfo
from src.config import AppConfig
from src.layers.audio.chunker import AudioChunker
from src.layers.audio.extractor import AudioExtractor
from src.layers.memory.compressor import MemoryCompressor
from src.layers.output.assembler import OutputAssembler
from src.layers.resolver.factory import ResolvedPodcast, resolve_podcast
from src.layers.semantic.llm_client import LLMClient
from src.layers.semantic.single_pass import SinglePassExtractor
from src.layers.semantic.summarizer import Summarizer
from src.layers.transcription.factory import transcribe_chunks

logger = structlog.get_logger()


class PipelineOrchestrator:
    """Orchestrate the full podcast processing pipeline.

    Requires ``PKA_LLM_API_KEY`` because it produces summary + memory blocks.
    If you only need the transcript, use the MCP ``transcribe_podcast`` tool
    instead (or call ``transcribe_chunks`` directly).
    """

    def __init__(self, config: AppConfig, job_id: str, progress_callback=None):
        self.config = config
        self.job_id = job_id
        self.progress_callback = progress_callback

    async def run(self, url: str, request_params: dict) -> Path:
        if not self.config.llm_enabled:
            raise RuntimeError(
                "PipelineOrchestrator requires PKA_LLM_API_KEY. For agent-driven "
                "workflows use the MCP ``transcribe_podcast`` tool and let the "
                "calling agent summarize the transcript itself."
            )

        started_at = datetime.now(timezone.utc)

        # --- Stage 1: Resolve ---
        await self._report_progress("resolving", 5)
        resolved = await resolve_podcast(url)
        logger.info("pipeline_resolved", title=resolved.title, platform=resolved.platform)

        # --- Stage 2: Download & Extract Audio ---
        await self._report_progress("downloading", 15)
        extractor = AudioExtractor(data_dir=self.config.data_dir)
        audio = await extractor.extract(resolved, self.job_id)

        # --- Stage 3: Chunk Audio ---
        chunker = AudioChunker()
        chunks = await chunker.chunk(audio.file_path, audio.duration_seconds)

        # --- Stage 4: Transcribe (Groq Whisper, in parallel) ---
        await self._report_progress("transcribing", 30)
        language_hint = request_params.get("language_hint") or resolved.language_hint
        segments = await transcribe_chunks(chunks, self.config, language=language_hint)
        logger.info("pipeline_transcribed", segments=len(segments))

        # --- Stage 5: LLM Summarization ---
        await self._report_progress("summarizing", 60)
        llm_model = request_params.get("llm_model") or self.config.llm_model
        llm = LLMClient(
            model=llm_model,
            api_key=self.config.llm_api_key,
            base_url=self.config.llm_base_url,
        )

        full_text = " ".join(seg.text for seg in segments)
        token_budget = request_params.get("agent_memory_token_budget", 2000)

        single_pass = SinglePassExtractor(llm, token_budget=token_budget)
        if single_pass.can_single_pass(full_text):
            summary, agent_memory = await single_pass.extract(
                full_text=full_text,
                title=resolved.title,
                duration=audio.duration_seconds,
                source_id=self.job_id,
                source_url=resolved.original_url,
            )
        else:
            summarizer = Summarizer(llm=llm)
            summary = await summarizer.summarize(full_text, title=resolved.title)

            await self._report_progress("compressing", 80)
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

        # --- Stage 7: Assemble Output ---
        await self._report_progress("assembling", 95)
        completed_at = datetime.now(timezone.utc)
        processing_info = ProcessingInfo(
            job_id=self.job_id,
            started_at=started_at.isoformat(),
            completed_at=completed_at.isoformat(),
            duration_seconds=(completed_at - started_at).total_seconds(),
            asr_model=f"groq/{self.config.groq_model}",
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

        output_path = self.config.data_dir / self.job_id / "result.json"
        assembler.save_to_file(knowledge, output_path)

        await self._report_progress("completed", 100)
        logger.info("pipeline_complete", job_id=self.job_id, output=str(output_path))
        return output_path

    async def _report_progress(self, stage: str, percent: float):
        if self.progress_callback:
            await self.progress_callback(stage, percent)
