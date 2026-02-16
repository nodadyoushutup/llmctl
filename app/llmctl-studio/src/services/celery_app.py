from __future__ import annotations

from celery import Celery

from core.config import Config
from rag.contracts import RAG_QUEUE_DRIVE, RAG_QUEUE_GIT, RAG_QUEUE_INDEX

STUDIO_TASK_QUEUE = "llmctl_studio"

celery_app = Celery("llmctl_studio")
celery_config = {
    "broker_url": Config.CELERY_BROKER_URL,
    "result_backend": Config.CELERY_RESULT_BACKEND,
    "task_default_queue": STUDIO_TASK_QUEUE,
    "task_track_started": True,
    "task_serializer": "json",
    "accept_content": ["json"],
    "result_serializer": "json",
    "timezone": "UTC",
    "task_routes": {
        "rag.worker.tasks.run_index_task": {"queue": RAG_QUEUE_INDEX},
    },
}
if Config.WORKSPACE_CLEANUP_ENABLED and Config.WORKSPACE_CLEANUP_INTERVAL_SECONDS > 0:
    celery_config["beat_schedule"] = {
        "workspace_cleanup": {
            "task": "services.tasks.cleanup_workspaces",
            "schedule": Config.WORKSPACE_CLEANUP_INTERVAL_SECONDS,
            "options": {"queue": STUDIO_TASK_QUEUE},
        }
    }
if Config.CELERY_BROKER_TRANSPORT_OPTIONS:
    celery_config["broker_transport_options"] = Config.CELERY_BROKER_TRANSPORT_OPTIONS
celery_app.conf.update(celery_config)

celery_app.autodiscover_tasks(["services", "rag.worker"])
