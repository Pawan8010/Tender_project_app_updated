from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


DATABASE_URL = settings()["database_url"]
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)
connect_args = {"check_same_thread": False, "timeout": 60} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=60000")
        cursor.close()

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker as async_sessionmaker

ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql+psycopg://", "postgresql+asyncpg://").replace("sqlite://", "sqlite+aiosqlite://")

async_engine = create_async_engine(ASYNC_DATABASE_URL, connect_args=connect_args, echo=False)

if ASYNC_DATABASE_URL.startswith("sqlite"):
    @event.listens_for(async_engine.sync_engine, "connect")
    def _set_async_sqlite_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=60000")
        cursor.close()
AsyncSessionLocal = async_sessionmaker(
    bind=async_engine, class_=AsyncSession, expire_on_commit=False
)

async def get_async_db():
    async with AsyncSessionLocal() as session:
        yield session


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401
    from app.services.tender_index import ensure_search_indexes

    Base.metadata.create_all(bind=engine)
    _ensure_user_profile_columns()
    _ensure_tender_intelligence_columns()
    _ensure_session_columns()
    ensure_search_indexes(engine)


def _ensure_user_profile_columns():
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("users")}
    wanted = {
        "full_name": "VARCHAR(255)",
        "phone": "VARCHAR(20)",
        "last_login_at": "TIMESTAMP",
        "preferred_language": "VARCHAR(10) DEFAULT 'en'",
    }
    missing = [(name, ddl_type) for name, ddl_type in wanted.items() if name not in existing]
    if not missing:
        return
    with engine.begin() as connection:
        dialect = engine.dialect.name
        for name, ddl_type in missing:
            if dialect == "postgresql":
                connection.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {name} {ddl_type}"))
            else:
                connection.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl_type}"))


def _add_missing_columns(table_name: str, wanted: dict[str, str]) -> None:
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns(table_name)}
    missing = [(name, ddl_type) for name, ddl_type in wanted.items() if name not in existing]
    if not missing:
        return
    with engine.begin() as connection:
        dialect = engine.dialect.name
        for name, ddl_type in missing:
            if dialect == "postgresql":
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {name} {ddl_type}"))
            else:
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {name} {ddl_type}"))


def _ensure_tender_intelligence_columns():
    _ensure_json_defaults = "JSON" if engine.dialect.name == "postgresql" else "TEXT"
    _add_missing_columns(
        "tenders",
        {
            "bid_number": "VARCHAR(255)",
            "reference_number": "VARCHAR(255)",
            "district": "VARCHAR(100)",
            "department": "VARCHAR(255)",
            "buyer": "VARCHAR(255)",
            "organization": "VARCHAR(255)",
            "location": "VARCHAR(255)",
            "currency": "VARCHAR(12) DEFAULT 'INR'",
            "tender_status": "VARCHAR(60) DEFAULT 'ACTIVE'",
            "classification_status": "VARCHAR(60) DEFAULT 'UNCLASSIFIED'",
            "ai_category": "VARCHAR(100)",
            "tender_category": "VARCHAR(100)",
            "tender_type": "VARCHAR(100)",
            "procurement_type": "VARCHAR(100)",
            "emd": "FLOAT",
            "tender_fee": "FLOAT",
            "publishing_authority": "VARCHAR(255)",
            "city": "VARCHAR(100)",
            "latitude": "FLOAT",
            "longitude": "FLOAT",
            "bid_start_date": "DATE",
            "pre_bid_date": "DATE",
            "corrigendum": "BOOLEAN DEFAULT 0",
            "contact_person": "VARCHAR(255)",
            "email": "VARCHAR(255)",
            "phone": "VARCHAR(100)",
            "website": "TEXT",
            "content_hash": "VARCHAR(64)",
            "search_text": "TEXT",
            "updated_at": "TIMESTAMP",
            "last_seen_at": "TIMESTAMP",
        },
    )
    _add_missing_columns(
        "portals",
        {
            "proxy_configuration": _ensure_json_defaults,
            "listing_urls": _ensure_json_defaults,
        },
    )


def _ensure_session_columns():
    _add_missing_columns(
        "user_sessions",
        {
            "access_token_id": "VARCHAR(64)",
            "refresh_token_id": "VARCHAR(64)",
            "refresh_token_hash": "VARCHAR(128)",
            "country": "VARCHAR(120)",
            "city": "VARCHAR(120)",
            "last_api_request": "TEXT",
            "remember_me": "BOOLEAN DEFAULT 0",
            "logout_time": "TIMESTAMP",
            "revoked": "BOOLEAN DEFAULT 0",
            "revoked_reason": "VARCHAR(255)",
            "updated_at": "TIMESTAMP",
        },
    )
