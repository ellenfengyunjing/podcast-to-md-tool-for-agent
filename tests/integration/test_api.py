import pytest
from unittest.mock import patch, MagicMock
import os

from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def setup_test_env(tmp_path):
    """Set up test environment variables and reset DB engine."""
    db_path = tmp_path / "test.db"
    os.environ["PKA_DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
    os.environ["PKA_DATA_DIR"] = str(tmp_path)
    os.environ["PKA_DEBUG"] = "false"
    os.environ["PKA_GROQ_API_KEY"] = "test-groq-key"
    os.environ["PKA_LLM_API_KEY"] = "test-llm-key"

    from src.storage.database import reset_engine
    reset_engine()

    yield

    reset_engine()


@pytest.fixture
async def initialized_app(setup_test_env):
    """Create app and initialize the database."""
    from src.main import create_app
    from src.storage.database import init_db
    from src.config import get_config

    config = get_config()
    config.ensure_data_dir()
    await init_db()

    return create_app()


@pytest.mark.asyncio
class TestAPIEndpoints:
    async def test_health_check(self, initialized_app):
        async with AsyncClient(
            transport=ASGITransport(app=initialized_app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"

    async def test_submit_podcast_returns_202(self, initialized_app):
        with patch("src.api.v1.endpoints.podcast.process_podcast_task") as mock_task:
            mock_task.delay = MagicMock()

            async with AsyncClient(
                transport=ASGITransport(app=initialized_app),
                base_url="http://test",
            ) as client:
                response = await client.post(
                    "/api/v1/podcast/process",
                    json={"url": "https://www.youtube.com/watch?v=test123"},
                )

        assert response.status_code == 202
        data = response.json()
        assert "job_id" in data
        assert data["status"] == "queued"
        assert "status_url" in data

    async def test_get_nonexistent_job_returns_404(self, initialized_app):
        async with AsyncClient(
            transport=ASGITransport(app=initialized_app),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/v1/podcast/jobs/nonexistent-id")

        assert response.status_code == 404
