import asyncio
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import SessionLocal, get_async_db
from app.models import ProcurementPortal, WorkerStatus, PortalRun, ScrapeLog, TenderChangeEvent
from app.config import settings
from scrapers.registry import portal_browser_enabled
from scrapers.worker import PortalWorker
from scrapers.engine_services import (
    CheckpointService,
    MonitoringService,
    PortalJob,
    ScraperDatabaseService,
    StructuredScrapeLogger,
    WorkerQueue,
)

class PortalManager:
    def __init__(self):
        self._workers: dict[str, asyncio.Task] = {}
        self._running = False
        self._stop_event = asyncio.Event()
        self._monitor_task = None
        self.run_id: str | None = None
        self.logger = StructuredScrapeLogger()
        self.checkpoints = CheckpointService()
        self.database_service = ScraperDatabaseService()
        self.monitoring = MonitoringService()
        self.stats = {
            "total_portals": 0,
            "running": 0,
            "failed": 0,
            "completed": 0,
            "total_fetched": 0,
            "total_new": 0,
            "total_updated": 0,
            "total_duplicates": 0,
            "total_failed_tenders": 0,
            "retry_count": 0,
            "queue_size": 0,
            "current_portal": None,
            "current_tender": None,
            "scraping_speed_per_minute": 0,
            "started_at": None,
            "finished_at": None,
        }

    async def start_all(self, db: AsyncSession, search_query: str | None = None) -> None:
        if self._running:
            return
            
        self._running = True
        self.run_id = str(uuid.uuid4())
        self.monitoring = MonitoringService()
        self._stop_event.clear()
        self.stats["started_at"] = datetime.utcnow()
        self.stats["running"] = 0
        self.stats["completed"] = 0
        self.stats["failed"] = 0
        self.stats["total_fetched"] = 0
        self.stats["total_new"] = 0
        self.stats["total_updated"] = 0
        self.stats["total_duplicates"] = 0
        self.stats["total_failed_tenders"] = 0
        self.stats["retry_count"] = 0
        self.stats["queue_size"] = 0
        self.stats["current_portal"] = None
        self.stats["current_tender"] = None
        self.stats["scraping_speed_per_minute"] = 0
        self.logger.event("scrape_run_started", run_id=self.run_id, message="Enterprise scraper run started")

        def ensure_portals_synced() -> None:
            from scrapers.registry import sync_portal_registry

            sync_db = SessionLocal()
            try:
                sync_portal_registry(sync_db)
            finally:
                sync_db.close()

        await asyncio.to_thread(ensure_portals_synced)
        
        result = await db.execute(select(ProcurementPortal).where(ProcurementPortal.enabled == True))
        portals = result.scalars().all()
        self.stats["total_portals"] = len(portals)

        from scrapers.registry import PORTAL_SCRAPER_MAP
        from scrapers.portals.nic_generic import NICGenericScraper

        scrapers = []
        cfg = settings()
        for row in portals:
            scraper_class = PORTAL_SCRAPER_MAP.get(row.name, NICGenericScraper)
            scraper_instance = scraper_class(
                portal_name=row.name,
                base_url=row.url,
                state=row.state or "National",
                use_playwright=portal_browser_enabled(row),
                listing_urls=row.listing_urls or [row.url],
            )
            scrapers.append(scraper_instance)

        queue = WorkerQueue()
        for s in scrapers:
            await queue.put(PortalJob(portal_name=s.portal_name, scraper=s))
        self.stats["queue_size"] = queue.qsize()

        async def worker_task():
            while not queue.empty():
                if self._stop_event.is_set():
                    break
                job = await queue.get()
                scraper = job.scraper
                worker_id = str(uuid.uuid4())
                self.stats["current_portal"] = scraper.portal_name
                self.stats["queue_size"] = queue.qsize()
                self.checkpoints.start_portal(scraper.portal_name, self.run_id or worker_id)
                self.logger.event("portal_started", run_id=self.run_id, portal=scraper.portal_name, worker_id=worker_id)
                worker = PortalWorker(
                    worker_id=worker_id,
                    scraper=scraper,
                    result_callback=self._process_portal_results,
                    max_retries=settings().get("scraper_retries", 2),
                )
                self.stats["running"] += 1
                try:
                    await worker.run(search_query=search_query)
                except Exception as e:
                    await self._process_portal_results(scraper.portal_name, [], e)
                finally:
                    queue.task_done()
                    self.stats["queue_size"] = queue.qsize()

        self._monitor_task = asyncio.create_task(self.monitor_workers())
        
        concurrency = cfg.get("scraper_concurrency", 3)
        num_workers = min(concurrency, len(scrapers))
        
        tasks = [asyncio.create_task(worker_task()) for _ in range(num_workers)]
        await asyncio.gather(*tasks, return_exceptions=True)

        self._running = False
        self.stats["finished_at"] = datetime.utcnow()
        self.stats["scraping_speed_per_minute"] = self.monitoring.speed_per_minute(self.stats["total_fetched"])
        self.logger.event(
            "scrape_run_finished",
            run_id=self.run_id,
            fetched=self.stats["total_fetched"],
            new=self.stats["total_new"],
            updated=self.stats["total_updated"],
            failed=self.stats["failed"],
            message="Enterprise scraper run finished",
        )
        if self._monitor_task:
            self._monitor_task.cancel()

    async def _process_portal_results(
        self,
        portal_name: str,
        tenders: list[dict],
        error: Exception | None,
    ) -> None:
        self.stats["running"] = max(0, self.stats["running"] - 1)
        
        if error:
            self.stats["failed"] += 1
            self.checkpoints.finish_portal(portal_name, "failed", error=str(error))
            self.logger.event("portal_failed", run_id=self.run_id, portal=portal_name, error=str(error), message="Portal failed; remaining portals continue")
        else:
            self.stats["completed"] += 1
            
        async for db in get_async_db():
            # Update PortalRun
            run = PortalRun(
                portal=portal_name,
                status="success" if not error else "failed",
                started_at=datetime.utcnow(),
                finished_at=datetime.utcnow(),
                fetched_count=len(tenders) if tenders else 0,
                updated_count=0,
                stored_count=0,
                duplicate_count=0,
                failed_count=1 if error else 0,
                error_message=str(error) if error else None
            )
            db.add(run)
            
            # Update Portal health
            res = await db.execute(select(ProcurementPortal).where(ProcurementPortal.name == portal_name))
            portal = res.scalars().first()
            if portal:
                portal.health_status = "degraded" if error else "online"
                portal.last_successful_run = datetime.utcnow() if not error else portal.last_successful_run
                portal.updated_at = datetime.utcnow()
                    
            if error:
                log = ScrapeLog(portal=portal_name, status="failed", tenders_found=0, error_message=f"Failed: {error}")
                db.add(log)
                await db.commit()
                try:
                    from app.routers.scrape import push_log
                    push_log(f"Worker {portal_name} failed: {error}")
                except Exception:
                    pass
                break

            await db.commit()
            
            new_this_portal = 0
            updated_this_portal = 0
            fetched_this_portal = len(tenders or [])
            self.stats["total_fetched"] += fetched_this_portal
            
            if tenders:
                def sync_upsert_batch():
                    return self.database_service.upsert_batch(portal_name, tenders)
                
                batch = await asyncio.to_thread(sync_upsert_batch)
                n = batch.new
                u = batch.updated
                changed_tenders = batch.changed_tenders
                self.stats["total_new"] += n
                self.stats["total_updated"] += u
                self.stats["total_duplicates"] += batch.duplicate
                self.stats["total_failed_tenders"] += batch.failed
                new_this_portal = n
                updated_this_portal = u
                
                run.stored_count = n + u
                run.updated_count = u
                run.duplicate_count = batch.duplicate
                run.failed_count = batch.failed
                run.logs = [
                    {
                        "message": (
                            f"{batch.fetched} fetched, {batch.new} new, {batch.updated} updated, "
                            f"{batch.duplicate} duplicates, {batch.failed} failed"
                        ),
                        "errors": batch.errors[:10],
                    }
                ]
                
                # Create change events
                for t_id, change_type, changes in changed_tenders:
                    event = TenderChangeEvent(
                        tender_id=t_id,
                        change_type=change_type,
                        changed_fields=changes,
                        snapshot={}
                    )
                    db.add(event)
            log = ScrapeLog(
                portal=portal_name,
                status="success",
                tenders_found=fetched_this_portal,
                error_message=None,
            )
            db.add(log)
            await db.commit()
            duplicate_count = max(0, fetched_this_portal - new_this_portal - updated_this_portal)
            self.stats["scraping_speed_per_minute"] = self.monitoring.speed_per_minute(self.stats["total_fetched"])
            self.checkpoints.finish_portal(
                portal_name,
                "success",
                stats={
                    "fetched": fetched_this_portal,
                    "new": new_this_portal,
                    "updated": updated_this_portal,
                    "duplicates": duplicate_count,
                },
            )
            self.logger.event(
                "portal_completed",
                run_id=self.run_id,
                portal=portal_name,
                fetched=fetched_this_portal,
                new=new_this_portal,
                updated=updated_this_portal,
                duplicates=duplicate_count,
                speed_per_minute=self.stats["scraping_speed_per_minute"],
                message="Portal completed",
            )
            
            try:
                from app.routers.scrape import push_log
                duplicate_count = max(0, fetched_this_portal - new_this_portal - updated_this_portal)
                push_log(
                    f"Worker {portal_name} completed: {fetched_this_portal} fetched, "
                    f"{new_this_portal} new, {updated_this_portal} updated, {duplicate_count} unchanged"
                )
            except Exception:
                pass
            
            break

    async def monitor_workers(self) -> None:
        cfg = settings()
        timeout = cfg.get("worker_heartbeat_timeout", 60)
        
        while self._running:
            await asyncio.sleep(30)
            async for db in get_async_db():
                res = await db.execute(select(WorkerStatus).where(WorkerStatus.status.in_(["running", "starting"])))
                workers = res.scalars().all()
                now = datetime.utcnow()
                
                for w in workers:
                    if w.last_heartbeat and (now - w.last_heartbeat).total_seconds() > timeout:
                        w.status = "crashed"
                        w.error_message = "Worker timed out (no heartbeat)"
                        
                        log = ScrapeLog(portal=w.portal_name, status="failed", tenders_found=0, error_message=f"Worker {w.worker_id} crashed.")
                        db.add(log)
                        
                await db.commit()
                break

    async def stop(self) -> None:
        self._running = False
        self._stop_event.set()

    def get_status(self) -> dict:
        return self.stats

PORTAL_MANAGER = PortalManager()
