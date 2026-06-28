from app.keywords import CATEGORY_MAP, KEYWORDS, analyze_tender_match, category_for_keyword, match_keywords
import time
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import Tender, TenderMatch, Keyword

__all__ = ["CATEGORY_MAP", "KEYWORDS", "analyze_tender_match", "category_for_keyword", "match_keywords", "match_tender_keywords"]

async def match_tender_keywords(db: AsyncSession, tender: Tender, text: str) -> dict:
    started = time.perf_counter()
    try:
        from app.services.ml_engine import ml_analyze_tender
        match_meta = ml_analyze_tender(text)
    except Exception:
        match_meta = analyze_tender_match(text)
        
    matched = match_meta.get("matched_keywords") or []
    categories = match_meta.get("categories") or []
    text_lower = (text or "").lower()

    res = await db.execute(select(Keyword).where(Keyword.is_active == True))
    active_keywords = res.scalars().all()
    
    category_set = set(categories)
    for row in active_keywords:
        keyword = (row.keyword or "").strip()
        if not keyword:
            continue
        if keyword.lower() in text_lower and keyword not in matched:
            matched.append(keyword)
            category = row.category or category_for_keyword(keyword)
            if category:
                category_set.add(category)

    match_meta["matched_keywords"] = matched
    match_meta["categories"] = sorted(category_set)
    
    # Save the matches
    if not (match_meta.get("matched_keywords") or match_meta.get("categories")):
        return match_meta
        
    processing_time_ms = int((time.perf_counter() - started) * 1000)
    cats_list = match_meta.get("categories") or [None]
    score = int(match_meta.get("match_score") or 0)
    reasons = match_meta.get("match_reasons") or []
    
    for keyword in match_meta.get("matched_keywords") or ["AI Classification"]:
        category = cats_list[0] if cats_list else None
        
        # Check existing match
        res = await db.execute(
            select(TenderMatch)
            .where(TenderMatch.tender_id == tender.id)
            .where(TenderMatch.matched_keyword == keyword)
            .where(TenderMatch.category == category)
        )
        exists = res.scalars().first()
        
        if exists:
            exists.confidence = min(1.0, max(0.0, score / 100))
            exists.score = score
            exists.reason = "; ".join(reasons[:3])[:1000] if reasons else None
            exists.processing_time_ms = processing_time_ms
        else:
            db.add(
                TenderMatch(
                    tender_id=tender.id,
                    matched_keyword=keyword,
                    category=category,
                    confidence=min(1.0, max(0.0, score / 100)),
                    reason="; ".join(reasons[:3])[:1000] if reasons else None,
                    score=score,
                    matching_fields=["title", "description", "metadata"],
                    processing_time_ms=processing_time_ms,
                )
            )
            
    # Update tender with the found info
    tender.categories = match_meta["categories"]
    tender.matched_keywords = match_meta["matched_keywords"]
    tender.classification_status = "CLASSIFIED"
    tender.ai_category = cats_list[0] if cats_list else "Uncategorized"
    
    await db.commit()
    return match_meta

