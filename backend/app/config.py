import os
from functools import lru_cache
from pathlib import Path


def _load_local_env():
    for env_path in (Path.cwd() / ".env", Path.cwd().parent / ".env"):
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip().lstrip("\ufeff"), value.strip().strip('"').strip("'"))


_load_local_env()


KEYWORDS = [
    "Reflex Sight", "Red Dot Sight", "Holographic Sight", "Thermal Weapon Sight",
    "Night Vision Sight", "Day Night Sight", "Thermal Imager", "Thermal Imaging Camera", "Long Range Thermal Imaging Camera", "Thermal Imaging Sight",
    "Handheld Thermal Imager", "Night Vision Device", "NVD", "Night Vision Goggles",
    "NVG", "Image Intensifier", "Uncooled Thermal", "Cooled Thermal", "LWIR", "MWIR",
    "Target Acquisition System", "Laser Range Finder", "Laser Range Finder Integrated Sight",
    "LRF", "LRF Integrated Sight",
    "Electro Optical Surveillance System", "EOSS", "Long Range Observation System",
    "LOROS", "Battlefield Surveillance Radar", "Battlefield Surveillance Radar EO",
    "Pan Tilt Zoom Camera", "PTZ with EO Payload", "PTZ Camera",
    "Thermal Camera", "Long Range PTZ Camera", "Optical Camera", "Night Vision Camera",
    "Border Surveillance System", "EO Payload", "Surveillance Equipment",
    "Security Equipment", "Binoculars", "Monocular", "Spotting Scope", "Infrared Camera",
    "IR Camera", "FLIR", "Perimeter Security", "Intrusion Detection", "Body Worn Camera",
    "BWC", "Drone Detection", "Counter UAV", "Anti-Drone", "Ballistic Helmet",
    "Bullet Proof", "Bulletproof", "Body Armor", "Riot Control", "Stun Grenade",
    "Tactical Equipment", "Communication Equipment", "Handheld Radio", "TETRA",
    "Walkie Talkie",
]

CATEGORY_MAP = {
    "Thermal": ["Thermal", "LWIR", "MWIR", "FLIR", "Infrared", "IR Camera"],
    "NVD": ["Night Vision", "NVD", "NVG", "Image Intensifier"],
    "PTZ": ["PTZ", "Pan Tilt Zoom", "Long Range PTZ", "PTZ with EO Payload"],
    "EOSS": [
        "EOSS", "LOROS", "Electro Optical", "Border Surveillance", "Target Acquisition",
        "Laser Range Finder", "Laser Range Finder Integrated Sight", "LRF",
        "LRF Integrated Sight", "Long Range Observation", "Battlefield Surveillance Radar",
        "Battlefield Surveillance Radar EO",
        "EO Payload", "Surveillance Equipment", "Binoculars", "Monocular", "Spotting Scope",
    ],
    "Camera": ["Camera", "Optical", "BWC", "Body Worn"],
    "Sight": ["Reflex Sight", "Red Dot", "Holographic", "Weapon Sight", "Day Night Sight"],
    "Communication": ["Radio", "TETRA", "Walkie Talkie", "Communication"],
    "Protection": ["Bulletproof", "Bullet Proof", "Body Armor", "Ballistic Helmet", "Riot Control", "Stun Grenade"],
    "Security": ["Security Equipment", "Perimeter Security", "Intrusion Detection"],
    "Tactical": ["Tactical Equipment"],
    "Counter-UAV": ["Drone", "UAV", "Anti-Drone", "Counter UAV"],
}


@lru_cache
def settings():
    return {
        "database_url": os.getenv("DATABASE_URL", "sqlite:///./tender_hunter.db"),
        "redis_url": os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        "environment": os.getenv("ENVIRONMENT", "development").lower(),
        "admin_email": os.getenv("ADMIN_EMAIL", "2317056@ritindia.edu").lower(),
        "admin_password": os.getenv("ADMIN_PASSWORD", "change-this-admin-password"),
        "secret_key": os.getenv("SECRET_KEY") or os.getenv("JWT_SECRET", "dev-secret-change-me"),
        "access_token_expire_minutes": int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES") or os.getenv("JWT_EXPIRE_MINUTES", "480")),
        "session_inactivity_minutes": max(5, int(os.getenv("SESSION_INACTIVITY_MINUTES", "30"))),
        "refresh_token_expire_days": max(1, int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))),
        "remember_me_expire_days": max(7, int(os.getenv("REMEMBER_ME_EXPIRE_DAYS", "30"))),
        "session_cleanup_interval_minutes": max(5, int(os.getenv("SESSION_CLEANUP_INTERVAL_MINUTES", "30"))),
        "sendgrid_api_key": os.getenv("SENDGRID_API_KEY", ""),
        "gmail_user": os.getenv("GMAIL_USER", ""),
        "gmail_app_password": os.getenv("GMAIL_APP_PASSWORD", ""),
        "smtp_host": os.getenv("SMTP_HOST", "smtp.gmail.com"),
        "smtp_port": int(os.getenv("SMTP_PORT", "465")),
        "alert_from_email": os.getenv("ALERT_FROM_EMAIL") or os.getenv("FROM_EMAIL", "alerts@example.in"),
        "alert_to_emails": os.getenv("ALERT_TO_EMAILS", ""),
        "alert_test_to_email": os.getenv("ALERT_TEST_TO_EMAIL", ""),
        "use_proxy": os.getenv("USE_PROXY", "false").lower() == "true",
        "scraper_api_key": os.getenv("SCRAPER_API_KEY", ""),
        "scraper_proxy_fallback": os.getenv("SCRAPER_PROXY_FALLBACK", "true").lower() == "true",
        "scraper_proxy_list": os.getenv("SCRAPER_PROXY_LIST", ""),
        "use_playwright": os.getenv("USE_PLAYWRIGHT", "false").lower() == "true",
        "enable_sample_fallback": os.getenv("ENABLE_SAMPLE_FALLBACK", "false").lower() == "true",
        "store_all_tenders": os.getenv("STORE_ALL_TENDERS", "true").lower() == "true",
        "seed_demo_data": os.getenv("SEED_DEMO_DATA", "false").lower() == "true",
        "historical_scrape_enabled": os.getenv("HISTORICAL_SCRAPE_ENABLED", "true").lower() == "true",
        "historical_scrape_lookback_days": max(30, int(os.getenv("HISTORICAL_SCRAPE_LOOKBACK_DAYS", "365"))),
        "historical_scrape_pages_per_portal": max(1, int(os.getenv("HISTORICAL_SCRAPE_PAGES_PER_PORTAL", "8"))),
        "max_tenders_per_portal": max(0, int(os.getenv("MAX_TENDERS_PER_PORTAL", "0"))),
        "max_pages_per_portal": max(1, int(os.getenv("MAX_PAGES_PER_PORTAL", "500"))),
        "gem_page_size": max(10, int(os.getenv("GEM_PAGE_SIZE", "10"))),
        "auto_scrape_enabled": os.getenv("AUTO_SCRAPE_ENABLED", "true").lower() == "true",
        "in_process_auto_scrape_enabled": os.getenv("IN_PROCESS_AUTO_SCRAPE_ENABLED", "true").lower() == "true",
        "auto_scrape_interval_minutes": max(5, int(os.getenv("AUTO_SCRAPE_INTERVAL_MINUTES", "60"))),
        "auto_scrape_startup_delay_seconds": max(0, int(os.getenv("AUTO_SCRAPE_STARTUP_DELAY_SECONDS", "15"))),
        "scraper_request_timeout_seconds": max(5, int(os.getenv("SCRAPER_REQUEST_TIMEOUT_SECONDS", "12"))),
        "scraper_portal_timeout_seconds": max(10, int(os.getenv("SCRAPER_PORTAL_TIMEOUT_SECONDS", "45"))),
        "scraper_retries": max(1, int(os.getenv("SCRAPER_RETRIES", "2"))),
        "scraper_concurrency": max(1, int(os.getenv("SCRAPER_CONCURRENCY", "6"))),
        "ml_engine_enabled": os.getenv("ML_ENGINE_ENABLED", "true").lower() == "true",
        "ml_model_name": os.getenv("ML_MODEL_NAME", "all-MiniLM-L6-v2"),
        "ml_similarity_threshold": float(os.getenv("ML_SIMILARITY_THRESHOLD", "0.45")),
        "backup_enabled": os.getenv("BACKUP_ENABLED", "true").lower() == "true",
        "backup_dir": os.getenv("BACKUP_DIR", "backups"),
        "backup_retention_count": max(3, int(os.getenv("BACKUP_RETENTION_COUNT", "30"))),
        "frontend_origins": [
            origin.strip()
            for origin in os.getenv(
                "FRONTEND_ORIGINS",
                "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000",
            ).split(",")
            if origin.strip()
        ],
    }
