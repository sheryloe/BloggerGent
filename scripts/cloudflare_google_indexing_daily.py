#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import requests
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_PATH = ROOT / "storage" / "reports" / "google-indexing-state.json"
DEFAULT_LOG_DIR = ROOT / "storage" / "reports"
INDEXING_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"


@dataclass(frozen=True)
class Config:
    api_base_url: str
    site_base_url: str
    service_account_file: Path
    daily_limit: int
    retry_days: int
    timeout_seconds: int
    dry_run: bool
    state_path: Path


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int, minimum: int) -> int:
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ValueError(f"{key} must be integer: {raw}") from exc
    return max(minimum, value)


def load_config() -> Config:
    api_base_url = os.getenv("BLOGGENT_API_BASE_URL", "http://localhost:7002").strip().rstrip("/")
    site_base_url = os.getenv("CLOUDFLARE_SITE_BASE_URL", "https://dongriarchive.com").strip().rstrip("/")
    service_account_raw = os.getenv("GOOGLE_INDEX_SERVICE_ACCOUNT_FILE", "").strip()
    if not service_account_raw:
        raise ValueError("GOOGLE_INDEX_SERVICE_ACCOUNT_FILE is required")
    service_account_file = Path(service_account_raw).expanduser().resolve()
    if not service_account_file.exists():
        raise ValueError(f"Service account file not found: {service_account_file}")

    state_path_raw = os.getenv("GOOGLE_INDEX_STATE_PATH", str(DEFAULT_STATE_PATH)).strip()
    state_path = Path(state_path_raw).expanduser().resolve()

    return Config(
        api_base_url=api_base_url,
        site_base_url=site_base_url,
        service_account_file=service_account_file,
        daily_limit=_env_int("GOOGLE_INDEX_DAILY_LIMIT", 10, 1),
        retry_days=_env_int("GOOGLE_INDEX_RETRY_DAYS", 30, 1),
        timeout_seconds=_env_int("GOOGLE_INDEX_TIMEOUT_SECONDS", 20, 5),
        dry_run=_env_bool("GOOGLE_INDEX_DRY_RUN", False),
        state_path=state_path,
    )


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"requested_at": {}}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {"requested_at": {}}
    if not isinstance(data, dict):
        return {"requested_at": {}}
    requested_at = data.get("requested_at")
    if not isinstance(requested_at, dict):
        requested_at = {}
    return {"requested_at": requested_at}


def save_state(path: Path, state: dict[str, Any]) -> None:
    _ensure_parent(path)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)


def fetch_urls_from_cloudflare_posts(config: Config) -> list[str]:
    url = f"{config.api_base_url}/api/v1/cloudflare/posts"
    response = requests.get(url, timeout=config.timeout_seconds)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("Cloudflare posts response is not a list")

    def sort_key(item: dict[str, Any]) -> str:
        published_at = str(item.get("published_at") or "")
        updated_at = str(item.get("updated_at") or "")
        return published_at or updated_at

    ordered = sorted(
        (item for item in payload if isinstance(item, dict)),
        key=sort_key,
        reverse=True,
    )
    urls: list[str] = []
    for item in ordered:
        if str(item.get("status") or "").lower() != "published":
            continue
        published_url = str(item.get("published_url") or "").strip()
        if not published_url.startswith(config.site_base_url):
            continue
        urls.append(published_url)
    return _dedupe_keep_order(urls)


def fetch_urls_from_sitemap(config: Config) -> list[str]:
    sitemap_url = f"{config.site_base_url}/sitemap.xml"
    response = requests.get(sitemap_url, timeout=config.timeout_seconds)
    response.raise_for_status()
    root = ElementTree.fromstring(response.text)
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls: list[str] = []
    for loc in root.findall(".//sm:url/sm:loc", namespaces=namespace):
        if not (loc.text or "").strip():
            continue
        current = loc.text.strip()
        if current.startswith(f"{config.site_base_url}/ko/post/"):
            urls.append(current)
    return _dedupe_keep_order(urls)


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def load_target_urls(config: Config) -> tuple[list[str], str]:
    try:
        urls = fetch_urls_from_cloudflare_posts(config)
        if urls:
            return urls, "cloudflare_posts_api"
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Failed to load /api/v1/cloudflare/posts: {exc}", file=sys.stderr)

    urls = fetch_urls_from_sitemap(config)
    return urls, "sitemap_fallback"


def select_daily_urls(config: Config, urls: list[str], state: dict[str, Any]) -> list[str]:
    requested_at: dict[str, str] = state["requested_at"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.retry_days)

    candidates: list[str] = []
    for url in urls:
        last = requested_at.get(url)
        if not last:
            candidates.append(url)
            continue
        try:
            parsed = datetime.fromisoformat(last.replace("Z", "+00:00"))
        except ValueError:
            candidates.append(url)
            continue
        if parsed < cutoff:
            candidates.append(url)

    return candidates[: config.daily_limit]


def build_google_session(config: Config) -> AuthorizedSession:
    credentials = service_account.Credentials.from_service_account_file(
        str(config.service_account_file),
        scopes=["https://www.googleapis.com/auth/indexing"],
    )
    return AuthorizedSession(credentials)


def submit_indexing_request(
    session: AuthorizedSession,
    *,
    url: str,
    timeout_seconds: int,
) -> tuple[bool, dict[str, Any]]:
    payload = {"url": url, "type": "URL_UPDATED"}
    response = session.post(INDEXING_ENDPOINT, json=payload, timeout=timeout_seconds)
    data: dict[str, Any]
    try:
        data = response.json()
    except ValueError:
        data = {"raw_text": response.text}
    if response.status_code >= 400:
        return False, {"status_code": response.status_code, "response": data}
    return True, {"status_code": response.status_code, "response": data}


def write_run_log(
    *,
    source: str,
    selected_urls: list[str],
    results: list[dict[str, Any]],
) -> Path:
    DEFAULT_LOG_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    path = DEFAULT_LOG_DIR / f"google-indexing-run-{now:%Y%m%dT%H%M%SZ}.json"
    body = {
        "run_at": now.isoformat(),
        "source": source,
        "selected_urls": selected_urls,
        "results": results,
    }
    with path.open("w", encoding="utf-8") as fh:
        json.dump(body, fh, ensure_ascii=False, indent=2)
    return path


def main() -> int:
    try:
        config = load_config()
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] config: {exc}", file=sys.stderr)
        return 2

    state = load_state(config.state_path)
    urls, source = load_target_urls(config)
    if not urls:
        print("[INFO] No URLs found from Cloudflare posts API or sitemap.")
        return 0

    selected = select_daily_urls(config, urls, state)
    if not selected:
        print("[INFO] No eligible URLs to request today.")
        return 0

    print(f"[INFO] source={source} total={len(urls)} selected={len(selected)} dry_run={config.dry_run}")

    results: list[dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    requested_at: dict[str, str] = state["requested_at"]

    if config.dry_run:
        for url in selected:
            print(f"[DRY_RUN] {url}")
            results.append({"url": url, "ok": True, "dry_run": True})
        write_run_log(source=source, selected_urls=selected, results=results)
        return 0

    session = build_google_session(config)
    success_count = 0
    for url in selected:
        ok, payload = submit_indexing_request(session, url=url, timeout_seconds=config.timeout_seconds)
        results.append({"url": url, "ok": ok, **payload})
        if ok:
            requested_at[url] = now_iso
            success_count += 1
            print(f"[OK] {url}")
        else:
            print(f"[FAIL] {url} status={payload.get('status_code')}", file=sys.stderr)

    save_state(config.state_path, state)
    log_path = write_run_log(source=source, selected_urls=selected, results=results)
    print(f"[INFO] success={success_count}/{len(selected)} log={log_path}")

    return 0 if success_count == len(selected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
