from __future__ import annotations

from celery import Celery

from core.config import Config

celery_app = Celery("llmctl_studio")
celery_config = {
    "broker_url": Config.CELERY_BROKER_URL,
    "result_backend": Config.CELERY_RESULT_BACKEND,
    "task_track_started": True,
    "task_serializer": "json",
    "accept_content": ["json"],
    "result_serializer": "json",
    "timezone": "UTC",
}
if Config.CELERY_BROKER_TRANSPORT_OPTIONS:
    celery_config["broker_transport_options"] = Config.CELERY_BROKER_TRANSPORT_OPTIONS
celery_app.conf.update(celery_config)

celery_app.autodiscover_tasks(["services"])
