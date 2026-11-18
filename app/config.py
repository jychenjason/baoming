import os
from dataclasses import dataclass


def _require_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


@dataclass(frozen=True)
class Settings:
    db_path: str
    admin_password: str
    session_secret: str
    timezone: str = "Asia/Taipei"
    cookie_secure: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=os.environ.get("DB_PATH", "data/app.db"),
            admin_password=_require_env("ADMIN_PASSWORD"),
            session_secret=_require_env("SESSION_SECRET"),
            timezone=os.environ.get("TZ", "Asia/Taipei"),
            cookie_secure=os.environ.get("COOKIE_SECURE", "").lower()
            in {"1", "true", "yes"},
        )
