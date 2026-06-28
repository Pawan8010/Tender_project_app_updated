import time
from datetime import datetime
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Tender
from app.keywords import _match_keywords_from_library
from app.notifier import alert_recipients_for_tender, send_alert_email
from scrapers.registry import _record_matches

def process_pending_tenders(db: Session, limit: int = 50) -> int:
    pending_tenders = (
        db.query(Tender)
        .filter(Tender.classification_status == "PENDING_CLASSIFICATION")
        .limit(limit)
        .all()
    )
    if not pending_tenders:
        return 0

    processed_count = 0
    for tender in pending_tenders:
        started = time.perf_counter()
        raw_data = dict(tender.raw_data or {})
        text = tender.search_text or f"{tender.title or ''} {tender.description or ''}"
        
        matched, categories, match_meta = _match_keywords_from_library(db, text)
        
        incoming_matched = tender.matched_keywords or []
        incoming_categories = tender.categories or []
        combined_matched = list(dict.fromkeys([*incoming_matched, *matched]))
        combined_categories = sorted(set([*incoming_categories, *categories]))

        tender.matched_keywords = combined_matched
        tender.categories = combined_categories
        tender.classification_status = "CLASSIFIED" if combined_matched or combined_categories else "UNCLASSIFIED"
        tender.ai_category = combined_categories[0] if combined_categories else "UNCLASSIFIED"
        
        raw_data["match_score"] = match_meta["match_score"]
        raw_data["match_aliases"] = match_meta["match_aliases"]
        raw_data["match_reasons"] = match_meta["match_reasons"]
        
        if match_meta.get("semantic_matches"):
            raw_data["semantic_matches"] = match_meta["semantic_matches"]
        if match_meta.get("ml_used"):
            raw_data["ml_used"] = True

        existing_alerted_recipients = set(raw_data.get("alerted_recipients") or [])
        
        tender_data = {
            "title": tender.title,
            "description": tender.description,
            "portal": tender.portal,
            "state": tender.state,
            "tender_url": tender.tender_url,
            "categories": combined_categories,
            "matched_keywords": combined_matched,
            "closing_date": tender.closing_date,
            "estimated_value": tender.estimated_value,
        }

        should_alert = False
        if combined_matched or combined_categories:
            current_recipients = set(alert_recipients_for_tender(tender_data, db))
            pending_recipients = current_recipients - existing_alerted_recipients
            if pending_recipients:
                sent = send_alert_email(tender_data, pending_recipients)
                raw_data["alert_attempted_at"] = datetime.utcnow().isoformat()
                if sent:
                    raw_data["alerted_recipients"] = sorted(existing_alerted_recipients | pending_recipients)
                    raw_data["alerted_at"] = raw_data["alert_attempted_at"]
        
        tender.raw_data = raw_data
        _record_matches(db, tender, match_meta, started)
        
        db.commit()
        processed_count += 1

    return processed_count
