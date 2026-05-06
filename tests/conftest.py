import pytest
from pathlib import Path


@pytest.fixture
def sample_data_dir(tmp_path):
    """Provide a temporary data directory for tests."""
    return tmp_path / "data"


@pytest.fixture
def app_config(sample_data_dir):
    """Provide a test configuration."""
    from src.config import AppConfig

    return AppConfig(
        debug=True,
        groq_api_key="test-groq-key",
        llm_api_key="test-llm-key",
        llm_model="gpt-4o",
        redis_url="redis://localhost:6379/0",
        data_dir=sample_data_dir,
        database_url=f"sqlite+aiosqlite:///{sample_data_dir}/test.db",
    )
