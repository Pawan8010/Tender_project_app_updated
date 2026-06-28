from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import date, datetime

from app.database import get_db
from app.models import Tender, ProcurementPortal, SchedulerLog, TenderDocument, KeywordMatch

router = APIRouter()

@router.get("/")
def get_dashboard_metrics(db: Session = Depends(get_db)):
    total_portals = db.query(ProcurementPortal).count()
    active_portals = db.query(ProcurementPortal).filter(ProcurementPortal.enabled == True).count()
    
    last_run = db.query(SchedulerLog).order_by(SchedulerLog.started_at.desc()).first()
    
    total_tenders = db.query(Tender).count()
    today_tenders = db.query(Tender).filter(func.date(Tender.published_date) == date.today()).count()
    active_tenders = db.query(Tender).filter(Tender.tender_status == "ACTIVE").count()
    expired_tenders = db.query(Tender).filter(Tender.tender_status != "ACTIVE").count()
    
    keyword_matches = db.query(KeywordMatch).count()
    downloads = db.query(TenderDocument).count()
    
    # Check SQLite file size or DB size approximation
    import os
    db_size = "0 MB"
    if os.path.exists("tender_hunter.db"):
        size_bytes = os.path.getsize("tender_hunter.db")
        db_size = f"{size_bytes / (1024 * 1024):.2f} MB"
        
    return {
        "cards": {
            "Total Portals": total_portals,
            "Active Portals": active_portals,
            "Running": last_run.status == "RUNNING" if last_run else False,
            "Completed": last_run.status == "COMPLETED" if last_run else False,
            "Failed": last_run.status == "FAILED" if last_run else False,
            "Queued": False,
            "Total Tenders": total_tenders,
            "Today's Tenders": today_tenders,
            "Active Tenders": active_tenders,
            "Expired": expired_tenders,
            "Keyword Matches": keyword_matches,
            "Downloads": downloads,
            "Database Size": db_size
        },
        "last_run": {
            "status": last_run.status if last_run else "Unknown",
            "started_at": last_run.started_at if last_run else None,
            "finished_at": last_run.finished_at if last_run else None
        }
    }
