from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.schemas import BackupOut, BackupRestoreOut
from app.services.backup import backup_path, create_tender_backup, list_tender_backups, restore_tender_backup
from app.models import TenderBackup

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/", response_model=list[BackupOut])
def backups(db: Session = Depends(get_db)):
    return list_tender_backups(db)


@router.post("/create", response_model=BackupOut)
def create_backup(backup_type: str = "matched", reason: str = "manual", db: Session = Depends(get_db)):
    try:
        return create_tender_backup(db, backup_type=backup_type, reason=reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{backup_id}/restore", response_model=BackupRestoreOut)
def restore_backup(backup_id: int, overwrite: bool = False, db: Session = Depends(get_db)):
    try:
        return restore_tender_backup(db, backup_id=backup_id, overwrite=overwrite)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{backup_id}/download")
def download_backup(backup_id: int, db: Session = Depends(get_db)):
    record = db.get(TenderBackup, backup_id)
    if not record:
        raise HTTPException(status_code=404, detail="Backup not found")
    try:
        path = backup_path(record)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(path, media_type="application/json", filename=record.file_name)
