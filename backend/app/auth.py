import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import urllib.request
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import AuditLog, User, UserSession

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return f"pbkdf2_sha256$200000${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, rounds, salt_b64, digest_b64 = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = _unb64(salt_b64)
        expected = _unb64(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def utcnow() -> datetime:
    return datetime.utcnow()


def _aware_utcnow() -> datetime:
    return datetime.now(timezone.utc)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_id() -> str:
    return secrets.token_urlsafe(32)


def create_access_token(subject: str, role: str, session_id: str | None = None, token_id: str | None = None) -> str:
    cfg = settings()
    now = _aware_utcnow()
    payload = {
        "sub": subject,
        "role": role,
        "sid": session_id,
        "jti": token_id or _new_id(),
        "typ": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=cfg["access_token_expire_minutes"])).timestamp()),
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}.{_b64(json.dumps(payload, separators=(',', ':')).encode())}"
    signature = hmac.new(cfg["secret_key"].encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}"


def create_refresh_token(subject: str, session_id: str, token_id: str, remember_me: bool = False) -> str:
    cfg = settings()
    now = _aware_utcnow()
    days = cfg["remember_me_expire_days"] if remember_me else cfg["refresh_token_expire_days"]
    payload = {
        "sub": subject,
        "sid": session_id,
        "jti": token_id,
        "typ": "refresh",
        "remember": remember_me,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=days)).timestamp()),
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}.{_b64(json.dumps(payload, separators=(',', ':')).encode())}"
    signature = hmac.new(cfg["secret_key"].encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}"


def decode_token(token: str) -> dict:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}"
        expected = hmac.new(settings()["secret_key"].encode(), signing_input.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64(expected), signature_b64):
            raise credentials_error
        payload = json.loads(_unb64(payload_b64))
        if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
            raise credentials_error
        return payload
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise credentials_error from exc


def token_payload(token: str) -> dict:
    return decode_token(token)


def _clean_forwarded_ip(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip().strip('"')
    if candidate.lower().startswith("for="):
        candidate = candidate.split("=", 1)[1].strip().strip('"')
    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1:].split("]", 1)[0]
    elif candidate.count(":") == 1 and candidate.rsplit(":", 1)[1].isdigit():
        candidate = candidate.rsplit(":", 1)[0]
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return None


def _client_ip(request: Request) -> str | None:
    candidates: list[str] = []
    for header in ("cf-connecting-ip", "x-real-ip", "x-client-ip", "x-forwarded-for"):
        raw = request.headers.get(header)
        if raw:
            candidates.extend(part.strip() for part in raw.split(","))
    forwarded = request.headers.get("forwarded")
    if forwarded:
        for segment in forwarded.split(","):
            for token in segment.split(";"):
                if token.strip().lower().startswith("for="):
                    candidates.append(token.strip())
    if request.client and request.client.host:
        candidates.append(request.client.host)

    valid = [ip for ip in (_clean_forwarded_ip(candidate) for candidate in candidates) if ip]
    for ip in valid:
        if ipaddress.ip_address(ip).is_global:
            return ip
    return valid[0] if valid else None


@lru_cache(maxsize=2048)
def _public_ip_location(ip_address: str) -> tuple[str | None, str | None]:
    try:
        request = urllib.request.Request(
            f"https://ipapi.co/{ip_address}/json/",
            headers={"User-Agent": "ApnaTender/2.0"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode("utf-8"))
        city = payload.get("city") or payload.get("region")
        country_parts = [payload.get("region"), payload.get("country_name")]
        country = ", ".join(part for part in country_parts if part)
        return city or "Public internet", country or payload.get("country_code")
    except Exception:
        return "Public internet", None


def _session_location(ip_address: str | None) -> tuple[str | None, str | None]:
    if not ip_address:
        return "Unknown location", None
    try:
        ip_obj = ipaddress.ip_address(ip_address)
    except ValueError:
        return "Unknown location", None
    if ip_obj.is_loopback:
        return "This device", "Localhost"
    if ip_obj.is_private or ip_obj.is_link_local:
        return "Local network", "Private IP"
    if not ip_obj.is_global:
        return "Network location", None
    return _public_ip_location(str(ip_obj))


def parse_user_agent(user_agent: str | None) -> tuple[str, str, str]:
    ua = user_agent or ""
    lowered = ua.lower()
    if "edg/" in lowered:
        browser = "Microsoft Edge"
    elif "chrome/" in lowered:
        browser = "Chrome"
    elif "firefox/" in lowered:
        browser = "Firefox"
    elif "safari/" in lowered:
        browser = "Safari"
    else:
        browser = "Unknown Browser"
    if "windows" in lowered:
        os_name = "Windows"
    elif "android" in lowered:
        os_name = "Android"
    elif "iphone" in lowered or "ipad" in lowered:
        os_name = "iOS"
    elif "mac os" in lowered or "macintosh" in lowered:
        os_name = "macOS"
    elif "linux" in lowered:
        os_name = "Linux"
    else:
        os_name = "Unknown OS"
    return f"{browser} on {os_name}", browser, os_name


def audit(db: Session, action: str, actor: str | None = None, entity_type: str | None = None, entity_id: str | None = None, metadata: dict | None = None) -> None:
    db.add(AuditLog(actor=actor, action=action, entity_type=entity_type, entity_id=entity_id, metadata_json=metadata or {}))


def cleanup_expired_sessions(db: Session) -> int:
    now = utcnow()
    expired = (
        db.query(UserSession)
        .filter(UserSession.is_active.is_(True))
        .filter((UserSession.session_expires_at < now) | (UserSession.refresh_expires_at < now))
        .all()
    )
    for session in expired:
        session.is_active = False
        session.revoked = True
        session.revoked_reason = "expired"
        session.logout_time = now
        session.updated_at = now
        audit(db, "session_expired", entity_type="session", entity_id=session.session_id)
    return len(expired)


def create_session_tokens(user: User, db: Session, request: Request | None = None, remember_me: bool = False) -> dict:
    cfg = settings()
    now = utcnow()
    session_id = _new_id()
    access_id = _new_id()
    refresh_id = _new_id()
    access_token = create_access_token(user.email, user.role, session_id, access_id)
    refresh_token = create_refresh_token(user.email, session_id, refresh_id, remember_me)
    device_name, browser, os_name = parse_user_agent(request.headers.get("user-agent") if request else None)
    refresh_days = cfg["remember_me_expire_days"] if remember_me else cfg["refresh_token_expire_days"]
    ip_address = _client_ip(request) if request else None
    city, country = _session_location(ip_address)
    session = UserSession(
        session_id=session_id,
        user_id=user.id,
        access_token_id=access_id,
        refresh_token_id=refresh_id,
        refresh_token_hash=token_hash(refresh_token),
        device_name=device_name,
        browser=browser,
        operating_system=os_name,
        ip_address=ip_address,
        country=country,
        city=city,
        login_time=now,
        last_activity_at=now,
        last_api_request=str(request.url.path) if request else None,
        session_expires_at=now + timedelta(minutes=cfg["session_inactivity_minutes"]),
        refresh_expires_at=now + timedelta(days=refresh_days),
        remember_me=remember_me,
        is_active=True,
    )
    db.add(session)
    audit(db, "session_created", actor=user.email, entity_type="session", entity_id=session_id, metadata={"remember_me": remember_me})
    return {"access_token": access_token, "refresh_token": refresh_token, "session": session}


def rotate_refresh_token(refresh_token: str, db: Session, request: Request | None = None) -> dict:
    payload = decode_token(refresh_token)
    if payload.get("typ") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    session = db.query(UserSession).filter(UserSession.session_id == payload.get("sid")).first()
    now = utcnow()
    if not session or not session.is_active or session.revoked or session.refresh_expires_at < now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
    if session.refresh_token_id != payload.get("jti") or not hmac.compare_digest(session.refresh_token_hash or "", token_hash(refresh_token)):
        session.is_active = False
        session.revoked = True
        session.revoked_reason = "refresh_token_reuse"
        session.logout_time = now
        session.updated_at = now
        audit(db, "refresh_token_reuse_detected", entity_type="session", entity_id=session.session_id)
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token reuse detected")
    user = db.query(User).filter(User.id == session.user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    access_id = _new_id()
    refresh_id = _new_id()
    new_access = create_access_token(user.email, user.role, session.session_id, access_id)
    new_refresh = create_refresh_token(user.email, session.session_id, refresh_id, session.remember_me)
    session.access_token_id = access_id
    session.refresh_token_id = refresh_id
    session.refresh_token_hash = token_hash(new_refresh)
    session.last_activity_at = now
    session.last_api_request = str(request.url.path) if request else session.last_api_request
    session.session_expires_at = now + timedelta(minutes=settings()["session_inactivity_minutes"])
    session.updated_at = now
    audit(db, "token_refreshed", actor=user.email, entity_type="session", entity_id=session.session_id)
    return {"access_token": new_access, "refresh_token": new_refresh, "user": user, "session": session}


def get_current_user(request: Request, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    payload = decode_token(token)
    if payload.get("typ") not in (None, "access"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
    user = db.query(User).filter(User.email == payload.get("sub")).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    session_id = payload.get("sid")
    if session_id:
        session = db.query(UserSession).filter(UserSession.session_id == session_id).first()
        now = utcnow()
        if not session or not session.is_active or session.revoked:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session revoked")
        if session.access_token_id != payload.get("jti"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session token rotated")
        if session.session_expires_at < now or session.refresh_expires_at < now:
            session.is_active = False
            session.revoked = True
            session.revoked_reason = "expired"
            session.logout_time = now
            session.updated_at = now
            audit(db, "session_expired", actor=user.email, entity_type="session", entity_id=session.session_id)
            db.commit()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session expired")
        should_touch = not session.last_activity_at or (now - session.last_activity_at).total_seconds() >= 30
        if should_touch:
            try:
                current_ip = _client_ip(request)
                if current_ip and (not session.ip_address or session.ip_address != current_ip and ipaddress.ip_address(current_ip).is_global):
                    session.ip_address = current_ip
                if not session.city or session.city.lower().startswith("unknown"):
                    session.city, session.country = _session_location(session.ip_address)
                session.last_activity_at = now
                session.last_api_request = str(request.url.path)
                session.session_expires_at = now + timedelta(minutes=settings()["session_inactivity_minutes"])
                session.updated_at = now
                db.commit()
            except SQLAlchemyError:
                db.rollback()
    return user
