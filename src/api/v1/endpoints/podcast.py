import json

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.v1.schemas.request import PodcastProcessRequest
from src.api.v1.schemas.response import JobCreatedResponse, JobStatusResponse, ProgressInfo
from src.storage.database import get_session
from src.storage.models import JobStatus
from src.storage.repository import JobRepository
from src.pipeline.tasks import process_podcast_task

logger = structlog.get_logger()
router = APIRouter()

STAGE_ORDER = [
    "resolving", "downloading", "transcribing",
    "summarizing", "compressing", "assembling",
]


def _build_progress(job) -> ProgressInfo:
    if job.status == JobStatus.COMPLETED:
        return ProgressInfo(
            current_stage="completed",
            stages_completed=STAGE_ORDER,
            stages_remaining=[],
            percent_complete=100.0,
        )
    if job.status == JobStatus.FAILED:
        return ProgressInfo(
            current_stage="failed",
            stages_completed=[],
            stages_remaining=[],
            percent_complete=job.progress_percent or 0.0,
        )

    current = job.current_stage or "queued"
    if current in STAGE_ORDER:
        idx = STAGE_ORDER.index(current)
        completed = STAGE_ORDER[:idx]
        remaining = STAGE_ORDER[idx + 1:]
    else:
        completed = []
        remaining = STAGE_ORDER

    return ProgressInfo(
        current_stage=current,
        stages_completed=completed,
        stages_remaining=remaining,
        percent_complete=job.progress_percent or 0.0,
    )


@router.post("/process", status_code=202, response_model=JobCreatedResponse)
async def submit_podcast(
    request: PodcastProcessRequest,
    session: AsyncSession = Depends(get_session),
):
    repo = JobRepository(session)
    job = await repo.create(
        url=request.url,
        request_payload=request.model_dump_json(),
    )

    # Dispatch Celery task
    process_podcast_task.delay(job.id, request.model_dump())

    logger.info("job_created", job_id=job.id, url=request.url)
    return JobCreatedResponse(
        job_id=job.id,
        status="queued",
        status_url=f"/api/v1/podcast/jobs/{job.id}",
    )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    session: AsyncSession = Depends(get_session),
):
    repo = JobRepository(session)
    job = await repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusResponse(
        job_id=job.id,
        status=job.status.value,
        progress=_build_progress(job),
        created_at=job.created_at.isoformat() if job.created_at else None,
        updated_at=job.updated_at.isoformat() if job.updated_at else None,
        error_message=job.error_message,
    )


@router.get("/jobs/{job_id}/result")
async def get_job_result(
    job_id: str,
    session: AsyncSession = Depends(get_session),
):
    repo = JobRepository(session)
    job = await repo.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == JobStatus.QUEUED or job.status in (
        JobStatus.RESOLVING, JobStatus.DOWNLOADING, JobStatus.TRANSCRIBING,
        JobStatus.SUMMARIZING, JobStatus.COMPRESSING, JobStatus.ASSEMBLING,
    ):
        return JSONResponse(status_code=202, content={"status": "processing", "job_id": job_id})

    if job.status == JobStatus.FAILED:
        raise HTTPException(status_code=500, detail=job.error_message or "Processing failed")

    if not job.result_path:
        raise HTTPException(status_code=500, detail="Result file not found")

    with open(job.result_path, "r", encoding="utf-8") as f:
        result = json.load(f)

    return JSONResponse(content=result)


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
):
    repo = JobRepository(session)
    deleted = await repo.delete(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Job not found")
