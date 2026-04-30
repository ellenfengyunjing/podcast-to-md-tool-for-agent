from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from src.config import get_config
from src.api.router import api_router
from src.storage.database import init_db

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()
    config.ensure_data_dir()
    await init_db()
    logger.info("application_started", host=config.host, port=config.port)
    yield
    logger.info("application_shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Podcast Knowledge Agent",
        description="Podcast → Agent-readable Structured Knowledge System",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(api_router)
    return app


app = create_app()
