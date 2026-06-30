from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember_me: bool = False


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: str
    full_name: str | None = None
    phone: str | None = None
    last_login_at: datetime | None = None
    preferred_language: str = "en"


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=20)
    preferred_language: str | None = Field(default=None, max_length=10)


class SessionInfoOut(BaseModel):
    email: EmailStr
    role: str
    issued_at: datetime
    expires_at: datetime
    remaining_seconds: int
    last_login_at: datetime | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class Token(BaseModel):
    access_token: str
    refresh_token: str | None = None
    token_type: str = "bearer"
    session_id: str | None = None
    user: UserOut


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class UserSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: str
    user_id: int
    user_email: EmailStr | None = None
    device_name: str | None = None
    browser: str | None = None
    operating_system: str | None = None
    ip_address: str | None = None
    country: str | None = None
    city: str | None = None
    login_time: datetime
    last_activity_at: datetime
    last_api_request: str | None = None
    session_expires_at: datetime
    refresh_expires_at: datetime
    remember_me: bool
    is_active: bool
    logout_time: datetime | None = None
    revoked: bool
    revoked_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    current: bool = False


class TenderBase(BaseModel):
    title: str
    description: str | None = None
    portal: str
    state: str | None = None
    district: str | None = None
    department: str | None = None
    buyer: str | None = None
    organization: str | None = None
    location: str | None = None
    bid_number: str | None = None
    reference_number: str | None = None
    tender_url: str | None = None
    open_url: str | None = None
    published_date: date | None = None
    opening_date: date | None = None
    closing_date: date | None = None
    estimated_value: float | None = None
    currency: str | None = "INR"
    tender_status: str = "ACTIVE"
    classification_status: str = "UNCLASSIFIED"
    ai_category: str | None = None
    categories: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    raw_data: dict = Field(default_factory=dict)


class TenderCreate(TenderBase):
    tender_id: str


class TenderOut(TenderBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tender_id: str
    scraped_at: datetime
    is_active: bool


class TenderList(BaseModel):
    total: int
    page: int
    limit: int
    results: list[TenderOut]


class StatsOut(BaseModel):
    total: int
    active: int
    matched: int = 0
    unmatched: int = 0
    unclassified: int = 0
    queued_documents: int = 0
    processed_documents: int = 0
    failed_documents: int = 0
    duplicate_runs: int = 0
    failed_runs: int = 0
    new_today: int = 0
    by_portal: dict[str, int]
    matched_by_portal: dict[str, int] = Field(default_factory=dict)
    by_state: dict[str, int]
    by_category: dict[str, int]
    by_keyword: dict[str, int] = Field(default_factory=dict)
    recent: list[TenderOut]
    recent_matched: list[TenderOut] = Field(default_factory=list)
    last_scrape: "ScrapeLogOut | None" = None


class PortalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str
    portal_type: str
    kind: str | None = None
    state: str | None = None
    authentication: str
    scraper_type: str
    uses_playwright: bool = False
    scheduler: str
    retry_count: int
    health_status: str
    proxy_configuration: dict = Field(default_factory=dict)
    captcha_strategy: str
    last_successful_run: datetime | None = None
    next_run: datetime | None = None
    enabled: bool
    listing_urls: list[str] = Field(default_factory=list)


class PortalUpdate(BaseModel):
    enabled: bool | None = None
    retry_count: int | None = Field(default=None, ge=0, le=10)
    scheduler: str | None = Field(default=None, max_length=80)
    scraper_type: str | None = Field(default=None, max_length=80)
    captcha_strategy: str | None = Field(default=None, max_length=80)
    proxy_configuration: dict | None = None


class PortalRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    portal: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    fetched_count: int
    stored_count: int
    updated_count: int
    duplicate_count: int
    failed_count: int
    average_response_time_ms: int | None = None
    error_message: str | None = None
    logs: list[dict] = Field(default_factory=list)


class AlertCreate(BaseModel):
    categories: list[str] = Field(default_factory=list)
    portals: list[str] = Field(default_factory=list)
    email_enabled: bool = True


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    categories: list[str]
    portals: list[str]
    email_enabled: bool
    created_at: datetime


class KeywordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    keyword: str
    category: str | None
    is_active: bool


class KeywordCreate(BaseModel):
    keyword: str
    category: str | None = None
    is_active: bool = True


class KeywordUpdate(BaseModel):
    keyword: str | None = None
    category: str | None = None
    is_active: bool | None = None


class ScrapeRunOut(BaseModel):
    status: str
    portals: int
    tenders_found: int
    updated_tenders: int = 0
    logs: list[dict]


class ScrapeLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    portal: str
    status: str
    tenders_found: int
    error_message: str | None
    scraped_at: datetime


class CleanupOut(BaseModel):
    deleted: int


class BackupOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_name: str
    backup_type: str
    reason: str
    tender_count: int
    matched_count: int
    size_bytes: int
    checksum_sha256: str
    created_at: datetime


class BackupRestoreOut(BaseModel):
    backup_id: int
    restored: int
    updated: int
    skipped: int
    total_in_backup: int


class MessageOut(BaseModel):
    message: str
