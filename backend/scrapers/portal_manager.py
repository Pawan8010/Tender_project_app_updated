import asyncio
import uuid
from datetime import datetime
import json
import traceback

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import SessionLocal, get_async_db
from app.models import ProcurementPortal, WorkerStatus, PortalRun, ScrapeLog, TenderChangeEvent
from app.config import settings
from scrapers.registry import all_scrapers, _upsert_tender
from scrapers.worker import PortalWorker
from app.services.keyword_engine import match_tender_keywords

class PortalManager:
    def __init__(self):
        self._workers: dict[str, asyncio.Task] = {}
        self._running = False
        self._stop_event = asyncio.Event()
        self._monitor_task = None
        self.stats = {
            "total_portals": 0,
            "running": 0,
            "failed": 0,
            "completed": 0,
            "total_new": 0,
            "total_updated": 0,
            "started_at": None,
            "finished_at": None,
        }

    async def start_all(self, db: AsyncSession, search_query: str | None = None) -> None:
        if self._running:
            return
            
        self._running = True
        self._stop_event.clear()
        self.stats["started_at"] = datetime.utcnow()
        self.stats["running"] = 0
        self.stats["completed"] = 0
        self.stats["failed"] = 0
        self.stats["total_new"] = 0
        self.stats["total_updated"] = 0

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
        for row in portals:
            scraper_class = PORTAL_SCRAPER_MAP.get(row.name, NICGenericScraper)
            scraper_instance = scraper_class(
                portal_name=row.name,
                base_url=row.url,
                state=row.state or "National",
                use_playwright=row.scraper_type == "playwright",
                listing_urls=row.listing_urls or [row.url],
            )
            scrapers.append(scraper_instance)

        queue = asyncio.Queue()
        for s in scrapers:
            await queue.put(s)

        async def worker_task():
            while not queue.empty():
                if self._stop_event.is_set():
                    break
                scraper = await queue.get()
                worker_id = str(uuid.uuid4())
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

        self._monitor_task = asyncio.create_task(self.monitor_workers())
        
        concurrency = settings().get("scraper_concurrency", 3)
        num_workers = min(concurrency, len(scrapers))
        
        tasks = [asyncio.create_task(worker_task()) for _ in range(num_workers)]
        await asyncio.gather(*tasks, return_exceptions=True)

        self._running = False
        self.stats["finished_at"] = datetime.utcnow()
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
            
            new_this_portal = 0
            updated_this_portal = 0
            
            if not error and tenders:
                from scrapers.registry import _upsert_tender
                from sqlalchemy.orm import Session
                from app.database import engine
                
                def sync_upsert_batch():
                    n = 0
                    u = 0
                    changed_tenders = []
                    with Session(engine) as sync_db:
                        for td in tenders:
                            try:
                                status, t_id, changes = _upsert_tender(sync_db, td, return_changes=True)
                                if status == "new" or status == "created":
                                    n += 1
                                    changed_tenders.append((t_id, "new", changes))
                                elif status == "updated":
                                    u += 1
                                    changed_tenders.append((t_id, "updated", changes))
                            except Exception as e:
                                pass
                        sync_db.commit()
                    return n, u, changed_tenders
                
                n, u, changed_tenders = await asyncio.to_thread(sync_upsert_batch)
                self.stats["total_new"] += n
                self.stats["total_updated"] += u
                new_this_portal = n
                updated_this_portal = u
                
                run.stored_count = n
                run.updated_count = u
                
                # Create change events
                for t_id, change_type, changes in changed_tenders:
                    event = TenderChangeEvent(
                        tender_id=t_id,
                        change_type=change_type,
                        changed_fields=changes,
                        snapshot={}
                    )
                    db.add(event)
                await db.commit()

            await db.commit()
            
            try:
                from app.routers.scrape import push_log
                if error:
                    push_log(f"Worker {portal_name} failed: {error}")
                else:
                    push_log(f"Worker {portal_name} completed: {len(tenders)} scraped, {new_this_portal} new, {updated_this_portal} updated")
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
