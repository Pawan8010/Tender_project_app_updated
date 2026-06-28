from celery import Celery
from celery.schedules import crontab
from app.config import settings
from app.database import init_db
from app.notifier import send_daily_digest_email

celery_app = Celery("tender_hunter", broker=settings()["redis_url"], backend=settings()["redis_url"])
celery_app.conf.update(
    broker_connection_retry_on_startup=True,
    enable_utc=True,
    task_track_started=True,
    timezone="Asia/Kolkata",
)

celery_app.conf.beat_schedule = {
    "scrape-all-portals-every-30-minutes": {
        "task": "celery_worker.scrape_all_portals",
        "schedule": crontab(minute="*/30"),
    },
    "download-documents-every-10-minutes": {
        "task": "celery_worker.download_documents",
        "schedule": crontab(minute="*/10"),
    },
    "daily-tender-digest": {
        "task": "celery_worker.send_daily_digest",
        "schedule": crontab(hour=8, minute=0),
    }
}


@celery_app.task(name="celery_worker.scrape_all_portals")
def scrape_all_portals():
    import asyncio
    from scrapers.portal_manager import PORTAL_MANAGER
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    from app.database import get_async_db
    
    async def run_mgr():
        async for db in get_async_db():
            await PORTAL_MANAGER.start_all(db)
            break
            
    loop.run_until_complete(run_mgr())


@celery_app.task(name="celery_worker.download_documents")
def download_documents():
    import asyncio
    from scrapers.document_downloader import DOCUMENT_DOWNLOADER
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(DOCUMENT_DOWNLOADER.run())


@celery_app.task(name="celery_worker.send_daily_digest")
def send_daily_digest():
    return {"sent": send_daily_digest_email()}
