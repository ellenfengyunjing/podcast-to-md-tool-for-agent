from celery import Celery

from src.config import get_config

config = get_config()

celery_app = Celery(
    "podcast_knowledge_agent",
    broker=config.redis_url,
    backend=config.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,  # One task at a time per worker
)
