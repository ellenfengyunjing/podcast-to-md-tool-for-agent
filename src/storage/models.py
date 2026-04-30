import enum
from datetime import datetime, timezone

from sqlalchemy import Column, String, Float, DateTime, Text, Enum as SAEnum
from sqlalchemy.orm import DeclarativeBase


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    RESOLVING = "resolving"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    SUMMARIZING = "summarizing"
    COMPRESSING = "compressing"
    ASSEMBLING = "assembling"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True)
    url = Column(String, nullable=False)
    status = Column(SAEnum(JobStatus), default=JobStatus.QUEUED, nullable=False)
    progress_percent = Column(Float, default=0.0)
    current_stage = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)
    request_payload = Column(Text, nullable=False)
    result_path = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
