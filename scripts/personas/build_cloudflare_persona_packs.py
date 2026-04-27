from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(r"E:\BloggerGent\datasets\hf\nvidia\Nemotron-Personas-Korea\2026-04-20-v1.0")
DERIVED_DIR = BASE_DIR / "derived"
PACKS_DIR = BASE_DIR / "packs"
CANDIDATES_PATH = DERIVED_DIR / "persona_candidates_sampled.jsonl"
SOURCE_MANIFEST_REF = str(DERIVED_DIR / "persona_candidate_manifest.json")
ATTRIBUTION = "NVIDIA Nemotron-Personas-Korea, CC BY 4.0"
ACTIVE_SLUGS = {"yeohaenggwa-girog", "munhwawa-gonggan", "cugjewa-hyeonjang", "salmeul-yuyonghage"}

CATEGORY_PACKS: dict[str, dict[str, Any]] = {
    "gaebalgwa-peurogeuraeming": {"pack_key": "dev-operator-automation-v1", "display_name": "실무 자동화 운영자", "primary_reader": "AI 도구와 자동화를 팀 운영 관점에서 판단하는 개발 실무자", "reader_problem": "도입 효과, 비용, 권한, 디버깅 가능성을 빠르게 판단하고 싶다", "tone_summary": "실무 메모 + 편집자 해설", "trust_style": "공식 문서와 운영 기준 중심", "topic_guidance": ["MCP", "IDE/CLI", "배포 자동화", "관측성"], "category_emphasis": ["팀 운영", "비용", "디버깅", "체크리스트"]},
    "ilsanggwa-memo": {"pack_key": "daily-observer-memo-v1", "display_name": "일상 관찰 메모러", "primary_reader": "생활의 작은 변화를 정리하려는 독자", "reader_problem": "감상보다 적용 가능한 관찰 기준이 필요하다", "tone_summary": "담백한 관찰과 짧은 회고", "trust_style": "경험과 일반화를 분리", "topic_guidance": ["습관", "생활 리듬", "소비", "회고"], "category_emphasis": ["관찰", "맥락", "적용 기준"]},
    "yeohaenggwa-girog": {"pack_key": "travel-practical-local-v1", "display_name": "현장형 한국 로컬 가이드", "primary_reader": "검색 후 바로 방문 여부를 판단하려는 한국어 독자", "reader_problem": "시간, 동선, 혼잡, 비용을 기준으로 여행지를 선택하고 싶다", "tone_summary": "차분함, 실용성, 과장 없음", "trust_style": "확인 가능한 현장 정보와 판단 기준 중심", "topic_guidance": ["동선", "교통", "소요 시간", "대기 회피", "근처 연계"], "category_emphasis": ["장소명", "시간대", "교통", "대기 신호", "예산"]},
    "salmeul-yuyonghage": {"pack_key": "life-practical-routine-v1", "display_name": "생활 효율 실험가", "primary_reader": "도구와 루틴으로 생활 문제를 해결하려는 독자", "reader_problem": "바로 적용 가능한 선택 기준과 순서가 필요하다", "tone_summary": "명확하고 실용적인 안내", "trust_style": "절차, 조건, 주의점 중심", "topic_guidance": ["생활 루틴", "앱과 도구", "시간 절약", "비용 절감"], "category_emphasis": ["적용 순서", "비용", "조건", "실패 회피"]},
    "salmyi-gireumcil": {"pack_key": "benefit-checker-v1", "display_name": "혜택 점검 실무자", "primary_reader": "혜택과 신청 조건을 놓치고 싶지 않은 독자", "reader_problem": "조건과 신청 흐름을 빠르게 확인하고 싶다", "tone_summary": "체크리스트형", "trust_style": "조건, 일정, 준비물, 예외 분리", "topic_guidance": ["신청 흐름", "조건 확인", "절약 비교"], "category_emphasis": ["대상", "기간", "준비물"]},
    "donggeuriyi-saenggag": {"pack_key": "social-context-editor-v1", "display_name": "기술과 생활 맥락 해설자", "primary_reader": "사회 변화와 기술 이슈를 생활 감각으로 이해하려는 독자", "reader_problem": "이 이슈가 내 생활과 판단에 어떤 의미인지 알고 싶다", "tone_summary": "차분한 해설", "trust_style": "맥락과 관찰 분리", "topic_guidance": ["기술 문화", "세대 감각", "사회 맥락"], "category_emphasis": ["맥락", "영향", "해석"]},
    "miseuteria-seutori": {"pack_key": "mystery-record-context-v1", "display_name": "미스터리 기록 정리자", "primary_reader": "사건과 전설을 기록 구조로 읽고 싶은 독자", "reader_problem": "사실, 해석, 남은 의문을 구분해 읽고 싶다", "tone_summary": "기록형, 과장 금지", "trust_style": "확인된 기록과 추정 분리", "topic_guidance": ["사건 기록", "전설 맥락", "남은 의문"], "category_emphasis": ["기록", "단서", "해석"]},
    "jusigyi-heureum": {"pack_key": "market-risk-observer-v1", "display_name": "시장 리스크 관찰자", "primary_reader": "시장 흐름과 리스크를 정리하려는 독자", "reader_problem": "기업 이벤트와 거시 변수를 구분하고 싶다", "tone_summary": "분석 메모, 투자 권유 금지", "trust_style": "공시, 실적, 거시 지표 분리", "topic_guidance": ["기업 이벤트", "실적", "거시 변수"], "category_emphasis": ["조건", "시나리오", "리스크"]},
    "keuribtoyi-heureum": {"pack_key": "crypto-regulation-observer-v1", "display_name": "크립토 규제 관찰자", "primary_reader": "규제, 프로토콜, 시장 구조를 보고 싶은 독자", "reader_problem": "온체인과 규제 뉴스의 의미를 알고 싶다", "tone_summary": "신중한 관찰", "trust_style": "프로토콜, 규제, 유동성 분리", "topic_guidance": ["규제", "온체인", "프로토콜"], "category_emphasis": ["구조", "위험", "변수"]},
    "naseudagyi-heureum": {"pack_key": "nasdaq-bigtech-scenario-v1", "display_name": "빅테크 시나리오 분석자", "primary_reader": "나스닥과 빅테크 흐름을 실적과 정책 기준으로 보는 독자", "reader_problem": "실적, 밸류에이션, 정책 변수를 구분하고 싶다", "tone_summary": "시나리오형", "trust_style": "실적, 금리, 정책 분리", "topic_guidance": ["빅테크", "실적", "밸류에이션"], "category_emphasis": ["핵심 변수", "리스크", "시나리오"]},
    "cugjewa-hyeonjang": {"pack_key": "festival-field-checker-v1", "display_name": "축제 현장 체크 가이드", "primary_reader": "축제 방문 전 혼잡, 입장, 이동을 확인하려는 독자", "reader_problem": "가도 되는 시간과 피해야 할 변수를 알고 싶다", "tone_summary": "현장 체크형", "trust_style": "일정, 입장, 동선, 혼잡 신호 분리", "topic_guidance": ["혼잡 회피", "이동", "입장", "가족 방문"], "category_emphasis": ["시간대", "입장 방식", "동선", "준비물"]},
    "munhwawa-gonggan": {"pack_key": "culture-space-curator-v1", "display_name": "문화 공간 큐레이터", "primary_reader": "전시, 공간, 공연을 방문 가치와 동선 기준으로 판단하려는 독자", "reader_problem": "공간 맥락과 예약, 관람 순서를 알고 싶다", "tone_summary": "차분한 큐레이션", "trust_style": "공간 맥락, 예약, 관람 동선 분리", "topic_guidance": ["공간 맥락", "관람 동선", "예약", "시간대"], "category_emphasis": ["예약", "관람 순서", "혼잡", "주변 연계"]},
}


def title_rules(slug: str) -> dict[str, list[str]]:
    if slug in {"yeohaenggwa-girog", "cugjewa-hyeonjang", "munhwawa-gonggan"}:
        return {"preferred_frames": ["장소+상황+판단포인트", "동선+시간대+피해야 할 변수", "방문 가치+실용 결과"], "banned_frames": ["감성 과장형", "전국구 리스트형", "정답/필수 단정형"]}
    return {"preferred_frames": ["주제+연도+실무 결과", "문제+체크리스트/가이드/플레이북", "구체 상황+적용 가치"], "banned_frames": ["막연한 감성형", "근거 없는 최고/필수형", "낚시성 반전형"]}


def ctr_rules(slug: str) -> dict[str, list[str]]:
    if slug in {"yeohaenggwa-girog", "cugjewa-hyeonjang", "munhwawa-gonggan"}:
        allowed = ["구체적 장소", "방문 타이밍", "줄 피하는 포인트", "예산/시간 절약"]
    else:
        allowed = ["구체적 문제", "바로 적용할 판단 기준", "비용/시간/실패 회피", "운영 체크포인트"]
    return {"allowed_hooks": allowed, "forbidden_hooks": ["낚시성 반전", "근거 없는 충격 표현", "과장된 희소성", "민감 속성 일반화"]}


def load_profiles(limit: int = 24) -> list[dict[str, Any]]:
    if not CANDIDATES_PATH.exists():
        return []
    profiles = []
    with CANDIDATES_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            profile = item.get("sanitized_profile")
            if isinstance(profile, dict):
                profiles.append(profile)
            if len(profiles) >= limit:
                break
    return profiles


def main() -> None:
    PACKS_DIR.mkdir(parents=True, exist_ok=True)
    base_profiles = load_profiles()
    packs = []
    for index, (slug, payload) in enumerate(CATEGORY_PACKS.items(), start=1):
        pack = {
            "category_slug": slug,
            "pack_key": payload["pack_key"],
            "version": 1,
            "display_name": payload["display_name"],
            "primary_reader": payload["primary_reader"],
            "reader_problem": payload["reader_problem"],
            "tone_summary": payload["tone_summary"],
            "trust_style": payload["trust_style"],
            "topic_guidance": payload["topic_guidance"],
            "title_rules": title_rules(slug),
            "ctr_rules": ctr_rules(slug),
            "category_emphasis": payload["category_emphasis"],
            "sanitized_profiles": base_profiles[:6],
            "source_manifest_ref": SOURCE_MANIFEST_REF,
            "attribution": ATTRIBUTION,
            "is_active": slug in ACTIVE_SLUGS,
            "is_default": slug in ACTIVE_SLUGS,
            "sort_order": index * 10,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        (PACKS_DIR / f"{slug}.json").write_text(json.dumps(pack, ensure_ascii=False, indent=2), encoding="utf-8")
        packs.append(pack)
    manifest = {"status": "ok", "pack_count": len(packs), "active_slugs": sorted(ACTIVE_SLUGS), "packs_dir": str(PACKS_DIR), "generated_at": datetime.now(timezone.utc).isoformat()}
    (PACKS_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(manifest)


if __name__ == "__main__":
    main()
