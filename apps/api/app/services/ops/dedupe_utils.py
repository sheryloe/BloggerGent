from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

TRACKING_QUERY_KEYS = {"amp", "fbclid", "gclid", "m"}
TRACKING_QUERY_PREFIXES = ("utm_",)

DEFAULT_STATUS_PRIORITY: dict[str, int] = {
    "published": 500,
    "live": 400,
    "scheduled": 300,
    "draft": 200,
    "failed": 100,
    "error": 100,
    "error_deleted": 100,
}

KST = ZoneInfo("Asia/Seoul")


def normalize_title(value: str | None) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def canonicalize_url(url: str | None) -> str | None:
    normalized = str(url or "").strip()
    if not normalized:
        return None
    try:
        parsed = urlsplit(normalized)
    except ValueError:
        return normalized.rstrip("/") or normalized

    if not parsed.scheme or not parsed.netloc:
        return normalized.rstrip("/") or normalized

    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key and key.lower() not in TRACKING_QUERY_KEYS and not key.lower().startswith(TRACKING_QUERY_PREFIXES)
    ]
    path = (parsed.path or "").rstrip("/")
    canonical = urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            urlencode(filtered_query, doseq=True),
            "",
        )
    )
    return canonical or normalized


def url_identity_key(url: str | None) -> str | None:
    canonical = canonicalize_url(url)
    if not canonical:
        return None
    try:
        parsed = urlsplit(canonical)
    except ValueError:
        return canonical.casefold()
    if not parsed.netloc:
        return canonical.casefold()
    path = (parsed.path or "").rstrip("/")
    query = parsed.query or ""
    if query:
        return f"{parsed.netloc.lower()}{path}?{query}"
    return f"{parsed.netloc.lower()}{path}"


def status_priority(value: str | None, *, priorities: dict[str, int] | None = None) -> int:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return 0
    bucket = priorities or DEFAULT_STATUS_PRIORITY
    if normalized in bucket:
        return bucket[normalized]
    if normalized.startswith("error"):
        return bucket.get("error", 100)
    if normalized.startswith("fail"):
        return bucket.get("failed", 100)
    return 50


def pick_best_status(*values: str | None, priorities: dict[str, int] | None = None) -> str | None:
    candidates = [str(item or "").strip().lower() for item in values if str(item or "").strip()]
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: status_priority(item, priorities=priorities), reverse=True)[0]


def pick_preferred_url(*values: str | None) -> str | None:
    scored: list[tuple[int, str]] = []
    for raw in values:
        normalized = canonicalize_url(raw)
        if not normalized:
            continue
        try:
            scheme = urlsplit(normalized).scheme.lower()
        except ValueError:
            scheme = ""
        score = 2 if scheme == "https" else 1 if scheme == "http" else 0
        scored.append((score, normalized))
    if not scored:
        return None
    scored.sort(reverse=True)
    return scored[0][1]


def kst_date_key(value: datetime | None) -> str:
    if value is None:
        return "na"
    if value.tzinfo is None:
        return value.date().isoformat()
    return value.astimezone(KST).date().isoformat()


def dedupe_key(
    *,
    scope: str,
    url: str | None,
    title: str | None,
    published_at: datetime | None,
) -> str:
    identity = url_identity_key(url)
    if identity:
        return f"{scope}|url|{identity}"
    return f"{scope}|title|{normalize_title(title)}|{kst_date_key(published_at)}"
