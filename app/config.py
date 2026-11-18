import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str
    admin_password: str
    session_secret: str
    timezone: str = "Asia/Taipei"
    cookie_secure: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        admin_password = os.environ.get("ADMIN_PASSWORD", "")
        session_secret = os.environ.get("SESSION_SECRET", "")
        if not admin_password:
            raise RuntimeError("ADMIN_PASSWORD is required")
        if not session_secret:
            raise RuntimeError("SESSION_SECRET is required")
        return cls(
            db_path=os.environ.get("DB_PATH", "data/app.db"),
            admin_password=admin_password,
            session_secret=session_secret,
            timezone=os.environ.get("TZ", "Asia/Taipei"),
            cookie_secure=os.environ.get("COOKIE_SECURE", "").lower()
            in {"1", "true", "yes"},
        )
