from pathlib import Path

from pydantic_settings import BaseSettings


class AppConfig(BaseSettings):
    model_config = {"env_file": ".env", "env_prefix": "PKA_"}

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # OpenRouter API (single key for all services)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # ASR Model (audio transcription via chat completions)
    asr_model: str = "openai/gpt-4o-audio-preview"

    # LLM Model (chat completions)
    llm_model: str = "meta-llama/llama-4-maverick"

    # Embedding Model
    embedding_model: str = "baai/bge-large-en-v1.5"

    # ASR Backend: "local" (faster-whisper CPU), "groq" (Groq Whisper API), "api" (OpenRouter)
    asr_backend: str = "local"
    whisper_model_size: str = "large-v3"

    # Groq API (for cloud ASR - extremely fast)
    groq_api_key: str = ""

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"

    # Storage
    data_dir: Path = Path("./data")
    database_url: str = "sqlite+aiosqlite:///./data/jobs.db"

    def ensure_data_dir(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


def get_config() -> AppConfig:
    return AppConfig()
