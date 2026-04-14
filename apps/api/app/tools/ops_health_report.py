from __future__ import annotations

import json

from app.db.session import SessionLocal
from app.services.ops.ops_health_service import generate_ops_health_report


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

