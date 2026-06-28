from datetime import date, datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


SESSION_BOUND_QUERY_KEYS = {"session", "sp", "jsessionid"}


def _remove_session_query(url: str) -> str:
    parsed = urlparse(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in SESSION_BOUND_QUERY_KEYS
    ]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _is_session_bound_url(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    query_keys = {key.lower() for key, _value in parse_qsl(parsed.query, keep_blank_values=True)}
    lowered = url.lower()
    return "nicgep/app" in lowered and (bool(query_keys & SESSION_BOUND_QUERY_KEYS) or "directlink" in lowered)


class Tender(Base):
    __tablename__ = "tenders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tender_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    bid_number: Mapped[str | None] = mapped_column(String(255), index=True)
    reference_number: Mapped[str | None] = mapped_column(String(255), index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    portal: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    state: Mapped[str | None] = mapped_column(String(100), index=True)
    district: Mapped[str | None] = mapped_column(String(100), index=True)
    department: Mapped[str | None] = mapped_column(String(255), index=True)
    buyer: Mapped[str | None] = mapped_column(String(255), index=True)
    organization: Mapped[str | None] = mapped_column(String(255), index=True)
    location: Mapped[str | None] = mapped_column(String(255))
    tender_url: Mapped[str | None] = mapped_column(Text)
    published_date: Mapped[date | None] = mapped_column(Date)
    closing_date: Mapped[date | None] = mapped_column(Date)
    estimated_value: Mapped[float | None] = mapped_column(Float)
    currency: Mapped[str | None] = mapped_column(String(12), default="INR")
    tender_status: Mapped[str] = mapped_column(String(60), default="ACTIVE", index=True)
    classification_status: Mapped[str] = mapped_column(String(60), default="PENDING_CLASSIFICATION", index=True)
    ai_category: Mapped[str | None] = mapped_column(String(100), index=True)
    
    # New fields
    tender_category: Mapped[str | None] = mapped_column(String(100), index=True)
    tender_type: Mapped[str | None] = mapped_column(String(100), index=True)
    procurement_type: Mapped[str | None] = mapped_column(String(100), index=True)
    emd: Mapped[float | None] = mapped_column(Float)
    tender_fee: Mapped[float | None] = mapped_column(Float)
    publishing_authority: Mapped[str | None] = mapped_column(String(255))
    city: Mapped[str | None] = mapped_column(String(100))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    bid_start_date: Mapped[date | None] = mapped_column(Date)
    pre_bid_date: Mapped[date | None] = mapped_column(Date)
    corrigendum: Mapped[bool] = mapped_column(Boolean, default=False)
    contact_person: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(100))
    website: Mapped[str | None] = mapped_column(Text)

    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    search_text: Mapped[str | None] = mapped_column(Text)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    matched_keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    raw_data: Mapped[dict] = mapped_column(JSON, default=dict)
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    documents: Mapped[list["TenderDocument"]] = relationship(back_populates="tender", cascade="all, delete-orphan")
    history: Mapped[list["TenderHistory"]] = relationship(back_populates="tender", cascade="all, delete-orphan")
    matches: Mapped[list["TenderMatch"]] = relationship(back_populates="tender", cascade="all, delete-orphan")
    change_events: Mapped[list["TenderChangeEvent"]] = relationship(back_populates="tender", cascade="all, delete-orphan")

    @property
    def opening_date(self) -> date | None:
        raw_opening_date = (self.raw_data or {}).get("opening_date")
        if not raw_opening_date:
            return None
        if isinstance(raw_opening_date, date):
            return raw_opening_date
        try:
            return date.fromisoformat(str(raw_opening_date)[:10])
        except ValueError:
            return None

    @property
    def open_url(self) -> str | None:
        raw_data = self.raw_data or {}
        stable_url = raw_data.get("stable_url") or raw_data.get("source_url")
        if _is_session_bound_url(self.tender_url):
            return _remove_session_query(stable_url) if stable_url else None
        return self.tender_url or stable_url


class Keyword(Base):
    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ProcurementPortal(Base):
    __tablename__ = "portals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    portal_type: Mapped[str] = mapped_column(String(60), default="State", index=True)
    state: Mapped[str | None] = mapped_column(String(100), index=True)
    authentication: Mapped[str] = mapped_column(String(80), default="public")
    scraper_type: Mapped[str] = mapped_column(String(80), default="http")
    scheduler: Mapped[str] = mapped_column(String(80), default="interval")
    retry_count: Mapped[int] = mapped_column(Integer, default=2)
    health_status: Mapped[str] = mapped_column(String(60), default="unknown", index=True)
    proxy_configuration: Mapped[dict] = mapped_column(JSON, default=dict)
    captcha_strategy: Mapped[str] = mapped_column(String(80), default="detect_and_retry")
    last_successful_run: Mapped[datetime | None] = mapped_column(DateTime)
    next_run: Mapped[datetime | None] = mapped_column(DateTime)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    listing_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PortalRun(Base):
    __tablename__ = "portal_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portal: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(60), index=True, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    fetched_count: Mapped[int] = mapped_column(Integer, default=0)
    stored_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    average_response_time_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    logs: Mapped[list[dict]] = mapped_column(JSON, default=list)


class TenderDocument(Base):
    __tablename__ = "tender_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255))
    document_type: Mapped[str] = mapped_column(String(60), default="attachment", index=True)
    storage_path: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(60), default="queued", index=True)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    ocr_text: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)

    tender: Mapped[Tender] = relationship(back_populates="documents")


class TenderHistory(Base):
    __tablename__ = "tender_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id"), nullable=False, index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    change_type: Mapped[str] = mapped_column(String(60), default="updated", index=True)
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    new_hash: Mapped[str | None] = mapped_column(String(64))
    changed_fields: Mapped[dict] = mapped_column(JSON, default=dict)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)

    tender: Mapped[Tender] = relationship(back_populates="history")


class TenderMatch(Base):
    __tablename__ = "tender_matches"
    __table_args__ = (UniqueConstraint("tender_id", "matched_keyword", "category", name="uq_tender_match_keyword_category"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("tenders.id"), nullable=False, index=True)
    matched_keyword: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    reason: Mapped[str | None] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, default=0)
    matching_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    processing_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    tender: Mapped[Tender] = relationship(back_populates="matches")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str | None] = mapped_column(String(255), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(120), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(120), index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SystemLog(Base):
    __tablename__ = "system_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(120), index=True)
    level: Mapped[str] = mapped_column(String(40), default="info", index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="user")
    full_name: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(20))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    preferred_language: Mapped[str] = mapped_column(String(10), default="en")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    subscriptions: Mapped[list["AlertSubscription"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sessions: Mapped[list["UserSession"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    access_token_id: Mapped[str | None] = mapped_column(String(64), index=True)
    refresh_token_id: Mapped[str | None] = mapped_column(String(64), index=True)
    refresh_token_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    device_name: Mapped[str | None] = mapped_column(String(255))
    browser: Mapped[str | None] = mapped_column(String(120), index=True)
    operating_system: Mapped[str | None] = mapped_column(String(120), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), index=True)
    country: Mapped[str | None] = mapped_column(String(120), index=True)
    city: Mapped[str | None] = mapped_column(String(120), index=True)
    login_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    last_api_request: Mapped[str | None] = mapped_column(Text)
    session_expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    refresh_expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    remember_me: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    logout_time: Mapped[datetime | None] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    revoked_reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    user: Mapped[User] = relationship(back_populates="sessions")


class AlertSubscription(Base):
    __tablename__ = "alert_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    portals: Mapped[list[str]] = mapped_column(JSON, default=list)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user: Mapped[User] = relationship(back_populates="subscriptions")


class ScrapeLog(Base):
    __tablename__ = "scrape_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portal: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(50), index=True)
    tenders_found: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class SchedulerLog(Base):
    __tablename__ = "scheduler_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(50), index=True)  # RUNNING, DEDUPLICATING, MATCHING, COMPLETED, FAILED
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    total_portals: Mapped[int] = mapped_column(Integer, default=0)
    completed_portals: Mapped[int] = mapped_column(Integer, default=0)
    failed_portals: Mapped[int] = mapped_column(Integer, default=0)
    tenders_scraped: Mapped[int] = mapped_column(Integer, default=0)
    tenders_updated: Mapped[int] = mapped_column(Integer, default=0)
    matches_found: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)


class TenderBackup(Base):
    __tablename__ = "tender_backups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    backup_type: Mapped[str] = mapped_column(String(50), default="matched", index=True)
    reason: Mapped[str] = mapped_column(String(120), default="manual")
    tender_count: Mapped[int] = mapped_column(Integer, default=0)
    matched_count: Mapped[int] = mapped_column(Integer, default=0)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class WorkerStatus(Base):
    __tablename__ = "worker_statuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    worker_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    portal_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str | None] = mapped_column(String(32), default="idle")
    current_page: Mapped[int | None] = mapped_column(Integer, default=0)
    current_tender: Mapped[str | None] = mapped_column(String(500))
    tenders_scraped_session: Mapped[int | None] = mapped_column(Integer, default=0)
    new_tenders: Mapped[int | None] = mapped_column(Integer, default=0)
    updated_tenders: Mapped[int | None] = mapped_column(Integer, default=0)
    failed_tenders: Mapped[int | None] = mapped_column(Integer, default=0)
    retry_count: Mapped[int | None] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)


class TenderChangeEvent(Base):
    __tablename__ = "tender_change_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tender_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenders.id"), nullable=False)
    change_type: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_fields: Mapped[dict | None] = mapped_column(JSON)
    snapshot: Mapped[dict | None] = mapped_column(JSON)
    detected_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)
    
    tender: Mapped["Tender"] = relationship(back_populates="change_events")


class DocumentDownload(Base):
    __tablename__ = "document_downloads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tender_id: Mapped[int] = mapped_column(Integer, ForeignKey("tenders.id"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str | None] = mapped_column(String(255))
    file_type: Mapped[str | None] = mapped_column(String(20))
    file_size: Mapped[int | None] = mapped_column(Integer)
    checksum: Mapped[str | None] = mapped_column(String(64))
    storage_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(20), default="pending")
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)
    
    tender: Mapped["Tender"] = relationship()


class ScraperPerformance(Base):
    __tablename__ = "scraper_performance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portal_name: Mapped[str | None] = mapped_column(String(255))
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.utcnow)
    tenders_per_minute: Mapped[float | None] = mapped_column(Float)
    pages_scraped: Mapped[int | None] = mapped_column(Integer)
    avg_page_time_ms: Mapped[int | None] = mapped_column(Integer)
    errors: Mapped[int | None] = mapped_column(Integer, default=0)
    total_runtime_seconds: Mapped[int | None] = mapped_column(Integer)
