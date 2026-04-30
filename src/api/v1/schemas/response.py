from pydantic import BaseModel, Field


# --- Job Status Response ---

class ProgressInfo(BaseModel):
    current_stage: str | None = None
    stages_completed: list[str] = []
    stages_remaining: list[str] = []
    percent_complete: float = 0.0


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: ProgressInfo
    created_at: str | None = None
    updated_at: str | None = None
    error_message: str | None = None


class JobCreatedResponse(BaseModel):
    job_id: str
    status: str = "queued"
    status_url: str


# --- Final Output Schemas ---

class AudioMetadata(BaseModel):
    source_url: str
    platform: str
    title: str
    author: str | None = None
    description: str | None = None
    duration_seconds: float
    published_at: str | None = None
    language: str
    thumbnail_url: str | None = None


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str
    speaker: str = "SPEAKER_00"


class TimedParagraph(BaseModel):
    """A paragraph of transcript text grouped by time window."""
    time_start: float
    time_end: float
    time_label: str  # e.g. "00:00 - 01:00"
    text: str


class FullTranscript(BaseModel):
    segments: list[TranscriptSegment]
    paragraphs: list[TimedParagraph] = Field(default_factory=list)
    full_text: str
    word_count: int
    speaker_count: int = 1
    speakers: list[str] = ["SPEAKER_00"]


class TopicBlock(BaseModel):
    topic: str
    summary: str
    timestamp_range: list[float] = Field(default_factory=list)
    related_quotes: list[str] = Field(default_factory=list)


class Entity(BaseModel):
    name: str
    type: str
    context: str


class StructuredSummary(BaseModel):
    title: str
    one_line_summary: str
    executive_summary: str
    key_topics: list[TopicBlock] = Field(default_factory=list)
    key_insights: list[str] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    content_type: str = "unknown"
    language: str = "en"


class AgentMemoryBlock(BaseModel):
    block_id: str
    block_type: str
    content: str
    source_timestamp: list[float] = Field(default_factory=list)
    speaker: str | None = None
    importance_score: float = 0.0
    tokens: int = 0
    tags: list[str] = Field(default_factory=list)
    embedding_text: str = ""


class CompressedAgentMemory(BaseModel):
    source_id: str
    source_title: str
    source_url: str
    total_duration_seconds: float
    language: str
    memory_blocks: list[AgentMemoryBlock] = Field(default_factory=list)
    retrieval_summary: str = ""
    total_tokens: int = 0
    compression_ratio: float = 0.0


class ProcessingInfo(BaseModel):
    job_id: str
    started_at: str
    completed_at: str
    duration_seconds: float
    asr_model: str
    llm_model: str
    pipeline_version: str = "0.1.0"


class PodcastKnowledge(BaseModel):
    metadata: AudioMetadata
    transcript: FullTranscript
    summary: StructuredSummary
    agent_memory: CompressedAgentMemory
    processing: ProcessingInfo
