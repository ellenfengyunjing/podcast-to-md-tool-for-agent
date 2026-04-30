from fastapi import APIRouter

from src.api.v1.endpoints import podcast, health

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(podcast.router, prefix="/podcast", tags=["podcast"])
