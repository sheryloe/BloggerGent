from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    CloudflareCategoryPersonaPack,
    CloudflarePrnRun,
    CloudflarePrnTitleCandidate,
)


PRN_VERSION = 1
PRN_TITLE_PUBLISH_MIN = {
    "final_score": 78.0,
    "prn": 72.0,
    "ctr_quality": 68.0,
    "practicality": 65.0,
    "pattern_fit": 70.0,
}

_BANNED_TITLE_TERMS = {
    "충격",
    "무조건",
    "반드시",
    "대박",
    "비밀",
    "절대",
    "수익 보장",
    "급등",
    "폭락 확정",
    "최고",
}

_PRACTICAL_TERMS = {
    "체크리스트",
    "가이드",
    "플레이북",
    "운영",
    "판단",
    "정리",
    "비교",
    "순서",
    "기준",
    "실무",
    "동선",
    "시간",
    "리스크",
    "시나리오",
}

_TITLE_FRAME_SUFFIXES = (
    "{keyword} 2026 | {value}",
    "{keyword} 체크리스트 2026 | {value}",
    "{keyword} 운영 가이드 2026 | {value}",
    "{keyword} 플레이북 2026 | {value}",
    "{keyword}: {value}",
    "{keyword} 비교 정리 | {value}",
    "{keyword} 실무 메모 | {value}",
    "{keyword} 판단 기준 | {value}",
    "{keyword} 적용 순서 | {value}",
    "{keyword} 리스크 점검 | {value}",
)


@dataclass(frozen=True, slots=True)
class CloudflarePrnOptions:
    enabled: bool = True
    version: int = PRN_VERSION
    candidate_count: int = 10
    preselect_count: int = 3
    required: bool = False
    persist_candidates: bool = True


def normalize_prn_options(value: Any) -> CloudflarePrnOptions:
    if not isinstance(value, dict):
        return CloudflarePrnOptions()
    enabled = value.get("enabled")
    candidate_count = _safe_int(value.get("candidate_count"), 10)
    preselect_count = _safe_int(value.get("preselect_count"), 3)
    version = _safe_int(value.get("version"), PRN_VERSION)
    return CloudflarePrnOptions(
        enabled=True if enabled is None else bool(enabled),
        version=max(1, version),
        candidate_count=max(4, min(candidate_count, 20)),
        preselect_count=max(1, min(preselect_count, 5)),
        required=bool(value.get("required", False)),
        persist_candidates=bool(value.get("persist_candidates", True)),
    )


def preview_cloudflare_prn_titles(
    *,
    keyword: str,
    category_slug: str,
    category_name: str = "",
    persona_pack: CloudflareCategoryPersonaPack | None = None,
    article_pattern_id: str | None = None,
    article_pattern_version: int | None = None,
    existing_titles: list[str] | None = None,
    planner_brief: dict[str, Any] | None = None,
    options: CloudflarePrnOptions | None = None,
) -> dict[str, Any]:
    options = options or CloudflarePrnOptions()
    if not options.enabled:
        return {
            "enabled": False,
            "version": options.version,
            "status": "disabled",
            "selected_title": "",
            "selected_score": None,
            "candidates": [],
        }

    titles = build_prn_title_candidates(
        keyword=keyword,
        category_slug=category_slug,
        category_name=category_name,
        persona_pack=persona_pack,
        planner_brief=planner_brief,
        candidate_count=options.candidate_count,
    )
    candidates = [
        score_prn_title_candidate(
            title=title,
            keyword=keyword,
            category_slug=category_slug,
            persona_pack=persona_pack,
            article_pattern_id=article_pattern_id,
            article_pattern_version=article_pattern_version,
            existing_titles=existing_titles or [],
            rank=index + 1,
        )
        for index, title in enumerate(titles)
    ]
    candidates.sort(key=lambda item: (float(item.get("final_score") or 0), -int(item.get("rank") or 0)), reverse=True)
    for index, item in enumerate(candidates, start=1):
        item["rank"] = index
    selected = next((item for item in candidates if item.get("decision") != "reject"), candidates[0] if candidates else {})
    return {
        "enabled": True,
        "version": options.version,
        "status": "ready" if selected else "empty",
        "category_slug": category_slug,
        "category_name": category_name,
        "keyword": keyword,
        "article_pattern_id": article_pattern_id,
        "article_pattern_version": article_pattern_version,
        "persona_pack_key": getattr(persona_pack, "pack_key", None),
        "persona_pack_version": getattr(persona_pack, "version", None),
        "selected_title": str(selected.get("title") or ""),
        "selected_score": selected.get("final_score"),
        "top_candidates": candidates[: options.preselect_count],
        "candidates": candidates,
        "thresholds": dict(PRN_TITLE_PUBLISH_MIN),
    }


def build_prn_prompt_block(prn_preview: dict[str, Any]) -> str:
    if not prn_preview.get("enabled") or not prn_preview.get("selected_title"):
        return ""
    lines = [
        "\n\n[PRN title and CTR lock]",
        "- PRN means Persona Relevance Normalization. Pattern is authority; persona is lens.",
        f"- Use this locked title unless it violates factual accuracy: {prn_preview['selected_title']}",
        f"- Locked pattern id: {prn_preview.get('article_pattern_id') or 'auto'}",
        "- The article must solve the reader problem implied by this title, not drift into a generic overview.",
        "- Do not add clickbait, miracle claims, or persona demographic details.",
        "- Keep FAQ optional. Use FAQ only when the locked category pattern needs it.",
    ]
    top_candidates = prn_preview.get("top_candidates") if isinstance(prn_preview.get("top_candidates"), list) else []
    if top_candidates:
        lines.append("- Backup title angles:")
        for item in top_candidates[:3]:
            title = str(item.get("title") or "").strip()
            score = item.get("final_score")
            if title:
                lines.append(f"  - {title} (score: {score})")
    return "\n".join(lines)


def rerank_prn_after_article(
    prn_preview: dict[str, Any],
    *,
    article_title: str,
    article_excerpt: str,
    article_body: str,
    persona_fit_score: float | None = None,
    quality_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not prn_preview.get("enabled"):
        return prn_preview
    candidates = list(prn_preview.get("candidates") or [])
    existing_titles = {str(item.get("title") or "").strip().casefold() for item in candidates}
    generated_title = str(article_title or "").strip()
    if generated_title and generated_title.casefold() not in existing_titles:
        candidates.append(
            score_prn_title_candidate(
                title=generated_title,
                keyword=str(prn_preview.get("keyword") or ""),
                category_slug=str(prn_preview.get("category_slug") or ""),
                persona_pack=None,
                article_pattern_id=str(prn_preview.get("article_pattern_id") or ""),
                article_pattern_version=_safe_int(prn_preview.get("article_pattern_version"), PRN_VERSION),
                existing_titles=[],
                rank=len(candidates) + 1,
                source="article_output",
            )
        )
    body_signal = _body_practicality_signal(article_excerpt, article_body)
    persona_bonus = min(max(float(persona_fit_score or 0.0) - 70.0, 0.0), 15.0) * 0.2
    quality_scores = quality_gate.get("scores") if isinstance(quality_gate, dict) else {}
    ctr_bonus = min(max(float((quality_scores or {}).get("ctr_score") or 0.0) - 70.0, 0.0), 15.0) * 0.2
    for item in candidates:
        adjusted = float(item.get("final_score") or 0.0) + body_signal + persona_bonus + ctr_bonus
        item["final_score"] = round(min(100.0, adjusted), 2)
        item["post_article_adjustment"] = {
            "body_signal": round(body_signal, 2),
            "persona_bonus": round(persona_bonus, 2),
            "ctr_bonus": round(ctr_bonus, 2),
        }
        item["decision"] = "selectable" if _passes_thresholds(item) else item.get("decision", "candidate")
    candidates.sort(key=lambda item: (float(item.get("final_score") or 0), -int(item.get("rank") or 0)), reverse=True)
    for index, item in enumerate(candidates, start=1):
        item["rank"] = index
    selected = next((item for item in candidates if item.get("decision") != "reject"), candidates[0] if candidates else {})
    updated = dict(prn_preview)
    updated["status"] = "reranked"
    updated["selected_title"] = str(selected.get("title") or prn_preview.get("selected_title") or "")
    updated["selected_score"] = selected.get("final_score")
    updated["top_candidates"] = candidates[:3]
    updated["candidates"] = candidates
    return updated


def persist_prn_run(
    db: Session,
    *,
    managed_channel_id: int | None,
    prn_preview: dict[str, Any],
    status: str = "generated",
) -> CloudflarePrnRun | None:
    if not managed_channel_id or not prn_preview.get("enabled"):
        return None
    run = CloudflarePrnRun(
        managed_channel_id=managed_channel_id,
        category_slug=str(prn_preview.get("category_slug") or ""),
        keyword=str(prn_preview.get("keyword") or ""),
        article_pattern_id=str(prn_preview.get("article_pattern_id") or "").strip() or None,
        article_pattern_version=_safe_optional_int(prn_preview.get("article_pattern_version")),
        persona_pack_key=str(prn_preview.get("persona_pack_key") or "").strip() or None,
        persona_pack_version=_safe_optional_int(prn_preview.get("persona_pack_version")),
        prn_version=_safe_int(prn_preview.get("version"), PRN_VERSION),
        selected_title=str(prn_preview.get("selected_title") or ""),
        selected_score=_safe_optional_float(prn_preview.get("selected_score")),
        status=status,
        payload=_public_prn_payload(prn_preview),
    )
    db.add(run)
    db.flush()
    for item in list(prn_preview.get("candidates") or []):
        db.add(
            CloudflarePrnTitleCandidate(
                run_id=run.id,
                title=str(item.get("title") or "")[:500],
                rank=_safe_int(item.get("rank"), 0),
                source=str(item.get("source") or "heuristic")[:50],
                final_score=_safe_optional_float(item.get("final_score")),
                prn_score=_safe_optional_float(item.get("prn")),
                ctr_quality_score=_safe_optional_float(item.get("ctr_quality")),
                practicality_score=_safe_optional_float(item.get("practicality")),
                pattern_fit_score=_safe_optional_float(item.get("pattern_fit")),
                forbidden_hygiene_score=_safe_optional_float(item.get("forbidden_hygiene")),
                decision=str(item.get("decision") or "candidate")[:30],
                rejection_reason=str(item.get("rejection_reason") or "").strip()[:255] or None,
                payload={key: value for key, value in item.items() if key not in {"title"}},
            )
        )
    return run


def list_prn_runs(db: Session, *, managed_channel_id: int, limit: int = 50) -> list[dict[str, Any]]:
    rows = (
        db.execute(
            select(CloudflarePrnRun)
            .where(CloudflarePrnRun.managed_channel_id == managed_channel_id)
            .order_by(CloudflarePrnRun.created_at.desc())
            .limit(max(1, min(int(limit), 200)))
        )
        .scalars()
        .all()
    )
    return [_run_to_dict(row, include_candidates=False) for row in rows]


def get_prn_run(db: Session, *, managed_channel_id: int, run_id: int) -> dict[str, Any] | None:
    row = (
        db.execute(
            select(CloudflarePrnRun).where(
                CloudflarePrnRun.id == run_id,
                CloudflarePrnRun.managed_channel_id == managed_channel_id,
            )
        )
        .scalars()
        .first()
    )
    return _run_to_dict(row, include_candidates=True) if row is not None else None


def build_prn_title_candidates(
    *,
    keyword: str,
    category_slug: str,
    category_name: str = "",
    persona_pack: CloudflareCategoryPersonaPack | None = None,
    planner_brief: dict[str, Any] | None = None,
    candidate_count: int = 10,
) -> list[str]:
    clean_keyword = _clean_title_part(keyword) or _clean_title_part(category_name) or "운영 주제"
    value_phrases = _value_phrases(category_slug, persona_pack=persona_pack, planner_brief=planner_brief)
    titles: list[str] = []
    seen: set[str] = set()
    for index, frame in enumerate(_TITLE_FRAME_SUFFIXES):
        value = value_phrases[index % len(value_phrases)]
        title = frame.format(keyword=clean_keyword, value=value)
        title = _normalize_title(title)
        key = title.casefold()
        if key in seen:
            continue
        seen.add(key)
        titles.append(title)
        if len(titles) >= candidate_count:
            break
    return titles


def score_prn_title_candidate(
    *,
    title: str,
    keyword: str,
    category_slug: str,
    persona_pack: CloudflareCategoryPersonaPack | None,
    article_pattern_id: str | None,
    article_pattern_version: int | None,
    existing_titles: list[str],
    rank: int,
    source: str = "heuristic_pre",
) -> dict[str, Any]:
    normalized_title = _normalize_title(title)
    lower = normalized_title.casefold()
    banned_hits = [term for term in _BANNED_TITLE_TERMS if term.casefold() in lower]
    duplicate_hit = any(_rough_similarity(normalized_title, existing) >= 0.86 for existing in existing_titles)
    persona_terms = _persona_terms(persona_pack)
    prn = _term_overlap_score(normalized_title, persona_terms, base=64.0, per_hit=7.5, max_score=96.0)
    ctr_quality = _ctr_quality_score(normalized_title, category_slug=category_slug, persona_pack=persona_pack)
    practicality = _term_overlap_score(normalized_title, _PRACTICAL_TERMS, base=58.0, per_hit=8.5, max_score=95.0)
    pattern_fit = _pattern_fit_score(normalized_title, article_pattern_id=article_pattern_id)
    forbidden_hygiene = 100.0 - (len(banned_hits) * 18.0) - (20.0 if duplicate_hit else 0.0)
    forbidden_hygiene = max(0.0, forbidden_hygiene)
    final_score = (
        0.30 * prn
        + 0.25 * ctr_quality
        + 0.20 * practicality
        + 0.15 * pattern_fit
        + 0.10 * forbidden_hygiene
    )
    rejection_reason = ""
    decision = "candidate"
    if banned_hits:
        decision = "reject"
        rejection_reason = f"banned_hook:{','.join(banned_hits)}"
    elif duplicate_hit:
        decision = "reject"
        rejection_reason = "duplicate_title"
    elif final_score >= PRN_TITLE_PUBLISH_MIN["final_score"]:
        decision = "selectable"
    return {
        "rank": rank,
        "title": normalized_title,
        "source": source,
        "final_score": round(final_score, 2),
        "prn": round(prn, 2),
        "ctr_quality": round(ctr_quality, 2),
        "practicality": round(practicality, 2),
        "pattern_fit": round(pattern_fit, 2),
        "forbidden_hygiene": round(forbidden_hygiene, 2),
        "article_pattern_id": article_pattern_id,
        "article_pattern_version": article_pattern_version,
        "decision": decision,
        "rejection_reason": rejection_reason,
        "banned_hits": banned_hits,
    }


def _run_to_dict(row: CloudflarePrnRun, *, include_candidates: bool) -> dict[str, Any]:
    payload = row.payload if isinstance(row.payload, dict) else {}
    result = {
        "id": row.id,
        "managed_channel_id": row.managed_channel_id,
        "category_slug": row.category_slug,
        "keyword": row.keyword,
        "article_pattern_id": row.article_pattern_id,
        "article_pattern_version": row.article_pattern_version,
        "persona_pack_key": row.persona_pack_key,
        "persona_pack_version": row.persona_pack_version,
        "prn_version": row.prn_version,
        "selected_title": row.selected_title,
        "selected_score": row.selected_score,
        "status": row.status,
        "payload": payload,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if include_candidates:
        result["candidates"] = [
            {
                "id": item.id,
                "title": item.title,
                "rank": item.rank,
                "source": item.source,
                "final_score": item.final_score,
                "prn": item.prn_score,
                "ctr_quality": item.ctr_quality_score,
                "practicality": item.practicality_score,
                "pattern_fit": item.pattern_fit_score,
                "forbidden_hygiene": item.forbidden_hygiene_score,
                "decision": item.decision,
                "rejection_reason": item.rejection_reason,
                "payload": item.payload if isinstance(item.payload, dict) else {},
            }
            for item in row.title_candidates
        ]
    return result


def _public_prn_payload(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "enabled": bool(value.get("enabled")),
        "version": _safe_int(value.get("version"), PRN_VERSION),
        "status": str(value.get("status") or ""),
        "selected_title": str(value.get("selected_title") or ""),
        "selected_score": _safe_optional_float(value.get("selected_score")),
        "thresholds": value.get("thresholds") if isinstance(value.get("thresholds"), dict) else dict(PRN_TITLE_PUBLISH_MIN),
        "top_candidates": list(value.get("top_candidates") or [])[:5],
    }


def _value_phrases(
    category_slug: str,
    *,
    persona_pack: CloudflareCategoryPersonaPack | None,
    planner_brief: dict[str, Any] | None,
) -> list[str]:
    base = [
        "팀 단위로 바로 적용하는 기준",
        "실패를 줄이는 실행 순서",
        "도입 전에 확인할 운영 포인트",
        "현장에서 쓰는 판단 체크",
        "비용과 리스크를 함께 보는 구조",
    ]
    if category_slug in {"yeohaenggwa-girog", "cugjewa-hyeonjang", "munhwawa-gonggan"}:
        base = [
            "방문 전에 확인할 동선과 시간대",
            "혼잡과 비용을 줄이는 선택 기준",
            "현장에서 바로 쓰는 체크포인트",
            "예약과 이동을 함께 보는 방법",
            "방문 가치 판단을 빠르게 끝내는 구조",
        ]
    elif category_slug in {"jusigyi-heureum", "keuribtoyi-heureum", "naseudagyi-heureum"}:
        base = [
            "리스크와 시나리오를 분리하는 방법",
            "실적과 정책 변수를 함께 보는 구조",
            "과장 없이 확인할 핵심 지표",
            "매수 권유 없이 흐름을 해석하는 기준",
            "다음 변곡점을 점검하는 관찰 포인트",
        ]
    elif category_slug == "ilsanggwa-memo":
        base = [
            "작은 장면에서 건지는 생활 기준",
            "과장 없이 정리하는 하루의 변화",
            "다음 선택을 가볍게 만드는 메모",
            "생활 리듬을 다시 보는 관찰 포인트",
            "일상 기록을 실용적으로 남기는 방법",
        ]
    if persona_pack is not None:
        emphasis = [str(item).strip() for item in (persona_pack.category_emphasis or []) if str(item or "").strip()]
        if emphasis:
            base.extend(f"{item} 중심으로 읽는 판단 기준" for item in emphasis[:4])
    if isinstance(planner_brief, dict):
        audience = str(planner_brief.get("audience") or "").strip()
        if audience:
            base.insert(0, f"{audience}를 위한 적용 가치")
    return base


def _persona_terms(persona_pack: CloudflareCategoryPersonaPack | None) -> set[str]:
    terms: set[str] = set()
    if persona_pack is None:
        return {"실무", "판단", "운영", "기준", "리스크", "시간", "비용"}
    for value in (
        persona_pack.display_name,
        persona_pack.primary_reader,
        persona_pack.reader_problem,
        persona_pack.tone_summary,
        persona_pack.trust_style,
    ):
        terms.update(_tokens(str(value or "")))
    for item in list(persona_pack.topic_guidance or []) + list(persona_pack.category_emphasis or []):
        terms.update(_tokens(str(item or "")))
    title_rules = persona_pack.title_rules if isinstance(persona_pack.title_rules, dict) else {}
    ctr_rules = persona_pack.ctr_rules if isinstance(persona_pack.ctr_rules, dict) else {}
    for key in ("preferred_frames", "allowed_hooks"):
        for item in title_rules.get(key, []) if key in title_rules else ctr_rules.get(key, []):
            terms.update(_tokens(str(item or "")))
    return {term for term in terms if len(term) >= 2}


def _ctr_quality_score(
    title: str,
    *,
    category_slug: str,
    persona_pack: CloudflareCategoryPersonaPack | None,
) -> float:
    score = 58.0
    if re.search(r"20\d{2}", title):
        score += 8.0
    if "|" in title or ":" in title:
        score += 8.0
    if any(term in title for term in _PRACTICAL_TERMS):
        score += 10.0
    if 18 <= len(title) <= 72:
        score += 6.0
    if category_slug.startswith("gaebal") and any(term in title for term in ("IDE", "CLI", "MCP", "AI", "배포", "디버깅")):
        score += 8.0
    allowed_hooks = []
    if persona_pack is not None and isinstance(persona_pack.ctr_rules, dict):
        allowed_hooks = [str(item).strip() for item in persona_pack.ctr_rules.get("allowed_hooks", []) if str(item or "").strip()]
    if allowed_hooks and any(hook in title for hook in allowed_hooks):
        score += 7.0
    return min(100.0, score)


def _pattern_fit_score(title: str, *, article_pattern_id: str | None) -> float:
    pattern = str(article_pattern_id or "").strip().casefold()
    if not pattern:
        return 72.0
    title_lower = title.casefold()
    if "chat" in pattern and any(term in title for term in ("비교", "관점", "대화")):
        return 90.0
    if "guide" in pattern and any(term in title for term in ("가이드", "기준", "순서")):
        return 90.0
    if "check" in pattern and "체크" in title:
        return 92.0
    if "deep" in pattern and any(term in title_lower for term in ("deep", "정리", "분석")):
        return 86.0
    if "memo" in pattern and "메모" in title:
        return 90.0
    if "review" in pattern and any(term in title for term in ("리뷰", "비교", "선택")):
        return 88.0
    return 76.0


def _term_overlap_score(text: str, terms: set[str], *, base: float, per_hit: float, max_score: float) -> float:
    if not terms:
        return base
    hits = 0
    for term in terms:
        if term and term in text:
            hits += 1
    return min(max_score, base + hits * per_hit)


def _body_practicality_signal(excerpt: str, body: str) -> float:
    text = f"{excerpt} {body}"
    hits = sum(1 for term in _PRACTICAL_TERMS if term in text)
    return min(6.0, hits * 0.8)


def _passes_thresholds(item: dict[str, Any]) -> bool:
    return (
        float(item.get("final_score") or 0) >= PRN_TITLE_PUBLISH_MIN["final_score"]
        and float(item.get("prn") or 0) >= PRN_TITLE_PUBLISH_MIN["prn"]
        and float(item.get("ctr_quality") or 0) >= PRN_TITLE_PUBLISH_MIN["ctr_quality"]
        and float(item.get("practicality") or 0) >= PRN_TITLE_PUBLISH_MIN["practicality"]
        and float(item.get("pattern_fit") or 0) >= PRN_TITLE_PUBLISH_MIN["pattern_fit"]
    )


def _clean_title_part(value: str) -> str:
    text = _normalize_title(value)
    text = re.sub(r"\s+", " ", text)
    return text[:90].strip()


def _normalize_title(value: str) -> str:
    text = str(value or "").replace("\n", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:150].strip()


def _tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^0-9A-Za-z가-힣]+", value) if len(token) >= 2}


def _rough_similarity(left: str, right: str) -> float:
    left_tokens = _tokens(left.casefold())
    right_tokens = _tokens(right.casefold())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens | right_tokens), 1)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_optional_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
