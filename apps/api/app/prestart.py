from __future__ import annotations

import time

from redis import Redis
from sqlalchemy import text

from app.core.config import settings
from app.db.session import engine


def wait_for_services() -> None:
    for _ in range(30):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            Redis.from_url(settings.redis_url).ping()
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError("Database or Redis is not ready")


if __name__ == "__main__":
    wait_for_services()
