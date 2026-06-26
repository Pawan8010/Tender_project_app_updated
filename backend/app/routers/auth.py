from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth import (
    audit,
    create_session_tokens,
    decode_token,
    get_current_user,
    hash_password,
    rotate_refresh_token,
    token_payload,
    utcnow,
    verify_password,
)
from app.database import get_db
from app.models import User, UserSession
from app.schemas import LoginRequest, LogoutRequest, PasswordChange, RefreshRequest, SignupRequest, Token, UserOut, UserSessionOut

router = APIRouter()
token_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def _session_response(session: UserSession, current_session_id: str | None = None) -> dict:
    return {
        "id": session.id,
        "session_id": session.session_id,
        "user_id": session.user_id,
        "device_name": session.device_name,
        "browser": session.browser,
        "operating_system": session.operating_system,
        "ip_address": session.ip_address,
        "country": session.country,
        "city": session.city,
        "login_time": session.login_time,
        "last_activity_at": session.last_activity_at,
        "last_api_request": session.last_api_request,
        "session_expires_at": session.session_expires_at,
        "refresh_expires_at": session.refresh_expires_at,
        "remember_me": session.remember_me,
        "is_active": session.is_active,
        "logout_time": session.logout_time,
        "revoked": session.revoked,
        "revoked_reason": session.revoked_reason,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "current": session.session_id == current_session_id,
    }


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    email = payload.email.lower()
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(payload.password, user.password_hash):
        audit(db, "failed_login", actor=email, metadata={"ip": request.client.host if request.client else None})
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    user.last_login_at = datetime.utcnow()
    tokens = create_session_tokens(user, db, request, payload.remember_me)
    db.commit()
    db.refresh(user)
    db.refresh(tokens["session"])
    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": "bearer",
        "session_id": tokens["session"].session_id,
        "user": user,
    }


@router.post("/signup", response_model=Token, status_code=status.HTTP_201_CREATED)
def signup(payload: SignupRequest, request: Request, db: Session = Depends(get_db)):
    email = payload.email.lower()
    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")

    user = User(email=email, password_hash=hash_password(payload.password), role="user")
    db.add(user)
    db.flush()
    tokens = create_session_tokens(user, db, request, remember_me=False)
    db.commit()
    db.refresh(user)
    db.refresh(tokens["session"])
    return {
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "token_type": "bearer",
        "session_id": tokens["session"].session_id,
        "user": user,
    }


@router.post("/refresh", response_model=Token)
def refresh(payload: RefreshRequest, request: Request, db: Session = Depends(get_db)):
    result = rotate_refresh_token(payload.refresh_token, db, request)
    db.commit()
    return {
        "access_token": result["access_token"],
        "refresh_token": result["refresh_token"],
        "token_type": "bearer",
        "session_id": result["session"].session_id,
        "user": result["user"],
    }


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


@router.get("/session", response_model=UserSessionOut)
def current_session(token: str = Depends(token_scheme), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    payload = token_payload(token)
    session = db.query(UserSession).filter(UserSession.session_id == payload.get("sid"), UserSession.user_id == user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return _session_response(session, payload.get("sid"))


@router.get("/sessions", response_model=list[UserSessionOut])
def sessions(token: str = Depends(token_scheme), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    payload = token_payload(token)
    rows = db.query(UserSession).filter(UserSession.user_id == user.id).order_by(UserSession.last_activity_at.desc()).all()
    return [_session_response(row, payload.get("sid")) for row in rows]


@router.get("/admin/sessions", response_model=list[UserSessionOut])
def admin_sessions(status_filter: str | None = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    query = db.query(UserSession).order_by(UserSession.last_activity_at.desc())
    if status_filter == "active":
        query = query.filter(UserSession.is_active.is_(True), UserSession.revoked.is_(False))
    elif status_filter == "revoked":
        query = query.filter(UserSession.revoked.is_(True))
    elif status_filter == "expired":
        query = query.filter(UserSession.refresh_expires_at < utcnow())
    return [_session_response(row) for row in query.limit(500).all()]


@router.post("/logout")
def logout(payload: LogoutRequest | None = None, token: str = Depends(token_scheme), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    token_data = decode_token(token)
    session = db.query(UserSession).filter(UserSession.session_id == token_data.get("sid"), UserSession.user_id == user.id).first()
    if session:
        now = utcnow()
        session.is_active = False
        session.revoked = True
        session.revoked_reason = "logout"
        session.logout_time = now
        session.updated_at = now
        audit(db, "logout", actor=user.email, entity_type="session", entity_id=session.session_id)
        db.commit()
    return {"message": "Logged out"}


@router.post("/logout-all")
def logout_all(token: str = Depends(token_scheme), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    token_data = token_payload(token)
    now = utcnow()
    sessions = db.query(UserSession).filter(UserSession.user_id == user.id, UserSession.is_active.is_(True)).all()
    for session in sessions:
        session.is_active = False
        session.revoked = True
        session.revoked_reason = "logout_all"
        session.logout_time = now
        session.updated_at = now
    audit(db, "logout_all", actor=user.email, entity_type="user", entity_id=str(user.id), metadata={"current_session": token_data.get("sid"), "count": len(sessions)})
    db.commit()
    return {"message": "Logged out from all devices", "revoked": len(sessions)}


@router.delete("/session/{session_id}")
def revoke_session(session_id: str, token: str = Depends(token_scheme), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current = token_payload(token).get("sid")
    session = db.query(UserSession).filter(UserSession.session_id == session_id, UserSession.user_id == user.id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    now = utcnow()
    session.is_active = False
    session.revoked = True
    session.revoked_reason = "revoked_by_user"
    session.logout_time = now
    session.updated_at = now
    audit(db, "session_revoked", actor=user.email, entity_type="session", entity_id=session.session_id)
    db.commit()
    return {"message": "Session revoked", "current": session_id == current}


@router.post("/change-password")
def change_password(payload: PasswordChange, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"message": "Password changed successfully"}
