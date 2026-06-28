from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from datetime import datetime

from app.database import get_async_db
from app.models import ProcurementPortal, WorkerStatus, PortalRun, Tender, TenderDocument

router = APIRouter(prefix="/api/v1/statistics", tags=["statistics"])

@router.get("/")
async def get_portal_statistics(db: AsyncSession = Depends(get_async_db)):
    res_portals = await db.execute(select(ProcurementPortal).order_by(ProcurementPortal.name))
    portals = res_portals.scalars().all()
    
    stats = []
    for portal in portals:
        res_worker = await db.execute(
            select(WorkerStatus)
            .where(WorkerStatus.portal_name == portal.name)
            .where(WorkerStatus.status.in_(["running", "starting"]))
            .order_by(desc(WorkerStatus.last_heartbeat))
        )
        worker = res_worker.scalars().first()
        
        res_run = await db.execute(
            select(PortalRun)
            .where(PortalRun.portal == portal.name)
            .order_by(desc(PortalRun.started_at))
        )
        last_run = res_run.scalars().first()
        
        tender_count = (await db.execute(
            select(func.count(Tender.id))
            .where(Tender.portal == portal.name)
        )).scalar() or 0
        
        doc_count = (await db.execute(
            select(func.count(TenderDocument.id))
            .join(Tender, TenderDocument.tender_id == Tender.id)
            .where(Tender.portal == portal.name)
            .where(TenderDocument.status == "processed")
        )).scalar() or 0
        
        failed_doc_count = (await db.execute(
            select(func.count(TenderDocument.id))
            .join(Tender, TenderDocument.tender_id == Tender.id)
            .where(Tender.portal == portal.name)
            .where(TenderDocument.status == "failed")
        )).scalar() or 0
        
        avg_duration = 0
        if last_run and last_run.finished_at and last_run.started_at:
            avg_duration = int((last_run.finished_at - last_run.started_at).total_seconds())
            
        stats.append({
            "portal_name": portal.name,
            "worker_id": worker.worker_id if worker else None,
            "status": worker.status if worker else (last_run.status if last_run else "offline"),
            "current_page": worker.current_page if worker else 0,
            "pages_completed": last_run.fetched_count if last_run and last_run.status == "success" else 0,
            "estimated_total_pages": 100,
            "current_tender": worker.current_tender if worker else None,
            "total_scraped": tender_count,
            "documents_downloaded": doc_count,
            "new_tenders": last_run.stored_count if last_run else 0,
            "updated_tenders": last_run.updated_count if last_run else 0,
            "failed_downloads": failed_doc_count,
            "retry_count": worker.retry_count if worker else 0,
            "average_scraping_time_seconds": avg_duration,
            "last_successful_scrape": portal.last_successful_run
        })
        
    return stats
