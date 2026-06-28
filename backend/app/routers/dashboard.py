from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import date, datetime
import psutil

from app.database import get_async_db
from app.models import ProcurementPortal, WorkerStatus, Tender, TenderMatch, TenderDocument, PortalRun, ScrapeLog
from scrapers.portal_manager import PORTAL_MANAGER

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])

@router.get("/")
async def get_dashboard_stats(db: AsyncSession = Depends(get_async_db)):
    res_portals = await db.execute(select(ProcurementPortal))
    portals = res_portals.scalars().all()
    
    res_workers = await db.execute(select(WorkerStatus))
    workers = res_workers.scalars().all()
    
    total_tenders = (await db.execute(select(func.count(Tender.id)))).scalar() or 0
    today_tenders = (await db.execute(select(func.count(Tender.id)).where(Tender.published_date == date.today()))).scalar() or 0
    keyword_matches = (await db.execute(select(func.count(TenderMatch.id)))).scalar() or 0
    downloaded_docs = (await db.execute(select(func.count(TenderDocument.id)).where(TenderDocument.status == "processed"))).scalar() or 0
    
    runs_count = (await db.execute(select(func.count(PortalRun.id)))).scalar() or 0
    logs_count = (await db.execute(select(func.count(ScrapeLog.id)))).scalar() or 0
    db_records = total_tenders + keyword_matches + downloaded_docs + runs_count + logs_count
    
    manager_stats = PORTAL_MANAGER.get_status()
    
    cpu_usage = psutil.cpu_percent()
    ram_usage = psutil.virtual_memory().percent
    
    online_workers = [w for w in workers if w.status in ("running", "starting")]
    
    return {
        "total_portals": len(portals),
        "running_portals": manager_stats.get("running", 0),
        "completed_portals": manager_stats.get("completed", 0),
        "failed_portals": manager_stats.get("failed", 0),
        "queued_portals": max(0, len(portals) - manager_stats.get("running", 0) - manager_stats.get("completed", 0) - manager_stats.get("failed", 0)),
        "workers_online": len(online_workers),
        "current_workers": [
            {
                "worker_id": w.worker_id,
                "portal": w.portal_name,
                "status": w.status,
                "current_page": w.current_page or 0,
                "current_tender": w.current_tender or "",
                "new_tenders": w.new_tenders or 0,
                "updated_tenders": w.updated_tenders or 0,
                "retry_count": w.retry_count or 0
            } for w in online_workers
        ],
        "total_tenders": total_tenders,
        "today_tenders": today_tenders,
        "updated_tenders": manager_stats.get("total_updated", 0),
        "keyword_matches": keyword_matches,
        "downloaded_documents": downloaded_docs,
        "database_records": db_records,
        "errors": manager_stats.get("failed", 0),
        "retries": sum(w.retry_count or 0 for w in workers),
        "average_speed": round(total_tenders / max(1, (datetime.utcnow() - (manager_stats.get("started_at") or datetime.utcnow())).total_seconds() / 60), 2),
        "system_cpu": cpu_usage,
        "system_ram": ram_usage,
        "portals_list": [
            {
                "name": p.name,
                "health": p.health_status,
                "enabled": p.enabled,
                "last_successful_run": p.last_successful_run,
                "next_run": p.next_run
            } for p in portals
        ]
    }
