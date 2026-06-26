from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Tender, TenderBackup


BACKUP_SCHEMA_VERSION = 1
VALID_BACKUP_TYPES = {"matched", "all"}


def _backup_root() -> Path:
    configured = Path(settings()["backup_dir"]).expanduser()
    root = configured if configured.is_absolute() else Path.cwd() / configured
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _date_or_none(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _datetime_or_now(value):
    if not value:
        return datetime.utcnow()
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def _is_matched(tender: Tender) -> bool:
    return bool(tender.matched_keywords or tender.categories)


def _query_tenders(db: Session, backup_type: str) -> list[Tender]:
    tenders = db.query(Tender).filter(Tender.is_active.is_(True)).order_by(Tender.scraped_at.desc()).all()
    if backup_type == "matched":
        return [tender for tender in tenders if _is_matched(tender)]
    return tenders


def _tender_to_dict(tender: Tender) -> dict:
    return {
        "tender_id": tender.tender_id,
        "title": tender.title,
        "description": tender.description,
        "portal": tender.portal,
        "state": tender.state,
        "tender_url": tender.tender_url,
        "open_url": tender.open_url,
        "published_date": tender.published_date,
        "opening_date": tender.opening_date,
        "closing_date": tender.closing_date,
        "estimated_value": tender.estimated_value,
        "categories": tender.categories or [],
        "matched_keywords": tender.matched_keywords or [],
        "raw_data": tender.raw_data or {},
        "scraped_at": tender.scraped_at,
        "is_active": tender.is_active,
    }


def _payload(db: Session, backup_type: str, reason: str, tenders: list[Tender]) -> dict:
    active_total = db.query(Tender).filter(Tender.is_active.is_(True)).count()
    active_matched = sum(1 for tender in db.query(Tender).filter(Tender.is_active.is_(True)).all() if _is_matched(tender))
    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "backup_type": backup_type,
        "reason": reason,
        "created_at": datetime.utcnow(),
        "active_tender_count": active_total,
        "active_matched_count": active_matched,
        "tender_count": len(tenders),
        "tenders": [_tender_to_dict(tender) for tender in tenders],
    }


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prune_old_backups(db: Session, backup_type: str) -> None:
    retention = settings()["backup_retention_count"]
    old_records = (
        db.query(TenderBackup)
        .filter(TenderBackup.backup_type == backup_type)
        .order_by(TenderBackup.created_at.desc())
        .offset(retention)
        .all()
    )
    for record in old_records:
        path = Path(record.storage_path)
        if path.exists():
            path.unlink()
        db.delete(record)
    if old_records:
        db.commit()


def create_tender_backup(db: Session, backup_type: str = "matched", reason: str = "manual") -> TenderBackup:
    backup_type = backup_type.lower().strip()
    if backup_type not in VALID_BACKUP_TYPES:
        raise ValueError("backup_type must be matched or all")

    tenders = _query_tenders(db, backup_type)
    created_at = datetime.utcnow()
    safe_reason = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in reason.lower())[:40].strip("-") or "manual"
    file_name = f"tender-{backup_type}-{created_at.strftime('%Y%m%d-%H%M%S')}-{safe_reason}.json"
    target = _backup_root() / file_name
    temp_target = target.with_suffix(".json.tmp")

    data = _payload(db, backup_type, reason, tenders)
    temp_target.write_text(json.dumps(data, indent=2, default=_json_default), encoding="utf-8")
    temp_target.replace(target)

    checksum = _checksum(target)
    matched_count = sum(1 for tender in tenders if _is_matched(tender))
    record = TenderBackup(
        file_name=file_name,
        backup_type=backup_type,
        reason=reason[:120],
        tender_count=len(tenders),
        matched_count=matched_count,
        size_bytes=target.stat().st_size,
        checksum_sha256=checksum,
        storage_path=str(target),
        created_at=created_at,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    _prune_old_backups(db, backup_type)
    return record


def latest_backup(db: Session) -> TenderBackup | None:
    return db.query(TenderBackup).order_by(TenderBackup.created_at.desc()).first()


def list_tender_backups(db: Session) -> list[TenderBackup]:
    return db.query(TenderBackup).order_by(TenderBackup.created_at.desc()).limit(100).all()


def backup_path(record: TenderBackup) -> Path:
    root = _backup_root()
    path = Path(record.storage_path).resolve()
    if root not in path.parents and path != root:
        raise ValueError("backup path is outside backup directory")
    if not path.exists():
        raise FileNotFoundError(record.file_name)
    return path


def restore_tender_backup(db: Session, backup_id: int, overwrite: bool = False) -> dict:
    record = db.get(TenderBackup, backup_id)
    if not record:
        raise FileNotFoundError(f"Backup {backup_id} was not found")

    path = backup_path(record)
    payload = json.loads(path.read_text(encoding="utf-8"))
    tenders = payload.get("tenders") or []
    restored = 0
    updated = 0
    skipped = 0
    restored_at = datetime.utcnow().isoformat()

    for item in tenders:
        tender_id = item.get("tender_id")
        if not tender_id:
            skipped += 1
            continue

        raw_data = dict(item.get("raw_data") or {})
        raw_data["backup_restored_at"] = restored_at
        raw_data["backup_file"] = record.file_name

        values = {
            "tender_id": tender_id,
            "title": item.get("title") or "Restored tender",
            "description": item.get("description"),
            "portal": item.get("portal") or "Restored",
            "state": item.get("state"),
            "tender_url": item.get("tender_url") or item.get("open_url"),
            "published_date": _date_or_none(item.get("published_date")),
            "closing_date": _date_or_none(item.get("closing_date")),
            "estimated_value": item.get("estimated_value"),
            "categories": item.get("categories") or [],
            "matched_keywords": item.get("matched_keywords") or [],
            "raw_data": raw_data,
            "scraped_at": _datetime_or_now(item.get("scraped_at")),
            "is_active": True,
        }

        existing = db.query(Tender).filter(Tender.tender_id == tender_id).first()
        if existing:
            if overwrite or not existing.is_active:
                for field, value in values.items():
                    setattr(existing, field, value)
                updated += 1
            else:
                skipped += 1
            continue

        db.add(Tender(**values))
        restored += 1

    db.commit()
    return {
        "backup_id": backup_id,
        "restored": restored,
        "updated": updated,
        "skipped": skipped,
        "total_in_backup": len(tenders),
    }
