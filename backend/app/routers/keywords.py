from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Keyword, User
from app.schemas import KeywordCreate, KeywordOut, KeywordUpdate

router = APIRouter(dependencies=[Depends(get_current_user)])


def _require_admin(user: User):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")


@router.get("/", response_model=list[KeywordOut])
def list_keywords(db: Session = Depends(get_db)):
    return db.query(Keyword).order_by(Keyword.category, Keyword.keyword).all()


@router.get("/categories", response_model=list[str])
def categories(db: Session = Depends(get_db)):
    rows = db.query(Keyword.category).filter(Keyword.is_active.is_(True), Keyword.category.is_not(None)).distinct().all()
    return sorted(row[0] for row in rows if row[0])


@router.post("/", response_model=KeywordOut, status_code=201)
def create_keyword(payload: KeywordCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_admin(user)
    existing = db.query(Keyword).filter(Keyword.keyword == payload.keyword).first()
    if existing:
        raise HTTPException(status_code=409, detail="Keyword already exists")
    keyword = Keyword(keyword=payload.keyword.strip(), category=payload.category, is_active=payload.is_active)
    db.add(keyword)
    db.commit()
    db.refresh(keyword)
    return keyword


@router.patch("/{keyword_id}", response_model=KeywordOut)
def update_keyword(keyword_id: int, payload: KeywordUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_admin(user)
    keyword = db.query(Keyword).filter(Keyword.id == keyword_id).first()
    if not keyword:
        raise HTTPException(status_code=404, detail="Keyword not found")
    if payload.keyword is not None:
        keyword.keyword = payload.keyword.strip()
    if payload.category is not None:
        keyword.category = payload.category
    if payload.is_active is not None:
        keyword.is_active = payload.is_active
    db.commit()
    db.refresh(keyword)
    return keyword


@router.delete("/{keyword_id}", status_code=204)
def delete_keyword(keyword_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require_admin(user)
    keyword = db.query(Keyword).filter(Keyword.id == keyword_id).first()
    if not keyword:
        raise HTTPException(status_code=404, detail="Keyword not found")
    db.delete(keyword)
    db.commit()
