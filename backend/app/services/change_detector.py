from datetime import datetime, date
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from app.models import Tender, TenderHistory, TenderChangeEvent, TenderDocument

def find_existing_tender(db: Session, portal: str, tender_id: str | None, reference_number: str | None, organization: str | None, closing_date: date | None, title: str | None) -> Tender | None:
    # 1. Try by tender_id
    if tender_id:
        existing = db.query(Tender).filter(Tender.tender_id == tender_id).first()
        if existing:
            return existing
            
    # 2. Try by reference_number
    if portal and reference_number:
        existing = db.query(Tender).filter(Tender.portal == portal, Tender.reference_number == reference_number).first()
        if existing:
            return existing

    # 3. Try by organization and closing_date
    if portal and organization and closing_date and title:
        existing = db.query(Tender).filter(
            Tender.portal == portal,
            Tender.organization == organization,
            Tender.closing_date == closing_date
        ).first()
        if existing:
            # Verify title similarity or title match
            if title.lower()[:50] in (existing.title or "").lower():
                return existing
                
    return None

def detect_and_log_changes(db: Session, existing: Tender, incoming: dict) -> tuple[str, dict]:
    changed_fields = {}
    change_types = []
    
    # 1. Closing Date Change
    old_closing = existing.closing_date
    new_closing = incoming.get("closing_date")
    if new_closing and str(old_closing) != str(new_closing):
        changed_fields["closing_date"] = {"old": str(old_closing), "new": str(new_closing)}
        change_types.append("Changed Closing Date")
        
    # 2. Status changes (Cancelled / Reopened)
    old_status = existing.tender_status or "ACTIVE"
    new_status = incoming.get("tender_status") or "ACTIVE"
    if old_status != new_status:
        changed_fields["tender_status"] = {"old": old_status, "new": new_status}
        if new_status.upper() in {"CANCELLED", "TERMINATED", "WITHDRAWN"}:
            change_types.append("Cancelled Tender")
        elif old_status.upper() in {"CANCELLED", "TERMINATED", "WITHDRAWN"} and new_status.upper() == "ACTIVE":
            change_types.append("Reopened Tender")
            
    # 3. Corrigendum detection
    old_corr = existing.corrigendum or False
    new_corr = incoming.get("corrigendum") or False
    if old_corr != new_corr or (new_corr and not old_corr):
        changed_fields["corrigendum"] = {"old": old_corr, "new": True}
        change_types.append("New Corrigendum")
        
    # 4. Check for document attachments / BOQ changes
    # We can inspect the raw data urls
    old_raw = existing.raw_data or {}
    new_raw = incoming.get("raw_data") or {}
    
    old_attachments = old_raw.get("attachments") or old_raw.get("attachment_urls") or []
    new_attachments = new_raw.get("attachments") or new_raw.get("attachment_urls") or []
    if set(old_attachments) != set(new_attachments):
        changed_fields["attachments"] = {"old": list(old_attachments), "new": list(new_attachments)}
        # Check if BOQ specifically changed
        if any("boq" in str(url).lower() for url in new_attachments):
            change_types.append("Changed BOQ")
        else:
            change_types.append("Updated PDF")
            
    # 5. Metadata updates
    for field in ("title", "description", "estimated_value", "department", "buyer", "location"):
        old_val = getattr(existing, field, None)
        new_val = incoming.get(field)
        if new_val is not None and str(old_val or "") != str(new_val or ""):
            changed_fields[field] = {"old": str(old_val or ""), "new": str(new_val)}
            
    if changed_fields and not change_types:
        change_types.append("Updated Tender")
        
    primary_change = change_types[0] if change_types else "Updated Tender"
    return primary_change, changed_fields
