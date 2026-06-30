import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.models import ScrapeCheckpoint, Tender
from app.services.tender_index import index_tender
from scrapers.registry import _upsert_tender


LOG_DIR = Path("logs")
SESSION_DIR = Path("data") / "browser_sessions"


@dataclass(slots=True)
class PortalJob:
    portal_name: str
    scraper: Any
    priority: int = 100
    attempts: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(slots=True)
class UpsertBatchResult:
    fetched: int = 0
    new: int = 0
    updated: int = 0
    duplicate: int = 0
    failed: int = 0
    changed_tenders: list[tuple[int, str, dict]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class StructuredScrapeLogger:
    def __init__(self, log_name: str = "scraper-events.jsonl"):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        self.path = LOG_DIR / log_name

    def event(self, event: str, **payload: Any) -> None:
        record = {
            "event": event,
            "at": datetime.utcnow().isoformat(),
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str, ensure_ascii=False) + "\n")
        try:
            from app.routers.scrape import push_log

            portal = payload.get("portal")
            message = payload.get("message") or event.replace("_", " ")
            push_log(f"{portal}: {message}" if portal else message)
        except Exception:
            pass


class WorkerQueue:
    def __init__(self):
        self._queue: asyncio.PriorityQueue[tuple[int, int, PortalJob]] = asyncio.PriorityQueue()
        self._counter = 0

    async def put(self, job: PortalJob) -> None:
        self._counter += 1
        await self._queue.put((job.priority, self._counter, job))

    async def get(self) -> PortalJob:
        _priority, _counter, job = await self._queue.get()
        return job

    def task_done(self) -> None:
        self._queue.task_done()

    def empty(self) -> bool:
        return self._queue.empty()

    def qsize(self) -> int:
        return self._queue.qsize()


class CheckpointService:
    def start_portal(self, portal_name: str, run_id: str) -> None:
        db = SessionLocal()
        try:
            row = db.query(ScrapeCheckpoint).filter(ScrapeCheckpoint.portal == portal_name).first()
            if not row:
                row = ScrapeCheckpoint(portal=portal_name)
                db.add(row)
            row.run_id = run_id
            row.status = "running"
            row.started_at = datetime.utcnow()
            row.updated_at = datetime.utcnow()
            row.last_error = None
            db.commit()
        finally:
            db.close()

    def finish_portal(self, portal_name: str, status: str, stats: dict | None = None, error: str | None = None) -> None:
        db = SessionLocal()
        try:
            row = db.query(ScrapeCheckpoint).filter(ScrapeCheckpoint.portal == portal_name).first()
            if not row:
                row = ScrapeCheckpoint(portal=portal_name)
                db.add(row)
            row.status = status
            row.finished_at = datetime.utcnow()
            row.updated_at = datetime.utcnow()
            row.last_success_at = datetime.utcnow() if status in {"success", "completed"} else row.last_success_at
            row.last_error = error
            row.stats = stats or {}
            db.commit()
        finally:
            db.close()


class ScraperDatabaseService:
    def upsert_batch(self, portal_name: str, tenders: list[dict]) -> UpsertBatchResult:
        result = UpsertBatchResult(fetched=len(tenders or []))
        with Session(engine) as db:
            for tender_data in tenders or []:
                try:
                    status, tender_id, changes = _upsert_tender(db, tender_data, return_changes=True)
                    tender = db.get(Tender, tender_id)
                    if tender:
                        index_tender(db, tender)
                    if status in {"new", "created"}:
                        result.new += 1
                        result.changed_tenders.append((tender_id, "new", changes))
                    elif status == "updated":
                        result.updated += 1
                        result.changed_tenders.append((tender_id, "updated", changes))
                    else:
                        result.duplicate += 1
                    if (result.new + result.updated + result.duplicate) % 100 == 0:
                        db.commit()
                except Exception as exc:
                    db.rollback()
                    result.failed += 1
                    result.errors.append(str(exc)[:240])
            db.commit()
        return result


class SessionManager:
    def __init__(self, session_dir: Path = SESSION_DIR):
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def state_path(self, portal_name: str) -> Path:
        safe = "".join(char if char.isalnum() or char in "-_" else "_" for char in portal_name)
        return self.session_dir / f"{safe}.json"

    async def load_context_state(self, browser, portal_name: str):
        path = self.state_path(portal_name)
        if path.exists():
            return await browser.new_context(storage_state=str(path))
        return await browser.new_context()

    async def save_context_state(self, context, portal_name: str) -> None:
        await context.storage_state(path=str(self.state_path(portal_name)))


class BrowserPool:
    def __init__(self, size: int = 3, headless: bool = True):
        self.size = max(1, size)
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._semaphore = asyncio.Semaphore(self.size)

    async def start(self):
        if self._browser:
            return self
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        return self

    async def acquire_context(self, portal_name: str, session_manager: SessionManager):
        await self._semaphore.acquire()
        await self.start()
        try:
            return await session_manager.load_context_state(self._browser, portal_name)
        except Exception:
            self._semaphore.release()
            raise

    async def release_context(self, context, portal_name: str, session_manager: SessionManager) -> None:
        try:
            await session_manager.save_context_state(context, portal_name)
            await context.close()
        finally:
            self._semaphore.release()

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._playwright = None


class MonitoringService:
    def __init__(self):
        self.started = time.perf_counter()

    def speed_per_minute(self, total_fetched: int) -> float:
        elapsed = max(1.0, time.perf_counter() - self.started)
        return round(total_fetched / elapsed * 60, 2)
