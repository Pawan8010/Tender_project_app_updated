from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth import get_current_user, token_payload
from app.database import get_db
from app.models import User, UserSession
from app.schemas import SessionInfoOut, UserOut, UserUpdate

router = APIRouter(dependencies=[Depends(get_current_user)])
token_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=UserOut)
def update_me(payload: UserUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    for field in ("full_name", "phone", "preferred_language"):
        value = getattr(payload, field)
        if value is not None:
            setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user


@router.get("/me/session-info", response_model=SessionInfoOut)
def session_info(token: str = Depends(token_scheme), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    payload = token_payload(token)
    issued_at = datetime.fromtimestamp(int(payload["iat"]), timezone.utc)
    expires_at = datetime.fromtimestamp(int(payload["exp"]), timezone.utc)
    session = None
    if payload.get("sid"):
        session = db.query(UserSession).filter(UserSession.session_id == payload.get("sid"), UserSession.user_id == user.id).first()
        if session:
            expires_at = session.session_expires_at.replace(tzinfo=timezone.utc)
    remaining = max(0, int((expires_at - datetime.now(timezone.utc)).total_seconds()))
    return {
        "email": user.email,
        "role": user.role,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "remaining_seconds": remaining,
        "last_login_at": user.last_login_at,
    }
