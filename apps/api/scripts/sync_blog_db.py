from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.services.blogger.blogger_sync_service import sync_connected_blogger_posts
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def main() -> int:
    db = SessionLocal()
    try:
        blogger_warnings = sync_connected_blogger_posts(db)
        cloudflare_result = sync_cloudflare_posts(db)
        payload = {
            "status": "ok" if not blogger_warnings else "warning",
            "blogger": {
                "warnings": blogger_warnings,
            },
            "cloudflare": {
                "channel_id": cloudflare_result.get("channel_id"),
                "count": cloudflare_result.get("count"),
                "last_synced_at": _iso(cloudflare_result.get("last_synced_at")),
            },
            "timestamp": _iso(datetime.now(timezone.utc)),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # noqa: BLE001
        error_payload = {
            "status": "failed",
            "error": str(exc),
        }
        print(json.dumps(error_payload, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
