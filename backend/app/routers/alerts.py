from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import AlertSubscription, User
from app.notifier import send_pending_matched_alerts, send_test_email
from app.schemas import AlertCreate, AlertOut, MessageOut

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/", response_model=list[AlertOut])
def list_alerts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(AlertSubscription).filter(AlertSubscription.user_id == user.id).order_by(AlertSubscription.created_at.desc()).all()


@router.post("/", response_model=AlertOut, status_code=201)
def create_alert(payload: AlertCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    subscription = AlertSubscription(
        user_id=user.id,
        categories=payload.categories,
        portals=payload.portals,
        email_enabled=payload.email_enabled,
    )
    db.add(subscription)
    db.commit()
    db.refresh(subscription)
    return subscription


@router.delete("/{subscription_id}", status_code=204)
def delete_alert(subscription_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    subscription = db.query(AlertSubscription).filter(
        AlertSubscription.id == subscription_id,
        AlertSubscription.user_id == user.id,
    ).first()
    if not subscription:
        raise HTTPException(status_code=404, detail="Alert subscription not found")
    db.delete(subscription)
    db.commit()


@router.post("/test", response_model=MessageOut)
def test_email(user: User = Depends(get_current_user)):
    sent, message = send_test_email(user)
    return {"message": message}


@router.post("/send-pending", response_model=MessageOut)
def send_pending_alerts(user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    result = send_pending_matched_alerts()
    return {
        "message": (
            f"Matched alert check complete: {result['attempted']} tender(s) attempted, "
            f"{result['notified_tenders']} tender(s) marked emailed, {result['delivered_messages']} email message(s) accepted."
        )
    }


@router.get("/email-config")
def get_email_config(user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    from app.config import settings
    cfg = settings()
    pwd = cfg.get("gmail_app_password", "")
    masked_pwd = pwd[:2] + "*" * (len(pwd) - 2) if len(pwd) > 2 else "*" * len(pwd)
    return {
        "gmail_user": cfg.get("gmail_user", ""),
        "gmail_app_password": masked_pwd,
        "smtp_host": cfg.get("smtp_host", ""),
        "smtp_port": cfg.get("smtp_port", 465),
        "alert_from_email": cfg.get("alert_from_email", ""),
        "alert_to_emails": cfg.get("alert_to_emails", ""),
    }


@router.post("/email-config")
def update_email_config(payload: dict, user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    updates = {}
    if "gmail_user" in payload:
        updates["GMAIL_USER"] = payload["gmail_user"]
    if "gmail_app_password" in payload:
        pwd = payload["gmail_app_password"]
        if pwd and "*" not in pwd:
            updates["GMAIL_APP_PASSWORD"] = pwd
    if "smtp_host" in payload:
        updates["SMTP_HOST"] = payload["smtp_host"]
    if "smtp_port" in payload:
        updates["SMTP_PORT"] = str(payload["smtp_port"])
    if "alert_from_email" in payload:
        updates["ALERT_FROM_EMAIL"] = payload["alert_from_email"]
    if "alert_to_emails" in payload:
        updates["ALERT_TO_EMAILS"] = payload["alert_to_emails"]

    if updates:
        from pathlib import Path
        env_path = Path.cwd() / ".env"
        if not env_path.exists():
            env_path = Path.cwd().parent / ".env"
        if not env_path.exists():
            env_path = Path.cwd() / ".env"

        lines = []
        if env_path.exists():
            lines = env_path.read_text(encoding="utf-8").splitlines()

        updated_keys = set()
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, v = stripped.split("=", 1)
                k = k.strip().lstrip("\ufeff")
                if k in updates:
                    new_lines.append(f"{k}={updates[k]}")
                    updated_keys.add(k)
                    continue
            new_lines.append(line)

        for k, v in updates.items():
            if k not in updated_keys:
                new_lines.append(f"{k}={v}")

        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

        from app.config import reload_settings
        reload_settings()

    return {"message": "Email settings updated successfully"}


@router.post("/digest", response_model=MessageOut)
def trigger_daily_digest(user: User = Depends(get_current_user)):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    from app.notifier import send_daily_digest_email
    sent = send_daily_digest_email()
    return {"message": f"Daily digest email successfully sent to {sent} user(s)"}
