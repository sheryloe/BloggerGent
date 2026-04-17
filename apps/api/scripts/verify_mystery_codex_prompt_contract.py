from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = REPO_ROOT.parent.parent
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = os.environ.get(
        "BLOGGENT_DATABASE_URL",
        "postgresql://bloggent:bloggent@localhost:15432/bloggent",
    )
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import WorkflowStageType  # noqa: E402
from app.services.platform.blog_service import (  # noqa: E402
    get_blog,
    get_workflow_step,
    render_agent_prompt,
    sync_stage_prompts_from_profile_files,
)


def _safe_str(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify mystery Codex prompt contract without API calls.")
    parser.add_argument("--blog-id", type=int, default=35)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--report-path", default="", help="Optional JSON report output path.")
    return parser.parse_args(argv)


def _channel_prompt_paths() -> tuple[Path, Path]:
    return (
        PROJECT_ROOT / "prompts" / "channels" / "blogger" / "the-midnight-archives" / "channel.json",
        PROJECT_ROOT / "apps" / "api" / "prompts" / "channels" / "blogger" / "the-midnight-archives" / "channel.json",
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _check_channel_payload(path: Path, payload: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if _safe_str(payload.get("channel_id")) != "blogger:35":
        failures.append(f"{path}: channel_id must be blogger:35")
    steps = {str(item.get("stage_type") or ""): item for item in payload.get("steps", [])}
    required = {"topic_discovery", "article_generation", "image_prompt_generation", "image_generation"}
    missing = sorted(required - set(steps))
    if missing:
        failures.append(f"{path}: missing_steps={missing}")
        return failures

    if _safe_str(steps["topic_discovery"].get("provider_hint")) != "codex_cli":
        failures.append(f"{path}: topic_discovery.provider_hint must be codex_cli")
    if _safe_str(steps["article_generation"].get("provider_hint")) != "codex_cli":
        failures.append(f"{path}: article_generation.provider_hint must be codex_cli")
    if _safe_str(steps["image_prompt_generation"].get("provider_hint")) != "codex_cli":
        failures.append(f"{path}: image_prompt_generation.provider_hint must be codex_cli")
    if _safe_str(steps["article_generation"].get("planner_provider_hint")) != "codex_cli":
        failures.append(f"{path}: article_generation.planner_provider_hint must be codex_cli")
    if _safe_str(steps["article_generation"].get("pass_provider_hint")) != "codex_cli":
        failures.append(f"{path}: article_generation.pass_provider_hint must be codex_cli")
    if _safe_str(steps["article_generation"].get("structure_mode")) != "mystery_planner_pass4":
        failures.append(f"{path}: article_generation.structure_mode must be mystery_planner_pass4")
    if _safe_str(steps["image_generation"].get("locked_image_size")) != "1024x1024":
        failures.append(f"{path}: image_generation.locked_image_size must be 1024x1024")
    return failures


def run(args: argparse.Namespace) -> dict[str, Any]:
    runs = max(1, int(args.runs))
    report: dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "blog_id": int(args.blog_id),
        "runs": runs,
        "summary": {
            "checks": 0,
            "failed": 0,
            "passed": 0,
        },
        "failures": [],
        "run_checks": [],
    }

    inline_prompt_paths = [
        PROJECT_ROOT / "prompts" / "channels" / "blogger" / "the-midnight-archives" / "mystery_inline_collage_prompt.md",
        PROJECT_ROOT / "apps" / "api" / "prompts" / "channels" / "blogger" / "the-midnight-archives" / "mystery_inline_collage_prompt.md",
    ]
    for inline_path in inline_prompt_paths:
        report["summary"]["checks"] += 1
        if inline_path.exists():
            report["failures"].append(f"{inline_path}: inline prompt file must be removed")

    for channel_path in _channel_prompt_paths():
        report["summary"]["checks"] += 1
        if not channel_path.exists():
            report["failures"].append(f"{channel_path}: channel.json not found")
            continue
        failures = _check_channel_payload(channel_path, _load_json(channel_path))
        report["summary"]["checks"] += len(failures)
        report["failures"].extend(failures)

    with SessionLocal() as db:
        blog = get_blog(db, int(args.blog_id))
        if blog is None:
            raise RuntimeError(f"blog_not_found:{args.blog_id}")
        if _safe_str(blog.profile_key).lower() != "world_mystery":
            raise RuntimeError(f"blog_profile_not_mystery:{blog.profile_key}")
        sync_stage_prompts_from_profile_files(
            db,
            blog=blog,
            stage_types=(
                WorkflowStageType.TOPIC_DISCOVERY,
                WorkflowStageType.ARTICLE_GENERATION,
                WorkflowStageType.IMAGE_PROMPT_GENERATION,
            ),
        )
        blog = get_blog(db, int(args.blog_id))
        if blog is None:
            raise RuntimeError(f"blog_not_found_after_sync:{args.blog_id}")

        topic_step = get_workflow_step(blog, WorkflowStageType.TOPIC_DISCOVERY)
        article_step = get_workflow_step(blog, WorkflowStageType.ARTICLE_GENERATION)
        image_prompt_step = get_workflow_step(blog, WorkflowStageType.IMAGE_PROMPT_GENERATION)
        if not topic_step or not article_step or not image_prompt_step:
            raise RuntimeError("required_workflow_steps_missing")

        samples = [
            "db cooper mystery evidence review what we still know",
            "black dahlia murder forensic advances cold case",
            "dyatlov pass incident timeline evidence reanalysis",
        ]

        for index in range(runs):
            keyword = samples[index % len(samples)]
            replacements = {
                "topic_count": "5",
                "keyword": keyword,
                "planner_brief": "No planner brief provided.",
                "editorial_category_key": "case-files",
                "editorial_category_label": "Case Files",
                "editorial_category_guidance": "Focus on documented cases, timeline, and unresolved evidence gaps.",
                "article_title": "Mystery sample title",
                "article_excerpt": "Mystery sample excerpt sentence one. Mystery sample excerpt sentence two.",
                "article_context": "Case timeline, evidence matrix, and unresolved questions.",
            }
            topic_prompt = render_agent_prompt(db, blog, topic_step, **replacements)
            article_prompt = render_agent_prompt(db, blog, article_step, **replacements)
            image_prompt = render_agent_prompt(db, blog, image_prompt_step, **replacements)

            checks: list[dict[str, Any]] = [
                {
                    "name": "topic_prompt_json_shape",
                    "ok": '"topics"' in topic_prompt or '"topics":' in topic_prompt,
                },
                {
                    "name": "article_prompt_no_inline",
                    "ok": "inline_collage_prompt must be null or empty" in article_prompt.lower(),
                },
                {
                    "name": "article_prompt_single_hero",
                    "ok": "one hero image only" in article_prompt.lower() or "one main image only" in article_prompt.lower(),
                },
                {
                    "name": "image_prompt_square_1024",
                    "ok": "1024x1024" in image_prompt,
                },
                {
                    "name": "image_prompt_8_panel_contract",
                    "ok": "8-panel collage" in image_prompt.lower(),
                },
                {
                    "name": "image_prompt_gutters_grid_contract",
                    "ok": "visible white gutters" in image_prompt.lower() and "clean grid layout" in image_prompt.lower(),
                },
                {
                    "name": "image_prompt_optimizer_output_contract",
                    "ok": "only return the optimized prompt" in image_prompt.lower(),
                },
                {
                    "name": "image_prompt_no_inline_request",
                    "ok": "do not request inline" in image_prompt.lower() or "one main image only" in image_prompt.lower(),
                },
            ]
            report["run_checks"].append({"run": index + 1, "keyword": keyword, "checks": checks})
            report["summary"]["checks"] += len(checks)
            for item in checks:
                if not bool(item.get("ok")):
                    report["failures"].append(f"run{index + 1}:{item['name']}")

    report["summary"]["failed"] = len(report["failures"])
    report["summary"]["passed"] = report["summary"]["checks"] - report["summary"]["failed"]
    return report


def main() -> int:
    args = parse_args()
    report = run(args)
    report_path = (
        Path(args.report_path)
        if _safe_str(args.report_path)
        else PROJECT_ROOT / "storage" / "reports" / f"mystery-codex-contract-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(str(report_path))
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
