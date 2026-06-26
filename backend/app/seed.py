from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.auth import hash_password
from app.config import KEYWORDS, settings
from app.keywords import category_for_keyword, match_keywords
from app.models import AlertSubscription, Keyword, Tender, User


SAMPLE_TENDERS = [
    {
        "tender_id": "demo-gem-thermal-ptz",
        "title": "Supply of long range PTZ thermal camera and EO payload for border surveillance",
        "description": "Integrated thermal camera, optical camera and pan tilt zoom surveillance equipment.",
        "portal": "GeM",
        "state": "National",
        "tender_url": "https://gem.gov.in/bidding/bids",
        "estimated_value": 18500000,
    },
    {
        "tender_id": "demo-cppp-nvd",
        "title": "Procurement of Night Vision Device NVD and image intensifier units",
        "description": "Night vision goggles, handheld thermal imager and related tactical equipment.",
        "portal": "CPPP",
        "state": "National",
        "tender_url": "https://eprocure.gov.in/eprocure/app",
        "estimated_value": 9200000,
    },
    {
        "tender_id": "demo-maha-counter-uav",
        "title": "Anti-Drone and counter UAV detection system for police command center",
        "description": "Drone detection, perimeter security and communication equipment for field units.",
        "portal": "MahaTenders",
        "state": "Maharashtra",
        "tender_url": "https://mahatenders.gov.in/nicgep/app",
        "estimated_value": 24600000,
    },
    {
        "tender_id": "demo-gujarat-protection",
        "title": "Ballistic helmet, bullet proof jacket and riot control equipment",
        "description": "Body armor and tactical equipment procurement for police modernization.",
        "portal": "nProcure",
        "state": "Gujarat",
        "tender_url": "https://nprocure.com",
        "estimated_value": 12600000,
    },
]


def seed_defaults(db: Session):
    cfg = settings()
    admin_email = cfg["admin_email"]
    admin_password = cfg["admin_password"]
    legacy_admin_emails = ("aiml123@gmail.com", "admin@example.in")
    admin = db.query(User).filter(User.email == admin_email).first()
    legacy_admins = db.query(User).filter(User.email.in_(legacy_admin_emails)).all()
    if admin:
        admin.password_hash = hash_password(admin_password)
        admin.role = "admin"
        for legacy_admin in legacy_admins:
            db.query(AlertSubscription).filter(AlertSubscription.user_id == legacy_admin.id).update({"user_id": admin.id})
            db.delete(legacy_admin)
    elif legacy_admins:
        admin = legacy_admins[0]
        admin.email = admin_email
        admin.password_hash = hash_password(admin_password)
        admin.role = "admin"
        for legacy_admin in legacy_admins[1:]:
            db.query(AlertSubscription).filter(AlertSubscription.user_id == legacy_admin.id).update({"user_id": admin.id})
            db.delete(legacy_admin)
    else:
        db.add(User(email=admin_email, password_hash=hash_password(admin_password), role="admin"))
        db.flush()
        admin = db.query(User).filter(User.email == admin_email).first()

    if admin:
        seen_alert_rules = set()
        for subscription in db.query(AlertSubscription).filter(AlertSubscription.user_id == admin.id).order_by(AlertSubscription.id).all():
            signature = (
                tuple(subscription.categories or []),
                tuple(subscription.portals or []),
                subscription.email_enabled,
            )
            if signature in seen_alert_rules:
                db.delete(subscription)
            else:
                seen_alert_rules.add(signature)

    if db.query(Keyword).count() == 0:
        for keyword in KEYWORDS:
            db.add(Keyword(keyword=keyword, category=category_for_keyword(keyword), is_active=True))
    else:
        existing = {row.keyword: row for row in db.query(Keyword).all()}
        for keyword in KEYWORDS:
            category = category_for_keyword(keyword)
            row = existing.get(keyword)
            if row:
                if row.category != category:
                    row.category = category
                row.is_active = True
            else:
                db.add(Keyword(keyword=keyword, category=category, is_active=True))

    if settings()["seed_demo_data"] and db.query(Tender).count() == 0:
        today = date.today()
        for idx, tender in enumerate(SAMPLE_TENDERS):
            matched, categories = match_keywords(f"{tender['title']} {tender['description']}")
            db.add(
                Tender(
                    **tender,
                    published_date=today - timedelta(days=idx + 1),
                    closing_date=today + timedelta(days=12 + idx * 5),
                    categories=categories,
                    matched_keywords=matched,
                    raw_data={"source": "seed"},
                )
            )
    db.commit()
