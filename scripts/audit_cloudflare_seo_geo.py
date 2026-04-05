from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from audit_blog_scores import main as audit_blog_scores_main  # noqa: E402


def _ensure_default_argument(flag: str, value: str) -> None:
    if flag not in sys.argv[1:]:
        sys.argv.extend([flag, value])


if __name__ == "__main__":
    _ensure_default_argument("--provider", "cloudflare")
    _ensure_default_argument("--report-prefix", "cloudflare-seo-geo-audit")
    raise SystemExit(audit_blog_scores_main())
