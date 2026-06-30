import asyncio
import traceback
from datetime import datetime
from typing import Callable, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_async_db
from app.models import WorkerStatus
from scrapers.base_scraper import BaseScraper
from app.config import settings

class PortalWorker:
    def __init__(
        self,
        worker_id: str,
        scraper: BaseScraper,
        result_callback: Callable,
        max_retries: int = 3,
        base_delay: float = 2.0,
    ):
        self.worker_id = worker_id
        self.scraper = scraper
        self.result_callback = result_callback
        self.max_retries = max_retries
        self.base_delay = base_delay
        self._heartbeat_task = None
        self._running = False
        self._db_generator = get_async_db()

    async def run(self, search_query: str | None = None) -> None:
        self._running = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        
        async for db in get_async_db():
            await self._update_status(db, status="starting", started_at=datetime.utcnow())
            break

        error = None
        tenders = []
        try:
            raw_tenders = await self._run_with_retry(search_query)
            tenders = raw_tenders
                
            async for db in get_async_db():
                await self._update_status(
                    db, 
                    status="completed", 
                    finished_at=datetime.utcnow(),
                    tenders_scraped_session=len(tenders)
                )
                break
        except Exception as exc:
            error = exc
            async for db in get_async_db():
                await self._update_status(
                    db, 
                    status="failed", 
                    finished_at=datetime.utcnow(), 
                    error_message=str(exc) + "\n" + traceback.format_exc()
                )
                break
        finally:
            self._running = False
            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                try:
                    await self._heartbeat_task
                except asyncio.CancelledError:
                    pass
            
            await self.result_callback(self.scraper.portal_name, tenders, error)

    async def _update_status(self, db: AsyncSession, status: str, **kwargs) -> None:
        try:
            result = await db.execute(select(WorkerStatus).where(WorkerStatus.worker_id == self.worker_id))
            worker = result.scalars().first()
            if not worker:
                worker = WorkerStatus(worker_id=self.worker_id, portal_name=self.scraper.portal_name)
                db.add(worker)
            
            worker.status = status
            worker.last_heartbeat = datetime.utcnow()
            for k, v in kwargs.items():
                setattr(worker, k, v)
                
            await db.commit()
        except Exception as exc:
            await db.rollback()
            from utils.logger import logger
            logger.error("Failed to update worker status", worker_id=self.worker_id, error=str(exc))

    async def _heartbeat_loop(self) -> None:
        cfg = settings()
        interval = cfg.get("worker_heartbeat_interval", 15)
        while self._running:
            await asyncio.sleep(interval)
            async for db in get_async_db():
                await self._update_status(db, status="running")
                break

    async def _run_with_retry(self, search_query: str | None = None) -> list[dict]:
        attempt = 0
        last_error = None
        
        while attempt <= self.max_retries:
            try:
                async for db in get_async_db():
                    await self._update_status(db, status="running", retry_count=attempt)
                    break
                
                return await self.scraper.scrape()
                
            except Exception as exc:
                last_error = exc
                attempt += 1
                if attempt <= self.max_retries:
                    delay = self.base_delay * (2 ** (attempt - 1))
                    await asyncio.sleep(delay)
                    
        raise RuntimeError(f"PortalWorker failed after {self.max_retries} retries: {last_error}") from last_error
