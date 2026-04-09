from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

DEFAULT_CATEGORIES = ("performance", "accessibility", "best-practices", "seo")
DEFAULT_WEIGHTS: dict[str, float] = {
    "performance": 0.55,
    "accessibility": 0.15,
    "best-practices": 0.15,
    "seo": 0.15,
}


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


def parse_lighthouse_report(
    report: Mapping[str, Any],
    *,
    weights: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    categories_payload = report.get("categories") if isinstance(report, Mapping) else None
    categories = categories_payload if isinstance(categories_payload, Mapping) else {}
    normalized_weights = dict(weights or DEFAULT_WEIGHTS)

    scores: dict[str, float | None] = {}
    for category in DEFAULT_CATEGORIES:
        category_payload = categories.get(category)
        raw_score = None
        if isinstance(category_payload, Mapping):
            raw_score = category_payload.get("score")
        scores[category] = _to_percentage(raw_score)

    total_weight = 0.0
    weighted_sum = 0.0
    for category, weight in normalized_weights.items():
        score = scores.get(category)
        if score is None:
            continue
        safe_weight = max(float(weight), 0.0)
        total_weight += safe_weight
        weighted_sum += safe_weight * score

    lighthouse_score = round(weighted_sum / total_weight, 1) if total_weight > 0 else None

    return {
        "lighthouse_score": lighthouse_score,
        "performance_score": scores.get("performance"),
        "accessibility_score": scores.get("accessibility"),
        "best_practices_score": scores.get("best-practices"),
        "seo_score": scores.get("seo"),
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
        "weights": dict(DEFAULT_WEIGHTS),
        "scores": parsed,
        "raw_report": raw_report,
    }
