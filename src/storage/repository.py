import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.models import Job, JobStatus


class JobRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, url: str, request_payload: str) -> Job:
        job = Job(
            id=str(uuid.uuid4()),
            url=url,
            status=JobStatus.QUEUED,
            request_payload=request_payload,
        )
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def get(self, job_id: str) -> Job | None:
        result = await self.session.execute(select(Job).where(Job.id == job_id))
        return result.scalar_one_or_none()

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        progress: float | None = None,
        stage: str | None = None,
        error: str | None = None,
        result_path: str | None = None,
    ) -> Job | None:
        job = await self.get(job_id)
        if not job:
            return None

        job.status = status
        job.updated_at = datetime.now(timezone.utc)

        if progress is not None:
            job.progress_percent = progress
        if stage is not None:
            job.current_stage = stage
        if error is not None:
            job.error_message = error
        if result_path is not None:
            job.result_path = result_path
        if status == JobStatus.COMPLETED:
            job.completed_at = datetime.now(timezone.utc)

        await self.session.commit()
        await self.session.refresh(job)
        return job

    async def delete(self, job_id: str) -> bool:
        job = await self.get(job_id)
        if not job:
            return False
        await self.session.delete(job)
        await self.session.commit()
        return True
