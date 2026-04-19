from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen


PUBLIC_API_BASE = "https://api.dongriarchive.com"
PUBLIC_SITE_BASE = "https://dongriarchive.com"
REPORT_DIR = Path(r"D:\Donggri_Runtime\BloggerGent\storage\cloudflare\reports")
GENERIC_COLLAGE_MARKERS = ("3x3", "9패널", "콜라주", "collage")

CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "여행과 기록": ("여행", "산책", "코스", "동선", "방문", "초봄", "봄축제", "지역", "풍경"),
    "일상과 메모": ("메모", "기록 습관", "루틴", "노트", "기록법", "시스템"),
    "문화와 공간": ("전시", "미술관", "박물관", "공간", "유적", "궁궐", "장릉", "영화", "드라마", "아이돌"),
    "축제와 현장": ("축제", "행사", "현장", "교통", "숙박", "혼잡", "입장", "체크리스트"),
    "미스테리아 스토리": ("미스터리", "mystery", "unsolved", "murders", "haunting", "legend", "실종", "사건", "전설"),
    "동그리의 생각": ("해설", "분석", "관점", "이유", "구조", "시대"),
    "개발과 프로그래밍": ("개발", "코드", "sdk", "에이전트", "프로그래밍", "디버깅"),
    "삶을 유용하게": ("활용", "도구", "기능", "설정", "앱", "서비스"),
    "삶의 기름칠": ("일상", "회복", "가볍게", "정리", "리셋"),
    "주식의 흐름": ("주식", "증시", "실적", "밸류에이션", "종목", "ceo"),
    "크립토의 흐름": ("크립토", "암호화폐", "체인", "온체인", "solana", "bitcoin"),
}

MYSTERY_ENTITY_TERMS = ("mary celeste", "black dahlia", "hope diamond", "hinterkaifeck")
MEMO_TERMS = ("메모", "기록 습관", "루틴", "노트", "시스템")
FESTIVAL_OPERATION_TERMS = ("교통", "숙박", "혼잡", "체크리스트", "현장", "입장")
TRAVEL_ROUTE_TERMS = ("여행", "산책", "하루 코스", "동선")
CULTURE_SPACE_TERMS = ("궁궐", "역사", "문화", "유적", "전시", "공간", "장릉", "관풍헌")


def fetch_json(path: str) -> Any:
    request = Request(
        f"{PUBLIC_API_BASE}{path}",
        headers={
            "Accept": "application/json",
            "User-Agent": "BloggerGent review script (+https://dongriarchive.com)",
        },
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8-sig"))
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def normalized_text(*parts: str | None) -> str:
    return " ".join(str(part or "").lower() for part in parts)


def score_category(text: str, category_name: str) -> int:
    return sum(1 for keyword in CATEGORY_KEYWORDS.get(category_name, ()) if keyword.lower() in text)


def detect_review_items(posts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    review_items: list[dict[str, Any]] = []

    for post in posts:
        category = post.get("category") if isinstance(post.get("category"), dict) else {}
        current_category = str(category.get("name") or "").strip()
        title = str(post.get("title") or "").strip()
        excerpt = str(post.get("excerpt") or "").strip()
        cover_alt = str(post.get("coverAlt") or post.get("coverImageAlt") or "").strip()
        slug = str(post.get("slug") or "").strip()
        text = normalized_text(title, excerpt, cover_alt)

        issue_types: list[str] = []
        reasons: list[str] = []
        suggested_category = current_category

        category_scores = {name: score_category(text, name) for name in CATEGORY_KEYWORDS}
        best_category, best_score = max(category_scores.items(), key=lambda item: item[1])
        current_score = category_scores.get(current_category, 0)
        if best_score >= 2 and best_category != current_category and current_score == 0:
            suggested_category = best_category
            issue_types.append("category_mismatch_candidate")
            reasons.append(f"현재 카테고리 점수는 0이고, '{best_category}' 관련 키워드가 {best_score}개 잡힙니다.")

        has_mystery_entity = any(term in text for term in MYSTERY_ENTITY_TERMS)
        has_memo_angle = any(term in title.lower() or term in excerpt.lower() for term in MEMO_TERMS)
        has_festival_operations = any(term in text for term in FESTIVAL_OPERATION_TERMS) and any(term in text for term in ("축제", "festival", "행사"))
        has_travel_route = any(term in text for term in TRAVEL_ROUTE_TERMS)
        has_culture_space = any(term in text for term in CULTURE_SPACE_TERMS)

        if has_mystery_entity and current_category in {"일상과 메모", "삶의 기름칠"} and has_memo_angle:
            issue_types.append("title_angle_drift")
            reasons.append("카테고리는 생활/메모인데 제목과 이미지가 미스터리 기사처럼 앞에 서 있어 1차 약속이 흔들립니다.")
        elif has_mystery_entity and current_category != "미스테리아 스토리":
            suggested_category = "미스테리아 스토리"
            issue_types.append("strong_category_mismatch")
            reasons.append("실제 사건/미스터리 고유명사가 제목의 전면에 나오므로 사건 카테고리 관점이 먼저여야 합니다.")

        if has_festival_operations and current_category != "축제와 현장":
            suggested_category = "축제와 현장"
            issue_types.append("strong_category_mismatch")
            reasons.append("축제 일정, 교통, 숙박, 현장 동선은 축제와 현장 카테고리 우선 주제입니다.")

        if current_category == "삶의 기름칠" and has_travel_route:
            suggested_category = "여행과 기록"
            issue_types.append("strong_category_mismatch")
            reasons.append("장소 이동과 계절 장면을 다루는 글은 여행과 기록 카테고리가 맞습니다.")

        if current_category == "미스테리아 스토리" and has_culture_space:
            suggested_category = "문화와 공간"
            issue_types.append("strong_category_mismatch")
            reasons.append("유적, 궁궐, 전시, 공간 경험 중심 글은 문화와 공간 카테고리 관점이 더 자연스럽습니다.")

        if any(marker.lower() in cover_alt.lower() for marker in GENERIC_COLLAGE_MARKERS):
            issue_types.append("generic_collage_image")
            reasons.append("커버 alt에 generic 콜라주 표현이 들어가 있어 주제와 장면성이 흐려질 가능성이 큽니다.")

        if issue_types:
            review_items.append(
                {
                    "title": title,
                    "slug": slug,
                    "url": f"{PUBLIC_SITE_BASE}/ko/post/{quote(slug)}" if slug else None,
                    "current_category": current_category,
                    "suggested_category": suggested_category,
                    "cover_alt": cover_alt,
                    "issue_types": sorted(set(issue_types)),
                    "reasons": reasons,
                }
            )

    return review_items


def build_markdown(items: list[dict[str, Any]]) -> str:
    lines = [
        "# Cloudflare Content Review",
        "",
        f"- generated_at_kst: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- total_flagged: {len(items)}",
        "",
    ]
    for index, item in enumerate(items, start=1):
        lines.extend(
            [
                f"## {index}. {item['title']}",
                f"- url: {item['url']}",
                f"- current_category: {item['current_category']}",
                f"- suggested_category: {item['suggested_category']}",
                f"- issue_types: {', '.join(item['issue_types'])}",
                f"- cover_alt: {item['cover_alt']}",
                "- reasons:",
            ]
        )
        for reason in item["reasons"]:
            lines.append(f"  - {reason}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    posts = fetch_json("/api/public/posts")
    if not isinstance(posts, list):
        raise SystemExit("Unexpected posts payload")

    review_items = detect_review_items([item for item in posts if isinstance(item, dict)])
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = REPORT_DIR / f"cloudflare-content-review-{timestamp}.json"
    md_path = REPORT_DIR / f"cloudflare-content-review-{timestamp}.md"

    json_path.write_text(json.dumps(review_items, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(build_markdown(review_items), encoding="utf-8")

    summary = defaultdict(int)
    for item in review_items:
        for issue_type in item["issue_types"]:
            summary[issue_type] += 1

    print(json.dumps({"json": str(json_path), "markdown": str(md_path), "summary": dict(summary)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
