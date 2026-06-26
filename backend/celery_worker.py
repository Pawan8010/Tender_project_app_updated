from celery import Celery
from celery.schedules import crontab
from app.config import settings
from app.database import init_db
from app.notifier import send_daily_digest_email
from scrapers.registry import run_all_scrapers_sync

celery_app = Celery("tender_hunter", broker=settings()["redis_url"], backend=settings()["redis_url"])
celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    enable_utc=True,
    task_track_started=True,
    timezone="Asia/Kolkata",
)

celery_app.conf.beat_schedule = {
    "scrape-all-portals-hourly": {
        "task": "celery_worker.scrape_all_portals",
        "schedule": settings()["auto_scrape_interval_minutes"] * 60,
    },
    "daily-tender-digest": {
        "task": "celery_worker.send_daily_digest",
        "schedule": crontab(hour=8, minute=0),
    }
}


@celery_app.task(name="celery_worker.scrape_all_portals")
def scrape_all_portals():
    init_db()
    return run_all_scrapers_sync()


@celery_app.task(name="celery_worker.send_daily_digest")
def send_daily_digest():
    return {"sent": send_daily_digest_email()}
