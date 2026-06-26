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
    sent, recipient = send_test_email(user)
    if not sent:
        return {"message": "SMTP/Gmail is not configured or rejected the sender. Check GMAIL_USER, GMAIL_APP_PASSWORD, ALERT_FROM_EMAIL, and SMTP settings in backend/.env."}
    return {"message": f"Test email sent to {recipient}"}


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
