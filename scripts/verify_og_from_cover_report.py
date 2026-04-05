#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen


OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify og:image by reading target_url/new_cover from a cover report.")
    parser.add_argument("--report", required=True, help="Path to cover regenerate report json.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout seconds.")
    return parser.parse_args()


def _safe_str(value: object) -> str:
    return str(value or "").strip()


def _fetch_og_image(url: str, timeout: float) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=float(timeout)) as response:  # noqa: S310
        html = response.read().decode("utf-8", errors="replace")
    match = OG_IMAGE_RE.search(html)
    return _safe_str(match.group(1) if match else "")


def main() -> int:
    args = parse_args()
    report_path = Path(args.report)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    rows = payload.get("items") if isinstance(payload, dict) else []
    rows = rows if isinstance(rows, list) else []

    results: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = _safe_str(row.get("target_url"))
        expected = _safe_str(row.get("new_cover"))
        if not url:
            results.append({"status": "failed", "error": "target_url_missing"})
            continue
        try:
            og_image = _fetch_og_image(url, timeout=float(args.timeout))
            results.append(
                {
                    "status": "ok" if (expected and og_image == expected) else "partial",
                    "target_url": url,
                    "expected_cover": expected,
                    "og_image": og_image,
                    "match": bool(expected and og_image == expected),
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "status": "failed",
                    "target_url": url,
                    "expected_cover": expected,
                    "error": str(exc),
                    "match": False,
                }
            )

    summary = {
        "status": "ok",
        "total": len(results),
        "matched": sum(1 for item in results if bool(item.get("match"))),
        "failed": sum(1 for item in results if item.get("status") == "failed"),
        "items": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
