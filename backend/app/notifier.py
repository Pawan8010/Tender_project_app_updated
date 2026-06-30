import re
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings
from app.database import SessionLocal
from app.models import AlertSubscription, Tender, User, _is_session_bound_url, _remove_session_query


_IMMEDIATE_ALERT_WINDOW = {
    "started_at": datetime.utcnow(),
    "sent": 0,
}


def _immediate_alert_quota() -> int:
    cfg = settings()
    if not cfg["alert_immediate_enabled"]:
        return 0
    max_per_hour = cfg["alert_max_immediate_emails_per_hour"]
    if max_per_hour <= 0:
        return 0
    now = datetime.utcnow()
    if (now - _IMMEDIATE_ALERT_WINDOW["started_at"]).total_seconds() >= 3600:
        _IMMEDIATE_ALERT_WINDOW["started_at"] = now
        _IMMEDIATE_ALERT_WINDOW["sent"] = 0
    return max(0, max_per_hour - int(_IMMEDIATE_ALERT_WINDOW["sent"]))


def send_alert_email_limited(tender: dict, recipients: list[str] | set[str] | None = None) -> tuple[int, list[str], list[str]]:
    recipient_list = sorted(set(alert_recipients_for_tender(tender) if recipients is None else recipients))
    quota = _immediate_alert_quota()
    if quota <= 0:
        return 0, recipient_list, []
    selected = recipient_list[:quota]
    deferred = recipient_list[quota:]
    sent_recipients = []
    html = build_tender_email_html([tender], "New Matching Tender Found")
    for recipient in selected:
        if send_email(recipient, f"Matched Tender Alert: {tender['title'][:80]}", html):
            sent_recipients.append(recipient)
        else:
            deferred.append(recipient)
    _IMMEDIATE_ALERT_WINDOW["sent"] += len(sent_recipients)
    return len(sent_recipients), sorted(set(deferred)), sent_recipients


def _opening_date_for_email(tender: dict | Tender):
    if isinstance(tender, Tender):
        if tender.opening_date:
            return tender.opening_date.isoformat()
        raw_data = tender.raw_data or {}
        return raw_data.get("opening_date") or "N/A"
    raw_data = tender.get("raw_data") or {}
    return tender.get("opening_date") or raw_data.get("opening_date") or "N/A"


def _open_url_for_email(tender: dict | Tender):
    if isinstance(tender, Tender):
        return tender.open_url or tender.tender_url or "#"
    raw_data = tender.get("raw_data") or {}
    tender_url = tender.get("open_url") or tender.get("tender_url")
    stable_url = raw_data.get("stable_url") or raw_data.get("source_url")
    if _is_session_bound_url(tender_url):
        return _remove_session_query(stable_url) if stable_url else "#"
    return tender_url or stable_url or "#"


def build_tender_email_html(tenders: list[dict | Tender], heading: str = "Apna Tender Alert") -> str:
    rows = ""
    for tender in tenders[:20]:
        if isinstance(tender, Tender):
            title = tender.title
            portal = tender.portal
            state = tender.state or "National"
            categories = tender.categories or []
            opening_date = _opening_date_for_email(tender)
            closing_date = tender.closing_date
            url = _open_url_for_email(tender)
        else:
            title = tender.get("title", "")
            portal = tender.get("portal", "N/A")
            state = tender.get("state") or "National"
            categories = tender.get("categories", [])
            opening_date = _opening_date_for_email(tender)
            closing_date = tender.get("closing_date")
            url = _open_url_for_email(tender)

        rows += f"""
        <tr style="border-bottom:1px solid #e5e7eb;">
            <td style="padding:10px;font-size:13px;">{title[:140]}</td>
            <td style="padding:10px;font-size:13px;">{portal}</td>
            <td style="padding:10px;font-size:13px;">{state}</td>
            <td style="padding:10px;font-size:13px;color:#f97316;font-weight:bold;">{', '.join(categories) or 'Uncategorized'}</td>
            <td style="padding:10px;font-size:13px;">{opening_date or 'N/A'}</td>
            <td style="padding:10px;font-size:13px;">{closing_date or 'N/A'}</td>
            <td style="padding:10px;"><a href="{url}" style="color:#1e3a5f;text-decoration:none;">View</a></td>
        </tr>"""
    return f"""
    <html><body style="font-family:Arial,sans-serif;max-width:860px;margin:0 auto;">
    <div style="background:#1e3a5f;padding:20px;text-align:center;">
        <h1 style="color:white;margin:0;">{heading}</h1>
        <p style="color:#cbd5e1;margin:5px 0;">{len(tenders)} tender(s)</p>
    </div>
    <table style="width:100%;border-collapse:collapse;margin:20px 0;">
        <thead><tr style="background:#f8fafc;">
            <th style="padding:12px;text-align:left;">Title</th>
            <th style="padding:12px;text-align:left;">Portal</th>
            <th style="padding:12px;text-align:left;">State</th>
            <th style="padding:12px;text-align:left;">Categories</th>
            <th style="padding:12px;text-align:left;">Opening Date</th>
            <th style="padding:12px;text-align:left;">Closing Date</th>
            <th style="padding:12px;text-align:left;">Link</th>
        </tr></thead>
        <tbody>{rows}</tbody>
    </table>
    </body></html>"""


def send_email_verbose(to_email: str, subject: str, html_content: str) -> tuple[bool, str]:
    cfg = settings()
    smtp_user = cfg["gmail_user"]
    smtp_password = cfg["gmail_app_password"]
    from_email = cfg["alert_from_email"] or smtp_user
    login_password = _normalized_smtp_password(smtp_password, cfg["smtp_host"])
    config_error = _smtp_config_error(smtp_user, login_password, cfg["smtp_host"])
    if config_error:
        err = config_error
        print(err)
        return False, err

    plain_text = re.sub(r"<[^>]+>", " ", html_content)
    plain_text = " ".join(plain_text.split())
    try:
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = f"Apna Tender Alerts <{from_email}>"
        message["To"] = to_email
        message.attach(MIMEText(plain_text, "plain"))
        message.attach(MIMEText(html_content, "html"))
        context = ssl.create_default_context()
        port = int(cfg["smtp_port"])
        host = cfg["smtp_host"]
        if port == 587:
            with smtplib.SMTP(host, port, timeout=10) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(smtp_user, login_password)
                server.sendmail(from_email, [to_email], message.as_string())
        else:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=10) as server:
                server.login(smtp_user, login_password)
                server.sendmail(from_email, [to_email], message.as_string())
        msg = f"SMTP email sent: to={to_email} subject={subject[:60]}"
        print(msg)
        return True, msg
    except smtplib.SMTPAuthenticationError as exc:
        err = _smtp_auth_message(exc)
        print(err)
        return False, err
    except Exception as exc:
        err = f"SMTP connection or delivery failed: {exc}"
        print(err)
        return False, err


def send_email(to_email: str, subject: str, html_content: str) -> bool:
    success, _ = send_email_verbose(to_email, subject, html_content)
    return success


def _normalized_smtp_password(password: str, host: str) -> str:
    return "".join((password or "").split()) if "gmail" in (host or "").lower() else (password or "")


def _smtp_config_error(smtp_user: str, login_password: str, host: str) -> str | None:
    if not smtp_user or not login_password:
        return "SMTP credentials missing. Please set GMAIL_USER and GMAIL_APP_PASSWORD in SMTP configuration."
    if "gmail" in (host or "").lower() and len(login_password) != 16:
        return (
            "Gmail App Password is not valid length after spaces are removed. "
            "Generate a 16-character Gmail App Password and save it again."
        )
    return None


def _smtp_auth_message(exc: smtplib.SMTPAuthenticationError) -> str:
    detail = exc.smtp_error.decode("utf-8", "ignore") if isinstance(exc.smtp_error, bytes) else str(exc.smtp_error)
    detail = " ".join(detail.split())
    if "BadCredentials" in detail or "Username and Password not accepted" in detail:
        return (
            "SMTP authentication failed: Gmail rejected the username/app password. "
            "Confirm 2-Step Verification is enabled and use a fresh Gmail App Password."
        )
    return f"SMTP authentication failed: {detail[:180]}"


def send_email_many_verbose(to_emails: list[str], subject: str, html_content: str) -> tuple[bool, str, int]:
    cfg = settings()
    smtp_user = cfg["gmail_user"]
    smtp_password = cfg["gmail_app_password"]
    from_email = cfg["alert_from_email"] or smtp_user
    recipients = list(dict.fromkeys(email.strip() for email in to_emails if email and email.strip()))
    if not recipients:
        return False, "No email recipients configured.", 0

    port = int(cfg["smtp_port"])
    host = cfg["smtp_host"]
    login_password = _normalized_smtp_password(smtp_password, host)
    config_error = _smtp_config_error(smtp_user, login_password, host)
    if config_error:
        print(config_error)
        return False, config_error, 0

    plain_text = re.sub(r"<[^>]+>", " ", html_content)
    plain_text = " ".join(plain_text.split())
    try:
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = f"Apna Tender Alerts <{from_email}>"
        message["To"] = from_email
        message.attach(MIMEText(plain_text, "plain"))
        message.attach(MIMEText(html_content, "html"))
        context = ssl.create_default_context()
        if port == 587:
            with smtplib.SMTP(host, port, timeout=10) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(smtp_user, login_password)
                server.sendmail(from_email, recipients, message.as_string())
        else:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=10) as server:
                server.login(smtp_user, login_password)
                server.sendmail(from_email, recipients, message.as_string())
        msg = f"SMTP email sent to {len(recipients)} recipient(s)."
        print(msg)
        return True, msg, len(recipients)
    except smtplib.SMTPAuthenticationError as exc:
        err = _smtp_auth_message(exc)
        print(err)
        return False, err, 0
    except Exception as exc:
        err = f"SMTP connection or delivery failed: {exc}"
        print(err)
        return False, err, 0


def configured_alert_recipients() -> list[str]:
    cfg = settings()
    raw = cfg["alert_to_emails"] or cfg["alert_test_to_email"]
    recipients = [email.strip() for email in raw.replace(";", ",").split(",") if email.strip()]
    return list(dict.fromkeys(recipients))


def alert_recipients_for_tender(tender: dict, db=None) -> list[str]:
    recipients = set(configured_alert_recipients())
    owns_session = db is None
    db = db or SessionLocal()
    try:
        subscriptions = db.query(AlertSubscription).filter(AlertSubscription.email_enabled.is_(True)).all()
        for subscription in subscriptions:
            if subscription.categories and not any(c in tender.get("categories", []) for c in subscription.categories):
                continue
            if subscription.portals and tender.get("portal") not in subscription.portals:
                continue
            user = db.query(User).filter(User.id == subscription.user_id).first()
            if not user:
                continue
            recipients.add(user.email)
    finally:
        if owns_session:
            db.close()
    return sorted(recipients)


def send_alert_email(tender: dict, recipients: list[str] | set[str] | None = None) -> int:
    sent = 0
    html = build_tender_email_html([tender], "New Matching Tender Found")
    recipient_list = sorted(set(alert_recipients_for_tender(tender) if recipients is None else recipients))
    for recipient in recipient_list:
        if send_email(recipient, f"Matched Tender Alert: {tender['title'][:80]}", html):
            sent += 1
    return sent


def _tender_payload(tender: Tender) -> dict:
    return {
        "title": tender.title,
        "portal": tender.portal,
        "state": tender.state,
        "categories": tender.categories or [],
        "matched_keywords": tender.matched_keywords or [],
        "raw_data": tender.raw_data or {},
        "published_date": tender.published_date.isoformat() if tender.published_date else None,
        "opening_date": tender.opening_date.isoformat() if tender.opening_date else None,
        "closing_date": tender.closing_date.isoformat() if tender.closing_date else None,
        "tender_url": tender.tender_url,
        "open_url": tender.open_url,
    }


def send_pending_matched_alerts(limit: int = 50) -> dict:
    db = SessionLocal()
    attempted = 0
    notified_tenders = 0
    delivered_messages = 0
    try:
        tenders = db.query(Tender).filter(Tender.is_active.is_(True)).order_by(Tender.scraped_at.desc()).all()
        for tender in tenders:
            if attempted >= limit:
                break
            raw_data = dict(tender.raw_data or {})
            try:
                match_score = int(raw_data.get("match_score") or 0)
            except (TypeError, ValueError):
                match_score = 0
            if not ((tender.matched_keywords or []) or (tender.categories or []) or match_score > 0):
                continue

            payload = _tender_payload(tender)
            recipients = set(alert_recipients_for_tender(payload))
            alerted_recipients = set(raw_data.get("alerted_recipients") or [])
            pending_recipients = recipients - alerted_recipients
            if recipients and not pending_recipients:
                continue

            attempted += 1
            sent = send_alert_email(payload, pending_recipients)
            raw_data["alert_attempted_at"] = datetime.utcnow().isoformat()
            if sent:
                raw_data["alerted_recipients"] = sorted(alerted_recipients | pending_recipients)
                raw_data["alerted_at"] = raw_data["alert_attempted_at"]
                notified_tenders += 1
                delivered_messages += sent
            tender.raw_data = raw_data
        db.commit()
    finally:
        db.close()
    return {"attempted": attempted, "notified_tenders": notified_tenders, "delivered_messages": delivered_messages}


def send_test_email(user: User) -> tuple[bool, str]:
    raw_recipients = settings()["alert_test_to_email"] or ",".join(configured_alert_recipients()) or user.email
    recipients = [
        email.strip()
        for email in raw_recipients.replace(";", ",").split(",")
        if email.strip()
    ]
    recipients = list(dict.fromkeys(recipients or [user.email]))
    sample = {
        "title": "Test tender alert from Apna Tender",
        "portal": "System",
        "state": "Test",
        "categories": ["Thermal"],
        "raw_data": {"opening_date": "N/A"},
        "closing_date": "N/A",
        "tender_url": "#",
    }
    html = build_tender_email_html([sample], "Apna Tender Test Email")

    success, msg, sent_count = send_email_many_verbose(recipients, "Apna Tender test email", html)
    if success and sent_count == len(recipients):
        return True, f"Test email sent successfully to {', '.join(recipients)}"
    return False, f"Failed to send test email. {msg}"


def send_daily_digest_email() -> int:
    db = SessionLocal()
    sent = 0
    try:
        tenders = (
            db.query(Tender)
            .filter(Tender.is_active.is_(True))
            .order_by(Tender.scraped_at.desc())
            .limit(50)
            .all()
        )
        matched = [t for t in tenders if (t.categories or []) or (t.matched_keywords or [])]
        if not matched:
            return 0
        users = db.query(User).filter(User.role.in_(["admin", "user"])).all()
        html = build_tender_email_html(matched, "Daily Tender Digest")
        for user in users:
            if send_email(user.email, f"Daily Tender Digest - {len(matched)} matches", html):
                sent += 1
    finally:
        db.close()
    return sent
