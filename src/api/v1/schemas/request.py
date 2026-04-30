from pydantic import BaseModel, Field, HttpUrl


class PodcastProcessRequest(BaseModel):
    url: str = Field(..., description="YouTube URL or RSS feed URL")
    episode_index: int | None = Field(None, description="For RSS: which episode (0=latest)")
    language_hint: str | None = Field(None, description="Language hint: 'zh', 'en', etc.")
    asr_backend: str | None = Field(None, description="Override ASR backend: 'api' or 'local'")
    llm_model: str | None = Field(None, description="Override LLM model name")
    agent_memory_token_budget: int = Field(2000, description="Token budget for agent memory")
    webhook_url: str | None = Field(None, description="Webhook URL for completion callback")
