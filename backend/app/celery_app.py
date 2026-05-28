from __future__ import annotations

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "vige",
    broker=settings.redis_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_track_started=True,
)

celery_app.autodiscover_tasks(["app.workers"])
