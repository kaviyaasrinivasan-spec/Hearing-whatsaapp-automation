"""Settings loaded from .env next to this file."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


API_BASE = os.getenv("API_BASE", "https://cases.abilawfirm.in/api/v1").rstrip("/")
APP_KEY = os.getenv("APP_KEY", "")

GROUP_NAME = os.getenv("GROUP_NAME", "ABI LAW FIRM")
SESSION_DIR = (BASE_DIR / os.getenv("SESSION_DIR", "whatsapp_session")).resolve()

SEND_TIME = os.getenv("SEND_TIME", "20:00")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Kolkata")
SEND_WHEN_EMPTY = _bool("SEND_WHEN_EMPTY", True)
HEADLESS = _bool("HEADLESS", False)

LOG_DIR = BASE_DIR / "logs"
SENT_LOG = BASE_DIR / "sent_log.json"
