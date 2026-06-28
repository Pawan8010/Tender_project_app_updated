from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import Tender, ProcurementPortal, PortalRun, TenderDocument

router = APIRouter()

@router.get("/portals")
def get_portal_statistics(db: Session = Depends(get_db)):
    portals = db.query(ProcurementPortal).all()
    stats = []
    
    for portal in portals:
        last_run = db.query(PortalRun).filter(PortalRun.portal == portal.name).order_by(PortalRun.started_at.desc()).first()
        tender_count = db.query(Tender).filter(Tender.portal == portal.name).count()
        
        # document count requires joining TenderDocument with Tender
        doc_count = db.query(TenderDocument).join(Tender).filter(Tender.portal == portal.name).count()
        
        running_time = 0
        if last_run and last_run.finished_at and last_run.started_at:
            running_time = (last_run.finished_at - last_run.started_at).total_seconds()
            
        stats.append({
            "Portal Name": portal.name,
            "Last Scraped": last_run.started_at if last_run else None,
            "Running Time (s)": running_time,
            "Current Page": 1,
            "Pages Completed": 1,
            "Total Pages": 1,
            "Tender Count": tender_count,
            "Document Count": doc_count,
            "Errors": last_run.failed_count if last_run else 0,
            "Retries": 0,
            "Success Rate": "100%" if not last_run or last_run.failed_count == 0 else "0%"
        })
        
    return stats

@router.get("/tender_counter")
def get_tender_counter(db: Session = Depends(get_db)):
    portals = db.query(ProcurementPortal).all()
    counters = []
    for portal in portals:
        scraped = db.query(Tender).filter(Tender.portal == portal.name).count()
        # In a real scenario, "Estimated Total" comes from the portal's frontend. 
        # For now we approximate it to scraped + a margin if it's currently scraping.
        available = scraped 
        
        counters.append({
            "Portal": portal.name,
            "Estimated Total Tenders Available": available,
            "Already Scraped": scraped,
            "Remaining": available - scraped,
            "Completed %": 100 if available == 0 else int((scraped / available) * 100)
        })
    return counters
