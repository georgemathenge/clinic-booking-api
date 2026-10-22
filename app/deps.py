from datetime import datetime

from app.config import get_settings


def get_now() -> datetime:
    """Current time in clinic tz. A dependency so tests can freeze the clock."""
    return datetime.now(get_settings().tz)
