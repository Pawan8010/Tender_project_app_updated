import hashlib
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import Tender, TenderDocument, TenderSearchIndex
from app.services.ai_intelligence import extract_entities, generate_tags, predict_category, summarize, text_embedding


SEARCH_TEXT_LIMIT = 1_000_000
EMBED_TEXT_LIMIT = 20_000


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def _document_text(tender: Tender) -> str:
    parts = []
    for doc in tender.documents or []:
        if doc.extracted_text:
            parts.append(doc.extracted_text)
        elif doc.file_name:
            parts.append(doc.file_name)
    raw = tender.raw_data or {}
    for key in ("document_text", "pdf_text", "boq_text", "technical_text", "financial_text", "ocr_text"):
        if raw.get(key):
            parts.append(str(raw.get(key)))
    return "\n".join(parts)[:SEARCH_TEXT_LIMIT]


def build_search_text(tender: Tender) -> dict:
    raw = tender.raw_data or {}
    document_text = _document_text(tender)
    field_parts = [
        tender.title,
        tender.description,
        tender.portal,
        tender.state,
        tender.district,
        tender.department,
        tender.buyer,
        tender.organization,
        tender.location,
        tender.bid_number,
        tender.reference_number,
        tender.tender_status,
        tender.ai_category,
        " ".join(tender.categories or []),
        " ".join(tender.matched_keywords or []),
        raw.get("detail_text"),
        raw.get("plain_summary"),
    ]
    title_text = _clean(" ".join(str(part) for part in field_parts[:11] if part))
    search_text = _clean("\n".join(str(part) for part in [*field_parts, document_text] if part))[:SEARCH_TEXT_LIMIT]
    return {"title_text": title_text, "document_text": document_text, "search_text": search_text}


def index_tender(db: Session, tender: Tender, *, commit: bool = False) -> TenderSearchIndex:
    texts = build_search_text(tender)
    search_text = texts["search_text"] or _clean(tender.title)
    source_hash = hashlib.sha256(search_text.encode("utf-8", errors="ignore")).hexdigest()
    existing = db.query(TenderSearchIndex).filter(TenderSearchIndex.tender_id == tender.id).first()
    raw_data = dict(tender.raw_data or {})
    search_index_raw = dict(raw_data.get("search_index") or {})
    if existing and existing.source_hash == source_hash:
        search_index_raw["indexed_at"] = existing.indexed_at.isoformat() if existing.indexed_at else datetime.utcnow().isoformat()
        raw_data["search_index"] = search_index_raw
        tender.raw_data = raw_data
        if commit:
            db.commit()
        return existing

    category, confidence = predict_category(search_text)
    tags = generate_tags(search_text)
    entities = extract_entities(search_text)
    summary = summarize(search_text)
    embedding = text_embedding(search_text[:EMBED_TEXT_LIMIT])

    if not existing:
        existing = TenderSearchIndex(tender_id=tender.id, search_text=search_text)
        db.add(existing)

    existing.search_text = search_text
    existing.title_text = texts["title_text"]
    existing.document_text = texts["document_text"][:SEARCH_TEXT_LIMIT]
    existing.embedding = embedding
    existing.tags = tags
    existing.entities = entities
    existing.ai_summary = summary
    existing.ai_category = category
    existing.indexed_at = datetime.utcnow()
    existing.source_hash = source_hash

    tender.search_text = search_text
    tender.ai_category = tender.ai_category or category
    combined_tags = list(dict.fromkeys([*(tender.matched_keywords or []), *tags]))
    combined_categories = list(dict.fromkeys([*(tender.categories or []), category]))
    tender.matched_keywords = combined_tags
    tender.categories = combined_categories
    raw_ai = dict(raw_data.get("ai") or {})
    raw_ai.update(
        {
            "category": raw_ai.get("category") or category,
            "confidence": max(float(raw_ai.get("confidence") or 0), confidence),
            "tags": list(dict.fromkeys([*(raw_ai.get("tags") or []), *tags])),
            "entities": {**entities, **(raw_ai.get("entities") or {})},
            "summary": raw_ai.get("summary") or summary,
            "embedding": raw_ai.get("embedding") or embedding,
            "indexed_at": existing.indexed_at.isoformat(),
        }
    )
    raw_data["ai"] = raw_ai
    raw_data["plain_summary"] = raw_data.get("plain_summary") or summary
    raw_data["search_index"] = {
        "indexed_at": existing.indexed_at.isoformat(),
        "source_hash": source_hash,
        "text_length": len(search_text),
        "document_text_length": len(texts["document_text"]),
    }
    tender.raw_data = raw_data
    tender.updated_at = datetime.utcnow()

    if commit:
        db.commit()
    return existing


def index_pending_tenders(db: Session, limit: int = 500) -> int:
    rows = (
        db.query(Tender)
        .outerjoin(TenderSearchIndex, TenderSearchIndex.tender_id == Tender.id)
        .filter(Tender.is_active.is_(True))
        .filter((TenderSearchIndex.id.is_(None)) | (Tender.updated_at > TenderSearchIndex.indexed_at))
        .order_by(Tender.updated_at.desc())
        .limit(limit)
        .all()
    )
    for tender in rows:
        index_tender(db, tender)
    db.commit()
    return len(rows)


def ensure_search_indexes(engine) -> None:
    dialect = engine.dialect.name
    with engine.begin() as connection:
        if dialect == "postgresql":
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_tenders_search_text_fts "
                    "ON tenders USING GIN (to_tsvector('english', coalesce(search_text, '')))"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_tender_search_index_text_fts "
                    "ON tender_search_index USING GIN (to_tsvector('english', coalesce(search_text, '')))"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_tender_search_index_trgm "
                    "ON tender_search_index USING GIN (search_text gin_trgm_ops)"
                )
            )
        else:
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tenders_search_text ON tenders(search_text)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tender_search_index_tender_id ON tender_search_index(tender_id)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_tender_search_index_category ON tender_search_index(ai_category)"))
