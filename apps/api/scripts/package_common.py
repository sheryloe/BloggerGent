from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse

import httpx


REPO_ROOT_ENV = os.environ.get("BLOGGENT_REPO_ROOT", "").strip()
REPO_ROOT = Path(REPO_ROOT_ENV).resolve() if REPO_ROOT_ENV else Path(__file__).resolve().parents[1]
DEFAULT_API_ROOT = REPO_ROOT / "apps" / "api"
if DEFAULT_API_ROOT.exists():
    API_ROOT = DEFAULT_API_ROOT
elif (REPO_ROOT / "app").exists():
    API_ROOT = REPO_ROOT
else:
    API_ROOT = DEFAULT_API_ROOT

STORAGE_ROOT_ENV = os.environ.get("BLOGGENT_STORAGE_ROOT", "").strip()
STORAGE_ROOT = Path(STORAGE_ROOT_ENV).resolve() if STORAGE_ROOT_ENV else (REPO_ROOT / "storage")
REPORT_ROOT = STORAGE_ROOT / "reports"
REWRITE_PACKAGE_ROOT = STORAGE_ROOT / "rewrite-packages"
PATCH_PACKAGE_ROOT = STORAGE_ROOT / "patch-packages"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
DEFAULT_LOW_SEO_REPORT = REPORT_ROOT / "seo-below-70-2026-04-02.csv"
WHITESPACE_RE = re.compile(r"\s+")
HTML_TAG_RE = re.compile(r"<[^>]+>")
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*]\(([^)]+)\)")
HTML_IMAGE_RE = re.compile(r"<img[^>]+src=['\"]([^'\"]+)['\"]", re.IGNORECASE)
HTML_HEADING_RE = re.compile(r"<h([23])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
HTML_PARAGRAPH_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.IGNORECASE | re.DOTALL)
PROMPT_SECTION_RE = re.compile(r"^\[(.+?)\]\s*$")
BROKEN_TEXT_RE = re.compile(r"\uFFFD|\?[가-힣ㄱ-ㅎㅏ-ㅣ]")

if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get("BLOGGENT_DATABASE_URL", DEFAULT_DATABASE_URL)
if "STORAGE_ROOT" not in os.environ:
    os.environ["STORAGE_ROOT"] = str(STORAGE_ROOT)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(API_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Blog, SyncedBloggerPost  # noqa: E402
from app.services.settings_service import get_settings_map  # noqa: E402


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_space(value: str | None) -> str:
    return WHITESPACE_RE.sub(" ", (value or "").replace("\xa0", " ")).strip()


def read_csv_utf8(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv_utf8(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def read_text_utf8(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Text file not found: {path}")
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", b"", 0, 1, f"Failed to decode text: {path}")


def write_text_utf8(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_filename(value: str, fallback: str = "item") -> str:
    cleaned = normalize_space(value)
    if not cleaned:
        return fallback
    ascii_only = re.sub(r"[^0-9A-Za-z._-]+", "-", cleaned)
    ascii_only = re.sub(r"-{2,}", "-", ascii_only).strip("-._")
    if ascii_only:
        return ascii_only[:120]
    lowered = re.sub(r"[^0-9a-z]+", "-", cleaned.casefold())
    lowered = re.sub(r"-{2,}", "-", lowered).strip("-")
    return (lowered or fallback)[:120]


def strip_tags(value: str) -> str:
    return normalize_space(HTML_TAG_RE.sub(" ", value or ""))


def cloudflare_slug_from_url(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    path = (parsed.path or "").strip("/")
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) >= 3 and segments[0].lower() == "ko" and segments[1].lower() == "post":
        return unquote("/".join(segments[2:])).strip("/")
    return unquote(segments[-1]).strip() if segments else ""


def blogger_url_key(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    host = (parsed.netloc or "").strip().lower()
    path = unquote((parsed.path or "").strip().rstrip("/"))
    return f"{host}{path}"


def parse_tag_string(raw_value: str | None) -> list[str]:
    seen: set[str] = set()
    values: list[str] = []
    for token in (raw_value or "").split("|"):
        tag = normalize_space(token)
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        values.append(tag)
    return values


def extract_tag_names(detail: dict[str, Any]) -> list[str]:
    raw_tags = detail.get("tags")
    if not isinstance(raw_tags, list):
        return []
    values: list[str] = []
    seen: set[str] = set()
    for item in raw_tags:
        if isinstance(item, dict):
            candidate = normalize_space(str(item.get("name") or item.get("label") or item.get("slug") or ""))
        else:
            candidate = normalize_space(str(item))
        if not candidate:
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        values.append(candidate)
    return values


def load_low_seo_rows(path: Path) -> list[dict[str, str]]:
    rows = read_csv_utf8(path)
    filtered = [row for row in rows if normalize_space(row.get("provider")) == "cloudflare"]
    if len(filtered) != len(rows):
        raise ValueError(f"Low SEO report must contain only provider=cloudflare rows: {path}")
    return filtered


def detect_broken_text(value: str | None) -> bool:
    text = value or ""
    if not text:
        return False
    return bool(BROKEN_TEXT_RE.search(text))


def collect_markdown_asset_refs(value: str | None) -> list[str]:
    text = value or ""
    refs: list[str] = []
    seen: set[str] = set()
    for pattern in (MARKDOWN_IMAGE_RE, HTML_IMAGE_RE):
        for match in pattern.findall(text):
            ref = normalize_space(match)
            if not ref or ref in seen:
                continue
            seen.add(ref)
            refs.append(ref)
    return refs


def extract_html_outline(value: str | None) -> list[dict[str, Any]]:
    outline: list[dict[str, Any]] = []
    for level, heading in HTML_HEADING_RE.findall(value or ""):
        outline.append({"level": int(level), "heading": strip_tags(heading)})
    return outline


def extract_html_paragraphs(value: str | None, *, limit: int = 8) -> list[str]:
    paragraphs: list[str] = []
    for paragraph in HTML_PARAGRAPH_RE.findall(value or ""):
        text = strip_tags(paragraph)
        if not text:
            continue
        paragraphs.append(text)
        if len(paragraphs) >= limit:
            break
    return paragraphs


def extract_prompt_sections(path: Path, section_names: list[str]) -> dict[str, list[str]]:
    text = read_text_utf8(path)
    sections: dict[str, list[str]] = {name: [] for name in section_names}
    current: str | None = None
    for line in text.splitlines():
        section_match = PROMPT_SECTION_RE.match(line.strip())
        if section_match:
            header = section_match.group(1).strip()
            current = header if header in sections else None
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped:
            sections[current].append(stripped)
    return sections


def resolve_blog_by_profile_key(db: Session, profile_key: str) -> Blog:
    blogs = (
        db.execute(
        select(Blog)
        .where(Blog.profile_key == profile_key)
        .order_by(Blog.is_active.desc(), Blog.id.desc())
        )
        .scalars()
        .all()
    )
    for blog in blogs:
        if blog.is_active:
            return blog
    if blogs:
        return blogs[0]
    if not blogs:
        raise ValueError(f"Blog not found for profile_key={profile_key}")
    raise ValueError(f"Blog not found for profile_key={profile_key}")


def fetch_synced_blogger_posts(db: Session, blog_id: int) -> list[SyncedBloggerPost]:
    return (
        db.execute(
            select(SyncedBloggerPost)
            .where(SyncedBloggerPost.blog_id == blog_id)
            .order_by(SyncedBloggerPost.published_at.desc().nullslast(), SyncedBloggerPost.id.desc())
        )
        .scalars()
        .all()
    )


class CloudflareIntegrationClient:
    def __init__(self, *, base_url: str, token: str) -> None:
        self.base_url = normalize_space(base_url).rstrip("/")
        self.token = normalize_space(token)
        if not self.base_url:
            raise ValueError("cloudflare_blog_api_base_url is empty.")
        if not self.token:
            raise ValueError("cloudflare_blog_m2m_token is empty.")

    @classmethod
    def from_db(cls, db: Session) -> "CloudflareIntegrationClient":
        values = get_settings_map(db)
        return cls(
            base_url=str(values.get("cloudflare_blog_api_base_url") or ""),
            token=str(values.get("cloudflare_blog_m2m_token") or ""),
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        timeout: float = 90.0,
    ) -> Any:
        response = httpx.request(
            method=method,
            url=f"{self.base_url}{path}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=json_payload,
            timeout=timeout,
        )
        try:
            payload: Any = response.json()
        except ValueError:
            payload = {}
        if not response.is_success:
            detail = response.text
            if isinstance(payload, dict):
                detail = str(payload.get("message") or payload.get("detail") or payload.get("error") or detail)
            raise ValueError(f"Cloudflare integration request failed ({response.status_code}): {detail}")
        if isinstance(payload, dict):
            if payload.get("success") is False:
                raise ValueError(f"Cloudflare integration error: {payload.get('error') or payload}")
            if "data" in payload:
                return payload["data"]
        return payload

    def list_posts(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/api/integrations/posts", timeout=60.0)
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def get_post(self, post_id: str) -> dict[str, Any]:
        payload = self._request("GET", f"/api/integrations/posts/{post_id}", timeout=60.0)
        return payload if isinstance(payload, dict) else {}

    def list_categories(self) -> list[dict[str, Any]]:
        payload = self._request("GET", "/api/integrations/post-categories", timeout=60.0)
        return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []

    def update_post(self, post_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._request("PUT", f"/api/integrations/posts/{post_id}", json_payload=payload, timeout=120.0)
        return response if isinstance(response, dict) else {}


def resolve_cloudflare_category_id(target: str, categories: list[dict[str, Any]]) -> str:
    normalized_target = re.sub(r"\s+", "", (target or "").strip()).casefold()
    if not normalized_target:
        return ""
    for category in categories:
        category_id = normalize_space(str(category.get("id") or ""))
        category_name = re.sub(r"\s+", "", str(category.get("name") or "")).casefold()
        category_slug = re.sub(r"\s+", "", str(category.get("slug") or "")).casefold()
        if not category_id:
            continue
        if category_name == normalized_target or category_slug == normalized_target:
            return category_id
    return ""
