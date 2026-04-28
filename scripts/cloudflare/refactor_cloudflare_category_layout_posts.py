from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from sqlalchemy import select
from sqlalchemy.orm import Session


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
RUNTIME_ROOT = Path(os.getenv("BLOGGENT_RUNTIME_ROOT", r"D:\Donggri_Runtime\BloggerGent"))
DEFAULT_WORK_ROOT = RUNTIME_ROOT / "Rool" / "30-cloudflare" / "12-category-layout-refactor"
RULE_ROOT = RUNTIME_ROOT / "Rool" / "30-cloudflare"
PUBLIC_LAYOUT_RULE_PATH = Path(r"D:\Donggri_Platform\dongriarhive-repo\docs\content_authoring_layout_rules.md")
CHANNEL_ID = "cloudflare:dongriarchive"
DEV_CATEGORY = "개발과-프로그래밍"
DAILY_CATEGORY = "일상과-메모"
TARGET_CATEGORIES = (DEV_CATEGORY, DAILY_CATEGORY)
PATTERN_VERSION = 3


def _bootstrap_local_runtime_env() -> None:
    env_path = REPO_ROOT / "env" / "runtime.settings.env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key and not os.environ.get(key):
            os.environ[key] = value.strip()


_bootstrap_local_runtime_env()
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://bloggent:bloggent@127.0.0.1:15432/bloggent")
os.environ.setdefault("SETTINGS_ENCRYPTION_SECRET", "cloudflare-bootstrap-20260418")
os.environ.setdefault("STORAGE_ROOT", str(RUNTIME_ROOT / "storage"))

if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import ManagedChannel, SyncedCloudflarePost  # noqa: E402
from app.services.cloudflare.cloudflare_channel_service import (  # noqa: E402
    _fetch_integration_post_detail,
    _integration_data_or_raise,
    _integration_request,
    _prepare_markdown_body,
    _strip_generated_body_images,
)
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402
from app.services.platform.codex_cli_queue_service import submit_codex_text_job  # noqa: E402
from app.services.providers.base import RuntimeProviderConfig  # noqa: E402


CODEX_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "meta_description": {"type": "string"},
        "excerpt": {"type": "string"},
        "html_article": {"type": "string"},
        "labels": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "meta_description", "excerpt", "html_article", "labels"],
}


@dataclass(frozen=True, slots=True)
class PatternPolicy:
    category_slug: str
    pattern_no: int
    pattern_id: str
    pattern_name: str
    faq_policy: str
    title_pattern: str
    structure_flow: str
    close_policy: str
    source_policy: str
    image_prompt_direction: str
    keywords: tuple[str, ...]
    negative_keywords: tuple[str, ...] = ()


DEV_POLICIES: tuple[PatternPolicy, ...] = (
    PatternPolicy(
        DEV_CATEGORY,
        1,
        "dev-01-mcp-agent-adoption",
        "MCP와 에이전트 도입",
        "none",
        "[MCP/에이전트 주제] 2026 | 팀 워크플로 적용 가치",
        "## 핵심 요약 -> ## 왜 지금 MCP와 에이전트가 중요한가 -> ## 팀 워크플로에 넣는 기준 -> ## 도입 전 확인할 위험 -> ## 팀 단위 적용 포인트",
        "팀 단위 적용 포인트로 닫는다.",
        "공식 MCP/도구 문서, 공식 릴리스 노트, 엔지니어링 블로그 순서로 근거를 둔다.",
        "개발자가 에이전트 워크플로 보드와 로컬 도구 체인을 점검하는 실무 장면.",
        ("mcp", "agent", "agents", "에이전트", "model context", "context protocol", "tool calling"),
    ),
    PatternPolicy(
        DEV_CATEGORY,
        2,
        "dev-02-ide-cli-workflow",
        "IDE / CLI 워크플로 변화",
        "none",
        "[IDE/CLI 워크플로] 2026 | 실무 적용 기준",
        "## 핵심 요약 -> ## IDE와 CLI 흐름이 바뀐 이유 -> ## 팀 개발 루틴에 미치는 영향 -> ## 바로 적용할 작업 순서 -> ## 실무 체크리스트",
        "실무 체크리스트로 닫는다.",
        "도구 공식 문서, 릴리스 노트, 실제 셋업 문서를 우선한다.",
        "IDE, 터미널, 리뷰 보드가 함께 보이는 AI 코딩 워크스테이션.",
        ("ide", "cli", "codex", "claude", "gemini", "cursor", "copilot", "vscode", "terminal", "터미널", "코덱스"),
    ),
    PatternPolicy(
        DEV_CATEGORY,
        3,
        "dev-03-deployment-automation",
        "배포 자동화",
        "none",
        "[배포/자동화 대상] 가이드 2026 | 실패를 줄이는 운영 구조",
        "## 핵심 요약 -> ## 자동화해야 하는 지점 -> ## 배포 파이프라인 설계 -> ## 실패 복구와 롤백 -> ## 운영 기준",
        "운영 기준으로 닫는다.",
        "플랫폼 공식 배포 문서, CI/CD 릴리스 노트, 운영 사례를 우선한다.",
        "배포 파이프라인, 체크포인트, 롤백 흐름이 보이는 운영 대시보드.",
        ("deploy", "deployment", "ci", "cd", "github actions", "worker", "pages", "docker", "배포", "자동화", "롤백"),
    ),
    PatternPolicy(
        DEV_CATEGORY,
        4,
        "dev-04-observability-debugging",
        "관측성 / 디버깅",
        "none",
        "[관측성/디버깅 문제] 체크리스트 2026 | 원인 추적 순서",
        "## 핵심 요약 -> ## 문제가 드러나는 신호 -> ## 로그와 지표로 좁히는 방법 -> ## 재현과 검증 -> ## 다음 분기 관찰 포인트",
        "다음 분기 관찰 포인트로 닫는다.",
        "공식 observability 문서, 장애 회고, 엔지니어링 블로그 순서로 근거를 둔다.",
        "로그 스트림, 트레이스, 알림 패널을 분석하는 개발 운영 장면.",
        ("observability", "debug", "debugging", "monitoring", "log", "trace", "error", "lighthouse", "관측성", "디버깅", "로그", "모니터링"),
    ),
    PatternPolicy(
        DEV_CATEGORY,
        5,
        "dev-05-cost-governance",
        "API 비용 / 호출 통제 / 팀 운영 거버넌스",
        "optional",
        "[비용/거버넌스 주제] 운영 가이드 2026 | 팀 단위 통제 구조",
        "## 핵심 요약 -> ## 비용이 새는 지점 -> ## 호출량과 권한 통제 -> ## 팀 운영 규칙 -> ## 실무 체크리스트 -> optional ## FAQ",
        "실무 체크리스트로 닫는다.",
        "공식 가격/사용량 문서, 계정 관리 문서, 릴리스 노트를 우선한다.",
        "API 사용량 그래프, 예산 경고, 팀 권한 테이블이 보이는 거버넌스 보드.",
        ("cost", "billing", "usage", "quota", "token", "budget", "rate limit", "api 비용", "비용", "호출", "거버넌스", "사용량"),
    ),
    PatternPolicy(
        DEV_CATEGORY,
        6,
        "dev-06-prompt-content-automation",
        "프롬프트 / 콘텐츠 자동화 파이프라인",
        "none",
        "[자동화 파이프라인] 플레이북 2026 | 기준 수립부터 운영 점검까지",
        "## 핵심 요약 -> ## 자동화 파이프라인의 병목 -> ## 프롬프트와 검증 기준 -> ## 운영 큐와 실패 복구 -> ## 팀 단위 적용 포인트",
        "팀 단위 적용 포인트로 닫는다.",
        "공식 API 문서, 프롬프트/에이전트 문서, 내부 운영 로그 근거를 우선한다.",
        "콘텐츠 큐, 프롬프트 카드, 검증 상태가 이어지는 자동화 파이프라인.",
        ("prompt", "프롬프트", "content automation", "pipeline", "queue", "batch", "image prompt", "콘텐츠", "파이프라인", "작업 큐"),
    ),
    PatternPolicy(
        DEV_CATEGORY,
        7,
        "dev-07-tool-comparison-playbook",
        "도구 비교와 도입 판단",
        "optional",
        "[도구A, 도구B, 도구C]: 비교 목적 또는 [도구 비교] 2026 | 선택 기준",
        "## 핵심 요약 -> ## 비교 기준 -> ## 도구별 강점과 한계 -> ## 팀 상황별 선택법 -> ## 다음 분기 관찰 포인트 -> optional ## FAQ",
        "다음 분기 관찰 포인트로 닫는다.",
        "각 도구 공식 문서, 공식 릴리스 노트, 가격/제한 문서를 우선한다.",
        "여러 AI 코딩 도구 카드를 비교하는 편집자 데스크 장면.",
        (" vs ", "compare", "comparison", "무료", "유료", "선택", "비교", "claude", "codex", "gemini", "copilot", "cursor"),
    ),
)

DAILY_POLICIES: tuple[PatternPolicy, ...] = (
    PatternPolicy(DAILY_CATEGORY, 1, "daily-01-reflective-monologue", "사유형 독백", "none", "[작은 장면] | 생각을 정리하는 메모", "## 장면 -> ## 생각 -> ## 남은 질문 -> ## 마무리 기록", "마무리 기록으로 닫는다.", "개인 기록형 글이므로 외부 출처보다 관찰 맥락을 우선한다.", "책상 위 노트와 조용한 빛이 있는 일상 사유 장면.", ("생각", "사유", "질문", "마음", "기록", "메모", "느낌")),
    PatternPolicy(DAILY_CATEGORY, 2, "daily-02-insight-memo", "일상 인사이트 메모", "none", "[일상 문제] | 바로 적용할 작은 통찰", "## 장면 -> ## 문제를 다시 보기 -> ## 적용할 수 있는 통찰 -> ## 작은 체크리스트 -> ## 마무리 기록", "작은 체크리스트 또는 마무리 기록으로 닫는다.", "생활 관찰과 실천 가능성을 우선한다.", "일상 도구와 메모 카드가 정돈된 생활 인사이트 장면.", ("팁", "방법", "정리", "문제", "통찰", "실천", "체크")),
    PatternPolicy(DAILY_CATEGORY, 3, "daily-03-habit-tracker", "루틴 / 습관 기록", "none", "[루틴/습관] | 꾸준히 남기는 기록", "## 장면 -> ## 루틴의 목적 -> ## 실행 순서 -> ## 작은 체크리스트 -> ## 마무리 기록", "작은 체크리스트로 닫는다.", "개인 루틴과 재현 가능한 절차를 우선한다.", "아침 루틴 체크리스트와 캘린더가 보이는 차분한 생활 장면.", ("routine", "habit", "morning", "walk", "루틴", "습관", "아침", "산책", "체크리스트")),
    PatternPolicy(DAILY_CATEGORY, 4, "daily-04-emotional-reflection", "감정 회고", "none", "[감정/분위기] | 하루를 다시 읽는 기록", "## 장면 -> ## 감정의 흐름 -> ## 내가 붙잡은 문장 -> ## 실천 -> ## 마무리 기록", "마무리 기록으로 닫는다.", "감정의 과장보다 구체적 장면과 언어를 우선한다.", "창가, 노트, 부드러운 그림자가 있는 감정 회고 장면.", ("감정", "외로움", "위로", "불안", "기분", "하루", "장면", "문장")),
)

POLICIES_BY_CATEGORY: dict[str, tuple[PatternPolicy, ...]] = {
    DEV_CATEGORY: DEV_POLICIES,
    DAILY_CATEGORY: DAILY_POLICIES,
}
POLICY_BY_ID: dict[str, PatternPolicy] = {policy.pattern_id: policy for policies in POLICIES_BY_CATEGORY.values() for policy in policies}

DEV_TERMS = ("ai", "api", "automation", "claude", "codex", "code", "copilot", "cursor", "developer", "docker", "gemini", "github", "ide", "llm", "mcp", "node", "openai", "programming", "react", "typescript", "workflow", "개발", "기술", "도구", "리팩토링", "자동화", "코드", "프로그래밍", "프롬프트")
DAILY_TERMS = ("daily", "habit", "memo", "morning", "note", "routine", "walk", "감정", "기록", "루틴", "메모", "사유", "생각", "습관", "아침", "일상")
MYSTERY_TERMS = ("agatha", "case", "disappearance", "expedition", "franklin", "mh370", "murder", "mysteria", "mystery", "oakville", "sodder", "somerton", "tamam", "unsolved", "wow-signal", "괴담", "미스터리", "사건", "실종", "살인")
MARKET_TERMS = ("bitcoin", "crypto", "ethereum", "nasdaq", "sec", "stock", "ticker", "나스닥", "비트코인", "시장", "주식", "크립토")
NON_DEV_SLUG_TERMS = ("iran", "jeonjaeng", "tariff", "war", "festival", "chukje", "stock", "crypto", "nasdaq")
TOOL_NAMES = ("claude", "codex", "gemini", "copilot", "cursor", "openai")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refactor Cloudflare category posts by pattern-specific Rool rules.")
    parser.add_argument("--mode", choices=("dry_run", "execute", "packet_only", "apply_packets"), default="dry_run")
    parser.add_argument("--categories", nargs="+", default=list(TARGET_CATEGORIES))
    parser.add_argument("--scope", choices=("validated_category_only",), default="validated_category_only")
    parser.add_argument("--provider", choices=("codex_cli",), default="codex_cli")
    parser.add_argument("--packet-results", default=str(DEFAULT_WORK_ROOT / "codex-app-results"))
    parser.add_argument("--work-root", default=str(DEFAULT_WORK_ROOT))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--skip-sync-before", action="store_true")
    parser.add_argument("--skip-sync-after", action="store_true")
    return parser.parse_args()


def _safe_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _casefold(value: Any) -> str:
    return unquote(_safe_text(value)).casefold()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = _casefold(text)
    return any(term.casefold() in lowered for term in terms)


def _matched_terms(text: str, terms: tuple[str, ...]) -> list[str]:
    lowered = _casefold(text)
    return [term for term in terms if term.casefold() in lowered]


def _safe_filename(value: str, *, fallback: str = "post") -> str:
    text = unquote(_safe_text(value))
    text = re.sub(r"[^a-zA-Z0-9가-힣_-]+", "-", text).strip("-")
    return (text[:140] or fallback).strip("-") or fallback


def _read_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8-sig")


def _rules_for_category(category_slug: str) -> dict[str, str]:
    rules = {
        "category_layout_rules": _read_file(RULE_ROOT / "category-layout-rules.md"),
        "public_layout_rules": _read_file(PUBLIC_LAYOUT_RULE_PATH),
    }
    if category_slug == DEV_CATEGORY:
        rules["category_specific_rules"] = _read_file(RULE_ROOT / "dev-programming.md")
    elif category_slug == DAILY_CATEGORY:
        rules["category_specific_rules"] = _read_file(RULE_ROOT / "daily-memo.md")
    else:
        rules["category_specific_rules"] = ""
    return rules


def _find_channel(db: Session) -> ManagedChannel:
    channel = db.execute(
        select(ManagedChannel).where(
            ManagedChannel.provider == "cloudflare",
            ManagedChannel.channel_id == CHANNEL_ID,
        )
    ).scalar_one_or_none()
    if channel is None:
        raise RuntimeError(f"Cloudflare channel not found: {CHANNEL_ID}")
    return channel


def _load_posts(db: Session, categories: list[str]) -> list[SyncedCloudflarePost]:
    channel = _find_channel(db)
    category_set = {str(item).strip() for item in categories if str(item).strip()}
    return list(
        db.execute(
            select(SyncedCloudflarePost)
            .where(
                SyncedCloudflarePost.managed_channel_id == channel.id,
                SyncedCloudflarePost.status.in_(["published", "live"]),
                SyncedCloudflarePost.canonical_category_slug.in_(category_set),
            )
            .order_by(
                SyncedCloudflarePost.canonical_category_slug.asc(),
                SyncedCloudflarePost.published_at.desc().nullslast(),
                SyncedCloudflarePost.id.desc(),
            )
        )
        .scalars()
        .all()
    )


def _combined_post_text(post: SyncedCloudflarePost) -> str:
    return "\n".join([_safe_text(post.slug), _safe_text(post.title), _safe_text(post.url), _safe_text(post.excerpt_text)])


def _classify_post(post: SyncedCloudflarePost) -> tuple[str, str]:
    category = _safe_text(post.canonical_category_slug or post.category_slug)
    combined = _combined_post_text(post)
    has_mystery = _contains_any(combined, MYSTERY_TERMS)
    has_market = _contains_any(combined, MARKET_TERMS)
    has_dev = _contains_any(combined, DEV_TERMS)
    has_daily = _contains_any(combined, DAILY_TERMS)
    slug_has_non_dev_subject = _contains_any(_safe_text(post.slug), NON_DEV_SLUG_TERMS)

    if category == DEV_CATEGORY:
        if has_mystery:
            return "misclassified", "mystery_tokens_in_development_category"
        if slug_has_non_dev_subject:
            return "needs_review", "non_development_subject_tokens_in_slug"
        if has_market and not has_dev:
            return "needs_review", "market_tokens_without_development_context"
        if not has_dev:
            return "needs_review", "development_terms_not_found"
        return "valid", "development_terms_found"

    if category == DAILY_CATEGORY:
        if has_mystery:
            return "needs_review", "mystery_tokens_in_daily_category"
        if has_market:
            return "needs_review", "market_tokens_in_daily_category"
        if has_dev and not has_daily:
            return "needs_review", "technical_tokens_without_daily_context"
        return "valid", "daily_category_accepted"

    return "needs_review", "unsupported_category"


def _select_policy(post: SyncedCloudflarePost) -> tuple[PatternPolicy | None, str]:
    category = _safe_text(post.canonical_category_slug or post.category_slug)
    policies = POLICIES_BY_CATEGORY.get(category)
    if not policies:
        return None, "no_policy_for_category"

    text = _combined_post_text(post)
    lowered = _casefold(text)
    scores: list[tuple[int, int, PatternPolicy, list[str]]] = []
    for policy in policies:
        matched = _matched_terms(lowered, policy.keywords)
        negative = _matched_terms(lowered, policy.negative_keywords)
        score = (len(matched) * 10) - (len(negative) * 5)
        if category == DEV_CATEGORY and policy.pattern_id == "dev-07-tool-comparison-playbook":
            tool_hits = [tool for tool in TOOL_NAMES if tool in lowered]
            if len(set(tool_hits)) >= 2:
                score += 25
                matched.append(f"multi_tool:{','.join(sorted(set(tool_hits)))}")
        scores.append((score, -policy.pattern_no, policy, matched))

    best_score, _, best_policy, matched_terms = max(scores, key=lambda item: (item[0], item[1]))
    if best_score <= 0:
        fallback = policies[0]
        return fallback, "fallback_no_keyword_hit"
    return best_policy, f"matched_terms={','.join(matched_terms[:8])}"


def _layout_metadata(policy: PatternPolicy | None, *, reason: str) -> dict[str, Any]:
    if policy is None:
        return {}
    return {
        "layout_refactor": {
            "pattern_no": policy.pattern_no,
            "pattern_id": policy.pattern_id,
            "pattern_name": policy.pattern_name,
            "pattern_version": PATTERN_VERSION,
            "faq_policy": policy.faq_policy,
            "pattern_reason": reason,
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
    }


def _manifest_row(
    post: SyncedCloudflarePost,
    *,
    decision: str,
    reason: str,
    policy: PatternPolicy | None,
    pattern_reason: str,
) -> dict[str, Any]:
    return {
        "remote_post_id": _safe_text(post.remote_post_id),
        "slug": _safe_text(post.slug),
        "title": _safe_text(post.title),
        "url": _safe_text(post.url),
        "status": _safe_text(post.status),
        "category_slug": _safe_text(post.canonical_category_slug or post.category_slug),
        "category_name": _safe_text(post.canonical_category_name or post.category_name),
        "published_at": _safe_text(post.published_at),
        "decision": decision,
        "reason": reason,
        "selected_pattern_no": policy.pattern_no if policy else "",
        "selected_pattern_id": policy.pattern_id if policy else "",
        "selected_pattern_name": policy.pattern_name if policy else "",
        "faq_policy": policy.faq_policy if policy else "",
        "pattern_reason": pattern_reason,
        "seo_score": post.seo_score,
        "geo_score": post.geo_score,
        "ctr": post.ctr,
        "lighthouse_score": post.lighthouse_score,
        "article_pattern_id": _safe_text(post.article_pattern_id),
        "article_pattern_version": post.article_pattern_version,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if columns is None:
        columns = list(rows[0].keys()) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _extract_content(detail: dict[str, Any], post: SyncedCloudflarePost) -> str:
    for key in ("contentMarkdown", "content", "contentHtml", "html", "markdown"):
        value = _safe_text(detail.get(key))
        if value:
            return value
    return _safe_text(post.excerpt_text)


def _detail_to_packet(
    post: SyncedCloudflarePost,
    detail: dict[str, Any],
    *,
    decision: str,
    reason: str,
    policy: PatternPolicy,
    pattern_reason: str,
) -> dict[str, Any]:
    category = _safe_text(post.canonical_category_slug or post.category_slug)
    return {
        "remote_post_id": _safe_text(post.remote_post_id),
        "slug": _safe_text(post.slug),
        "category_slug": category,
        "title": _safe_text(detail.get("title") or post.title),
        "excerpt": _safe_text(detail.get("excerpt") or post.excerpt_text),
        "current_content": _extract_content(detail, post),
        "coverImage": _safe_text(detail.get("coverImage") or post.thumbnail_url),
        "coverAlt": _safe_text(detail.get("coverAlt")),
        "seoTitle": _safe_text(detail.get("seoTitle") or detail.get("title") or post.title),
        "seoDescription": _safe_text(detail.get("seoDescription") or detail.get("excerpt") or post.excerpt_text),
        "tagNames": detail.get("tagNames") or detail.get("tags") or post.labels or [],
        "categoryId": _safe_text(detail.get("categoryId")),
        "status": _safe_text(detail.get("status") or post.status or "published"),
        "decision": decision,
        "decision_reason": reason,
        "pattern_policy": asdict(policy),
        "pattern_reason": pattern_reason,
        "layout_metadata": _layout_metadata(policy, reason=pattern_reason),
        "rules": _rules_for_category(category),
        "output_contract": {
            "title": "string",
            "meta_description": "string",
            "excerpt": "string",
            "html_article": "Markdown-only body. Name is kept for backwards compatibility.",
            "labels": ["string"],
        },
    }


def _build_codex_prompt(packet: dict[str, Any]) -> str:
    policy = packet.get("pattern_policy") or {}
    policy_text = "\n".join(
        f"{key}: {value}" for key, value in policy.items() if key not in {"keywords", "negative_keywords"}
    )
    rules = packet.get("rules") or {}
    faq_policy = _safe_text(policy.get("faq_policy"))
    faq_instruction = (
        "- Do not include a FAQ section."
        if faq_policy == "none"
        else "- FAQ is optional. Include ## FAQ only when it directly improves operational decision-making."
    )
    return f"""
You are refactoring an existing published Cloudflare blog post.
Return JSON only. Do not add markdown fences.

[Goal]
- Preserve the existing subject, useful facts, and intent.
- Refactor only title/excerpt/body structure to the selected category pattern.
- Do not generate images.
- Do not change coverImage, coverAlt, category, slug, remote_post_id, or URL.

[Selected pattern]
{policy_text}

[Hard body rules]
- Markdown only. Do not use raw HTML.
- Do not use # H1. The first heading in the body must start with ##.
- Include ## 핵심 요약.
- Use at least three ## headings.
- Target Korean body length: 3400~4200 characters for 개발과-프로그래밍; 2500~3600 characters for 일상과-메모.
- Do not insert image markdown, <img>, <figure>, <script>, <iframe>, <article>, <section>, or inline style.
{faq_instruction}
- Keep all reader-facing text Korean.
- Preserve concrete details from the existing post; do not replace the topic with a generic template.

[Category layout rules]
{rules.get("category_layout_rules", "")[:9000]}

[Category specific rules]
{rules.get("category_specific_rules", "")[:9000]}

[Public layout rules]
{rules.get("public_layout_rules", "")[:7000]}

[Existing post]
remote_post_id: {packet.get("remote_post_id")}
slug: {packet.get("slug")}
title: {packet.get("title")}
excerpt: {packet.get("excerpt")}

[Existing content]
{_safe_text(packet.get("current_content"))[:18000]}

[Output JSON schema]
{{
  "title": "Korean title, 40-100 chars. Follow the selected title_pattern.",
  "meta_description": "Korean SEO description, 80-160 chars",
  "excerpt": "Exactly 2 Korean sentences, 80-150 chars total",
  "html_article": "Markdown-only body using ##/###, paragraphs, bullets, ordered lists, and tables only",
  "labels": ["5 to 7 Korean labels"]
}}
""".strip()


def _run_codex_refactor(packet: dict[str, Any]) -> dict[str, Any]:
    runtime = RuntimeProviderConfig(
        provider_mode="live",
        openai_api_key="",
        openai_text_model="",
        openai_image_model="",
        topic_discovery_provider="codex_cli",
        topic_discovery_model="",
        gemini_api_key="",
        gemini_model="",
        blogger_access_token="",
        default_publish_mode="draft",
        text_runtime_kind="codex_cli",
        text_runtime_model="gpt-5.4",
        image_runtime_kind="none",
        codex_job_timeout_seconds=1200,
    )
    response = submit_codex_text_job(
        runtime=runtime,
        stage_name="cloudflare_category_layout_pattern_refactor",
        model="gpt-5.4",
        prompt=_build_codex_prompt(packet),
        response_kind="json_schema",
        response_schema=CODEX_SCHEMA,
        timeout_seconds=1200,
        inline=True,
    )
    content = _safe_text(response.get("content"))
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("Codex response must be a JSON object.")
    return payload


def _strip_raw_html(body: str) -> str:
    cleaned = _safe_text(body)
    cleaned = re.sub(r"(?is)<script\b[^>]*>.*?</script>", "", cleaned)
    cleaned = re.sub(r"(?is)<iframe\b[^>]*>.*?</iframe>", "", cleaned)
    cleaned = re.sub(r"(?is)<figure\b[^>]*>.*?</figure>", "", cleaned)
    cleaned = re.sub(r"(?is)<img\b[^>]*>", "", cleaned)
    cleaned = re.sub(
        r"(?is)</?(article|section|div|span|p|h1|h2|h3|ul|ol|li|strong|em|table|thead|tbody|tr|th|td|blockquote|aside|details|summary)\b[^>]*>",
        "",
        cleaned,
    )
    cleaned = re.sub(r"(?m)^\s*!\[[^\]]*\]\([^)]+\)\s*$", "", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _fit_publish_description(value: str, *, title: str, fallback: str) -> str:
    text = re.sub(r"\s+", " ", _safe_text(value)).strip()
    if len(text) < 90:
        addon = re.sub(r"\s+", " ", _safe_text(fallback or title)).strip()
        if addon and addon not in text:
            text = f"{text} {addon}".strip()
    if len(text) < 90:
        text = f"{text} 이 글은 실무 적용 기준과 점검 포인트를 중심으로 핵심 흐름을 정리합니다.".strip()
    if len(text) > 170:
        text = text[:169].rstrip(" ,.;:·") + "…"
    return text


def _normalize_refactor_output(payload: dict[str, Any], packet: dict[str, Any]) -> dict[str, Any]:
    title = _safe_text(payload.get("title") or packet.get("title"))
    excerpt = _safe_text(payload.get("excerpt") or packet.get("excerpt"))
    meta_description = _safe_text(payload.get("meta_description") or excerpt)
    excerpt = _fit_publish_description(excerpt, title=title, fallback=_safe_text(packet.get("excerpt")))
    meta_description = _fit_publish_description(meta_description, title=title, fallback=excerpt)
    labels = payload.get("labels")
    if not isinstance(labels, list):
        labels = packet.get("tagNames") or []
    labels = [_safe_text(item).replace("#", "").strip() for item in labels if _safe_text(item)]
    if not labels:
        labels = [_safe_text(packet.get("category_slug"))]

    body = _safe_text(payload.get("html_article") or payload.get("body_markdown"))
    body = _strip_generated_body_images(body)
    body = _strip_raw_html(body)
    if body.startswith("# "):
        body = "## " + body[2:].strip()
    return {
        "title": title,
        "meta_description": meta_description,
        "excerpt": excerpt,
        "html_article": body,
        "labels": labels[:7],
    }


def _validate_output(payload: dict[str, Any], policy: PatternPolicy) -> list[str]:
    body = _safe_text(payload.get("html_article"))
    reasons: list[str] = []
    if re.search(r"(?m)^#\s+", body):
        reasons.append("forbidden_h1_markdown")
    if re.search(r"(?is)<[a-z][^>]*>", body):
        reasons.append("forbidden_raw_html")
    if re.search(r"(?is)<script\b|<iframe\b|<article\b|<section\b|<img\b|!\[[^\]]*\]\([^)]+\)", body):
        reasons.append("forbidden_media_or_layout_tag")
    if not body.lstrip().startswith("## "):
        reasons.append("first_heading_must_be_h2")
    if len(re.findall(r"(?m)^##\s+", body)) < 3:
        reasons.append("h2_count_lt_3")
    if "## 핵심 요약" not in body:
        reasons.append("missing_core_summary")
    if policy.faq_policy == "none" and re.search(r"(?mi)^##\s*(FAQ|자주 묻는 질문)\b", body):
        reasons.append("faq_not_allowed_for_pattern")
    text_len = len(re.sub(r"[#*_`|>\-\s]", "", body))
    if policy.category_slug == DEV_CATEGORY and text_len < 1200:
        reasons.append("body_too_short_for_dev")
    if policy.category_slug == DAILY_CATEGORY and text_len < 900:
        reasons.append("body_too_short_for_daily")
    return reasons


def _update_remote_post(db: Session, packet: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    remote_id = _safe_text(packet.get("remote_post_id"))
    if not remote_id:
        raise ValueError("remote_post_id is missing.")
    policy = packet.get("pattern_policy") or {}
    metadata = packet.get("layout_metadata") or {}

    update_payload = {
        "title": payload["title"],
        "content": _prepare_markdown_body(payload["title"], payload["html_article"]),
        "excerpt": payload["excerpt"],
        "seoTitle": payload["title"],
        "seoDescription": payload["meta_description"],
        "tagNames": payload["labels"],
        "status": "published",
        "metadata": metadata,
        "articlePatternId": _safe_text(policy.get("pattern_id")),
        "articlePatternVersion": PATTERN_VERSION,
    }
    if _safe_text(packet.get("categoryId")):
        update_payload["categoryId"] = _safe_text(packet.get("categoryId"))
    if _safe_text(packet.get("coverImage")):
        update_payload["coverImage"] = _safe_text(packet.get("coverImage"))
    if _safe_text(packet.get("coverAlt")):
        update_payload["coverAlt"] = _safe_text(packet.get("coverAlt"))

    response = _integration_request(
        db,
        method="PUT",
        path=f"/api/integrations/posts/{quote(remote_id)}",
        json_payload=update_payload,
        timeout=120.0,
    )
    data = _integration_data_or_raise(response)
    return data if isinstance(data, dict) else {"result": data}


def _patch_synced_pattern(db: Session, remote_id: str, policy: PatternPolicy, *, reason: str) -> bool:
    post = db.execute(select(SyncedCloudflarePost).where(SyncedCloudflarePost.remote_post_id == remote_id)).scalar_one_or_none()
    if post is None:
        return False
    post.article_pattern_id = policy.pattern_id
    post.article_pattern_version = PATTERN_VERSION
    metadata = dict(post.render_metadata or {})
    metadata.update(_layout_metadata(policy, reason=reason))
    post.render_metadata = metadata
    return True


def _write_packet(work_root: Path, post: SyncedCloudflarePost, packet: dict[str, Any]) -> Path:
    packet_dir = work_root / "codex-app-packets"
    packet_path = packet_dir / f"{_safe_filename(_safe_text(post.slug) or _safe_text(post.remote_post_id))}.json"
    _write_json(packet_path, packet)
    return packet_path


def _write_result(work_root: Path, packet: dict[str, Any], result: dict[str, Any]) -> Path:
    result_dir = work_root / "codex-app-results"
    result_path = result_dir / f"{_safe_filename(_safe_text(packet.get('slug')) or _safe_text(packet.get('remote_post_id')))}.json"
    _write_json(result_path, result)
    return result_path


def _build_pattern_summary(manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in manifest:
        key = (
            _safe_text(row.get("category_slug")),
            _safe_text(row.get("decision")),
            _safe_text(row.get("selected_pattern_no")),
            _safe_text(row.get("selected_pattern_id")),
        )
        item = summary.setdefault(
            key,
            {
                "category_slug": key[0],
                "decision": key[1],
                "selected_pattern_no": key[2],
                "selected_pattern_id": key[3],
                "selected_pattern_name": _safe_text(row.get("selected_pattern_name")),
                "faq_policy": _safe_text(row.get("faq_policy")),
                "count": 0,
            },
        )
        item["count"] += 1
    return sorted(summary.values(), key=lambda item: (item["category_slug"], item["decision"], str(item["selected_pattern_no"])))


def _build_manifest(db: Session, args: argparse.Namespace, work_root: Path) -> tuple[list[SyncedCloudflarePost], list[dict[str, Any]]]:
    if not args.skip_sync_before:
        sync_cloudflare_posts(db, include_non_published=True)
    posts = _load_posts(db, args.categories)
    manifest: list[dict[str, Any]] = []
    for post in posts:
        decision, reason = _classify_post(post)
        policy, pattern_reason = _select_policy(post) if decision == "valid" else (None, "not_selected_for_non_valid_row")
        manifest.append(_manifest_row(post, decision=decision, reason=reason, policy=policy, pattern_reason=pattern_reason))

    pattern_summary = _build_pattern_summary(manifest)
    _write_csv(work_root / "manifest.csv", manifest)
    _write_csv(work_root / "misclassified.csv", [row for row in manifest if row["decision"] == "misclassified"])
    _write_csv(work_root / "needs-review.csv", [row for row in manifest if row["decision"] == "needs_review"])
    _write_csv(work_root / "pattern-summary.csv", pattern_summary)
    _write_json(work_root / "pattern-summary.json", {"items": pattern_summary, "generated_at_utc": datetime.now(timezone.utc).isoformat()})
    return posts, manifest


def _valid_post_context(posts: list[SyncedCloudflarePost], manifest: list[dict[str, Any]]) -> list[tuple[SyncedCloudflarePost, dict[str, Any], PatternPolicy]]:
    decisions = {row["remote_post_id"]: row for row in manifest}
    items: list[tuple[SyncedCloudflarePost, dict[str, Any], PatternPolicy]] = []
    for post in posts:
        row = decisions.get(_safe_text(post.remote_post_id))
        if not row or row.get("decision") != "valid":
            continue
        policy = POLICY_BY_ID.get(_safe_text(row.get("selected_pattern_id")))
        if policy is None:
            continue
        items.append((post, row, policy))
    return items


def _packet_only(db: Session, args: argparse.Namespace, work_root: Path) -> dict[str, Any]:
    posts, manifest = _build_manifest(db, args, work_root)
    valid_items = _valid_post_context(posts, manifest)
    if args.limit and args.limit > 0:
        valid_items = valid_items[: args.limit]

    packet_paths: list[str] = []
    for post, row, policy in valid_items:
        detail = _fetch_integration_post_detail(db, post.remote_post_id)
        packet = _detail_to_packet(
            post,
            detail,
            decision=row["decision"],
            reason=row["reason"],
            policy=policy,
            pattern_reason=_safe_text(row.get("pattern_reason")),
        )
        packet_paths.append(str(_write_packet(work_root, post, packet)))
    return {"packet_count": len(packet_paths), "packet_paths": packet_paths}


def _execute(db: Session, args: argparse.Namespace, work_root: Path) -> dict[str, Any]:
    if not shutil.which("codex.cmd") and not shutil.which("codex"):
        return {
            "status": "codex_cli_unavailable",
            "packet_only": _packet_only(db, args, work_root),
        }

    posts, manifest = _build_manifest(db, args, work_root)
    valid_items = _valid_post_context(posts, manifest)
    if args.limit and args.limit > 0:
        valid_items = valid_items[: args.limit]

    results: list[dict[str, Any]] = []
    updated_patterns: list[tuple[str, PatternPolicy, str]] = []
    for post, row, policy in valid_items:
        detail = _fetch_integration_post_detail(db, post.remote_post_id)
        packet = _detail_to_packet(
            post,
            detail,
            decision=row["decision"],
            reason=row["reason"],
            policy=policy,
            pattern_reason=_safe_text(row.get("pattern_reason")),
        )
        packet_path = _write_packet(work_root, post, packet)
        item = {
            "remote_post_id": packet["remote_post_id"],
            "slug": packet["slug"],
            "category_slug": packet["category_slug"],
            "selected_pattern_no": policy.pattern_no,
            "selected_pattern_id": policy.pattern_id,
            "selected_pattern_name": policy.pattern_name,
            "faq_policy": policy.faq_policy,
            "packet_path": str(packet_path),
            "status": "pending",
            "error": "",
        }
        try:
            raw_result = _run_codex_refactor(packet)
            normalized = _normalize_refactor_output(raw_result, packet)
            validation_errors = _validate_output(normalized, policy)
            before_after = {"packet": packet, "result": normalized, "validation_errors": validation_errors}
            _write_result(work_root, packet, before_after)
            _write_json(work_root / "before-after" / f"{_safe_filename(packet['slug'])}.json", before_after)
            if validation_errors:
                item["status"] = "validation_failed"
                item["error"] = ",".join(validation_errors)
            else:
                update_result = _update_remote_post(db, packet, normalized)
                item["status"] = "updated"
                item["updated_title"] = _safe_text(update_result.get("title") or normalized["title"])
                item["updated_url"] = _safe_text(update_result.get("publicUrl") or update_result.get("url"))
                updated_patterns.append((packet["remote_post_id"], policy, _safe_text(row.get("pattern_reason"))))
        except Exception as exc:  # noqa: BLE001
            item["status"] = "failed"
            item["error"] = str(exc)
        results.append(item)

    if updated_patterns and not args.skip_sync_after:
        sync_cloudflare_posts(db, include_non_published=True)
    for remote_id, policy, reason in updated_patterns:
        _patch_synced_pattern(db, remote_id, policy, reason=reason)
    if updated_patterns:
        db.commit()

    return {
        "status": "ok",
        "processed_count": len(results),
        "updated_count": sum(1 for item in results if item.get("status") == "updated"),
        "failed_count": sum(1 for item in results if item.get("status") in {"failed", "validation_failed"}),
        "items": results,
    }


def _load_packet_policy(packet: dict[str, Any]) -> PatternPolicy:
    policy_data = packet.get("pattern_policy") if isinstance(packet, dict) else None
    if not isinstance(policy_data, dict):
        raise ValueError("packet.pattern_policy is missing.")
    pattern_id = _safe_text(policy_data.get("pattern_id"))
    policy = POLICY_BY_ID.get(pattern_id)
    if policy is None:
        raise ValueError(f"Unknown pattern_id: {pattern_id}")
    return policy


def _apply_packets(db: Session, args: argparse.Namespace, work_root: Path) -> dict[str, Any]:
    results_dir = Path(args.packet_results)
    files = sorted(results_dir.glob("*.json")) if results_dir.exists() else []
    if args.limit and args.limit > 0:
        files = files[: args.limit]

    items: list[dict[str, Any]] = []
    updated_patterns: list[tuple[str, PatternPolicy, str]] = []
    for path in files:
        item = {"path": str(path), "status": "pending", "error": ""}
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            packet = payload.get("packet") if isinstance(payload, dict) else None
            result = payload.get("result") if isinstance(payload, dict) else None
            if not isinstance(packet, dict) or not isinstance(result, dict):
                raise ValueError("Result file must contain packet and result objects.")
            policy = _load_packet_policy(packet)
            normalized = _normalize_refactor_output(result, packet)
            validation_errors = _validate_output(normalized, policy)
            if validation_errors:
                raise ValueError(f"validation_failed: {','.join(validation_errors)}")
            update_result = _update_remote_post(db, packet, normalized)
            item["status"] = "updated"
            item["remote_post_id"] = _safe_text(packet.get("remote_post_id"))
            item["slug"] = _safe_text(packet.get("slug"))
            item["selected_pattern_no"] = policy.pattern_no
            item["selected_pattern_id"] = policy.pattern_id
            item["updated_url"] = _safe_text(update_result.get("publicUrl") or update_result.get("url"))
            updated_patterns.append((_safe_text(packet.get("remote_post_id")), policy, _safe_text(packet.get("pattern_reason"))))
        except Exception as exc:  # noqa: BLE001
            item["status"] = "failed"
            item["error"] = str(exc)
        items.append(item)

    if updated_patterns and not args.skip_sync_after:
        sync_cloudflare_posts(db, include_non_published=True)
    for remote_id, policy, reason in updated_patterns:
        _patch_synced_pattern(db, remote_id, policy, reason=reason)
    if updated_patterns:
        db.commit()

    _write_json(work_root / "apply-result.json", {"items": items})
    return {
        "status": "ok",
        "processed_count": len(items),
        "updated_count": sum(1 for item in items if item.get("status") == "updated"),
        "failed_count": sum(1 for item in items if item.get("status") == "failed"),
        "items": items,
    }


def main() -> int:
    args = parse_args()
    work_root = Path(args.work_root)
    work_root.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as db:
        if args.mode == "dry_run":
            _, manifest = _build_manifest(db, args, work_root)
            summary = {
                "status": "ok",
                "mode": args.mode,
                "total": len(manifest),
                "valid": sum(1 for row in manifest if row["decision"] == "valid"),
                "misclassified": sum(1 for row in manifest if row["decision"] == "misclassified"),
                "needs_review": sum(1 for row in manifest if row["decision"] == "needs_review"),
                "pattern_summary": _build_pattern_summary(manifest),
                "work_root": str(work_root),
            }
        elif args.mode == "packet_only":
            packet_result = _packet_only(db, args, work_root)
            summary = {"status": "ok", "mode": args.mode, **packet_result, "work_root": str(work_root)}
        elif args.mode == "execute":
            summary = {"mode": args.mode, **_execute(db, args, work_root), "work_root": str(work_root)}
        else:
            summary = {"mode": args.mode, **_apply_packets(db, args, work_root), "work_root": str(work_root)}

    summary["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    _write_json(work_root / "apply-result.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if int(summary.get("failed_count") or 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
