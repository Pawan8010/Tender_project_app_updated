from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from datetime import date, datetime, timedelta
import psutil

from app.auth import get_current_user
from app.database import get_async_db
from app.models import ProcurementPortal, WorkerStatus, Tender, TenderMatch, TenderDocument, PortalRun, ScrapeLog
from app.services.ai_intelligence import trend_summary
from scrapers.portal_manager import PORTAL_MANAGER

router = APIRouter(tags=["dashboard"], dependencies=[Depends(get_current_user)])

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


@router.get("/ai")
async def get_ai_dashboard(db: AsyncSession = Depends(get_async_db)):
    res = await db.execute(select(Tender).where(Tender.is_active == True).order_by(Tender.scraped_at.desc()).limit(5000))
    tenders = res.scalars().all()
    trends = trend_summary(tenders)
    today = date.today()
    closing_soon = [
        tender
        for tender in tenders
        if tender.closing_date and today <= tender.closing_date <= today + timedelta(days=7)
    ]
    largest = sorted(
        [tender for tender in tenders if tender.estimated_value],
        key=lambda tender: tender.estimated_value or 0,
        reverse=True,
    )[:10]
    recommended = sorted(
        tenders,
        key=lambda tender: float(((tender.raw_data or {}).get("ai") or {}).get("confidence") or 0),
        reverse=True,
    )[:10]

    return {
        **trends,
        "closing_soon": [
            {"id": t.id, "title": t.title, "portal": t.portal, "state": t.state, "closing_date": t.closing_date}
            for t in closing_soon[:10]
        ],
        "largest_tenders": [
            {"id": t.id, "title": t.title, "portal": t.portal, "state": t.state, "estimated_value": t.estimated_value}
            for t in largest
        ],
        "ai_recommended": [
            {
                "id": t.id,
                "title": t.title,
                "portal": t.portal,
                "state": t.state,
                "ai_category": t.ai_category,
                "confidence": ((t.raw_data or {}).get("ai") or {}).get("confidence"),
                "tags": ((t.raw_data or {}).get("ai") or {}).get("tags") or [],
            }
            for t in recommended
        ],
        "predictive_analytics": {
            "procurement_trends": trends["trending_sectors"][:5],
            "technology_demand": trends["trending_technologies"][:5],
            "department_purchasing_trends": trends["active_departments"][:5],
        },
    }
