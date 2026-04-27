from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
import re
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.entities import CloudflareCategoryPersonaPack, ManagedChannel


PERSONA_ATTRIBUTION = "NVIDIA Nemotron-Personas-Korea, CC BY 4.0"
PERSONA_SOURCE_URL = "https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea"

PILOT_ACTIVE_SLUGS = {
    "yeohaenggwa-girog",
    "munhwawa-gonggan",
    "cugjewa-hyeonjang",
    "salmeul-yuyonghage",
}

FORBIDDEN_PERSONA_FIELD_KEYS = {
    "name",
    "exact_age",
    "age",
    "sex",
    "gender",
    "marital_status",
    "military_status",
    "district",
    "province",
    "occupation",
    "education",
    "health",
    "politics",
    "religion",
}

_DEFAULT_PACKS: dict[str, dict[str, Any]] = {
    "gaebalgwa-peurogeuraeming": {
        "pack_key": "dev-operator-automation-v1",
        "display_name": "실무 자동화 운영자",
        "description": "AI 도구, IDE/CLI 워크플로, 배포 자동화, 관측성 중심의 개발 운영 독자 렌즈",
        "primary_reader": "새 도구를 팀 운영 기준으로 판단해야 하는 개발 리더와 실무자",
        "reader_problem": "AI 도구와 자동화가 팀 개발 방식, 비용, 디버깅 흐름에 어떤 영향을 주는지 빠르게 판단하고 싶다",
        "tone_summary": "실무 메모와 편집자 해설을 섞은 차분한 운영 기준",
        "trust_style": "공식 문서, 릴리스 노트, 엔지니어링 블로그 기반의 근거형 정리",
        "topic_guidance": ["MCP와 에이전트 도입", "IDE/CLI 워크플로 변화", "배포 자동화", "관측성과 디버깅"],
        "category_emphasis": ["팀 운영 영향", "비용과 권한", "디버깅 가능성", "도입 체크리스트"],
    },
    "ilsanggwa-memo": {
        "pack_key": "daily-observer-memo-v1",
        "display_name": "일상 관찰 메모러",
        "primary_reader": "작은 생활 변화에서 쓸 만한 생각을 찾는 독자",
        "reader_problem": "일상 장면을 과장 없이 정리하고 내 생활에 적용할 기준을 얻고 싶다",
        "tone_summary": "담백한 관찰, 짧은 회고, 실용적인 마무리",
        "trust_style": "경험을 일반화하지 않고 관찰과 적용 기준을 분리",
        "topic_guidance": ["습관", "생활 리듬", "소비와 선택", "작은 회고"],
        "category_emphasis": ["관찰", "맥락", "적용 기준", "짧은 결론"],
    },
    "yeohaenggwa-girog": {
        "pack_key": "travel-practical-local-v1",
        "display_name": "현장형 한국 로컬 가이드",
        "primary_reader": "검색 후 바로 방문 여부를 판단하려는 한국어 독자",
        "reader_problem": "시간, 동선, 혼잡, 비용을 기준으로 여행지를 선택하고 싶다",
        "tone_summary": "차분함, 실용성, 과장 없음",
        "trust_style": "확인 가능한 현장 정보와 판단 기준 중심",
        "topic_guidance": ["동선", "교통", "소요 시간", "대기 회피", "근처 연계"],
        "category_emphasis": ["장소명", "시간대", "교통", "대기 신호", "예산"],
    },
    "salmeul-yuyonghage": {
        "pack_key": "life-practical-routine-v1",
        "display_name": "생활 효율 실험가",
        "primary_reader": "도구와 루틴으로 생활 문제를 해결하려는 독자",
        "reader_problem": "복잡한 설명보다 바로 적용 가능한 선택 기준과 순서가 필요하다",
        "tone_summary": "명확하고 실용적인 안내, 과장 없는 비교",
        "trust_style": "절차, 조건, 주의점, 대체 선택지를 함께 제시",
        "topic_guidance": ["생활 루틴", "앱과 도구", "시간 절약", "비용 절감"],
        "category_emphasis": ["적용 순서", "비용", "조건", "실패 회피"],
    },
    "salmyi-gireumcil": {
        "pack_key": "benefit-checker-v1",
        "display_name": "혜택 점검 실무자",
        "primary_reader": "지원금, 카드, 신청 절차, 생활 혜택을 놓치고 싶지 않은 독자",
        "reader_problem": "조건과 신청 흐름을 빠르게 확인하고 손해를 줄이고 싶다",
        "tone_summary": "체크리스트형, 조건 중심, 단정 과장 금지",
        "trust_style": "조건, 일정, 준비물, 예외를 분리",
        "topic_guidance": ["신청 흐름", "조건 확인", "절약 비교", "주의사항"],
        "category_emphasis": ["대상", "기간", "준비물", "실수 방지"],
    },
    "donggeuriyi-saenggag": {
        "pack_key": "social-context-editor-v1",
        "display_name": "기술과 생활 맥락 해설자",
        "primary_reader": "사회 변화와 기술 이슈를 생활 감각으로 이해하려는 독자",
        "reader_problem": "이 이슈가 내 생활과 판단에 어떤 의미인지 알고 싶다",
        "tone_summary": "차분한 해설, 개인적 단상은 짧게, 일반화 금지",
        "trust_style": "맥락과 관찰을 분리하고 결론은 열린 형태로 제시",
        "topic_guidance": ["기술 문화", "세대 감각", "사회 맥락", "일상의 변화"],
        "category_emphasis": ["맥락", "영향", "해석", "다음 관찰 지점"],
    },
    "miseuteria-seutori": {
        "pack_key": "mystery-record-context-v1",
        "display_name": "미스터리 기록 정리자",
        "primary_reader": "사건과 전설을 흥미보다 기록 구조로 보고 싶은 독자",
        "reader_problem": "무서운 이야기보다 사실, 해석, 남은 의문을 구분해 읽고 싶다",
        "tone_summary": "기록형, 과장 금지, 단서와 해석 분리",
        "trust_style": "확인된 기록, 전승, 추정, 현재 상태를 명확히 구분",
        "topic_guidance": ["사건 기록", "전설 맥락", "현장 상상", "남은 의문"],
        "category_emphasis": ["기록", "단서", "해석", "현재 추적 상태"],
    },
    "jusigyi-heureum": {
        "pack_key": "market-risk-observer-v1",
        "display_name": "시장 리스크 관찰자",
        "primary_reader": "투자 조언이 아니라 시장 흐름과 리스크를 정리하려는 독자",
        "reader_problem": "기업 이벤트와 거시 변수를 과장 없이 구분해 보고 싶다",
        "tone_summary": "분석 메모, 투자 권유 금지, 시나리오 중심",
        "trust_style": "공시, 실적, 거시 지표, 리스크를 분리",
        "topic_guidance": ["기업 이벤트", "실적", "거시 변수", "리스크 체크"],
        "category_emphasis": ["조건", "시나리오", "리스크", "관찰 지표"],
    },
    "keuribtoyi-heureum": {
        "pack_key": "crypto-regulation-observer-v1",
        "display_name": "크립토 규제 관찰자",
        "primary_reader": "가격 예측보다 규제, 프로토콜, 시장 구조를 보고 싶은 독자",
        "reader_problem": "온체인과 규제 뉴스가 실제 흐름에 어떤 의미인지 알고 싶다",
        "tone_summary": "신중한 관찰, 투자 권유 금지, 용어 설명은 간결하게",
        "trust_style": "프로토콜, 규제, 유동성, 리스크를 분리",
        "topic_guidance": ["규제", "온체인", "프로토콜", "거래소 흐름"],
        "category_emphasis": ["구조", "위험", "변수", "확인 지표"],
    },
    "naseudagyi-heureum": {
        "pack_key": "nasdaq-bigtech-scenario-v1",
        "display_name": "빅테크 시나리오 분석자",
        "primary_reader": "나스닥과 빅테크 흐름을 실적과 정책 기준으로 보려는 독자",
        "reader_problem": "단기 가격보다 실적, 밸류에이션, 정책 변수를 구분하고 싶다",
        "tone_summary": "시나리오형, 숫자와 변수 중심, 투자 권유 금지",
        "trust_style": "실적, 금리, 정책, 밸류에이션을 분리",
        "topic_guidance": ["빅테크", "실적", "밸류에이션", "금리와 정책"],
        "category_emphasis": ["핵심 변수", "리스크", "시나리오", "관찰 일정"],
    },
    "cugjewa-hyeonjang": {
        "pack_key": "festival-field-checker-v1",
        "display_name": "축제 현장 체크 가이드",
        "primary_reader": "축제 방문 전 혼잡, 입장, 이동, 가족 동반 가능성을 확인하려는 독자",
        "reader_problem": "가도 되는 시간과 피해야 할 변수를 빠르게 알고 싶다",
        "tone_summary": "현장 체크형, 실용적, 과장 없는 기대치 조정",
        "trust_style": "행사 일정, 입장, 동선, 혼잡 신호를 분리",
        "topic_guidance": ["혼잡 회피", "이동", "입장", "가족 방문", "현장 체크"],
        "category_emphasis": ["시간대", "입장 방식", "동선", "준비물", "대체 코스"],
    },
    "munhwawa-gonggan": {
        "pack_key": "culture-space-curator-v1",
        "display_name": "문화 공간 큐레이터",
        "primary_reader": "전시, 공간, 공연을 방문 가치와 동선 기준으로 판단하려는 독자",
        "reader_problem": "공간의 맥락과 예약, 관람 순서, 주변 연계를 알고 싶다",
        "tone_summary": "차분한 큐레이션, 감성 과장보다 관람 판단 중심",
        "trust_style": "공간 맥락, 예약, 관람 동선, 혼잡 시간을 분리",
        "topic_guidance": ["공간 맥락", "관람 동선", "예약", "시간대", "경험 종합"],
        "category_emphasis": ["예약", "관람 순서", "혼잡", "주변 연계", "추천 대상"],
    },
}


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)


def _plain_text(value: str) -> str:
    parser = _HTMLTextExtractor()
    parser.feed(value or "")
    return " ".join(" ".join(parser.parts).split())


def _normalize_slug(value: Any) -> str:
    return str(value or "").strip()


def _safe_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    text = str(value or "").strip()
    return [text] if text else []


def _default_title_rules(category_slug: str) -> dict[str, list[str]]:
    if category_slug in {"yeohaenggwa-girog", "cugjewa-hyeonjang", "munhwawa-gonggan"}:
        return {
            "preferred_frames": ["장소+상황+판단포인트", "동선+시간대+피해야 할 변수", "방문 가치+실용 결과"],
            "banned_frames": ["감성 과장형", "전국구 뭉뚱그린 리스트형", "정답/필수/무조건 단정형"],
        }
    if category_slug in {"jusigyi-heureum", "keuribtoyi-heureum", "naseudagyi-heureum"}:
        return {
            "preferred_frames": ["시장 변수+연도+관찰 포인트", "기업/섹터+리스크+시나리오", "정책/실적+흐름 정리"],
            "banned_frames": ["수익 보장형", "급등/폭락 단정형", "매수/매도 권유형"],
        }
    return {
        "preferred_frames": ["주제+연도+실무 결과", "문제+체크리스트/가이드/플레이북", "구체 상황+적용 가치"],
        "banned_frames": ["막연한 감성형", "근거 없는 최고/필수형", "낚시성 반전형"],
    }


def _default_ctr_rules(category_slug: str) -> dict[str, list[str]]:
    if category_slug in {"yeohaenggwa-girog", "cugjewa-hyeonjang", "munhwawa-gonggan"}:
        allowed = ["구체적 장소", "방문 타이밍", "줄 피하는 포인트", "예산/시간 절약"]
    elif category_slug in {"jusigyi-heureum", "keuribtoyi-heureum", "naseudagyi-heureum"}:
        allowed = ["핵심 변수", "실적/정책 일정", "리스크 점검", "시나리오 비교"]
    else:
        allowed = ["구체적 문제", "바로 적용할 판단 기준", "비용/시간/실패 회피", "운영 체크포인트"]
    return {
        "allowed_hooks": allowed,
        "forbidden_hooks": ["낚시성 반전", "근거 없는 충격 표현", "과장된 희소성", "민감 속성 일반화"],
    }


def _pack_to_dict(pack: CloudflareCategoryPersonaPack, *, include_profiles: bool = False) -> dict[str, Any]:
    payload = {
        "id": pack.id,
        "managed_channel_id": pack.managed_channel_id,
        "category_slug": pack.category_slug,
        "category_id": pack.category_id,
        "pack_key": pack.pack_key,
        "display_name": pack.display_name,
        "description": pack.description,
        "primary_reader": pack.primary_reader,
        "reader_problem": pack.reader_problem,
        "tone_summary": pack.tone_summary,
        "trust_style": pack.trust_style,
        "topic_guidance": list(pack.topic_guidance or []),
        "title_rules": dict(pack.title_rules or {}),
        "ctr_rules": dict(pack.ctr_rules or {}),
        "category_emphasis": list(pack.category_emphasis or []),
        "source_manifest_ref": pack.source_manifest_ref,
        "attribution": pack.attribution,
        "version": pack.version,
        "is_active": pack.is_active,
        "is_default": pack.is_default,
        "sort_order": pack.sort_order,
        "created_at": pack.created_at.isoformat() if pack.created_at else None,
        "updated_at": pack.updated_at.isoformat() if pack.updated_at else None,
    }
    if include_profiles:
        payload["sanitized_profiles"] = list(pack.sanitized_profiles or [])
    return payload


def default_cloudflare_persona_pack_payload(category: dict[str, Any], *, sort_order: int = 100) -> dict[str, Any]:
    category_slug = _normalize_slug(category.get("slug"))
    base = dict(_DEFAULT_PACKS.get(category_slug) or {})
    if not base:
        category_name = str(category.get("name") or category_slug or "Cloudflare category").strip()
        base = {
            "pack_key": f"{category_slug or 'category'}-reader-fit-v1",
            "display_name": f"{category_name} 독자 관점 팩",
            "primary_reader": f"{category_name} 주제를 실용적으로 판단하려는 독자",
            "reader_problem": "핵심 맥락, 판단 기준, 실행 포인트를 빠르게 확인하고 싶다",
            "tone_summary": "명확하고 실용적인 운영 메모",
            "trust_style": "확인 가능한 근거와 적용 기준 중심",
            "topic_guidance": [category_name],
            "category_emphasis": ["맥락", "판단 기준", "실행 포인트"],
        }
    return {
        "category_slug": category_slug,
        "category_id": _normalize_slug(category.get("id")) or None,
        "pack_key": str(base.get("pack_key") or f"{category_slug}-reader-fit-v1").strip(),
        "display_name": str(base.get("display_name") or "Cloudflare persona pack").strip(),
        "description": str(base.get("description") or "").strip() or None,
        "primary_reader": str(base.get("primary_reader") or "").strip() or None,
        "reader_problem": str(base.get("reader_problem") or "").strip() or None,
        "tone_summary": str(base.get("tone_summary") or "").strip() or None,
        "trust_style": str(base.get("trust_style") or "").strip() or None,
        "topic_guidance": _safe_list(base.get("topic_guidance")),
        "title_rules": _default_title_rules(category_slug),
        "ctr_rules": _default_ctr_rules(category_slug),
        "category_emphasis": _safe_list(base.get("category_emphasis")),
        "sanitized_profiles": [
            {
                "traveler_style": "practical",
                "trip_pace": "moderate",
                "crowd_preference": "avoid-busy-hours",
                "transport_preference": "public-transit-first",
                "tone_register": "practical-and-polite",
                "decision_style": "compare-time-cost-risk",
            }
        ],
        "source_manifest_ref": r"E:\BloggerGent\datasets\hf\nvidia\Nemotron-Personas-Korea\2026-04-20-v1.0\derived\persona_candidate_manifest.json",
        "attribution": PERSONA_ATTRIBUTION,
        "version": 1,
        "is_active": category_slug in PILOT_ACTIVE_SLUGS,
        "is_default": category_slug in PILOT_ACTIVE_SLUGS,
        "sort_order": sort_order,
    }


def ensure_default_cloudflare_persona_packs(
    db: Session,
    *,
    managed_channel: ManagedChannel,
    categories: list[dict[str, Any]],
) -> dict[str, int]:
    created = 0
    updated = 0
    for index, category in enumerate(categories):
        payload = default_cloudflare_persona_pack_payload(category, sort_order=(index + 1) * 10)
        category_slug = payload["category_slug"]
        pack_key = payload["pack_key"]
        existing = db.execute(
            select(CloudflareCategoryPersonaPack).where(
                CloudflareCategoryPersonaPack.managed_channel_id == managed_channel.id,
                CloudflareCategoryPersonaPack.category_slug == category_slug,
                CloudflareCategoryPersonaPack.pack_key == pack_key,
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(CloudflareCategoryPersonaPack(managed_channel_id=managed_channel.id, **payload))
            created += 1
            continue
        changed = False
        for field in (
            "category_id",
            "display_name",
            "description",
            "primary_reader",
            "reader_problem",
            "tone_summary",
            "trust_style",
            "topic_guidance",
            "title_rules",
            "ctr_rules",
            "category_emphasis",
            "source_manifest_ref",
            "attribution",
            "version",
            "sort_order",
        ):
            value = payload[field]
            if getattr(existing, field) != value:
                setattr(existing, field, value)
                changed = True
        if changed:
            updated += 1
    db.flush()
    return {"created": created, "updated": updated}


def list_cloudflare_persona_packs(
    db: Session,
    *,
    managed_channel_id: int,
    category_slug: str | None = None,
    include_profiles: bool = False,
) -> list[dict[str, Any]]:
    query = select(CloudflareCategoryPersonaPack).where(CloudflareCategoryPersonaPack.managed_channel_id == managed_channel_id)
    if category_slug:
        query = query.where(CloudflareCategoryPersonaPack.category_slug == category_slug)
    rows = db.execute(
        query.order_by(
            CloudflareCategoryPersonaPack.category_slug.asc(),
            CloudflareCategoryPersonaPack.sort_order.asc(),
            CloudflareCategoryPersonaPack.id.asc(),
        )
    ).scalars().all()
    return [_pack_to_dict(row, include_profiles=include_profiles) for row in rows]


def get_cloudflare_persona_pack(
    db: Session,
    *,
    managed_channel_id: int,
    category_slug: str,
    pack_key: str | None = None,
    active_only: bool = False,
) -> CloudflareCategoryPersonaPack | None:
    query = select(CloudflareCategoryPersonaPack).where(
        CloudflareCategoryPersonaPack.managed_channel_id == managed_channel_id,
        CloudflareCategoryPersonaPack.category_slug == category_slug,
    )
    if pack_key:
        query = query.where(CloudflareCategoryPersonaPack.pack_key == pack_key)
    else:
        query = query.where(CloudflareCategoryPersonaPack.is_default.is_(True))
    if active_only:
        query = query.where(CloudflareCategoryPersonaPack.is_active.is_(True))
    return db.execute(query.order_by(CloudflareCategoryPersonaPack.sort_order.asc())).scalar_one_or_none()


def upsert_cloudflare_persona_pack(
    db: Session,
    *,
    managed_channel_id: int,
    category_slug: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    pack_key = str(payload.get("pack_key") or "").strip()
    if not pack_key:
        raise ValueError("pack_key_required")
    existing = db.execute(
        select(CloudflareCategoryPersonaPack).where(
            CloudflareCategoryPersonaPack.managed_channel_id == managed_channel_id,
            CloudflareCategoryPersonaPack.category_slug == category_slug,
            CloudflareCategoryPersonaPack.pack_key == pack_key,
        )
    ).scalar_one_or_none()
    values = {
        "category_id": str(payload.get("category_id") or "").strip() or None,
        "display_name": str(payload.get("display_name") or pack_key).strip(),
        "description": str(payload.get("description") or "").strip() or None,
        "primary_reader": str(payload.get("primary_reader") or "").strip() or None,
        "reader_problem": str(payload.get("reader_problem") or "").strip() or None,
        "tone_summary": str(payload.get("tone_summary") or "").strip() or None,
        "trust_style": str(payload.get("trust_style") or "").strip() or None,
        "topic_guidance": _safe_list(payload.get("topic_guidance")),
        "title_rules": dict(payload.get("title_rules") or {}),
        "ctr_rules": dict(payload.get("ctr_rules") or {}),
        "category_emphasis": _safe_list(payload.get("category_emphasis")),
        "sanitized_profiles": _sanitize_profiles(payload.get("sanitized_profiles")),
        "source_manifest_ref": str(payload.get("source_manifest_ref") or "").strip() or None,
        "attribution": str(payload.get("attribution") or PERSONA_ATTRIBUTION).strip(),
        "version": int(payload.get("version") or 1),
        "is_active": bool(payload.get("is_active", False)),
        "is_default": bool(payload.get("is_default", False)),
        "sort_order": int(payload.get("sort_order") or 100),
    }
    if values["is_default"]:
        db.execute(
            update(CloudflareCategoryPersonaPack)
            .where(
                CloudflareCategoryPersonaPack.managed_channel_id == managed_channel_id,
                CloudflareCategoryPersonaPack.category_slug == category_slug,
            )
            .values(is_default=False)
        )
    if existing is None:
        existing = CloudflareCategoryPersonaPack(
            managed_channel_id=managed_channel_id,
            category_slug=category_slug,
            pack_key=pack_key,
            **values,
        )
        db.add(existing)
    else:
        for field, value in values.items():
            setattr(existing, field, value)
    db.flush()
    return _pack_to_dict(existing, include_profiles=True)


def set_default_cloudflare_persona_pack(
    db: Session,
    *,
    managed_channel_id: int,
    category_slug: str,
    pack_key: str,
) -> dict[str, Any]:
    pack = get_cloudflare_persona_pack(
        db,
        managed_channel_id=managed_channel_id,
        category_slug=category_slug,
        pack_key=pack_key,
    )
    if pack is None:
        raise ValueError("persona_pack_not_found")
    db.execute(
        update(CloudflareCategoryPersonaPack)
        .where(
            CloudflareCategoryPersonaPack.managed_channel_id == managed_channel_id,
            CloudflareCategoryPersonaPack.category_slug == category_slug,
        )
        .values(is_default=False)
    )
    pack.is_default = True
    pack.is_active = True
    db.flush()
    return _pack_to_dict(pack, include_profiles=True)


def build_persona_prompt_block(pack: CloudflareCategoryPersonaPack | None, *, stage: str) -> str:
    if pack is None:
        return ""
    title_rules = dict(pack.title_rules or {})
    ctr_rules = dict(pack.ctr_rules or {})
    lines = [
        "",
        "",
        "[Persona lens]",
        f"- Persona pack: {pack.display_name} ({pack.pack_key} v{pack.version})",
        f"- Reader: {pack.primary_reader or 'category-specific practical reader'}",
        f"- Reader problem: {pack.reader_problem or 'needs clear context and decision criteria'}",
        f"- Tone: {pack.tone_summary or 'practical, clear, no exaggeration'}",
        f"- Trust style: {pack.trust_style or 'verified context and actionable criteria'}",
        "- Persona controls phrasing, emphasis, title hook, and reader angle only.",
        "- Persona must not change category scope, allowed_article_patterns, article_pattern_id, length gate, HTML policy, image policy, or FAQ policy.",
        "- If persona preference conflicts with category guidance, category guidance wins.",
    ]
    if pack.topic_guidance:
        lines.append("- Topic guidance: " + "; ".join(str(item) for item in pack.topic_guidance[:8]))
    if pack.category_emphasis:
        lines.append("- Category emphasis: " + "; ".join(str(item) for item in pack.category_emphasis[:8]))
    if stage in {"article_generation", "title", "ctr"}:
        preferred = _safe_list(title_rules.get("preferred_frames"))
        banned = _safe_list(title_rules.get("banned_frames"))
        if preferred:
            lines.append("- Preferred title frames: " + "; ".join(preferred[:5]))
        if banned:
            lines.append("- Banned title frames: " + "; ".join(banned[:5]))
    if stage in {"topic_discovery", "article_generation", "ctr"}:
        allowed_hooks = _safe_list(ctr_rules.get("allowed_hooks"))
        forbidden_hooks = _safe_list(ctr_rules.get("forbidden_hooks"))
        if allowed_hooks:
            lines.append("- CTR hooks allowed: " + "; ".join(allowed_hooks[:5]))
        if forbidden_hooks:
            lines.append("- CTR hooks forbidden: " + "; ".join(forbidden_hooks[:5]))
    lines.extend(
        [
            "",
            "[Pattern preservation rule]",
            "- Persona is a style lens, not a structure selector.",
            "- Keep allowed_article_patterns unchanged.",
            "- Keep article_pattern_id and article_pattern_version governed by category pattern rules.",
            "- Do not mention dataset, persona pack, synthetic persona, or demographic profile in the public article.",
        ]
    )
    return "\n".join(lines)


def score_persona_fit(
    pack: CloudflareCategoryPersonaPack | None,
    *,
    title: str,
    body_html: str,
    excerpt: str = "",
    labels: list[str] | None = None,
    article_pattern_id: str | None = None,
) -> dict[str, Any]:
    if pack is None:
        return {"status": "skipped", "score": None, "reason": "no_persona_pack"}
    text = " ".join([title or "", excerpt or "", _plain_text(body_html or ""), " ".join(labels or [])]).lower()
    checks: dict[str, float] = {}
    semantic_terms = [pack.primary_reader, pack.reader_problem, pack.tone_summary, pack.trust_style]
    semantic_terms.extend(pack.topic_guidance or [])
    semantic_terms.extend(pack.category_emphasis or [])
    semantic_tokens = _tokens(" ".join(str(item or "") for item in semantic_terms))
    text_tokens = set(_tokens(text))
    if semantic_tokens:
        semantic_ratio = min(len(text_tokens.intersection(semantic_tokens)) / max(len(set(semantic_tokens)), 1), 1.0)
        checks["semantic_match"] = 20.0 + (semantic_ratio * 20.0)
    else:
        checks["semantic_match"] = 20.0
    pattern_bonus = 20.0 if article_pattern_id else 12.0
    checks["pattern_compatibility"] = pattern_bonus
    checks["practicality_signal"] = min(_term_hits(text, ["체크", "순서", "동선", "시간", "비용", "예산", "기준", "비교", "주의", "리스크", "일정"]) / 3.0, 1.0) * 15.0
    checks["locality_signal"] = min(_term_hits(text, ["장소", "현장", "방문", "공간", "지역", "이동", "예약"]) / 2.0, 1.0) * 10.0
    checks["narrative_richness"] = min(len(set(text_tokens)) / 80.0, 1.0) * 10.0
    complete_fields = sum(
        1
        for value in (
            pack.primary_reader,
            pack.reader_problem,
            pack.tone_summary,
            pack.trust_style,
            pack.topic_guidance,
            pack.category_emphasis,
        )
        if value
    )
    checks["field_completeness"] = min(complete_fields / 6.0, 1.0) * 5.0
    penalty = 0.0
    if _term_hits(text, ["무조건", "충격", "반드시", "급등", "폭락", "수익 보장", "필수 코스"]) >= 2:
        penalty += 10.0
    if _term_hits(text, ["남성", "여성", "나이", "출신", "학력", "종교", "정치 성향", "병역"]) > 0:
        penalty += 15.0
    if pack.category_slug in {"jusigyi-heureum", "keuribtoyi-heureum", "naseudagyi-heureum", "miseuteria-seutori"}:
        if _term_hits(text, ["추천 종목", "매수", "매도", "확정", "진실은"]) > 0:
            penalty += 10.0
    score = max(0.0, min(100.0, sum(checks.values()) - penalty))
    return {
        "status": "scored",
        "score": round(score, 2),
        "band": "strong" if score >= 80 else "ok" if score >= 65 else "weak",
        "pack_key": pack.pack_key,
        "pack_version": pack.version,
        "checks": {key: round(value, 2) for key, value in checks.items()},
        "penalty": round(penalty, 2),
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "attribution": PERSONA_ATTRIBUTION,
    }


def _tokens(value: str) -> list[str]:
    return [token for token in re.split(r"[^0-9A-Za-z가-힣]+", value.lower()) if len(token) >= 2]


def _term_hits(value: str, terms: list[str]) -> int:
    return sum(1 for term in terms if term.lower() in value)


def _sanitize_profiles(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    sanitized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        clean = {
            str(key): val
            for key, val in item.items()
            if str(key).strip().lower() not in FORBIDDEN_PERSONA_FIELD_KEYS
        }
        if clean:
            sanitized.append(clean)
    return sanitized[:20]
