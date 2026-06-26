from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_current_user
from app.database import SessionLocal
from app.models import Tender
from app.services.ml_engine import find_similar_titles, fuzzy_search, semantic_search

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/search")
def smart_search(q: str = Query(..., min_length=2), mode: str = "both", limit: int = Query(10, ge=1, le=50)):
    if mode == "fuzzy":
        results = fuzzy_search(q, limit)
    elif mode == "semantic":
        results = semantic_search(q, limit)
    else:
        seen = set()
        results = []
        for item in [*semantic_search(q, limit), *fuzzy_search(q, limit)]:
            if item["term"] not in seen:
                seen.add(item["term"])
                results.append(item)
        results = sorted(results, key=lambda row: row["score"], reverse=True)[:limit]
    return {"query": q, "mode": mode, "count": len(results), "results": results}


@router.get("/similar/{tender_id}")
def similar_tenders(tender_id: int, limit: int = Query(5, ge=1, le=20)):
    db = SessionLocal()
    try:
        target = db.get(Tender, tender_id)
        if not target:
            raise HTTPException(status_code=404, detail="Tender not found")
        candidates = db.query(Tender).filter(Tender.id != tender_id, Tender.is_active.is_(True)).order_by(Tender.scraped_at.desc()).limit(500).all()
        matches = find_similar_titles(target.title, [row.title for row in candidates], limit)
        return {
            "target_id": tender_id,
            "target_title": target.title,
            "similar": [{**item, "tender_id": candidates[item["index"]].id, "portal": candidates[item["index"]].portal} for item in matches],
        }
    finally:
        db.close()


@router.get("/status")
def ml_status():
    from app.services.ml_engine import _load_model

    model = _load_model()
    return {"enabled": True, "loaded": model is not None, "status": "ready" if model else "fallback_to_fuzzy"}
