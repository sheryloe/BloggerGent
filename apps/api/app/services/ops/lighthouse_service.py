from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import httpx
from app.core.config import settings

DEFAULT_CATEGORIES = ("performance", "accessibility", "best-practices", "seo")
LIGHTHOUSE_10_PERFORMANCE_METRIC_WEIGHTS: dict[str, float] = {
    "first-contentful-paint": 0.10,
    "speed-index": 0.10,
    "largest-contentful-paint": 0.25,
    "total-blocking-time": 0.30,
    "cumulative-layout-shift": 0.25,
}
LIGHTHOUSE_SCORING_METHOD = "chrome-lighthouse-performance-category"


class LighthouseAuditError(RuntimeError):
    pass


def _safe_slug(value: object | None, *, fallback: str = "post") -> str:
    text = str(value or "").strip()
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", text).strip("-")
    return (normalized[:80] if normalized else fallback).strip("-") or fallback


def _optional_score(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def resolve_lighthouse_report_root(*, provider: str | None = None) -> Path:
    configured_root = str(os.getenv("LIGHTHOUSE_REPORT_ROOT") or "").strip()
    if configured_root:
        root = Path(configured_root)
    else:
        root = settings.storage_lighthouse_dir

    provider_slug = _safe_slug(provider, fallback="manual") if provider else ""
    return root / provider_slug if provider_slug else root


def write_lighthouse_raw_report(
    audit: Mapping[str, Any],
    *,
    provider: str,
    identity: str | int,
    slug: str | None = None,
    audited_at: datetime | None = None,
) -> Path:
    timestamp = (audited_at or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    report_root = resolve_lighthouse_report_root(provider=provider)
    report_root.mkdir(parents=True, exist_ok=True)
    report_path = report_root / f"{_safe_slug(provider)}-{_safe_slug(identity)}-{timestamp}-{_safe_slug(slug)}.json"
    report_path.write_text(json.dumps(audit.get("raw_report") or {}, ensure_ascii=False), encoding="utf-8")
    return report_path


def _required_scores(audit: Mapping[str, Any]) -> dict[str, Any]:
    scores = dict(audit.get("scores") or {})
    lighthouse_score = _optional_score(scores.get("lighthouse_score"))
    if lighthouse_score is None:
        raise LighthouseAuditError("Missing lighthouse_score in parsed report.")
    scores["lighthouse_score"] = lighthouse_score
    return scores


def _lighthouse_payload(
    *,
    version: str,
    url: str,
    form_factor: str,
    audit: Mapping[str, Any],
    report_path: Path,
    audited_at: datetime,
) -> dict[str, Any]:
    return {
        "version": version,
        "status": "ok",
        "url": url,
        "form_factor": form_factor,
        "measurement_source": audit.get("measurement_source") or "google_pagespeed_insights_lighthouse",
        "weights": dict(audit.get("weights") or {}),
        "scores": dict(audit.get("scores") or {}),
        "report_path": str(report_path),
        "audited_at": audited_at.isoformat(),
    }


def apply_lighthouse_audit_to_article(
    article: Any,
    audit: Mapping[str, Any],
    *,
    url: str,
    form_factor: str = "mobile",
    report_path: Path,
    audited_at: datetime | None = None,
) -> dict[str, Any]:
    resolved_audited_at = audited_at or datetime.now(timezone.utc)
    scores = _required_scores(audit)

    article.quality_lighthouse_score = scores["lighthouse_score"]
    article.quality_lighthouse_accessibility_score = _optional_score(scores.get("accessibility_score"))
    article.quality_lighthouse_best_practices_score = _optional_score(scores.get("best_practices_score"))
    article.quality_lighthouse_seo_score = _optional_score(scores.get("seo_score"))
    article.quality_lighthouse_last_audited_at = resolved_audited_at
    article.quality_lighthouse_payload = _lighthouse_payload(
        version="article-publish-lighthouse-v1",
        url=url,
        form_factor=form_factor,
        audit={**dict(audit), "scores": scores},
        report_path=report_path,
        audited_at=resolved_audited_at,
    )
    return dict(article.quality_lighthouse_payload)


def apply_lighthouse_audit_to_cloudflare_post(
    post: Any,
    audit: Mapping[str, Any],
    *,
    url: str,
    form_factor: str = "mobile",
    report_path: Path,
    audited_at: datetime | None = None,
) -> dict[str, Any]:
    resolved_audited_at = audited_at or datetime.now(timezone.utc)
    scores = _required_scores(audit)

    post.lighthouse_score = scores["lighthouse_score"]
    post.lighthouse_accessibility_score = _optional_score(scores.get("accessibility_score"))
    post.lighthouse_best_practices_score = _optional_score(scores.get("best_practices_score"))
    post.lighthouse_seo_score = _optional_score(scores.get("seo_score"))
    post.lighthouse_last_audited_at = resolved_audited_at
    post.lighthouse_payload = _lighthouse_payload(
        version="cloudflare-publish-lighthouse-v1",
        url=url,
        form_factor=form_factor,
        audit={**dict(audit), "scores": scores},
        report_path=report_path,
        audited_at=resolved_audited_at,
    )
    return dict(post.lighthouse_payload)


def run_required_article_lighthouse_audit(
    db: Any,
    article: Any,
    *,
    url: str | None,
    form_factor: str = "mobile",
    timeout_seconds: int = 180,
    commit: bool = True,
    required: bool = True,
) -> dict[str, Any]:
    target_url = str(url or "").strip()
    if not target_url:
        payload = {
            "version": "article-publish-lighthouse-v1",
            "status": "pending_url" if required else "unmeasured",
            "reason": "public_url_missing",
            "form_factor": form_factor,
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "measurement_source": "google_pagespeed_insights_lighthouse",
        }
        article.quality_lighthouse_payload = payload
        db.add(article)
        if commit:
            db.commit()
        else:
            db.flush()
        if not required:
            return payload
        raise LighthouseAuditError("lighthouse_pending_url: public URL is required before publish completion.")

    try:
        audit = run_lighthouse_audit(target_url, form_factor=form_factor, timeout_seconds=timeout_seconds)
        audited_at = datetime.now(timezone.utc)
        report_path = write_lighthouse_raw_report(
            audit,
            provider="blogger",
            identity=getattr(article, "id", "article"),
            slug=getattr(article, "slug", None) or getattr(article, "title", None),
            audited_at=audited_at,
        )
        payload = apply_lighthouse_audit_to_article(
            article,
            audit,
            url=target_url,
            form_factor=form_factor,
            report_path=report_path,
            audited_at=audited_at,
        )
    except LighthouseAuditError as exc:
        payload = {
            "version": "article-publish-lighthouse-v1",
            "status": "failed" if required else "unmeasured",
            "reason": str(exc),
            "url": target_url,
            "form_factor": form_factor,
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "measurement_source": "google_pagespeed_insights_lighthouse",
        }
        article.quality_lighthouse_payload = payload
        db.add(article)
        if commit:
            db.commit()
        else:
            db.flush()
        if not required:
            return payload
        raise
    except Exception as exc:  # noqa: BLE001
        payload = {
            "version": "article-publish-lighthouse-v1",
            "status": "failed" if required else "unmeasured",
            "reason": str(exc),
            "url": target_url,
            "form_factor": form_factor,
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "measurement_source": "google_pagespeed_insights_lighthouse",
        }
        article.quality_lighthouse_payload = payload
        db.add(article)
        if commit:
            db.commit()
        else:
            db.flush()
        if not required:
            return payload
        raise LighthouseAuditError(f"lighthouse_audit_failed: {exc}") from exc

    db.add(article)

    from app.services.ops.analytics_service import upsert_article_fact

    touched_months = upsert_article_fact(db, int(article.id), commit=False)
    payload["touched_months"] = touched_months
    if commit:
        db.commit()
    else:
        db.flush()
    return payload


def run_required_cloudflare_lighthouse_audit(
    db: Any,
    post: Any,
    *,
    url: str | None = None,
    form_factor: str = "mobile",
    timeout_seconds: int = 180,
    commit: bool = True,
    required: bool = True,
) -> dict[str, Any]:
    target_url = str(url or getattr(post, "url", "") or "").strip()
    if not target_url:
        payload = {
            "version": "cloudflare-publish-lighthouse-v1",
            "status": "pending_url" if required else "unmeasured",
            "reason": "public_url_missing",
            "form_factor": form_factor,
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "measurement_source": "google_pagespeed_insights_lighthouse",
        }
        post.lighthouse_payload = payload
        db.add(post)
        if commit:
            db.commit()
        else:
            db.flush()
        if not required:
            return payload
        raise LighthouseAuditError("lighthouse_pending_url: public URL is required before Cloudflare publish completion.")

    try:
        audit = run_lighthouse_audit(target_url, form_factor=form_factor, timeout_seconds=timeout_seconds)
        audited_at = datetime.now(timezone.utc)
        report_path = write_lighthouse_raw_report(
            audit,
            provider="cloudflare",
            identity=getattr(post, "remote_post_id", None) or getattr(post, "id", "post"),
            slug=getattr(post, "slug", None) or getattr(post, "title", None),
            audited_at=audited_at,
        )
        payload = apply_lighthouse_audit_to_cloudflare_post(
            post,
            audit,
            url=target_url,
            form_factor=form_factor,
            report_path=report_path,
            audited_at=audited_at,
        )
    except LighthouseAuditError as exc:
        payload = {
            "version": "cloudflare-publish-lighthouse-v1",
            "status": "failed" if required else "unmeasured",
            "reason": str(exc),
            "url": target_url,
            "form_factor": form_factor,
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "measurement_source": "google_pagespeed_insights_lighthouse",
        }
        post.lighthouse_payload = payload
        db.add(post)
        if commit:
            db.commit()
        else:
            db.flush()
        if not required:
            return payload
        raise
    except Exception as exc:  # noqa: BLE001
        payload = {
            "version": "cloudflare-publish-lighthouse-v1",
            "status": "failed" if required else "unmeasured",
            "reason": str(exc),
            "url": target_url,
            "form_factor": form_factor,
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "measurement_source": "google_pagespeed_insights_lighthouse",
        }
        post.lighthouse_payload = payload
        db.add(post)
        if commit:
            db.commit()
        else:
            db.flush()
        if not required:
            return payload
        raise LighthouseAuditError(f"lighthouse_audit_failed: {exc}") from exc

    db.add(post)
    if commit:
        db.commit()
    else:
        db.flush()
    return payload


def _to_percentage(score_value: Any) -> float | None:
    if score_value is None:
        return None
    try:
        score = float(score_value)
    except (TypeError, ValueError):
        return None
    if score < 0:
        return 0.0
    return round(min(score, 1.0) * 100.0, 1)


def _extract_numeric_value(audits: Mapping[str, Any], audit_id: str) -> float | None:
    audit_payload = audits.get(audit_id)
    if not isinstance(audit_payload, Mapping):
        return None
    numeric_value = audit_payload.get("numericValue")
    if numeric_value is None:
        return None
    try:
        return float(numeric_value)
    except (TypeError, ValueError):
        return None


def _extract_performance_metrics(audits: Mapping[str, Any]) -> dict[str, float | None]:
    return {
        "first_contentful_paint_ms": _extract_numeric_value(audits, "first-contentful-paint"),
        "speed_index_ms": _extract_numeric_value(audits, "speed-index"),
        "largest_contentful_paint_ms": _extract_numeric_value(audits, "largest-contentful-paint"),
        "total_blocking_time_ms": _extract_numeric_value(audits, "total-blocking-time"),
        "cumulative_layout_shift": _extract_numeric_value(audits, "cumulative-layout-shift"),
    }


def parse_lighthouse_report(
    report: Mapping[str, Any],
    *,
    weights: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    categories_payload = report.get("categories") if isinstance(report, Mapping) else None
    categories = categories_payload if isinstance(categories_payload, Mapping) else {}
    audits_payload = report.get("audits") if isinstance(report, Mapping) else None
    audits = audits_payload if isinstance(audits_payload, Mapping) else {}

    scores: dict[str, float | None] = {}
    for category in DEFAULT_CATEGORIES:
        category_payload = categories.get(category)
        raw_score = None
        if isinstance(category_payload, Mapping):
            raw_score = category_payload.get("score")
        scores[category] = _to_percentage(raw_score)

    lighthouse_score = scores.get("performance")
    performance_metric_weights = dict(weights or LIGHTHOUSE_10_PERFORMANCE_METRIC_WEIGHTS)

    return {
        "lighthouse_score": lighthouse_score,
        "performance_score": scores.get("performance"),
        "accessibility_score": scores.get("accessibility"),
        "best_practices_score": scores.get("best-practices"),
        "seo_score": scores.get("seo"),
        "scoring_method": LIGHTHOUSE_SCORING_METHOD,
        "performance_metric_weights": performance_metric_weights,
        "performance_metrics": _extract_performance_metrics(audits),
        "strategy": report.get("configSettings", {}).get("formFactor") if isinstance(report.get("configSettings"), Mapping) else None,
        "fetch_time": report.get("fetchTime"),
        "lhr_version": report.get("lighthouseVersion"),
        "final_url": report.get("finalUrl") or report.get("requestedUrl"),
    }


def run_lighthouse_audit(
    url: str,
    *,
    form_factor: str = "mobile",
    timeout_seconds: int = 180,
    chrome_flags: str | None = None,
    locale: str = "ko",
) -> dict[str, Any]:
    """Run Google's PageSpeed Insights Lighthouse audit.

    This intentionally does not invoke a local measurement process. Chrome DevTools
    plugin audits can be imported through the same parser/apply functions, while
    automated DB refreshes use Google's hosted Lighthouse result.
    """
    _ = timeout_seconds, chrome_flags, locale
    return run_pagespeed_insights_audit(url, strategy=form_factor)


def run_pagespeed_insights_audit(
    url: str,
    *,
    strategy: str = "mobile",
    api_key: str | None = None,
    categories: tuple[str, ...] = DEFAULT_CATEGORIES,
) -> dict[str, Any]:
    """
    Run PageSpeed Insights audit via Google API (HTTP).
    This is faster and doesn't require local Chrome/Lighthouse installation.
    """
    target = str(url or "").strip()
    if not target:
        raise LighthouseAuditError("URL is required.")

    if strategy not in {"mobile", "desktop"}:
        raise LighthouseAuditError("strategy must be either 'mobile' or 'desktop'.")

    actual_api_key = api_key or settings.pagespeed_api_key
    
    # Construct API URL
    psi_url = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
    params = {
        "url": target,
        "strategy": strategy,
        "category": list(categories),
        "locale": "ko",
    }
    if actual_api_key:
        params["key"] = actual_api_key

    try:
        with httpx.Client(timeout=180.0) as client:
            response = client.get(psi_url, params=params)
            
            if response.status_code == 429:
                raise LighthouseAuditError("PageSpeed Insights API rate limit exceeded (429).")
            
            response.raise_for_status()
            raw_report = response.json().get("lighthouseResult")
            
            if not raw_report:
                raise LighthouseAuditError("Invalid PageSpeed Insights API response: missing lighthouseResult.")

            parsed = parse_lighthouse_report(raw_report)
            return {
                "url": target,
                "form_factor": strategy,
                "measurement_source": "google_pagespeed_insights_lighthouse",
                "weights": dict(LIGHTHOUSE_10_PERFORMANCE_METRIC_WEIGHTS),
                "scores": parsed,
                "raw_report": raw_report,
            }
    except httpx.HTTPStatusError as exc:
        raise LighthouseAuditError(f"PageSpeed Insights API failed: {exc.response.text}") from exc
    except Exception as exc:
        raise LighthouseAuditError(f"PageSpeed Insights API request failed: {exc}") from exc
