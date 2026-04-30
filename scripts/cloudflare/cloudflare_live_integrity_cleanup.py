from __future__ import annotations

import argparse
import csv
import html
import json
import re
import shutil
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urljoin, urlparse

import requests
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.entities import SyncedCloudflarePost
from app.services.cloudflare.cloudflare_channel_service import _integration_data_or_raise, _integration_request
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts


OUT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\Rool\30-cloudflare\10-live-health-audit")
FALLBACK_URL = (
    "https://api.dongriarchive.com/assets/media/cloudflare/dongri-archive/ilsanggwa-memo/2026/04/"
    "morning-5-minute-check-note-routine-2026/morning-5-minute-check-note-routine-2026.webp"
)
FALLBACK_OWNER_SLUG = "morning-5-minute-check-note-routine-2026"
PUBLIC_ORIGIN = "https://dongriarchive.com"
USER_AGENT = "BloggerGent-Cloudflare-LiveIntegrity/2026.04"
REQUEST_TIMEOUT = 15

TITLE_RE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
WORD_RE = re.compile(r"[\uac00-\ud7a3a-zA-Z0-9]{2,}")
ATTR_URL_RE = re.compile(r"\b(?:src|href)\s*=\s*(['\"])(.*?)\1", re.I | re.S)
SRCSET_RE = re.compile(r"\bsrcset\s*=\s*(['\"])(.*?)\1", re.I | re.S)
META_IMAGE_RE = re.compile(
    r"<meta\b(?=[^>]*(?:property|name)\s*=\s*(['\"])(?:og:image|twitter:image|image)\1)"
    r"(?=[^>]*content\s*=\s*(['\"])(.*?)\2)[^>]*>",
    re.I | re.S,
)
IMAGE_EXT_RE = re.compile(r"\.(?:webp|png|jpe?g|gif|avif)(?:[?#].*)?$", re.I)
HTTP_RE = re.compile(r"^https?://", re.I)
MOJIBAKE_TOKENS = ("怨", "誘", "媛", "湲", "留", "諛", "蹂", "쒖", "섏", "뚮", "?뚮", "?섏", "�")

HANGUL_BASE = 0xAC00
HANGUL_LAST = 0xD7A3
INITIAL_ROMAN = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
VOWEL_ROMAN = ["a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i"]
FINAL_ROMAN = ["", "k", "k", "ks", "n", "nj", "nh", "t", "l", "lk", "lm", "lb", "ls", "lt", "lp", "lh", "m", "p", "ps", "t", "t", "ng", "t", "t", "k", "t", "p", "h"]


@dataclass
class UrlCheck:
    ok: bool
    status: int | None = None
    content_type: str = ""
    error: str = ""


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def normalize_title(value: str | None) -> str:
    text = html.unescape(value or "")
    suffix = "| 동그리의 기록소"
    if suffix in text:
        text = text.rsplit(suffix, 1)[0]
    return WS_RE.sub(" ", text).strip()


def title_words(value: str | None) -> set[str]:
    return set(WORD_RE.findall(normalize_title(value).lower()))


def strip_html(value: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", value, flags=re.I | re.S)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.I | re.S)
    text = TAG_RE.sub(" ", text)
    return WS_RE.sub(" ", text).strip()


def text_garbage_score(value: str | None) -> int:
    text = value or ""
    score = sum(text.count(token) for token in MOJIBAKE_TOKENS)
    question_count = text.count("?")
    if question_count >= 5:
        score += question_count
    return score


def normalize_url(base: str, raw: str | None) -> str | None:
    text = (raw or "").strip()
    if not text or text.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None
    if text.startswith("//"):
        text = "https:" + text
    absolute = urljoin(base, text)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return absolute


def extract_relevant_urls(page_url: str, html_text: str) -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []
    for match in ATTR_URL_RE.finditer(html_text or ""):
        url = normalize_url(page_url, match.group(2))
        if url:
            urls.append((url, "attr"))
    for match in SRCSET_RE.finditer(html_text or ""):
        for part in match.group(2).split(","):
            candidate = part.strip().split()[0] if part.strip() else ""
            url = normalize_url(page_url, candidate)
            if url:
                urls.append((url, "srcset"))
    for match in META_IMAGE_RE.finditer(html_text or ""):
        url = normalize_url(page_url, match.group(3))
        if url:
            urls.append((url, "meta_image"))

    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for url, source in urls:
        if url not in seen:
            seen.add(url)
            result.append((url, source))
    return result


def is_candidate_image_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc == "api.dongriarchive.com" and parsed.path.startswith("/assets/"):
        return True
    return bool(IMAGE_EXT_RE.search(parsed.path))


def is_garbage_url(url: str) -> bool:
    parsed = urlparse(url)
    lowered = url.lower()
    if "width=device-width" in lowered or "initial-scale" in lowered:
        return False
    if any(char in url for char in ("<", ">", '"')):
        return True
    if " " in url:
        return True
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return True
    return parsed.netloc.endswith("dongriarchive.com") and "/assets/assets/" in parsed.path


def check_url(session: requests.Session, url: str, *, want_image: bool = False, allow_redirects: bool = True) -> UrlCheck:
    try:
        response = session.head(url, allow_redirects=allow_redirects, timeout=REQUEST_TIMEOUT)
        content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
        if response.status_code in {403, 404, 405, 500} or (want_image and not content_type.startswith("image/")):
            response = session.get(url, stream=True, allow_redirects=allow_redirects, timeout=REQUEST_TIMEOUT)
            content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
        ok = 200 <= response.status_code < 400 and (not want_image or content_type.startswith("image/"))
        error = "" if ok else ("non_image_content_type" if want_image and 200 <= response.status_code < 400 else f"http_{response.status_code}")
        response.close()
        return UrlCheck(ok=ok, status=response.status_code, content_type=content_type, error=error)
    except Exception as exc:  # noqa: BLE001
        return UrlCheck(ok=False, error=f"{type(exc).__name__}: {str(exc)[:160]}")


def romanize_korean(value: str) -> str:
    output: list[str] = []
    for char in value:
        code = ord(char)
        if HANGUL_BASE <= code <= HANGUL_LAST:
            syllable_index = code - HANGUL_BASE
            initial_index = syllable_index // 588
            vowel_index = (syllable_index % 588) // 28
            final_index = syllable_index % 28
            output.append(f"{INITIAL_ROMAN[initial_index]}{VOWEL_ROMAN[vowel_index]}{FINAL_ROMAN[final_index]}")
        elif re.match(r"[a-zA-Z0-9]", char):
            output.append(char)
        elif re.match(r"\s|[-_/]+", char):
            output.append(" ")
    return "".join(output)


def slugify_like_worker(value: str) -> str:
    romanized = romanize_korean(value)
    text = romanized.lower().strip()
    text = re.sub(r"^#+", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:80]


def unique_slug(base: str, used: set[str]) -> str:
    candidate = base[:80].strip("-")
    if candidate and candidate not in used:
        used.add(candidate)
        return candidate
    stem = candidate[:75].strip("-") or "post"
    index = 2
    while True:
        candidate = f"{stem}-{index}"[:80].strip("-")
        if candidate not in used:
            used.add(candidate)
            return candidate
        index += 1


def public_post_url(slug: str) -> str:
    return f"{PUBLIC_ORIGIN}/ko/post/{quote(slug, safe='')}"


def load_posts(db: Session) -> list[SyncedCloudflarePost]:
    return (
        db.query(SyncedCloudflarePost)
        .filter(SyncedCloudflarePost.status == "published")
        .order_by(SyncedCloudflarePost.canonical_category_slug, SyncedCloudflarePost.published_at, SyncedCloudflarePost.slug)
        .all()
    )


def audit_posts(db: Session) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    image_cache: dict[str, UrlCheck] = {}
    posts = load_posts(db)
    used_slugs = {post.slug for post in posts if post.slug}
    rows: list[dict[str, Any]] = []
    encoded_slug_rows: list[dict[str, Any]] = []
    actual_broken_rows: list[dict[str, Any]] = []
    fallback_rows: list[dict[str, Any]] = []
    title_mismatch_rows: list[dict[str, Any]] = []
    legacy_rows: list[dict[str, Any]] = []
    stale_rows: list[dict[str, Any]] = []

    for index, post in enumerate(posts, 1):
        slug = post.slug or ""
        page_url = post.url or public_post_url(slug)
        response = session.get(page_url, timeout=REQUEST_TIMEOUT)
        public_status = response.status_code
        html_text = response.text if response.ok else ""
        response.close()
        public_title = ""
        title_match = TITLE_RE.search(html_text)
        if title_match:
            public_title = normalize_title(title_match.group(1))
        db_title = normalize_title(post.title)
        db_words = title_words(db_title)
        public_words = title_words(public_title)
        title_ratio = len(db_words & public_words) / max(1, min(len(db_words), len(public_words))) if public_words else 0.0
        title_identity_ok = public_status == 200 and title_ratio >= 0.45

        image_urls: list[tuple[str, str]] = []
        if post.thumbnail_url:
            image_urls.append((post.thumbnail_url, "db_thumbnail_url"))
        for url, source in extract_relevant_urls(page_url, html_text):
            if is_candidate_image_url(url):
                image_urls.append((url, source))

        unique_images: list[tuple[str, str]] = []
        seen_images: set[str] = set()
        for url, source in image_urls:
            if url not in seen_images:
                seen_images.add(url)
                unique_images.append((url, source))

        verified_images: list[str] = []
        broken_images: list[str] = []
        garbage_urls = [url for url, _ in extract_relevant_urls(page_url, html_text) if is_garbage_url(url)]
        legacy_images = [url for url, _ in unique_images if "/assets/media/posts/" in urlparse(url).path]
        for url, _source in unique_images:
            check = image_cache.get(url)
            if check is None:
                check = check_url(session, url, want_image=True)
                image_cache[url] = check
            if check.ok:
                verified_images.append(url)
            else:
                broken_images.append(f"{url} ({check.status} {check.content_type} {check.error})")

        decoded_slug = unquote(slug)
        encoded_slug = decoded_slug != slug and bool(re.search(r"[\uac00-\ud7a3]", decoded_slug))
        target_slug = ""
        if encoded_slug:
            used_slugs.discard(slug)
            target_slug = unique_slug(slugify_like_worker(decoded_slug), used_slugs)

        db_stale = (
            post.live_image_issue == "missing_images"
            or (post.image_health_status == "broken" and bool(verified_images))
            or post.live_image_count in {None, 0}
        )
        fallback = (
            slug != FALLBACK_OWNER_SLUG
            and (post.thumbnail_url == FALLBACK_URL or FALLBACK_URL in verified_images)
        )
        actual_broken = bool(broken_images) or not verified_images
        text_garbage = text_garbage_score(" ".join([post.title or "", post.excerpt_text or ""])) >= 2 or text_garbage_score(strip_html(html_text)[:20000]) >= 4
        reasons = []
        if public_status != 200:
            reasons.append(f"public_status_{public_status}")
        if not title_identity_ok:
            reasons.append("title_identity_mismatch")
        if encoded_slug:
            reasons.append("encoded_korean_slug")
        if actual_broken:
            reasons.append("actual_broken_image")
        if fallback:
            reasons.append("fallback_placeholder")
        if legacy_images:
            reasons.append("legacy_media_posts_url")
        if db_stale:
            reasons.append("db_image_state_stale")
        if text_garbage:
            reasons.append("text_garbage_suspect")
        if garbage_urls:
            reasons.append("garbage_url")

        if actual_broken:
            image_status = "broken"
            image_issue = "broken_image_url"
        elif fallback:
            image_status = "fallback_placeholder"
            image_issue = "fallback_placeholder"
        else:
            image_status = "ok"
            image_issue = ""

        row = {
            "remote_post_id": post.remote_post_id,
            "category_slug": post.canonical_category_slug or post.category_slug or "",
            "slug": slug,
            "target_slug": target_slug,
            "title": post.title,
            "public_url": page_url,
            "target_public_url": public_post_url(target_slug) if target_slug else "",
            "public_status": public_status,
            "public_title": public_title,
            "title_identity_ratio": f"{title_ratio:.3f}",
            "thumbnail_url": post.thumbnail_url or "",
            "verified_image_count": len(verified_images),
            "broken_image_count": len(broken_images),
            "legacy_image_count": len(legacy_images),
            "db_image_health_status": post.image_health_status or "",
            "db_live_image_issue": post.live_image_issue or "",
            "target_image_health_status": image_status,
            "target_live_image_issue": image_issue,
            "reasons": ";".join(reasons),
            "verified_images": " | ".join(verified_images[:5]),
            "broken_images": " | ".join(broken_images[:5]),
            "legacy_images": " | ".join(legacy_images[:5]),
            "garbage_urls": " | ".join(garbage_urls[:5]),
        }
        rows.append(row)
        if encoded_slug:
            encoded_slug_rows.append(row)
        if actual_broken:
            actual_broken_rows.append(row)
        if fallback:
            fallback_rows.append(row)
        if not title_identity_ok:
            title_mismatch_rows.append(row)
        if legacy_images:
            legacy_rows.append(row)
        if db_stale:
            stale_rows.append(row)
        if index % 50 == 0:
            print(f"audited {index}/{len(posts)}")

    by_reason = Counter()
    for row in rows:
        for reason in filter(None, row["reasons"].split(";")):
            by_reason[reason] += 1
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_published": len(rows),
        "by_reason": dict(by_reason),
        "encoded_slug_count": len(encoded_slug_rows),
        "actual_broken_image_count": len(actual_broken_rows),
        "fallback_placeholder_count": len(fallback_rows),
        "title_mismatch_count": len(title_mismatch_rows),
        "legacy_image_url_count": len(legacy_rows),
        "db_stale_image_health_count": len(stale_rows),
    }
    splits = {
        "all": rows,
        "encoded_slug": encoded_slug_rows,
        "actual_broken_image": actual_broken_rows,
        "fallback_placeholder": fallback_rows,
        "title_mismatch": title_mismatch_rows,
        "legacy_image_url": legacy_rows,
        "db_stale_image_health": stale_rows,
    }
    return summary, rows, splits


def write_audit_outputs(summary: dict[str, Any], rows: list[dict[str, Any]], splits: dict[str, list[dict[str, Any]]], stamp: str) -> None:
    json_path = OUT_ROOT / f"cloudflare-live-integrity-audit-{stamp}.json"
    csv_path = OUT_ROOT / f"cloudflare-live-integrity-audit-{stamp}.csv"
    write_json(json_path, {"summary": summary, "rows": rows})
    write_csv(csv_path, rows)
    shutil.copy2(json_path, OUT_ROOT / "cloudflare-live-integrity-audit-latest.json")
    shutil.copy2(csv_path, OUT_ROOT / "cloudflare-live-integrity-audit-latest.csv")

    for name, split_rows in splits.items():
        if name == "all":
            continue
        path = OUT_ROOT / f"{name}_{len(split_rows)}.csv"
        latest = OUT_ROOT / f"{name}_latest.csv"
        write_csv(path, split_rows, fieldnames=list(rows[0].keys()) if rows else [])
        shutil.copy2(path, latest)


def execute_db_health_sync(db: Session, rows: list[dict[str, Any]]) -> dict[str, Any]:
    changed = 0
    by_status = Counter()
    by_issue = Counter()
    for row in rows:
        post = (
            db.query(SyncedCloudflarePost)
            .filter(SyncedCloudflarePost.remote_post_id == row["remote_post_id"])
            .one_or_none()
        )
        if post is None:
            continue
        status = row["target_image_health_status"]
        issue = row["target_live_image_issue"] or None
        unique_count = int(row["verified_image_count"])
        total_count = unique_count + int(row["broken_image_count"])
        post.image_health_status = status
        post.live_image_issue = issue
        post.live_image_count = total_count
        post.live_unique_image_count = unique_count
        post.live_duplicate_image_count = max(0, total_count - unique_count)
        post.live_webp_count = len(re.findall(r"\.webp(?:[?#]|$)", row["verified_images"], flags=re.I))
        post.live_png_count = len(re.findall(r"\.png(?:[?#]|$)", row["verified_images"], flags=re.I))
        post.live_other_image_count = max(0, unique_count - int(post.live_webp_count or 0) - int(post.live_png_count or 0))
        post.live_cover_present = unique_count > 0
        post.live_inline_present = unique_count > 1
        post.live_image_audited_at = datetime.now(timezone.utc)
        changed += 1
        by_status[status] += 1
        by_issue[issue or ""] += 1
    db.commit()
    return {"updated_count": changed, "by_status": dict(by_status), "by_issue": dict(by_issue)}


def execute_slug_cleanup(db: Session, rows: list[dict[str, Any]], *, limit: int | None = None) -> dict[str, Any]:
    candidates = [row for row in rows if row.get("target_slug")]
    if limit:
        candidates = candidates[:limit]
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    results: list[dict[str, Any]] = []
    success = 0
    failed = 0

    for row in candidates:
        old_slug = row["slug"]
        target_slug = row["target_slug"]
        remote_post_id = row["remote_post_id"]
        result = {
            "remote_post_id": remote_post_id,
            "old_slug": old_slug,
            "target_slug": target_slug,
            "old_url": row["public_url"],
            "target_url": row["target_public_url"],
            "api_slug": "",
            "api_ok": False,
            "old_url_status": "",
            "target_url_status": "",
            "error": "",
        }
        try:
            response = _integration_request(
                db,
                method="PUT",
                path=f"/api/integrations/posts/{remote_post_id}",
                json_payload={"slug": target_slug},
                timeout=60.0,
            )
            payload = _integration_data_or_raise(response)
            api_slug = str(payload.get("slug") or "") if isinstance(payload, dict) else ""
            result["api_slug"] = api_slug
            if api_slug != target_slug:
                raise RuntimeError(f"slug update not applied: expected {target_slug}, got {api_slug or '<empty>'}")
            target_check = check_url(session, row["target_public_url"], want_image=False, allow_redirects=True)
            old_check = check_url(session, row["public_url"], want_image=False, allow_redirects=False)
            result["target_url_status"] = str(target_check.status or "")
            result["old_url_status"] = str(old_check.status or "")
            if not target_check.ok:
                raise RuntimeError(f"new URL verification failed: {target_check.status} {target_check.error}")
            if old_check.status != 301:
                raise RuntimeError(f"old URL did not return 301: {old_check.status} {old_check.error}")
            result["api_ok"] = True
            result["status"] = "success"
            success += 1
        except Exception as exc:  # noqa: BLE001
            result["status"] = "failed"
            result["error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
            failed += 1
        results.append(result)
        time.sleep(0.3)

    stamp = now_stamp()
    result_path = OUT_ROOT / f"slug-cleanup-apply-{stamp}.csv"
    rollback_path = OUT_ROOT / f"slug-cleanup-rollback-{stamp}.csv"
    write_csv(result_path, results)
    write_csv(
        rollback_path,
        [
            {
                "remote_post_id": item["remote_post_id"],
                "current_slug": item["target_slug"],
                "rollback_slug": item["old_slug"],
                "rollback_command_note": "PUT /api/integrations/posts/{remote_post_id} with rollback_slug",
            }
            for item in results
            if item["api_ok"]
        ],
    )
    shutil.copy2(result_path, OUT_ROOT / "slug-cleanup-apply-latest.csv")
    shutil.copy2(rollback_path, OUT_ROOT / "slug-cleanup-rollback-latest.csv")
    return {"candidate_count": len(candidates), "success_count": success, "failed_count": failed, "result_path": str(result_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cloudflare live post URL/image/DB integrity cleanup.")
    parser.add_argument("--mode", choices=["dry_run", "execute_db_health_sync", "execute_slug_cleanup", "final_sync"], required=True)
    parser.add_argument("--limit", type=int, default=None, help="Limit slug cleanup candidates.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stamp = now_stamp()
    with SessionLocal() as db:
        if args.mode == "final_sync":
            result = sync_cloudflare_posts(db, include_non_published=True)
            print(json.dumps({"mode": args.mode, "sync_result": result}, ensure_ascii=False, indent=2, default=str))
            return

        summary, rows, splits = audit_posts(db)
        write_audit_outputs(summary, rows, splits, stamp)
        output: dict[str, Any] = {"mode": args.mode, "audit_summary": summary}
        if args.mode == "execute_db_health_sync":
            output["db_health_sync"] = execute_db_health_sync(db, rows)
        elif args.mode == "execute_slug_cleanup":
            output["slug_cleanup"] = execute_slug_cleanup(db, rows, limit=args.limit)
            output["sync_result"] = sync_cloudflare_posts(db, include_non_published=True)
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
