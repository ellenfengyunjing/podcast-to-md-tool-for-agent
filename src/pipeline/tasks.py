import asyncio
import traceback

import structlog

from src.celery_app import celery_app
from src.config import get_config
from src.storage.database import _get_session_factory
from src.storage.models import JobStatus
from src.storage.repository import JobRepository

logger = structlog.get_logger()


def _run_async(coro):
    """Run an async coroutine in a new event loop (for Celery workers)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def process_podcast_task(self, job_id: str, request_params: dict):
    """Celery task that runs the full podcast processing pipeline."""
    logger.info("task_started", job_id=job_id, task_id=self.request.id)

    try:
        _run_async(_process(job_id, request_params))
    except Exception as exc:
        logger.error("task_failed", job_id=job_id, error=str(exc))
        _run_async(_mark_failed(job_id, str(exc)))
        if _is_permanent_failure(exc):
            return
        raise self.retry(exc=exc)


async def _process(job_id: str, request_params: dict):
    """Async pipeline execution with progress updates."""
    from src.pipeline.orchestrator import PipelineOrchestrator

    config = get_config()
    config.ensure_data_dir()

    async def progress_callback(stage: str, percent: float):
        await _update_progress(job_id, stage, percent)

    orchestrator = PipelineOrchestrator(
        config=config,
        job_id=job_id,
        progress_callback=progress_callback,
    )

    result_path = await orchestrator.run(request_params["url"], request_params)

    # Mark completed
    async with _get_session_factory()() as session:
        repo = JobRepository(session)
        await repo.update_status(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            progress=100.0,
            stage="completed",
            result_path=str(result_path),
        )


async def _update_progress(job_id: str, stage: str, percent: float):
    """Update job progress in the database."""
    status_map = {
        "resolving": JobStatus.RESOLVING,
        "downloading": JobStatus.DOWNLOADING,
        "transcribing": JobStatus.TRANSCRIBING,
        "summarizing": JobStatus.SUMMARIZING,
        "compressing": JobStatus.COMPRESSING,
        "assembling": JobStatus.ASSEMBLING,
        "completed": JobStatus.COMPLETED,
    }
    status = status_map.get(stage, JobStatus.QUEUED)

    async with _get_session_factory()() as session:
        repo = JobRepository(session)
        await repo.update_status(
            job_id=job_id,
            status=status,
            progress=percent,
            stage=stage,
        )


async def _mark_failed(job_id: str, error_message: str):
    """Mark a job as failed."""
    async with _get_session_factory()() as session:
        repo = JobRepository(session)
        await repo.update_status(
            job_id=job_id,
            status=JobStatus.FAILED,
            error=error_message,
        )


def _is_permanent_failure(exc: Exception) -> bool:
    """Determine if an exception is a permanent failure (no retry)."""
    permanent_types = (ValueError, FileNotFoundError)
    return isinstance(exc, permanent_types)
