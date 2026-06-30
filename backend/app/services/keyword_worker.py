import time
from datetime import datetime
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import Tender
from app.keywords import _match_keywords_from_library
from app.notifier import alert_recipients_for_tender, send_alert_email_limited
from app.services.ai_intelligence import analyze_tender_payload
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
        ai_result = analyze_tender_payload(
            {
                "title": tender.title,
                "description": tender.description,
                "department": tender.department,
                "organization": tender.organization,
                "location": tender.location,
                "search_text": tender.search_text,
                "raw_data": raw_data,
            }
        )
        
        incoming_matched = tender.matched_keywords or []
        incoming_categories = tender.categories or []
        ai_tags = ai_result.get("tags") or []
        ai_category = ai_result.get("category")
        combined_matched = list(dict.fromkeys([*incoming_matched, *matched, *ai_tags]))
        combined_categories = sorted(set([*incoming_categories, *categories, *([ai_category] if ai_category else [])]))

        tender.matched_keywords = combined_matched
        tender.categories = combined_categories
        tender.classification_status = "CLASSIFIED" if combined_matched or combined_categories else "UNCLASSIFIED"
        tender.ai_category = ai_category or (combined_categories[0] if combined_categories else "UNCLASSIFIED")
        
        ai_confidence_score = int(float(ai_result.get("confidence") or 0) * 100)
        raw_data["match_score"] = max(int(match_meta["match_score"] or 0), ai_confidence_score)
        raw_data["match_aliases"] = match_meta["match_aliases"]
        raw_data["match_reasons"] = match_meta["match_reasons"]
        raw_data["ai"] = {
            "category": ai_category,
            "confidence": ai_result.get("confidence"),
            "tags": ai_tags,
            "entities": ai_result.get("entities") or {},
            "summary": ai_result.get("summary"),
            "important_dates": ai_result.get("important_dates") or [],
            "embedding": ai_result.get("embedding") or [],
            "processed_at": datetime.utcnow().isoformat(),
        }
        if ai_result.get("summary"):
            raw_data["plain_summary"] = ai_result["summary"]
        
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
                sent, deferred_recipients, delivered_recipients = send_alert_email_limited(tender_data, pending_recipients)
                raw_data["alert_attempted_at"] = datetime.utcnow().isoformat()
                if sent:
                    raw_data["alerted_recipients"] = sorted(existing_alerted_recipients | set(delivered_recipients))
                    raw_data["alerted_at"] = raw_data["alert_attempted_at"]
                if deferred_recipients:
                    raw_data["alert_deferred_recipients"] = sorted(set(deferred_recipients))
                    raw_data["alert_deferred_at"] = raw_data["alert_attempted_at"]
        
        tender.raw_data = raw_data
        enriched_match_meta = {
            **match_meta,
            "matched_keywords": combined_matched,
            "categories": combined_categories,
            "match_score": raw_data["match_score"],
            "match_reasons": list(dict.fromkeys([*(match_meta.get("match_reasons") or []), f"AI category: {tender.ai_category}"])),
        }
        _record_matches(db, tender, enriched_match_meta, started)
        try:
            from app.services.tender_index import index_tender

            index_tender(db, tender)
        except Exception:
            pass
        
        db.commit()
        processed_count += 1

    return processed_count
