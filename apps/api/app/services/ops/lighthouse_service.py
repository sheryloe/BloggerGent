from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

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


def _resolve_lighthouse_command() -> list[str]:
    custom = (os.getenv("LIGHTHOUSE_BIN") or "").strip()
    if custom:
        return [custom]

    lighthouse_path = shutil.which("lighthouse")
    if lighthouse_path:
        return [lighthouse_path]

    npx_path = shutil.which("npx")
    if npx_path:
        return [npx_path, "--yes", "lighthouse"]

    raise LighthouseAuditError("Cannot find Lighthouse CLI. Install Node.js + Lighthouse, or set LIGHTHOUSE_BIN.")


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
    target = str(url or "").strip()
    if not target:
        raise LighthouseAuditError("URL is required.")

    if form_factor not in {"mobile", "desktop"}:
        raise LighthouseAuditError("form_factor must be either 'mobile' or 'desktop'.")

    resolved_chrome_flags = (chrome_flags or os.getenv("LIGHTHOUSE_CHROME_FLAGS") or "").strip()
    if not resolved_chrome_flags:
        resolved_chrome_flags = "--headless=new --disable-gpu --no-first-run --no-default-browser-check"

    cmd_prefix = _resolve_lighthouse_command()
    with tempfile.TemporaryDirectory(prefix="lighthouse-") as tmp_dir:
        output_path = Path(tmp_dir) / "report.json"
        command = [
            *cmd_prefix,
            target,
            "--output=json",
            f"--output-path={output_path.as_posix()}",
            "--quiet",
            f"--only-categories={','.join(DEFAULT_CATEGORIES)}",
            f"--locale={locale}",
            f"--chrome-flags={resolved_chrome_flags}",
        ]
        if form_factor == "desktop":
            command.append("--preset=desktop")

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=max(timeout_seconds, 30),
        )

        if completed.returncode != 0:
            stderr = (completed.stderr or completed.stdout or "").strip()
            raise LighthouseAuditError(f"Lighthouse CLI failed: {stderr}")

        if not output_path.exists():
            raise LighthouseAuditError("Lighthouse report.json was not generated.")

        raw_report = json.loads(output_path.read_text(encoding="utf-8"))

    parsed = parse_lighthouse_report(raw_report)
    return {
        "url": target,
        "form_factor": form_factor,
        "weights": dict(LIGHTHOUSE_10_PERFORMANCE_METRIC_WEIGHTS),
        "scores": parsed,
        "raw_report": raw_report,
    }
