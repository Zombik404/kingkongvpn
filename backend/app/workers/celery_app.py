"""Celery application (ADR-011): `celery -A app.workers.celery_app worker|beat`."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "globalvpn",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    result_expires=3600,
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,  # a crashed worker's task is redelivered; tasks are idempotent
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=300,
    task_soft_time_limit=240,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "subscriptions-process-due": {
            "task": "subscriptions.process_due",
            "schedule": 300.0,
        },
        "subscriptions-send-reminders": {
            "task": "subscriptions.send_reminders",
            "schedule": crontab(minute=17),
        },
        "games-run-timers": {
            "task": "games.run_timers",
            "schedule": 5.0,
        },
        "payments-poll-pending": {
            "task": "payments.poll_pending",
            "schedule": 60.0,
        },
        "users-purge-deleted": {
            "task": "users.purge_deleted",
            "schedule": crontab(hour=3, minute=41),
        },
        "auth-cleanup-tokens": {
            "task": "auth.cleanup_tokens",
            "schedule": crontab(hour=4, minute=13),
        },
    },
)

app = celery_app  # `celery -A app.workers.celery_app` finds `app` or `celery_app`
