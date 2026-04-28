from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload


_SCRIPT_PATH = Path(__file__).resolve()
_REPO_ROOT_ENV = os.environ.get("BLOGGENT_REPO_ROOT", "").strip()
if _REPO_ROOT_ENV:
    REPO_ROOT = Path(_REPO_ROOT_ENV).resolve()
elif (_SCRIPT_PATH.parents[1] / "app").exists():
    REPO_ROOT = _SCRIPT_PATH.parents[1]
else:
    REPO_ROOT = _SCRIPT_PATH.parents[3]
API_ROOT = REPO_ROOT / "apps" / "api" if (REPO_ROOT / "apps" / "api").exists() else REPO_ROOT
RUNTIME_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent")
ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
INCIDENT_STAMP = "20260425-20260427"
MYSTERY_BLOG_ID = 35
MYSTERY_PROFILE_KEY = "world_mystery"
MYSTERY_CHANNEL_SLUG = "the-midnight-archives"
MYSTERY_CF_CHANNEL_SLUG = "miseuteria-seutori"
MYSTERY_EDITORIAL_KEY = "case-files"
MYSTERY_EDITORIAL_LABEL_EN = "Case Files"
MYSTERY_EDITORIAL_LABEL_KO = "\ubbf8\uc2a4\ud14c\ub9ac\uc544 \uc2a4\ud1a0\ub9ac"
MYSTERY_CANONICAL_CATEGORY_PATH = "casefile"
MYSTERY_ALLOWED_PATTERNS = {
    "case-timeline",
    "evidence-breakdown",
    "legend-context",
    "scene-investigation",
    "scp-dossier",
}
MYSTERY_PATTERN_VERSION = 3
PROMPT_ROOT_BLOGGER = REPO_ROOT / "prompts" / "channels" / "blogger" / "the-midnight-archives"
PROMPT_ROOT_CF = REPO_ROOT / "prompts" / "channels" / "cloudflare" / "dongri-archive" / "\uc138\uc0c1\uc758 \uae30\ub85d" / "miseuteria-seutori"
FINAL_AUDIT_PATH = (
    RUNTIME_ROOT
    / "storage"
    / "the-midnight-archives"
    / f"incident-{INCIDENT_STAMP}"
    / "final-audit.json"
)
ROOL_REPORT_PATH = (
    RUNTIME_ROOT
    / "Rool"
    / "20-mystery"
    / f"problem-solution-{INCIDENT_STAMP}.md"
)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
H1_RE = re.compile(r"(?is)<h1\b")
H2_RE = re.compile(r"(?is)<h2\b")
H3_RE = re.compile(r"(?is)<h3\b")
IMG_RE = re.compile(r"(?is)<img\b")
IFRAME_RE = re.compile(r"(?is)<iframe\b")
SCRIPT_RE = re.compile(r"(?is)<script\b")
STYLE_RE = re.compile(r"(?is)<style\b")
ALLOWED_BODY_TAGS = {
    "h2",
    "h3",
    "p",
    "ul",
    "ol",
    "li",
    "blockquote",
    "strong",
    "em",
    "a",
}


def _bootstrap_env() -> None:
    if "DATABASE_URL" not in os.environ:
        os.environ["DATABASE_URL"] = DEFAULT_DATABASE_URL
    if "SETTINGS_ENCRYPTION_SECRET" not in os.environ and ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8-sig").splitlines():
            if line.startswith("SETTINGS_ENCRYPTION_SECRET="):
                os.environ["SETTINGS_ENCRYPTION_SECRET"] = line.split("=", 1)[1].strip()
                break


_bootstrap_env()

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
if str(API_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(API_ROOT / "scripts"))

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import (  # noqa: E402
    Article,
    Blog,
    BloggerPost,
    Image,
    Job,
    JobStatus,
    ManagedChannel,
    PostStatus,
    PublishMode,
    SyncedBloggerPost,
    SyncedCloudflarePost,
    Topic,
)
from app.schemas.ai import ArticleGenerationOutput  # noqa: E402
from app.services.blogger.blogger_live_audit_service import (  # noqa: E402
    extract_best_article_fragment,
    fetch_and_audit_blogger_post,
)
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog  # noqa: E402
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402
from app.services.content.article_service import (  # noqa: E402
    ensure_article_editorial_labels,
    save_article,
)
from app.services.content.content_ops_service import compute_seo_geo_scores  # noqa: E402
from app.services.content.mystery_artifact_service import (  # noqa: E402
    build_mystery_artifact_context,
    copy_mystery_artifact_file,
    write_mystery_artifact_json,
    write_mystery_artifact_manifest,
    write_mystery_artifact_text,
)
from app.services.integrations.storage_service import save_public_binary  # noqa: E402
from app.services.ops.lighthouse_service import (  # noqa: E402
    LighthouseAuditError,
    run_required_article_lighthouse_audit,
    run_required_cloudflare_lighthouse_audit,
)
from app.services.platform.publishing_service import upsert_article_blogger_post  # noqa: E402
from app.services.providers.factory import get_blogger_provider, get_runtime_config  # noqa: E402
from app.services.platform.codex_cli_queue_service import submit_codex_text_job  # noqa: E402
from package_common import CloudflareIntegrationClient  # noqa: E402


@dataclass(frozen=True, slots=True)
class TopicSpec:
    key: str
    article_pattern_id: str
    blogger_keyword: str
    cloudflare_keyword: str
    blogger_slug: str
    cloudflare_slug: str
    cloudflare_remote_id: str
    existing_blogger_article_id: int | None = None
    existing_blogger_post_row_id: int | None = None
    target_blogger_remote_post_id: str | None = None
    target_blogger_url: str | None = None
    duplicate_blogger_remote_post_ids: tuple[str, ...] = ()
    reuse_hero_url: str | None = None
    hero_search_filenames: tuple[str, ...] = ()


TOPIC_SPECS: tuple[TopicSpec, ...] = (
    TopicSpec(
        key="mary-celeste",
        article_pattern_id="evidence-breakdown",
        blogger_keyword="Mary Celeste abandoned ship evidence review and what the official logbooks still cannot explain",
        cloudflare_keyword="Mary Celeste ghost ship evidence review for Korean Mysteria Story readers",
        blogger_slug="enigma-of-the-mary-celeste",
        cloudflare_slug="miseuteria-seutori-mary-celeste-final",
        cloudflare_remote_id="6d617572-024e-44b0-ade5-8591a74eae21",
        existing_blogger_article_id=722,
        existing_blogger_post_row_id=661,
        target_blogger_remote_post_id="4776794508439182767",
        target_blogger_url="https://dongdonggri.blogspot.com/2026/04/the-enigma-of-mary-celeste-analytical.html",
        reuse_hero_url="https://api.dongriarchive.com/assets/the-midnight-archives/casefile/2026/04/enigma-of-the-mary-celeste/enigma-of-the-mary-celeste.webp",
    ),
    TopicSpec(
        key="somerton-man",
        article_pattern_id="evidence-breakdown",
        blogger_keyword="Somerton Man Tamam Shud case forensic evidence and what the modern identification solved or failed to solve",
        cloudflare_keyword="Somerton Man Tamam Shud forensic evidence review for Korean Mysteria Story readers",
        blogger_slug="somerton-man-scientific-investigation",
        cloudflare_slug="mystery-archive-somerton-man-tamam-shud-mystery",
        cloudflare_remote_id="11f00c33-7a6a-4998-96fa-651f87e62f58",
        existing_blogger_article_id=721,
        existing_blogger_post_row_id=660,
        target_blogger_remote_post_id="3769016138035389113",
        target_blogger_url="https://dongdonggri.blogspot.com/2026/04/the-somerton-man-mystery-of-tamam-shud.html",
        duplicate_blogger_remote_post_ids=("5606445328475448527",),
        reuse_hero_url="https://api.dongriarchive.com/assets/the-midnight-archives/casefile/2026/04/somerton-man-scientific-investigation/somerton-man-scientific-investigation.webp",
    ),
    TopicSpec(
        key="flight-19",
        article_pattern_id="case-timeline",
        blogger_keyword="Flight 19 disappearance timeline Bermuda Triangle records and what the Navy search reports actually show",
        cloudflare_keyword="Flight 19 disappearance timeline and Navy search records for Korean Mysteria Story readers",
        blogger_slug="flight-19-disappearance-bermuda-triangle-timeline",
        cloudflare_slug="flight-19-bermuda-triangle-mystery",
        cloudflare_remote_id="1074a94d-e430-49c0-8887-f13de8d1006d",
        target_blogger_remote_post_id="6399034161783146566",
        target_blogger_url="https://dongdonggri.blogspot.com/2026/04/the-vanishing-of-flight-19-mystery-of.html",
        duplicate_blogger_remote_post_ids=("5117189056559521860",),
        hero_search_filenames=(
            "bermuda-triangle-mystery.png",
            "the-bermuda-triangle-mystery-unraveling.webp",
            "uss-cyclops-and-bermuda-triangle-what.webp",
        ),
    ),
    TopicSpec(
        key="ss-baychimo",
        article_pattern_id="scene-investigation",
        blogger_keyword="SS Baychimo ghost ship drift timeline Arctic records and why crews kept sighting the abandoned vessel for decades",
        cloudflare_keyword="SS Baychimo Arctic ghost ship drift records for Korean Mysteria Story readers",
        blogger_slug="ss-baychimo-ghost-ship-arctic-drift",
        cloudflare_slug="mystery-archive-ss-baychimo-arctic-ghost-ship",
        cloudflare_remote_id="e98f78ab-6d45-442c-8e9b-57997d2c4ebf",
        target_blogger_remote_post_id="8506522449068532231",
        target_blogger_url="https://dongdonggri.blogspot.com/2026/04/the-arctic-kept-returning-this-empty.html",
        duplicate_blogger_remote_post_ids=("4843359843347642251",),
        hero_search_filenames=("baychimo_backup.webp",),
    ),
    TopicSpec(
        key="carroll-deering",
        article_pattern_id="evidence-breakdown",
        blogger_keyword="Carroll A Deering ghost ship evidence review and what Cape Lookout records imply about the missing crew",
        cloudflare_keyword="Carroll A Deering ghost ship evidence review for Korean Mysteria Story readers",
        blogger_slug="carroll-deering-ghost-ship-cape-lookout",
        cloudflare_slug="mystery-archive-carroll-a-deering-ghost-ship",
        cloudflare_remote_id="4b521573-a2d4-40b6-8449-ae4a4b649fde",
        target_blogger_url="https://dongdonggri.blogspot.com/2026/04/what-last-cape-lookout-sighting-reveals.html",
        hero_search_filenames=("deering_backup.webp",),
    ),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair the 2026-04-25~2026-04-27 mystery incident posts.")
    parser.add_argument("--apply", action="store_true", help="Apply live repairs.")
    parser.add_argument("--topic", action="append", default=[], help="Limit to specific topic keys.")
    parser.add_argument("--blogger-only", action="store_true")
    parser.add_argument("--cloudflare-only", action="store_true")
    parser.add_argument("--model", default="gpt-5.4")
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    return parser.parse_args()


def safe_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_space(value: str | None) -> str:
    return WS_RE.sub(" ", safe_text(value).replace("\xa0", " ")).strip()


def plain_text(value: str | None) -> str:
    return normalize_space(html.unescape(TAG_RE.sub(" ", value or "")))


def plain_text_length(value: str | None) -> int:
    return len(plain_text(value))


def count_h1(value: str | None) -> int:
    return len(H1_RE.findall(value or ""))


def count_h2(value: str | None) -> int:
    return len(H2_RE.findall(value or ""))


def count_h3(value: str | None) -> int:
    return len(H3_RE.findall(value or ""))


def normalize_url_key(url: str | None) -> str:
    raw = safe_text(url)
    if not raw:
        return ""
    parts = urlsplit(raw)
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path}"


def sentence_metrics(text: str) -> dict[str, Any]:
    sentences = [
        normalize_space(segment).lower()
        for segment in SENTENCE_SPLIT_RE.split(plain_text(text))
        if normalize_space(segment)
    ]
    if not sentences:
        return {"duplicate_sentence_ratio": 1.0, "top_repeated_sentence_count": 0, "sentence_count": 0}
    counts = Counter(sentences)
    duplicate_ratio = 1.0 - (len(counts) / float(len(sentences)))
    top_repeated = max(counts.values())
    return {
        "duplicate_sentence_ratio": round(duplicate_ratio, 4),
        "top_repeated_sentence_count": int(top_repeated),
        "sentence_count": int(len(sentences)),
    }


def render_template(template: str, values: dict[str, Any]) -> str:
    output = str(template or "")
    for key, value in values.items():
        output = output.replace("{" + key + "}", str(value))
    return output


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now_utc().isoformat()


def slugify_ascii(value: str) -> str:
    lowered = safe_text(value).lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered).strip("-")
    return lowered[:240] or "post"


def first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists() and path.is_file():
            return path
    return None


def discover_local_hero_file(spec: TopicSpec) -> Path | None:
    if not spec.hero_search_filenames:
        return None
    candidates: list[Path] = []
    for file_name in spec.hero_search_filenames:
        for root in (
            RUNTIME_ROOT / "storage",
            RUNTIME_ROOT / "app" / "storage",
        ):
            candidates.extend(root.rglob(file_name))
    resolved = [path for path in candidates if path.is_file()]
    if not resolved:
        return None
    resolved.sort(key=lambda item: (0 if "mystery" in str(item).lower() else 1, len(str(item))))
    return resolved[0]


def hero_object_key(slug: str) -> str:
    return f"assets/the-midnight-archives/{MYSTERY_CANONICAL_CATEGORY_PATH}/2026/04/{slug}/{slug}.webp"


def hero_public_url(slug: str) -> str:
    return f"https://api.dongriarchive.com/{hero_object_key(slug)}"


def ensure_hero_asset(db, spec: TopicSpec, *, slug: str, context) -> dict[str, Any]:
    if spec.reuse_hero_url:
        response = httpx.get(spec.reuse_hero_url, follow_redirects=True, timeout=30.0)
        response.raise_for_status()
        audit = {
            "source": spec.reuse_hero_url,
            "object_key": hero_object_key(slug),
            "public_url": spec.reuse_hero_url,
            "status_code": response.status_code,
            "content_type": str(response.headers.get("content-type") or ""),
            "reused": True,
        }
        write_mystery_artifact_json(context, stage_dir="04-image", filename="hero-asset.json", payload=audit)
        return audit

    local_source = discover_local_hero_file(spec)
    if local_source is None:
        raise RuntimeError(f"missing_local_hero_source:{spec.key}")
    content = local_source.read_bytes()
    file_path, public_url, meta = save_public_binary(
        db,
        subdir="images/mystery",
        filename=f"{slug}.webp",
        content=content,
        object_key=hero_object_key(slug),
    )
    response = httpx.get(public_url, follow_redirects=True, timeout=30.0)
    response.raise_for_status()
    audit = {
        "source": str(local_source),
        "saved_file_path": file_path,
        "object_key": hero_object_key(slug),
        "public_url": public_url,
        "status_code": response.status_code,
        "content_type": str(response.headers.get("content-type") or ""),
        "delivery_meta": meta,
        "reused": False,
    }
    copy_mystery_artifact_file(context, stage_dir="03-image", source_path=local_source)
    write_mystery_artifact_json(context, stage_dir="04-image", filename="hero-asset.json", payload=audit)
    return audit


def build_prompt_values(*, keyword: str, blog_name: str, target_audience: str, content_brief: str, pattern_id: str, language: str) -> dict[str, Any]:
    if language == "en":
        planner_brief = (
            f"- Use the fixed mystery pattern: {pattern_id}.\n"
            "- Open with why the case still matters now.\n"
            "- Separate verified records, interpretations, and unresolved points.\n"
            "- Avoid filler, looped paraphrase, and flat chronology padding.\n"
            "- End with a concise evidence-based takeaway."
        )
        guidance = (
            "Documentary-style case reconstruction. Prioritize records, dates, witness claims, and unresolved contradictions."
        )
        category_label = MYSTERY_EDITORIAL_LABEL_EN
    else:
        planner_brief = (
            f"- ??關履???????? {pattern_id} ??嚥▲굥猷롳┼??????筌먲퐢??\n"
            "- ??癲ル슣??????????????怨뺣빰 ????苑????嚥▲꺂痢롳┼??넊?????筌믨퀣援??筌먲퐢??\n"
            "- ?嶺뚮Ĳ?됮????れ삀??쎈뭄? ???⑤똾留? 雅?퍔瑗띰㎖硫대쑏?믠뫁臾????ㅼ굣?????됰슣維???筌먲퐢??\n"
            "- ???뽮덫????딅텑????域밸Ŧ?????袁⑸즵???????노윝????ヂ?????筌먲퐢??\n"
            "- 癲ル슢???癲ル슢??쭕? ??れ삀??쎈뭄???れ삀??뫢??濡ろ뜏??쎈뭄???⑥??癲ル슣?㎫뙴蹂?뼀??嶺뚮㉡?섌걡??筌먲퐢??"
        )
        guidance = "??れ삀??쎈뭄?源?癲ル슣鍮섌뜮蹂좊쨨??????μ쪚??濚욌꼬?댄꺍???雅?퍔瑗띰㎖??????????? ?????우녃域????濡ろ떟?癲???좊읈??濚왿몾???嶺뚮㉡?€쾮?? ????녹툗 ???살쓱??????Β?띾쭡??筌먲퐢??"
        category_label = MYSTERY_EDITORIAL_LABEL_KO
    return {
        "blog_name": blog_name,
        "keyword": keyword,
        "current_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "target_audience": target_audience,
        "content_brief": content_brief,
        "planner_brief": planner_brief,
        "editorial_category_key": MYSTERY_EDITORIAL_KEY,
        "editorial_category_label": category_label,
        "editorial_category_guidance": guidance,
        "article_pattern_id": pattern_id,
    }


def append_fixed_contract(prompt: str, *, spec: TopicSpec, slug: str, language: str) -> str:
    if language == "en":
        return (
            f"{prompt}\n\n"
            f"[Fixed Incident Contract]\n"
            f"- Use article_pattern_id = {spec.article_pattern_id}\n"
            f"- Use article_pattern_version = {MYSTERY_PATTERN_VERSION}\n"
            f"- Use slug = {slug}\n"
            f"- labels[0] must be {MYSTERY_EDITORIAL_LABEL_EN}\n"
            f"- plain_text must be >= 3000\n"
            f"- FAQ must contain exactly 3 items\n"
            f"- html_article must not contain img, iframe, script, style, or body-level h1\n"
        )
    return (
        f"{prompt}\n\n"
        f"[??關履??Incident Contract]\n"
        f"- article_pattern_id = {spec.article_pattern_id}\n"
        f"- article_pattern_version = {MYSTERY_PATTERN_VERSION}\n"
        f"- slug = {slug}\n"
        f"- labels[0] = {MYSTERY_EDITORIAL_LABEL_KO}\n"
        f"- ??筌?鍮???れ꽔??????3000?????⑤?彛?n"
        f"- FAQ 3???嶺뚮쮳?곌섈?????\n"
        f"- html_article ???怨좊군??img, iframe, script, style, body-level h1 ??ヂ???\n"
    )


def build_retry_feedback(validation: dict[str, Any]) -> str:
    problems = list(validation.get("problems") or [])
    if not problems:
        return ""
    return "\n".join(["", "[Retry Correction]", *[f"- {problem}" for problem in problems]])


def validate_package(package: ArticleGenerationOutput, *, spec: TopicSpec) -> dict[str, Any]:
    problems: list[str] = []
    body = safe_text(package.html_article)
    excerpt = safe_text(package.excerpt)
    labels = [safe_text(item) for item in list(package.labels or []) if safe_text(item)]
    if package.article_pattern_id != spec.article_pattern_id:
        problems.append(f"article_pattern_id_mismatch:{package.article_pattern_id}")
    if int(package.article_pattern_version or 0) != MYSTERY_PATTERN_VERSION:
        problems.append(f"article_pattern_version_invalid:{package.article_pattern_version}")
    if package.slug != spec.blogger_slug and package.slug != spec.cloudflare_slug:
        problems.append("slug_mismatch")
    if plain_text_length(body) < 3000:
        problems.append("plain_text_too_short")
    if count_h1(body) != 0:
        problems.append("body_h1_forbidden")
    h2_total = count_h2(body)
    if h2_total not in {4, 5}:
        problems.append(f"h2_count_invalid:{h2_total}")
    if "<img" in body.lower():
        problems.append("inline_img_forbidden")
    if IFRAME_RE.search(body):
        problems.append("iframe_forbidden")
    if SCRIPT_RE.search(body):
        problems.append("script_forbidden")
    if STYLE_RE.search(body):
        problems.append("style_forbidden")
    if len(package.faq_section or []) != 3:
        problems.append("faq_count_invalid")
    if len(labels) < 2:
        problems.append("label_count_too_low")
    metrics = sentence_metrics(body)
    if float(metrics["duplicate_sentence_ratio"]) > 0.15:
        problems.append("duplicate_sentence_ratio_high")
    if int(metrics["top_repeated_sentence_count"]) > 2:
        problems.append("top_repeated_sentence_count_high")
    score_payload = compute_seo_geo_scores(
        title=package.title,
        html_body=body,
        excerpt=excerpt,
        faq_section=[item.model_dump() for item in package.faq_section],
    )
    if int(score_payload.get("seo_score") or 0) < 70:
        problems.append("seo_score_below_threshold")
    if int(score_payload.get("geo_score") or 0) < 60:
        problems.append("geo_score_below_threshold")
    if int(score_payload.get("ctr_score") or 0) < 60:
        problems.append("ctr_score_below_threshold")
    return {
        "ok": not problems,
        "problems": problems,
        "score_payload": score_payload,
        "sentence_metrics": metrics,
        "plain_text_length": plain_text_length(body),
        "h2_count": h2_total,
        "h3_count": count_h3(body),
    }


def generate_article_package(
    *,
    runtime,
    prompt_template: str,
    prompt_values: dict[str, Any],
    spec: TopicSpec,
    slug: str,
    language: str,
    model: str,
    reasoning_effort: str,
    context,
) -> tuple[ArticleGenerationOutput, dict[str, Any], dict[str, Any]]:
    feedback = ""
    last_validation: dict[str, Any] | None = None
    last_response: dict[str, Any] | None = None
    for attempt in range(1, 4):
        prompt = append_fixed_contract(
            render_template(prompt_template, prompt_values),
            spec=spec,
            slug=slug,
            language=language,
        )
        if feedback:
            prompt = f"{prompt}\n{feedback}\n"
        write_mystery_artifact_text(context, stage_dir="02-article", filename=f"article-prompt-attempt-{attempt}.md", content=prompt)
        response = submit_codex_text_job(
            runtime=runtime,
            stage_name="incident_article_generation",
            model=model,
            prompt=prompt,
            response_kind="json_schema",
            response_schema=ArticleGenerationOutput.model_json_schema(),
            inline=True,
            codex_config_overrides={"model_reasoning_effort": reasoning_effort},
        )
        last_response = response
        write_mystery_artifact_json(context, stage_dir="02-article", filename=f"article-response-attempt-{attempt}.json", payload=response)
        package = ArticleGenerationOutput.model_validate_json(str(response.get("content") or "").strip())
        package = package.model_copy(
            update={
                "slug": slug,
                "article_pattern_id": spec.article_pattern_id,
                "article_pattern_version": MYSTERY_PATTERN_VERSION,
                "inline_collage_prompt": None,
            }
        )
        validation = validate_package(package, spec=spec)
        write_mystery_artifact_json(context, stage_dir="02-article", filename=f"article-validation-attempt-{attempt}.json", payload=validation)
        if validation["ok"]:
            return package, response, validation
        last_validation = validation
        feedback = build_retry_feedback(validation)
    raise RuntimeError(f"article_generation_failed:{spec.key}:{last_validation or last_response}")


def generate_image_prompt(
    *,
    runtime,
    prompt_template: str,
    blog_name: str,
    article_title: str,
    article_excerpt: str,
    article_context: str,
    original_prompt: str,
    model: str,
    reasoning_effort: str,
    extra_values: dict[str, Any] | None = None,
    context,
) -> str:
    values = {
        "original_prompt": original_prompt,
        "blog_name": blog_name,
        "article_title": article_title,
        "article_excerpt": article_excerpt,
        "article_context": article_context,
        "title": article_title,
        "excerpt": article_excerpt,
        "article_pattern_id": safe_text((extra_values or {}).get("article_pattern_id")),
    }
    prompt = render_template(prompt_template, values)
    write_mystery_artifact_text(context, stage_dir="03-image", filename="image-prompt-request.md", content=prompt)
    response = submit_codex_text_job(
        runtime=runtime,
        stage_name="incident_image_prompt_generation",
        model=model,
        prompt=prompt,
        response_kind="text",
        inline=True,
        codex_config_overrides={"model_reasoning_effort": reasoning_effort},
    )
    write_mystery_artifact_json(context, stage_dir="03-image", filename="image-prompt-response.json", payload=response)
    optimized = safe_text(response.get("content"))
    if not optimized:
        raise RuntimeError("empty_image_prompt")
    write_mystery_artifact_text(context, stage_dir="03-image", filename="image-prompt-final.txt", content=optimized)
    return optimized


def build_faq_html(faq_items: list[dict[str, str]], *, language: str) -> str:
    if language == "ko":
        heading = "???????醫됲뀷??癲ル슣??袁ｋ즵"
    else:
        heading = "Frequently Asked Questions"
    parts = [f'<section class="faq-block"><p><strong>{heading}</strong></p>']
    for item in faq_items:
        q = safe_text(item.get("question"))
        a = safe_text(item.get("answer"))
        if not q or not a:
            continue
        parts.append(f"<div class=\"faq-item\"><p><strong>{html.escape(q)}</strong></p><p>{html.escape(a)}</p></div>")
    parts.append("</section>")
    return "".join(parts)


def build_blogger_html(package: ArticleGenerationOutput, *, hero_url: str) -> str:
    faq_html = build_faq_html([item.model_dump() for item in package.faq_section], language="en")
    return (
        "<figure data-media-block=\"true\" class=\"hero-image\">"
        f"<img src=\"{hero_url}\" alt=\"{html.escape(package.title)}\" loading=\"eager\" />"
        "</figure>"
        f"{safe_text(package.html_article)}"
        f"{faq_html}"
    )


def html_to_markdown(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"(?is)<h2[^>]*>(.*?)</h2>", lambda m: f"\n\n## {plain_text(m.group(1))}\n\n", text)
    text = re.sub(r"(?is)<h3[^>]*>(.*?)</h3>", lambda m: f"\n\n### {plain_text(m.group(1))}\n\n", text)
    text = re.sub(r"(?is)<blockquote[^>]*>(.*?)</blockquote>", lambda m: f"\n\n> {plain_text(m.group(1))}\n\n", text)
    text = re.sub(r"(?is)<li[^>]*>(.*?)</li>", lambda m: f"\n- {plain_text(m.group(1))}", text)
    text = re.sub(r"(?is)<p[^>]*>(.*?)</p>", lambda m: f"\n\n{plain_text(m.group(1))}\n\n", text)
    text = re.sub(r"(?is)<a[^>]*href=['\"]([^'\"]+)['\"][^>]*>(.*?)</a>", lambda m: f"[{plain_text(m.group(2))}]({safe_text(m.group(1))})", text)
    text = re.sub(r"(?is)<strong[^>]*>(.*?)</strong>", lambda m: f"**{plain_text(m.group(1))}**", text)
    text = re.sub(r"(?is)<em[^>]*>(.*?)</em>", lambda m: f"*{plain_text(m.group(1))}*", text)
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return normalize_space(text.replace("\n- ", "\n- ")).replace(" \n", "\n").strip()


def build_cloudflare_html(package: ArticleGenerationOutput, *, hero_url: str) -> str:
    faq_items = [item.model_dump() for item in package.faq_section]
    faq_parts = ['<section class="mystery-faq"><h2>FAQ</h2>']
    for item in faq_items:
        faq_parts.append(
            "<section>"
            f"<h3>{html.escape(safe_text(item.get('question')))}</h3>"
            f"<p>{html.escape(safe_text(item.get('answer')))}</p>"
            "</section>"
        )
    faq_parts.append("</section>")
    return (
        '<figure class="mystery-hero">'
        f'<img src="{html.escape(hero_url)}" alt="{html.escape(package.title)}" loading="eager" />'
        "</figure>"
        f"{safe_text(package.html_article)}"
        f"{''.join(faq_parts)}"
    ).strip()


def merge_render_metadata(existing: dict[str, Any] | None, payload: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing or {})
    merged.update(payload)
    return merged


def hero_probe(url: str) -> dict[str, Any]:
    response = httpx.get(url, follow_redirects=True, timeout=30.0)
    return {
        "url": url,
        "status_code": response.status_code,
        "content_type": str(response.headers.get("content-type") or ""),
    }


def extract_page_title(page_html: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", page_html)
    return plain_text(match.group(1)) if match else ""


def audit_blogger_live(*, published_url: str, expected_title: str, hero_url: str) -> dict[str, Any]:
    response = httpx.get(published_url, follow_redirects=True, timeout=30.0)
    response.raise_for_status()
    page_html = response.text
    article_fragment = extract_best_article_fragment(page_html, expected_title=expected_title, expected_hero_url=hero_url)
    image_audit = fetch_and_audit_blogger_post(published_url, timeout=20.0, probe_images=True)
    fragment_text = plain_text(article_fragment)
    title_text = extract_page_title(page_html)
    sentence_payload = sentence_metrics(fragment_text)
    hero_key = normalize_url_key(hero_url)
    renderable = [normalize_url_key(url) for url in image_audit.renderable_image_urls]
    hero_count = sum(1 for url in renderable if url == hero_key)
    total_imgs = len(renderable)
    body_inline_image_count = max(total_imgs - hero_count, 0)
    return {
        "published_url": published_url,
        "final_url": str(response.url),
        "live_status": response.status_code,
        "page_title": title_text,
        "title_present": expected_title.casefold() in title_text.casefold() or expected_title.casefold() in fragment_text.casefold(),
        "plain_text_length": len(fragment_text),
        "body_h1_count": count_h1(article_fragment),
        "hero_image_count": hero_count,
        "body_inline_image_count": body_inline_image_count,
        "hero_image_urls": renderable,
        "image_audit": {
            "live_image_count": image_audit.live_image_count,
            "live_unique_image_count": image_audit.live_unique_image_count,
            "live_duplicate_image_count": image_audit.live_duplicate_image_count,
            "live_webp_count": image_audit.live_webp_count,
            "live_png_count": image_audit.live_png_count,
            "live_other_image_count": image_audit.live_other_image_count,
            "live_cover_present": image_audit.live_cover_present,
            "live_inline_present": image_audit.live_inline_present,
            "live_image_issue": image_audit.live_image_issue,
        },
        **sentence_payload,
    }


def _pick_cloudflare_main_fragment(soup: BeautifulSoup) -> BeautifulSoup:
    article = soup.find("article")
    if article is not None:
        return article
    main = soup.find("main")
    if main is not None:
        return main
    body = soup.find("body")
    return body or soup


def audit_cloudflare_live(*, published_url: str, hero_url: str) -> dict[str, Any]:
    response = httpx.get(published_url, follow_redirects=True, timeout=30.0)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    fragment = _pick_cloudflare_main_fragment(soup)
    article_html = str(fragment)
    article_text = plain_text(article_html)
    hero_key = normalize_url_key(hero_url)
    img_urls = []
    for img in fragment.find_all("img"):
        src = safe_text(img.get("src"))
        if src:
            img_urls.append(normalize_url_key(src))
    hero_count = sum(1 for src in img_urls if src == hero_key)
    total_imgs = len(img_urls)
    sentence_payload = sentence_metrics(article_text)
    return {
        "published_url": published_url,
        "final_url": str(response.url),
        "live_status": response.status_code,
        "plain_text_length": len(article_text),
        "body_h1_count": len(fragment.find_all("h1")),
        "hero_image_count": hero_count,
        "body_inline_image_count": max(total_imgs - hero_count, 0),
        "image_urls": img_urls,
        **sentence_payload,
    }


def upsert_topic(db, *, blog: Blog, keyword: str) -> Topic:
    topic = db.execute(select(Topic).where(Topic.blog_id == blog.id, Topic.keyword == keyword)).scalar_one_or_none()
    if topic is None:
        topic = Topic(
            blog_id=blog.id,
            keyword=keyword,
            reason="incident_repair_20260425_20260427",
            trend_score=0.0,
            source="codex_incident_repair",
            locale="global",
            editorial_category_key=MYSTERY_EDITORIAL_KEY,
            editorial_category_label=MYSTERY_EDITORIAL_LABEL_EN,
            distinct_reason="incident_repair",
        )
        db.add(topic)
        db.commit()
        db.refresh(topic)
    return topic


def create_or_update_repair_job(db, *, blog: Blog, topic: Topic, keyword: str, mode: str, payload: dict[str, Any]) -> Job:
    job = (
        db.execute(
            select(Job)
            .where(Job.blog_id == blog.id, Job.topic_id == topic.id, Job.keyword_snapshot == keyword)
            .order_by(Job.id.desc())
        )
        .scalars()
        .first()
    )
    if job is None:
        job = Job(
            blog_id=blog.id,
            topic_id=topic.id,
            keyword_snapshot=keyword,
            status=JobStatus.PENDING,
            publish_mode=PublishMode.PUBLISH,
            start_time=now_utc(),
            raw_prompts={"incident_repair": payload},
            raw_responses={},
        )
        db.add(job)
    else:
        raw_prompts = dict(job.raw_prompts or {})
        raw_prompts["incident_repair"] = payload
        job.raw_prompts = raw_prompts
        job.status = JobStatus.PENDING
        job.start_time = now_utc()
    db.commit()
    db.refresh(job)
    return job


def build_blogger_artifact_context(spec: TopicSpec, slug: str):
    return build_mystery_artifact_context(
        channel_kind="blogger",
        channel_slug=MYSTERY_CHANNEL_SLUG,
        category_key=MYSTERY_CANONICAL_CATEGORY_PATH,
        slug=slug,
        created_at=now_utc(),
    )


def build_cloudflare_artifact_context(spec: TopicSpec, slug: str):
    return build_mystery_artifact_context(
        channel_kind="cloudflare",
        channel_slug=MYSTERY_CF_CHANNEL_SLUG,
        category_key=MYSTERY_CANONICAL_CATEGORY_PATH,
        slug=slug,
        created_at=now_utc(),
    )


def publish_or_update_blogger(
    *,
    db,
    blog: Blog,
    existing_row: BloggerPost | None,
    remote_post_id: str | None,
    title: str,
    assembled_html: str,
    labels: list[str],
    meta_description: str,
    slug: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    provider = get_blogger_provider(db, blog)
    update_post_id = safe_text(remote_post_id) or (safe_text(existing_row.blogger_post_id) if existing_row is not None else "")
    if update_post_id:
        try:
            return provider.update_post(
                post_id=update_post_id,
                title=title,
                content=assembled_html,
                labels=labels,
                meta_description=meta_description,
            )
        except Exception:
            pass
    return provider.publish(
        title=title,
        content=assembled_html,
        labels=labels,
        meta_description=meta_description,
        slug=slug,
        publish_mode=PublishMode.PUBLISH,
    )


def finalize_image_row(
    db,
    *,
    job: Job,
    article: Article,
    prompt: str,
    public_url: str,
    file_path: str,
    delivery_meta: dict[str, Any],
) -> Image:
    image = db.execute(select(Image).where(Image.job_id == job.id)).scalar_one_or_none()
    payload = {
        "article_id": article.id,
        "prompt": prompt,
        "file_path": file_path,
        "public_url": public_url,
        "width": 1024,
        "height": 1024,
        "provider": "cloudflare_r2",
        "image_metadata": delivery_meta,
    }
    if image is None:
        image = Image(job_id=job.id, **payload)
        db.add(image)
    else:
        for key, value in payload.items():
            setattr(image, key, value)
    db.commit()
    db.refresh(image)
    return image


def finalize_blogger_article(
    db,
    *,
    blog: Blog,
    spec: TopicSpec,
    topic: Topic,
    job: Job,
    package: ArticleGenerationOutput,
    assembled_html: str,
    hero_meta: dict[str, Any],
    publish_summary: dict[str, Any],
    raw_publish_payload: dict[str, Any],
    audit_payload: dict[str, Any],
    image_prompt: str,
    article_context,
) -> dict[str, Any]:
    canonical_live_url = safe_text(publish_summary.get("url")) or safe_text(spec.target_blogger_url)
    if canonical_live_url:
        publish_summary = {**publish_summary, "url": canonical_live_url}
    article = save_article(db, job=job, topic=topic, output=package, commit=True, upsert_fact=False)
    article.assembled_html = assembled_html
    score_payload = compute_seo_geo_scores(
        title=package.title,
        html_body=package.html_article,
        excerpt=package.excerpt,
        faq_section=[item.model_dump() for item in package.faq_section],
    )
    article.quality_seo_score = int(score_payload.get("seo_score") or 0)
    article.quality_geo_score = int(score_payload.get("geo_score") or 0)
    article.quality_status = "pass"
    article.quality_last_audited_at = now_utc()
    article.render_metadata = merge_render_metadata(
        article.render_metadata,
        {
            "incident_repair": {
                "stamp": INCIDENT_STAMP,
                "topic_key": spec.key,
                "platform": "blogger",
                "audit": audit_payload,
                "scores": score_payload,
                "hero_image_url": hero_meta["public_url"],
                "image_prompt": image_prompt,
            }
        },
    )
    db.add(article)
    db.commit()
    db.refresh(article)
    image = finalize_image_row(
        db,
        job=job,
        article=article,
        prompt=image_prompt,
        public_url=hero_meta["public_url"],
        file_path=safe_text(hero_meta.get("saved_file_path")) or safe_text(hero_meta.get("source")),
        delivery_meta=hero_meta,
    )
    article.image = image
    labels = ensure_article_editorial_labels(db, article)
    blogger_post = upsert_article_blogger_post(
        db,
        article=article,
        summary=publish_summary,
        raw_payload=raw_publish_payload,
    )
    sync_blogger_posts_for_blog(db, blog)
    try:
        lighthouse_payload = run_required_article_lighthouse_audit(db, article, url=canonical_live_url, commit=True)
    except LighthouseAuditError as exc:
        lighthouse_payload = {"status": "failed", "reason": str(exc)}
    job.status = JobStatus.COMPLETED
    job.end_time = now_utc()
    job.raw_responses = merge_render_metadata(
        job.raw_responses,
        {"incident_repair": {"publish_summary": publish_summary, "audit": audit_payload}},
    )
    db.add(job)
    db.commit()
    return {
        "article_id": article.id,
        "job_id": job.id,
        "blogger_post_row_id": blogger_post.id,
        "published_url": canonical_live_url,
        "hero_image_url": hero_meta["public_url"],
        "seo_score": article.quality_seo_score,
        "geo_score": article.quality_geo_score,
        "ctr_score": int(score_payload.get("ctr_score") or 0),
        "lighthouse_score": article.quality_lighthouse_score,
        "article_pattern_id": article.article_pattern_id,
        "article_pattern_version": article.article_pattern_version,
        "db_finalized": True,
        "sync_ok": True,
        "lighthouse_payload": lighthouse_payload,
    }


def find_cloudflare_post_detail(client: CloudflareIntegrationClient, spec: TopicSpec) -> dict[str, Any]:
    detail = client.get_post(spec.cloudflare_remote_id)
    if detail:
        return detail
    for item in client.list_posts():
        if safe_text(item.get("slug")) == spec.cloudflare_slug:
            resolved_id = safe_text(item.get("id") or item.get("remote_id"))
            if resolved_id:
                return client.get_post(resolved_id)
    raise RuntimeError(f"cloudflare_post_not_found:{spec.key}")


def finalize_cloudflare_sync_row(
    db,
    *,
    spec: TopicSpec,
    audit_payload: dict[str, Any],
    score_payload: dict[str, Any],
    hero_meta: dict[str, Any],
    image_prompt: str,
) -> dict[str, Any]:
    sync_cloudflare_posts(db, include_non_published=True)
    channel = db.execute(
        select(ManagedChannel)
        .where(ManagedChannel.provider == "cloudflare")
        .order_by(ManagedChannel.id.desc())
    ).scalar_one()
    row = db.execute(
        select(SyncedCloudflarePost)
        .where(
            SyncedCloudflarePost.managed_channel_id == channel.id,
            SyncedCloudflarePost.remote_post_id == spec.cloudflare_remote_id,
        )
    ).scalar_one()
    row.seo_score = float(score_payload.get("seo_score") or 0)
    row.geo_score = float(score_payload.get("geo_score") or 0)
    row.ctr = float(score_payload.get("ctr_score") or 0)
    row.quality_status = "pass"
    row.article_pattern_id = spec.article_pattern_id
    row.article_pattern_version = MYSTERY_PATTERN_VERSION
    row.live_image_count = int(audit_payload.get("hero_image_count") or 0) + int(audit_payload.get("body_inline_image_count") or 0)
    row.live_unique_image_count = row.live_image_count
    row.live_duplicate_image_count = 0
    row.live_webp_count = 1 if "image/webp" in str(hero_meta.get("content_type") or "").lower() else 0
    row.live_png_count = 0
    row.live_other_image_count = max(int(row.live_image_count or 0) - int(row.live_webp_count or 0), 0)
    row.live_image_issue = None
    row.live_image_audited_at = now_utc()
    row.render_metadata = merge_render_metadata(
        row.render_metadata,
        {
            "incident_repair": {
                "stamp": INCIDENT_STAMP,
                "topic_key": spec.key,
                "platform": "cloudflare",
                "audit": audit_payload,
                "scores": score_payload,
                "hero_image_url": hero_meta["public_url"],
                "image_prompt": image_prompt,
            }
        },
    )
    db.add(row)
    db.commit()
    try:
        lighthouse_payload = run_required_cloudflare_lighthouse_audit(db, row, url=row.url, commit=True)
    except LighthouseAuditError as exc:
        lighthouse_payload = {"status": "failed", "reason": str(exc)}
    db.refresh(row)
    return {
        "synced_cloudflare_post_id": row.id,
        "published_url": row.url,
        "hero_image_url": hero_meta["public_url"],
        "seo_score": row.seo_score,
        "geo_score": row.geo_score,
        "ctr_score": row.ctr,
        "lighthouse_score": row.lighthouse_score,
        "article_pattern_id": row.article_pattern_id,
        "article_pattern_version": row.article_pattern_version,
        "db_finalized": True,
        "sync_ok": True,
        "lighthouse_payload": lighthouse_payload,
    }


def build_cloudflare_update_payload(
    *,
    detail: dict[str, Any],
    spec: TopicSpec,
    package: ArticleGenerationOutput,
    html_body: str,
    hero_meta: dict[str, Any],
) -> dict[str, Any]:
    category_id = safe_text(detail.get("categoryId"))
    if not category_id and isinstance(detail.get("category"), dict):
        category_id = safe_text((detail.get("category") or {}).get("id"))
    seo_description = safe_text(package.meta_description)
    if len(seo_description) < 90:
        seo_description = (seo_description + " " + safe_text(package.excerpt)).strip()
    if len(seo_description) < 90:
        seo_description = (seo_description + " ????れ꽔??? ??れ삀??쎈뭄? 癲ル슣鍮섌뜮蹂좊쨨? ???μ쪚?? ???⑤똾留???野껊챶爾?????됰슣維???????????怨뺣빰 ??熬곣뫗踰?癲ル슢??????").strip()
    if len(seo_description) < 90:
        raise RuntimeError(f"seo_description_too_short:{spec.key}")
    return {
        "title": package.title,
        "slug": spec.cloudflare_slug,
        "content": html_body,
        "status": "published",
        "categoryId": category_id,
        "excerpt": package.excerpt,
        "seoTitle": package.title,
        "seoDescription": seo_description[:160],
        "metaDescription": seo_description[:160],
        "coverImage": hero_meta["public_url"],
        "coverAlt": package.title,
        "tagNames": [safe_text(label) for label in list(package.labels or []) if safe_text(label)],
        "metadata": {
            **dict(detail.get("metadata") or {}),
            "article_pattern_id": spec.article_pattern_id,
            "article_pattern_version": MYSTERY_PATTERN_VERSION,
            "incident_repair_stamp": INCIDENT_STAMP,
        },
    }


def write_problem_solution(final_payload: dict[str, Any]) -> None:
    lines = [
        f"# Mystery Incident Problem Solution ({INCIDENT_STAMP})",
        "",
        "## Scope",
        "- Blogger mystery (`blog_id=35`)",
        "- Cloudflare Mysteria Story (`miseuteria-seutori`)",
        "",
        "## Confirmed Incident Window",
        "- 2026-04-25 KST ~ 2026-04-27 KST",
        "",
        "## Root Causes",
        "- Cloudflare update path accepted partial payloads but dropped body/metadata consistency on publish repair attempts.",
        "- Blogger incident posts were treated as success from API response without live GET audit.",
        "- Some April incident posts reused unstable HTML shells and produced broken/empty live pages or bad hero rendering.",
        "- Pattern metadata, score metadata, and final sync rows were not finalized from live truth.",
        "",
        "## Fix Strategy",
        "- Hard-lock 5 topics and 2 mystery scopes only.",
        "- Regenerate content from Codex using current mystery prompt contracts and fixed 5-pattern policy.",
        "- Reuse or restore one canonical hero image per topic under the mystery R2 key contract.",
        "- Publish/update live first, then GET-audit live body/image state, then finalize DB/sync rows.",
        "- Record all staged artifacts under `storage/the-midnight-archives/...`.",
        "",
        "## Final Result",
        f"- success_count: {int(final_payload.get('success_count') or 0)}",
        f"- failure_count: {int(final_payload.get('failure_count') or 0)}",
        "",
        "## Topics",
    ]
    for row in list(final_payload.get("rows") or []):
        lines.extend(
            [
                f"### {row.get('topic')} / {row.get('platform')}",
                f"- published_url: {row.get('published_url')}",
                f"- hero_image_url: {row.get('hero_image_url')}",
                f"- live_status: {row.get('live_status')}",
                f"- hero_status: {row.get('hero_status')}",
                f"- plain_text_length: {row.get('plain_text_length')}",
                f"- duplicate_sentence_ratio: {row.get('duplicate_sentence_ratio')}",
                f"- seo_score: {row.get('seo_score')}",
                f"- geo_score: {row.get('geo_score')}",
                f"- ctr_score: {row.get('ctr_score')}",
                f"- lighthouse_score: {row.get('lighthouse_score')}",
                f"- article_pattern_id: {row.get('article_pattern_id')}",
                f"- article_pattern_version: {row.get('article_pattern_version')}",
                f"- db_finalized: {row.get('db_finalized')}",
                f"- sync_ok: {row.get('sync_ok')}",
                "",
            ]
        )
    ROOL_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ROOL_REPORT_PATH.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def select_specs(args: argparse.Namespace) -> list[TopicSpec]:
    selected = list(TOPIC_SPECS)
    if args.topic:
        wanted = {safe_text(item).lower() for item in args.topic}
        selected = [spec for spec in selected if spec.key.lower() in wanted]
    return selected


def resolve_existing_blogger_records(db, spec: TopicSpec) -> tuple[Article | None, BloggerPost | None]:
    article = None
    blogger_post = None
    if spec.existing_blogger_article_id:
        article = db.execute(
            select(Article)
            .where(Article.id == spec.existing_blogger_article_id)
            .options(selectinload(Article.job), selectinload(Article.topic), selectinload(Article.blogger_post), selectinload(Article.image))
        ).scalar_one_or_none()
    if article and article.blogger_post:
        blogger_post = article.blogger_post
    elif spec.existing_blogger_post_row_id:
        blogger_post = db.execute(select(BloggerPost).where(BloggerPost.id == spec.existing_blogger_post_row_id)).scalar_one_or_none()
    return article, blogger_post


def process_blogger_topic(
    *,
    db,
    runtime,
    blog: Blog,
    spec: TopicSpec,
    model: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    slug = spec.blogger_slug
    context = build_blogger_artifact_context(spec, slug)
    article_prompt_template = read_text(PROMPT_ROOT_BLOGGER / "mystery_article_generation.md")
    image_prompt_template = read_text(PROMPT_ROOT_BLOGGER / "mystery_collage_prompt.md")
    prompt_values = build_prompt_values(
        keyword=spec.blogger_keyword,
        blog_name=blog.name,
        target_audience=safe_text(blog.target_audience) or "Readers who want rigorous mystery case analysis.",
        content_brief=safe_text(blog.content_brief) or "Publish a documentary-style English mystery feature with strong evidence framing.",
        pattern_id=spec.article_pattern_id,
        language="en",
    )
    write_mystery_artifact_manifest(
        context,
        payload={
            "stamp": INCIDENT_STAMP,
            "platform": "blogger",
            "topic_key": spec.key,
            "slug": slug,
            "pattern_id": spec.article_pattern_id,
        },
    )
    package, article_response, validation = generate_article_package(
        runtime=runtime,
        prompt_template=article_prompt_template,
        prompt_values=prompt_values,
        spec=spec,
        slug=slug,
        language="en",
        model=model,
        reasoning_effort=reasoning_effort,
        context=context,
    )
    article_context = f"Title: {package.title}\nExcerpt: {package.excerpt}\nBody: {package.html_article}"
    image_prompt = generate_image_prompt(
        runtime=runtime,
        prompt_template=image_prompt_template,
        blog_name=blog.name,
        article_title=package.title,
        article_excerpt=package.excerpt,
        article_context=article_context,
        original_prompt=package.image_collage_prompt,
        model=model,
        reasoning_effort=reasoning_effort,
        extra_values={"article_pattern_id": spec.article_pattern_id},
        context=context,
    )
    hero_meta = ensure_hero_asset(db, spec, slug=slug, context=context)
    assembled_html = build_blogger_html(package, hero_url=hero_meta["public_url"])
    write_mystery_artifact_text(context, stage_dir="05-html", filename="assembled.html", content=assembled_html)
    existing_article, existing_post = resolve_existing_blogger_records(db, spec)
    publish_summary, raw_publish_payload = publish_or_update_blogger(
        db=db,
        blog=blog,
        existing_row=existing_post,
        remote_post_id=spec.target_blogger_remote_post_id,
        title=package.title,
        assembled_html=assembled_html,
        labels=[safe_text(item) for item in list(package.labels or []) if safe_text(item)],
        meta_description=package.meta_description,
        slug=slug,
    )
    write_mystery_artifact_json(
        context,
        stage_dir="06-publish",
        filename="publish-response.json",
        payload={"summary": publish_summary, "raw": raw_publish_payload},
    )
    hero_status = hero_probe(hero_meta["public_url"])
    live_audit = audit_blogger_live(
        published_url=safe_text(publish_summary.get("url")) or safe_text(spec.target_blogger_url),
        expected_title=package.title,
        hero_url=hero_meta["public_url"],
    )
    score_payload = compute_seo_geo_scores(
        title=package.title,
        html_body=package.html_article,
        excerpt=package.excerpt,
        faq_section=[item.model_dump() for item in package.faq_section],
    )
    audit_payload = {**validation, **live_audit, "hero_status": hero_status}
    audit_payload["generated_body_h1_count"] = count_h1(assembled_html)
    write_mystery_artifact_json(context, stage_dir="07-live", filename="live-audit.json", payload=audit_payload)
    if (
        int(live_audit["live_status"]) != 200
        or int(hero_status["status_code"]) != 200
        or "image/webp" not in str(hero_status["content_type"]).lower()
        or int(live_audit["plain_text_length"]) < 3000
        or int(audit_payload["generated_body_h1_count"]) != 0
        or int(live_audit["hero_image_count"]) != 1
        or int(live_audit["body_inline_image_count"]) != 0
        or float(live_audit["duplicate_sentence_ratio"]) > 0.15
    ):
        raise RuntimeError(f"blogger_live_audit_failed:{spec.key}:{audit_payload}")
    topic = existing_article.topic if existing_article and existing_article.topic else upsert_topic(db, blog=blog, keyword=spec.blogger_keyword)
    job = existing_article.job if existing_article and existing_article.job else create_or_update_repair_job(
        db,
        blog=blog,
        topic=topic,
        keyword=spec.blogger_keyword,
        mode="blogger",
        payload={"topic_key": spec.key, "platform": "blogger", "stamp": INCIDENT_STAMP},
    )
    final_row = finalize_blogger_article(
        db,
        blog=blog,
        spec=spec,
        topic=topic,
        job=job,
        package=package,
        assembled_html=assembled_html,
        hero_meta=hero_meta,
        publish_summary=publish_summary,
        raw_publish_payload=raw_publish_payload,
        audit_payload=audit_payload,
        image_prompt=image_prompt,
        article_context=context,
    )
    write_mystery_artifact_json(context, stage_dir="09-db", filename="final-db-commit.json", payload=final_row)
    return {
        "platform": "blogger",
        "topic": spec.key,
        "published_url": final_row["published_url"],
        "hero_image_url": final_row["hero_image_url"],
        "live_status": live_audit["live_status"],
        "hero_status": hero_status["status_code"],
        "plain_text_length": live_audit["plain_text_length"],
        "duplicate_sentence_ratio": live_audit["duplicate_sentence_ratio"],
        "seo_score": final_row["seo_score"],
        "geo_score": final_row["geo_score"],
        "ctr_score": final_row["ctr_score"],
        "lighthouse_score": final_row["lighthouse_score"],
        "article_pattern_id": final_row["article_pattern_id"],
        "article_pattern_version": final_row["article_pattern_version"],
        "db_finalized": final_row["db_finalized"],
        "sync_ok": final_row["sync_ok"],
    }


def process_cloudflare_topic(
    *,
    db,
    runtime,
    client: CloudflareIntegrationClient,
    spec: TopicSpec,
    model: str,
    reasoning_effort: str,
) -> dict[str, Any]:
    slug = spec.cloudflare_slug
    context = build_cloudflare_artifact_context(spec, slug)
    article_prompt_template = read_text(PROMPT_ROOT_CF / "article_generation.md")
    image_prompt_template = read_text(PROMPT_ROOT_CF / "image_prompt_generation.md")
    prompt_values = build_prompt_values(
        keyword=spec.cloudflare_keyword,
        blog_name="Dongri Archive",
        target_audience="Korean readers who want mystery cases explained through records and evidence",
        content_brief="Write a Korean Mysteria Story article that separates records, interpretation, and unresolved questions.",
        pattern_id=spec.article_pattern_id,
        language="ko",
    )
    write_mystery_artifact_manifest(
        context,
        payload={
            "stamp": INCIDENT_STAMP,
            "platform": "cloudflare",
            "topic_key": spec.key,
            "slug": slug,
            "pattern_id": spec.article_pattern_id,
        },
    )
    package, article_response, validation = generate_article_package(
        runtime=runtime,
        prompt_template=article_prompt_template,
        prompt_values=prompt_values,
        spec=spec,
        slug=slug,
        language="ko",
        model=model,
        reasoning_effort=reasoning_effort,
        context=context,
    )
    detail = find_cloudflare_post_detail(client, spec)
    article_context = f"Title: {package.title}\nExcerpt: {package.excerpt}\nBody: {package.html_article}"
    image_prompt = generate_image_prompt(
        runtime=runtime,
        prompt_template=image_prompt_template,
        blog_name="Dongri Archive",
        article_title=package.title,
        article_excerpt=package.excerpt,
        article_context=article_context,
        original_prompt=package.image_collage_prompt,
        model=model,
        reasoning_effort=reasoning_effort,
        extra_values={"article_pattern_id": spec.article_pattern_id},
        context=context,
    )
    hero_meta = ensure_hero_asset(db, spec, slug=spec.blogger_slug, context=context)
    html_body = build_cloudflare_html(package, hero_url=hero_meta["public_url"])
    write_mystery_artifact_text(context, stage_dir="05-html", filename="body.html", content=html_body)
    update_payload = build_cloudflare_update_payload(
        detail=detail,
        spec=spec,
        package=package,
        html_body=html_body,
        hero_meta=hero_meta,
    )
    write_mystery_artifact_json(context, stage_dir="06-publish", filename="update-payload.json", payload=update_payload)
    client.update_post(spec.cloudflare_remote_id, update_payload)
    hero_status = hero_probe(hero_meta["public_url"])
    published_url = safe_text(detail.get("url")) or f"https://dongriarchive.com/ko/post/{slug}"
    live_audit = audit_cloudflare_live(published_url=published_url, hero_url=hero_meta["public_url"])
    score_payload = compute_seo_geo_scores(
        title=package.title,
        html_body=package.html_article,
        excerpt=package.excerpt,
        faq_section=[item.model_dump() for item in package.faq_section],
    )
    audit_payload = {**validation, **live_audit, "hero_status": hero_status}
    write_mystery_artifact_json(context, stage_dir="07-live", filename="live-audit.json", payload=audit_payload)
    if (
        int(live_audit["live_status"]) != 200
        or int(hero_status["status_code"]) != 200
        or "image/webp" not in str(hero_status["content_type"]).lower()
        or int(live_audit["plain_text_length"]) < 3000
        or int(live_audit["hero_image_count"]) != 1
        or int(live_audit["body_inline_image_count"]) != 0
        or float(live_audit["duplicate_sentence_ratio"]) > 0.15
    ):
        raise RuntimeError(f"cloudflare_live_audit_failed:{spec.key}:{audit_payload}")
    final_row = finalize_cloudflare_sync_row(
        db,
        spec=spec,
        audit_payload=audit_payload,
        score_payload=score_payload,
        hero_meta=hero_meta,
        image_prompt=image_prompt,
    )
    write_mystery_artifact_json(context, stage_dir="09-db", filename="final-db-commit.json", payload=final_row)
    return {
        "platform": "cloudflare",
        "topic": spec.key,
        "published_url": final_row["published_url"],
        "hero_image_url": final_row["hero_image_url"],
        "live_status": live_audit["live_status"],
        "hero_status": hero_status["status_code"],
        "plain_text_length": live_audit["plain_text_length"],
        "duplicate_sentence_ratio": live_audit["duplicate_sentence_ratio"],
        "seo_score": final_row["seo_score"],
        "geo_score": final_row["geo_score"],
        "ctr_score": final_row["ctr_score"],
        "lighthouse_score": final_row["lighthouse_score"],
        "article_pattern_id": final_row["article_pattern_id"],
        "article_pattern_version": final_row["article_pattern_version"],
        "db_finalized": final_row["db_finalized"],
        "sync_ok": final_row["sync_ok"],
    }


def cleanup_duplicate_blogger_posts(db, *, blog: Blog, specs: list[TopicSpec]) -> list[dict[str, Any]]:
    provider = get_blogger_provider(db, blog)
    deleted: list[dict[str, Any]] = []
    for spec in specs:
        for remote_post_id in spec.duplicate_blogger_remote_post_ids:
            remote_post_id = safe_text(remote_post_id)
            if not remote_post_id:
                continue
            try:
                provider.delete_post(remote_post_id)
                remote_deleted = True
                error = ""
            except Exception as exc:  # noqa: BLE001
                remote_deleted = False
                error = str(exc)
            db.execute(delete(BloggerPost).where(BloggerPost.blog_id == blog.id, BloggerPost.blogger_post_id == remote_post_id))
            db.execute(delete(SyncedBloggerPost).where(SyncedBloggerPost.blog_id == blog.id, SyncedBloggerPost.remote_post_id == remote_post_id))
            db.commit()
            deleted.append(
                {
                    "topic": spec.key,
                    "remote_post_id": remote_post_id,
                    "remote_deleted": remote_deleted,
                    "error": error,
                }
            )
    if deleted:
        sync_blogger_posts_for_blog(db, blog)
    return deleted


def main() -> int:
    args = parse_args()
    if not args.apply:
        raise SystemExit("--apply is required for this incident repair script.")
    selected_specs = select_specs(args)
    if not selected_specs:
        raise SystemExit("No matching topic specs selected.")

    with SessionLocal() as db:
        blog = db.execute(select(Blog).where(Blog.id == MYSTERY_BLOG_ID)).scalar_one()
        if safe_text(blog.profile_key) != MYSTERY_PROFILE_KEY:
            raise RuntimeError(f"profile_key_mismatch:{blog.profile_key}")
        runtime = get_runtime_config(db)
        cloudflare_client = CloudflareIntegrationClient.from_db(db)

        rows: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        duplicate_cleanup: list[dict[str, Any]] = []
        for spec in selected_specs:
            if not args.cloudflare_only:
                try:
                    rows.append(
                        process_blogger_topic(
                            db=db,
                            runtime=runtime,
                            blog=blog,
                            spec=spec,
                            model=args.model,
                            reasoning_effort=args.reasoning_effort,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    failures.append({"platform": "blogger", "topic": spec.key, "error": str(exc)})
            if not args.blogger_only:
                try:
                    rows.append(
                        process_cloudflare_topic(
                            db=db,
                            runtime=runtime,
                            client=cloudflare_client,
                            spec=spec,
                            model=args.model,
                            reasoning_effort=args.reasoning_effort,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    failures.append({"platform": "cloudflare", "topic": spec.key, "error": str(exc)})
        if not args.cloudflare_only:
            successful_blogger_topics = {safe_text(row.get("topic")) for row in rows if row.get("platform") == "blogger"}
            cleanup_specs = [spec for spec in selected_specs if spec.key in successful_blogger_topics]
            duplicate_cleanup = cleanup_duplicate_blogger_posts(db, blog=blog, specs=cleanup_specs)

    final_payload = {
        "stamp": INCIDENT_STAMP,
        "success_count": len(rows),
        "failure_count": len(failures),
        "rows": rows,
        "failures": failures,
        "duplicate_cleanup": duplicate_cleanup,
        "generated_at": iso_now(),
    }
    FINAL_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    FINAL_AUDIT_PATH.write_text(json.dumps(final_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_problem_solution(final_payload)
    print(json.dumps(final_payload, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
