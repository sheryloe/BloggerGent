#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql+psycopg2://bloggent:bloggent@localhost:15432/bloggent",
    )

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.services.ops_health_service import generate_ops_health_report  # noqa: E402


def main() -> None:
    with SessionLocal() as db:
        result = generate_ops_health_report(db)
    print(
        json.dumps(
            {
                "status": result["status"],
                "report_paths": result["report_paths"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()

