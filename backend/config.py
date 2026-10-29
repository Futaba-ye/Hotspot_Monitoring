from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    database_path: Path
    openrouter_api_key: str
    openrouter_model: str
    twitterapi_key: str
    official_rss_urls: tuple[str, ...]
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    alert_email: str
    smtp_starttls: bool
    smtp_ssl: bool
    scheduler_enabled: bool


def get_settings() -> Settings:
    return Settings(
        database_path=Path(os.getenv("DATABASE_PATH", str(ROOT / "data" / "hotspots.db"))),
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
        openrouter_model=os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3.5-super-vl:free").strip(),
        twitterapi_key=os.getenv("TWITTERAPI_IO_KEY", "").strip(),
        official_rss_urls=tuple(url.strip() for url in os.getenv("OFFICIAL_RSS_URLS", "https://openai.com/news/rss.xml").split(",") if url.strip()),
        smtp_host=os.getenv("SMTP_HOST", "").strip(),
        smtp_port=int(os.getenv("SMTP_PORT", "587")),
        smtp_user=os.getenv("SMTP_USER", "").strip(),
        smtp_password=os.getenv("SMTP_PASSWORD", ""),
        smtp_from=os.getenv("SMTP_FROM", "").strip(),
        alert_email=os.getenv("ALERT_EMAIL", "").strip(),
        smtp_starttls=os.getenv("SMTP_STARTTLS", "true").lower() == "true",
        smtp_ssl=os.getenv("SMTP_SSL", "false").lower() == "true",
        scheduler_enabled=os.getenv("SCHEDULER_ENABLED", "true").lower() == "true",
    )
