"""
Celery application configuration.

Includes:
- Celery app setup with Redis broker
- Task configuration
- Beat schedule for periodic tasks
"""
from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "email_agent",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks",
        "app.tasks.email_tasks",
        "app.tasks.ai_tasks",
        "app.tasks.notification_tasks",
        "app.tasks.response_tasks",
    ],
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    worker_prefetch_multiplier=1,
    result_expires=3600,  # 1 hour
)

# Celery Beat schedule for periodic tasks
celery_app.conf.beat_schedule = {
    "check-emails-every-minute": {
        "task": "app.tasks.email_tasks.schedule_email_checks",
        "schedule": 60.0,  # Every 60 seconds
        "options": {"queue": "default"},
    },
    "send-weekly-reports": {
        "task": "app.tasks.notification_tasks.send_weekly_reports",
        "schedule": crontab(hour=9, minute=0, day_of_week="monday"),  # Every Monday at 9 AM
        "options": {"queue": "default"},
    },
}

# Optional: Set default queue
celery_app.conf.task_default_queue = "default"
