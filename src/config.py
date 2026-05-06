from pathlib import Path

from pydantic_settings import BaseSettings


class AppConfig(BaseSettings):
    """Runtime configuration.

    By design, this tool is meant to be invoked by an AI agent (Claude Code,
    OpenClaw, Codex, Claude Desktop). The tool only transcribes; the calling
    agent uses its own model for summarization / analysis. Therefore only the
    Groq API key is required for the default workflow.

    If callers want a fully self-contained pipeline (transcription + LLM
    summary + memory blocks) without an enclosing agent, they can set the
    optional ``PKA_LLM_API_KEY`` to enable the ``process_podcast`` tool.
    """

    model_config = {"env_file": ".env", "env_prefix": "PKA_", "extra": "ignore"}

    # Server (only used when running the optional REST API)
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False

    # --- Required: Groq Whisper API (fast cloud ASR) ---
    # Get a free key at https://console.groq.com (~8 hours/day free tier)
    groq_api_key: str = ""
    groq_model: str = "whisper-large-v3-turbo"

    # --- Optional: LLM for built-in summary/memory extraction ---
    # Leave empty when the calling agent will handle summarization itself.
    # Compatible with any OpenAI-format endpoint (OpenRouter, OpenAI, DeepSeek,
    # Moonshot, local vLLM, etc).
    llm_api_key: str = ""
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "meta-llama/llama-4-maverick"

    # --- Celery / Redis (only used when running the optional REST API) ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Storage ---
    data_dir: Path = Path("./data")
    database_url: str = "sqlite+aiosqlite:///./data/jobs.db"

    def ensure_data_dir(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key)


def get_config() -> AppConfig:
    return AppConfig()
