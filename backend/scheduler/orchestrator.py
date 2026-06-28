import asyncio
from datetime import datetime
import uuid
from sqlalchemy.orm import Session

from app.database import SessionLocal, AsyncSessionLocal
from app.models import SchedulerLog
from scrapers.portal_manager import PORTAL_MANAGER
from scrapers.document_downloader import DOCUMENT_DOWNLOADER
from app.services.keyword_worker import process_pending_tenders

async def run_orchestrator():
    db = SessionLocal()
    run_id = str(uuid.uuid4())
    log = SchedulerLog(
        run_id=run_id,
        status="RUNNING",
        started_at=datetime.utcnow()
    )
    db.add(log)
    db.commit()

    try:
        # Step 1: Scrape ALL portals concurrently
        print(f"[{run_id}] Step 1: Scraping portals...")
        async with AsyncSessionLocal() as async_db:
            await PORTAL_MANAGER.start_all(async_db)

        # Get status from PORTAL_MANAGER
        stats = PORTAL_MANAGER.get_status()
        log.total_portals = stats.get("total_portals", 0)
        log.completed_portals = stats.get("completed", 0)
        log.failed_portals = stats.get("failed", 0)
        log.tenders_scraped = stats.get("total_new", 0)
        log.tenders_updated = stats.get("total_updated", 0)
        db.commit()

        # Step 2: Download ALL tender documents concurrently
        print(f"[{run_id}] Step 2: Downloading tender documents...")
        log.status = "DOWNLOADING"
        db.commit()
        await DOCUMENT_DOWNLOADER.run()

        # Step 3: Run Keyword Matching (strictly after scraping and downloading completes)
        print(f"[{run_id}] Step 3: Running Keyword Matching...")
        log.status = "MATCHING"
        db.commit()
        
        processed = await asyncio.to_thread(process_pending_tenders, db, limit=2000)
        log.matches_found = processed
        
        print(f"[{run_id}] Finished Orchestrator Run successfully.")
        log.status = "COMPLETED"
        log.finished_at = datetime.utcnow()
        db.commit()

    except Exception as exc:
        print(f"[{run_id}] Orchestrator Failed: {exc}")
        log.status = "FAILED"
        log.error_message = str(exc)
        log.finished_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(run_orchestrator())
