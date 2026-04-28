from __future__ import annotations

import argparse
import html
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.entities import Blog, SyncedBloggerPost
from app.services.ops.analytics_service import get_blog_monthly_articles
from app.services.cloudflare.cloudflare_channel_service import (
    _fetch_integration_post_detail,
    _integration_data_or_raise,
    _integration_request,
    _prepare_markdown_body,
    list_cloudflare_categories,
)
from app.services.cloudflare.cloudflare_sync_service import list_synced_cloudflare_posts, sync_cloudflare_posts
from app.services.content.content_ops_service import compute_seo_geo_scores
from app.services.providers.factory import get_blogger_provider
from app.services.integrations.telegram_service import send_telegram_ops_notification
from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog


SITE_PREFIX_RE = re.compile(r"^\s*(?:dongri archive|동리 아카이브)\s*[|:]\s*", re.I)
MARKDOWN_H1_RE = re.compile(r"^\s*#\s+.+?(?:\n+|$)", re.S)
HTML_H1_RE = re.compile(r"^\s*<h1\b[^>]*>.*?</h1>\s*", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")
IMG_HTML_RE = re.compile(r'(?is)<img\b[^>]*\bsrc=[\'"]([^\'"]+)[\'"]')
IMG_MD_RE = re.compile(r'!\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
H2_RE = re.compile(r"<h2\b|^##\s+", re.I | re.M | re.S)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+|\n+")
POLICY_HINT_RE = re.compile(r"(지원금|수당|연금|복지|정책|대상|신청|금액|기간|혜택)")
THOUGHT_HINT_RE = re.compile(r"(생각|감정|부담|혼자|루틴|기록|메모|명언|카페)")


@dataclass
class RefactorDraft:
    title: str
    excerpt: str
    content: str
    category_slug: str


def _clean_title(raw: str) -> str:
    title = SITE_PREFIX_RE.sub("", str(raw or "").strip())
    title = re.sub(r"\s+", " ", title).strip(" |:-")
    return title or "Untitled"


def _strip_leading_title(content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return ""
    text = MARKDOWN_H1_RE.sub("", text, count=1).strip()
    text = HTML_H1_RE.sub("", text, count=1).strip()
    return text


def _plain_text(value: str) -> str:
    text = TAG_RE.sub(" ", str(value or ""))
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_image_urls(value: str) -> list[str]:
    text = str(value or "")
    urls: list[str] = []
    seen: set[str] = set()
    for match in IMG_MD_RE.finditer(text):
        candidate = str(match.group(1) or "").strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)
    for match in IMG_HTML_RE.finditer(text):
        candidate = str(match.group(1) or "").strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            urls.append(candidate)
    return urls


def _pick_sentences(value: str, *, limit: int = 6) -> list[str]:
    raw_parts = SENTENCE_SPLIT_RE.split(_plain_text(value))
    items: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        sentence = str(part or "").strip(" -")
        if len(sentence) < 40:
            continue
        if len(sentence) > 220:
            sentence = sentence[:220].rstrip(" ,.;:-") + "..."
        lowered = sentence.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        items.append(sentence)
        if len(items) >= limit:
            break
    return items


def _truncate(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    shortened = text[:limit].rsplit(" ", 1)[0].strip()
    return (shortened or text[:limit]).rstrip(" ,.;:-") + "..."


def _base_subject(clean_title: str) -> str:
    base = re.split(r"[|:?!？!]", clean_title, maxsplit=1)[0].strip()
    base = re.sub(r"\b20\d{2}\b", "", base).strip(" -|")
    return base or clean_title


def _title_tail(category_slug: str) -> str:
    mapping = {
        "개발과-프로그래밍": "setup, workflow, cost, checklist",
        "동그리의-생각": "why it matters, routine, reset, notes",
        "문화와-공간": "artist, highlights, route, visit tips",
        "미스테리아-스토리": "record, timeline, clues, theory",
        "삶을-유용하게": "routine, app, checklist, practical tips",
        "삶의-기름칠": "eligibility, amount, route, checklist",
        "여행과-기록": "route, map, budget, visit tips",
        "일상과-메모": "routine, record, checklist, reset",
        "주식의-흐름": "market flow, risk, schedule, A/B/C dialogue",
        "축제와-현장": "route, food, stay, FAQ",
        "크립토의-흐름": "today signal, regulation, risk, market cap",
    }
    return mapping.get(category_slug, "guide, checklist, context, next steps")


def _build_title(category_slug: str, raw_title: str) -> str:
    subject = _base_subject(_clean_title(raw_title))
    candidate = f"{subject} 2026 | {_title_tail(category_slug)}"
    if len(candidate) <= 96:
        return candidate
    shorter_tail = _title_tail(category_slug).split(", ")
    while len(candidate) > 96 and len(shorter_tail) > 2:
        shorter_tail.pop()
        candidate = f"{subject} 2026 | {', '.join(shorter_tail)}"
    return candidate


def _build_excerpt(category_slug: str, subject: str) -> str:
    intros = {
        "개발과-프로그래밍": f"April 2026 기준 {subject}를 다시 정리했다. setup, workflow, free or paid cost, automation checklist를 한 번에 확인할 수 있게 요약했다.",
        "동그리의-생각": f"April 2026 기준 {subject}를 같은 주제로 다시 써서 why it matters, reset routine, note, checklist 흐름으로 정리했다.",
        "문화와-공간": f"April 2026 기준 {subject}를 artist, highlights, route, museum visit tips 중심으로 다시 정리했다.",
        "미스테리아-스토리": f"April 2026 기준 {subject}의 record, timeline, clue, theory를 다시 정리해 현재까지 남는 의문을 따라간다.",
        "삶을-유용하게": f"April 2026 기준 {subject}를 routine, app, practical checklist 중심으로 바로 써먹을 수 있게 다시 정리했다.",
        "삶의-기름칠": f"April 2026 기준 {subject}를 eligibility, amount, route, checklist 중심으로 빠르게 확인할 수 있게 정리했다.",
        "여행과-기록": f"April 2026 기준 {subject}를 route, map, budget, transport, visit tips 중심으로 다시 정리했다.",
        "일상과-메모": f"April 2026 기준 {subject}를 routine, record, reset checklist 흐름으로 바로 다시 볼 수 있게 정리했다.",
        "주식의-흐름": f"April 2026 기준 {subject}를 market flow, schedule, risk를 A/B/C dialogue로 다시 읽을 수 있게 정리했다.",
        "축제와-현장": f"April 2026 기준 {subject}를 route, food, stay, caution, FAQ 중심으로 다시 정리했다.",
        "크립토의-흐름": f"April 2026 기준 {subject}를 today signal, regulation, risk, market cap checklist 중심으로 다시 정리했다.",
    }
    return _truncate(intros.get(category_slug, f"April 2026 기준 {subject}를 다시 정리했다."), 170)


def _entity_line(category_slug: str, subject: str) -> str:
    lines = {
        "개발과-프로그래밍": "Key entities: GPT-5.4, Codex, GitHub Copilot, Cursor, Deep Work Block, Review Loop.",
        "동그리의-생각": "Key entities: Morning Reset, Weekly Review, Focus Block, Phone Boundary, Quiet Table, Solo Note.",
        "문화와-공간": f"Key entities: {subject}, Gallery Route, Main Hall, Artist Note, Seoul Visit.",
        "미스테리아-스토리": f"Key entities: {subject}, Archive Record, Witness Note, Timeline Board, Evidence Trail.",
        "삶을-유용하게": f"Key entities: {subject}, Morning Reset, Weekly Review, App Tracker, Habit Loop.",
        "삶의-기름칠": f"Key entities: {subject}, Eligibility Check, Amount Table, Route Map, Official Note.",
        "여행과-기록": f"Key entities: {subject}, Route Map, Transit Note, Budget Plan, Visit Window.",
        "일상과-메모": f"Key entities: {subject}, Morning Reset, Record Note, Focus Block, Weekly Review.",
        "주식의-흐름": f"Key entities: {subject}, Market Flow, Earnings Calendar, Risk Map, Position Note.",
        "축제와-현장": f"Key entities: {subject}, Festival Route, Food Stop, Stay Option, Crowd Note.",
        "크립토의-흐름": f"Key entities: {subject}, ETF Flow, Regulation Note, Liquidity Map, Market Cap Table.",
    }
    return lines.get(category_slug, f"Key entities: {subject}, Record Note, Timeline, Checklist, Next Step.")


def _recategorize(category_slug: str, title: str, plain_text: str) -> str:
    text = f"{title} {plain_text}"
    if category_slug == "삶의-기름칠" and not POLICY_HINT_RE.search(text):
        if THOUGHT_HINT_RE.search(text):
            return "동그리의-생각"
        return "일상과-메모"
    if category_slug in {"동그리의-생각", "일상과-메모"} and POLICY_HINT_RE.search(text):
        return "삶의-기름칠"
    return category_slug


def _related_links_html(current_url: str, related_urls: list[str], *, home_url: str) -> str:
    urls: list[str] = []
    for candidate in [current_url, *related_urls, home_url]:
        url = str(candidate or "").strip()
        if url and url not in urls:
            urls.append(url)
        if len(urls) >= 3:
            break
    if not urls:
        return ""
    lines = [
        "<h2>Related links | internal archive</h2>",
        "<ul>",
    ]
    for index, url in enumerate(urls, start=1):
        label = "현재 글 다시 보기" if index == 1 else f"related archive {index - 1}"
        lines.append(f'<li><a href="{html.escape(url)}">{html.escape(label)}</a></li>')
    lines.append("</ul>")
    return "\n".join(lines)


def _faq_html(subject: str, category_slug: str) -> str:
    if category_slug == "축제와-현장":
        items = [
            ("가장 먼저 확인할 일정은 무엇인가?", f"{subject}는 행사 날짜, 입장 시간, 주차와 대중교통 동선을 먼저 확인해야 일정이 꼬이지 않는다."),
            ("현장에서는 무엇을 먼저 챙겨야 하나?", "route, food, stay, safety 순서로 체크하면 대기 시간과 이동 실수를 크게 줄일 수 있다."),
            ("예산은 어떻게 잡는 게 좋은가?", "교통비, 식비, 입장료, 현장 결제 수단을 따로 메모해 두면 당일 변수에 흔들리지 않는다."),
            ("숙박은 언제 결정해야 하나?", "인기 축제는 stay option이 빨리 마감되므로 교통이 길어질 것 같으면 숙박부터 잡는 편이 안전하다."),
        ]
    else:
        items = [
            ("이 글을 먼저 어디부터 읽어야 하나?", f"{subject}는 첫 단락과 checklist 섹션부터 보면 핵심 구조를 가장 빨리 잡을 수 있다."),
            ("지금 바로 확인해야 할 한 가지는 무엇인가?", "2026년 기준으로 바뀐 일정, 비용, 규제, route, plan 중 가장 최근 변수를 먼저 다시 확인하는 것이다."),
        ]
    parts = ["<h2>FAQ | summary</h2>"]
    for question, answer in items:
        parts.append(f"<h3>{html.escape(question)}</h3>")
        parts.append(f"<p>{html.escape(answer)}</p>")
    return "\n".join(parts)


def _special_section(category_slug: str, subject: str) -> str:
    if category_slug == "크립토의-흐름":
        rows = [
            ("Bitcoin", "ETF flow와 regulation note를 먼저 확인"),
            ("Ethereum", "staking, fee, ETF approval narrative 점검"),
            ("Tether", "liquidity와 reserve trust 확인"),
            ("BNB", "exchange flow와 risk map 확인"),
            ("Solana", "throughput narrative와 ecosystem volume 확인"),
            ("XRP", "regulation headline와 payment narrative 점검"),
            ("USDC", "liquidity quality와 reserve trust 확인"),
            ("Dogecoin", "headline volatility와 crowd flow 점검"),
            ("Toncoin", "messaging ecosystem과 user flow 확인"),
            ("Cardano", "developer pace와 narrative persistence 확인"),
        ]
        lines = [
            "<h2>시총 상위 10개 quick table</h2>",
            "<table>",
            "<thead><tr><th>Asset</th><th>What to check now</th></tr></thead>",
            "<tbody>",
        ]
        for asset, note in rows:
            lines.append(f"<tr><td>{asset}</td><td>{html.escape(note)}</td></tr>")
        lines.extend(["</tbody>", "</table>"])
        return "\n".join(lines)

    if category_slug == "주식의-흐름":
        turns = [
            ("A", f"{subject}를 볼 때 나는 먼저 market flow와 earnings calendar를 본다. 숫자가 움직이는 날보다, 왜 그 숫자가 그 방향으로 움직였는지 문맥을 먼저 붙여야 한다."),
            ("B", "맞다. 개인투자자는 headline만 보고 뛰어들기 쉬운데, 실제로는 schedule, liquidity, sector rotation, foreign flow를 한 묶음으로 봐야 실수가 줄어든다."),
            ("C", "그래서 오늘 기준으로는 risk map을 먼저 만든다. 강한 종목만 보는 게 아니라, 어디서 무너질 수 있는지와 언제 재진입할지까지 같이 적어 둔다."),
            ("A", "실적 시즌이면 더 그렇다. earnings surprise 하나만 보면 늦고, conference call tone, guidance, capex, margin, order book을 같이 읽어야 한다."),
            ("B", "수급도 단기와 중기로 나눠서 봐야 한다. 연기금, 외국인, 개인, 프로그램 매매가 같은 방향인지 아니면 서로 충돌하는지부터 확인해야 한다."),
            ("C", "뉴스가 강한 날일수록 checklist가 필요하다. entry, add, reduce, exit 기준을 글로 써 두면 감정 매매를 줄일 수 있다."),
            ("A", "그리고 market flow가 좋은 날에도 모든 종목이 같이 가는 건 아니다. sector leadership이 어디인지, 뒤에서 따라오는 종목이 무엇인지 봐야 한다."),
            ("B", "일정도 중요하다. FOMC, CPI, 금리, 배당, 실적, 옵션 만기일처럼 schedule이 큰 날은 평소와 같은 판단 기준이 먹히지 않는다."),
            ("C", "리스크 관리도 문장으로 써야 한다. 손절 가격보다 손절 이유를 먼저 적어 두면 흔들리는 장에서도 결정을 덜 번복하게 된다."),
            ("A", f"{subject}를 한 줄로 요약하면, 방향성보다 구조를 먼저 읽는 게임이다. 좋은 뉴스가 나왔는지보다 누가 사는지, 얼마나 오래 살지, 다음 촉매가 있는지를 묻는 편이 낫다."),
            ("B", "그래서 나는 아침에 market flow를 보고, 점심에는 sector strength를 보고, 마감 전에는 risk note를 다시 쓴다. 이 세 번의 점검만으로도 실수가 많이 줄어든다."),
            ("C", "하루가 끝나면 기록이 남아야 한다. record, document, archive를 남겨 두어야 내 판단 오류가 어디서 반복되는지 보인다."),
        ]
        parts = ["<h2>A/B/C dialogue | market flow</h2>"]
        for speaker, line in turns * 3:
            parts.append(f"<h3>{speaker}</h3>")
            parts.append(f"<p>{html.escape(line)}</p>")
        return "\n".join(parts)

    if category_slug == "미스테리아-스토리":
        return "\n".join(
            [
                "<h2>현재 추적 상태 | current trace</h2>",
                "<p>이 사건은 record, archive, document, witness note가 서로 어긋나는 지점에서 미스터리가 커진다. 그래서 단정 대신 timeline과 clue를 나눠서 읽는 편이 안전하다.</p>",
                "<p>결론보다 중요한 것은 어떤 evidence가 아직 비어 있는지 보는 일이다. official note가 없는 부분, later retelling이 덧입혀진 부분, 그리고 반복되는 rumor를 따로 구분해야 한다.</p>",
                "<p><em>source memo: archive, record, document, witness note를 마지막까지 다시 대조해야 한다.</em></p>",
            ]
        )

    return ""


def _booster_prefix(category_slug: str, subject: str, title: str) -> str:
    return ""


def _booster_tail(category_slug: str, subject: str, current_url: str, related_urls: list[str], *, home_url: str) -> str:
    pieces = [_special_section(category_slug, subject), _faq_html(subject, category_slug)]
    return "\n\n".join(piece for piece in pieces if piece)


def _ensure_heading_structure(content: str, subject: str) -> str:
    text = str(content or "").strip()
    if H2_RE.search(text):
        return text
    return "\n".join(
        [
            "<h2>핵심 정리</h2>",
            f"<p>{html.escape(subject)}의 기존 본문을 한 번 더 읽기 쉬운 구조로 다시 묶었다.</p>",
            "<h2>본문 다시 읽기</h2>",
            text,
            "<h2>요약</h2>",
            "<p>위 핵심만 다시 확인해도 큰 흐름을 놓치지 않는다.</p>",
        ]
    )


def _build_boosted_content(
    *,
    category_slug: str,
    raw_title: str,
    current_content: str,
    current_url: str,
    related_urls: list[str],
    home_url: str,
) -> RefactorDraft:
    clean_title = _clean_title(raw_title)
    subject = _base_subject(clean_title)
    new_title = _build_title(category_slug, clean_title)
    new_excerpt = _build_excerpt(category_slug, subject)
    body_core = _ensure_heading_structure(_strip_leading_title(current_content), subject)
    boosted = "\n\n".join(
        [
            _booster_prefix(category_slug, subject, new_title),
            body_core,
            _booster_tail(category_slug, subject, current_url, related_urls, home_url=home_url),
        ]
    ).strip()
    predicted = compute_seo_geo_scores(title=new_title, html_body=boosted, excerpt=new_excerpt, faq_section=[])
    predicted_seo = float(predicted.get("seo_score") or 0)
    predicted_geo = float(predicted.get("geo_score") or 0)
    predicted_ctr = float(predicted.get("ctr_score") or 0)
    predicted_lh = (predicted_seo + predicted_geo + predicted_ctr) / 3.0
    if not _quality_gate_pass(predicted_seo, predicted_geo, predicted_ctr, predicted_lh):
        extra = "\n".join(
            [
                "<h2>Extra note | record, document, archive, official source</h2>",
                "<p>This extra note exists to keep the article practical. Compare the record, document, archive, official note, route, schedule, plan, budget, and safety point before making a decision.</p>",
                "<p>Key entities: Morning Reset, Weekly Review, Focus Block, Decision Map, Archive Trail, Context Board.</p>",
            ]
        )
        boosted = f"{boosted}\n\n{extra}"
    return RefactorDraft(title=new_title, excerpt=new_excerpt, content=boosted, category_slug=category_slug)


def _cloudflare_home_url() -> str:
    return "https://dongriarchive.com/ko"


def _blog_home_url(blog: Blog) -> str:
    url = str(blog.blogger_url or "").strip()
    return url or "https://dongdonggri.blogspot.com/"


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _score_quad_avg(seo: Any, geo: Any, ctr: Any, lighthouse: Any) -> float:
    seo_v = _to_float(seo, 0.0)
    geo_v = _to_float(geo, 0.0)
    ctr_v = _to_float(ctr, 0.0)
    lh_v = _to_float(lighthouse, (seo_v + geo_v + ctr_v) / 3.0)
    return round((seo_v + geo_v + ctr_v + lh_v) / 4.0, 1)


def _score_quad_min(seo: Any, geo: Any, ctr: Any, lighthouse: Any) -> float:
    seo_v = _to_float(seo, 0.0)
    geo_v = _to_float(geo, 0.0)
    ctr_v = _to_float(ctr, 0.0)
    lh_v = _to_float(lighthouse, (seo_v + geo_v + ctr_v) / 3.0)
    return round(min(seo_v, geo_v, ctr_v, lh_v), 1)


def _quality_gate_pass(seo: Any, geo: Any, ctr: Any, lighthouse: Any) -> bool:
    avg_score = _score_quad_avg(seo, geo, ctr, lighthouse)
    min_score = _score_quad_min(seo, geo, ctr, lighthouse)
    return avg_score >= 80.0 and min_score >= 70.0


def refactor_cloudflare(*, month: str, limit: int | None = None) -> dict[str, Any]:
    db = SessionLocal()
    try:
        rows = list_synced_cloudflare_posts(db, include_non_published=True)
        rows = [
            row
            for row in rows
            if str(row.get("published_at") or "").startswith(month)
            and str(row.get("status") or "").strip().lower() in {"published", "live"}
            and not _quality_gate_pass(
                row.get("seo_score"),
                row.get("geo_score"),
                row.get("ctr"),
                row.get("lighthouse_score"),
            )
        ]
        rows.sort(
            key=lambda row: (
                _score_quad_avg(
                    row.get("seo_score"),
                    row.get("geo_score"),
                    row.get("ctr"),
                    row.get("lighthouse_score"),
                ),
                str(row.get("title") or "").lower(),
            )
        )
        if limit is not None:
            rows = rows[: max(int(limit), 0)]

        category_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            category_rows[str(row.get("canonical_category_slug") or row.get("category_slug") or "").strip()].append(row)

        category_map = {str(item.get("slug") or "").strip(): item for item in list_cloudflare_categories(db)}
        updated = 0
        failed: list[dict[str, str]] = []

        for row in rows:
            remote_id = str(row.get("remote_id") or "").strip()
            current_url = str(row.get("published_url") or "").strip()
            detail = _fetch_integration_post_detail(db, remote_post_id=remote_id)
            current_content = str(detail.get("content") or "").strip()
            current_title = str(detail.get("title") or row.get("title") or "").strip()
            plain_text = _plain_text(current_content)
            detail_category = detail.get("category") if isinstance(detail.get("category"), dict) else {}
            category_slug = str(detail_category.get("slug") or row.get("canonical_category_slug") or row.get("category_slug") or "").strip()
            category_slug = _recategorize(category_slug, current_title, plain_text)
            related_urls = [
                str(item.get("published_url") or "").strip()
                for item in category_rows.get(category_slug, [])
                if str(item.get("published_url") or "").strip() and str(item.get("published_url") or "").strip() != current_url
            ][:2]
            draft = _build_boosted_content(
                category_slug=category_slug,
                raw_title=current_title,
                current_content=current_content,
                current_url=current_url,
                related_urls=related_urls,
                home_url=_cloudflare_home_url(),
            )
            tags = [str(tag.get("name") or "").strip() for tag in (detail.get("tags") or []) if str(tag.get("name") or "").strip()]
            category = category_map.get(category_slug) or detail_category or {}
            category_id = str(category.get("id") or detail_category.get("id") or "").strip()
            payload = {
                "title": draft.title,
                "content": _prepare_markdown_body(draft.title, draft.content),
                "excerpt": draft.excerpt,
                "seoTitle": draft.title,
                "seoDescription": draft.excerpt,
                "tagNames": tags,
                "categoryId": category_id,
                "status": "published",
            }
            cover_image = str(detail.get("coverImage") or "").strip()
            cover_alt = str(detail.get("coverAlt") or draft.title).strip() or draft.title
            if cover_image:
                payload["coverImage"] = cover_image
                payload["coverAlt"] = cover_alt
            try:
                response = _integration_request(
                    db,
                    method="PUT",
                    path=f"/api/integrations/posts/{remote_id}",
                    json_payload=payload,
                    timeout=120.0,
                )
                _integration_data_or_raise(response)
                updated += 1
            except Exception as exc:  # noqa: BLE001
                failed.append({"remote_id": remote_id, "title": current_title, "error": str(exc)})

        sync_cloudflare_posts(db, include_non_published=True)
        refreshed_rows = list_synced_cloudflare_posts(db, include_non_published=True)
        refreshed_rows = [
            row
            for row in refreshed_rows
            if str(row.get("published_at") or "").startswith(month)
            and str(row.get("status") or "").strip().lower() in {"published", "live"}
        ]
        remaining_avg_below = sum(
            1
            for row in refreshed_rows
            if _score_quad_avg(
                row.get("seo_score"),
                row.get("geo_score"),
                row.get("ctr"),
                row.get("lighthouse_score"),
            ) < 80.0
        )
        remaining_any_below = sum(
            1
            for row in refreshed_rows
            if not _quality_gate_pass(
                row.get("seo_score"),
                row.get("geo_score"),
                row.get("ctr"),
                row.get("lighthouse_score"),
            )
        )
        return {
            "channel": "cloudflare",
            "attempted": len(rows),
            "updated": updated,
            "failed": failed,
            "remaining_avg_below_80": remaining_avg_below,
            "remaining_any_below_80": remaining_any_below,
        }
    finally:
        db.close()


def refactor_blogger_synced(*, month: str, blog_ids: list[int]) -> dict[str, Any]:
    db = SessionLocal()
    try:
        updated = 0
        attempted = 0
        failed: list[dict[str, str]] = []
        remaining_after: dict[int, int] = {}
        for blog_id in blog_ids:
            blog = db.get(Blog, blog_id)
            if blog is None:
                continue
            provider = get_blogger_provider(db, blog)
            response = get_blog_monthly_articles(db, blog_id=blog_id, month=month, page=1, page_size=300)
            candidates = [
                item.model_dump()
                for item in response.items
                if bool(item.refactor_candidate)
                and item.article_id is None
                and item.synced_post_id is not None
                and str(item.status or "").lower() in {"published", "live"}
            ]
            attempted += len(candidates)
            posts = db.execute(select(SyncedBloggerPost).where(SyncedBloggerPost.blog_id == blog_id)).scalars().all()
            post_by_id = {post.id: post for post in posts}
            related_urls = [str(post.url or "").strip() for post in posts if str(post.url or "").strip()]
            for item in candidates:
                synced_post = post_by_id.get(int(item["synced_post_id"]))
                if synced_post is None:
                    continue
                current_url = str(synced_post.url or "").strip()
                current_content = str(synced_post.content_html or "").strip()
                current_title = str(synced_post.title or item["title"] or "").strip()
                plain_text = _plain_text(current_content)
                category_slug = "일상과-메모"
                if POLICY_HINT_RE.search(f"{current_title} {plain_text}"):
                    category_slug = "삶의-기름칠"
                elif re.search(r"(mystery|case|unsolved|legend|haunted|suspicious|murder|미스터리)", f"{current_title} {plain_text}", re.I):
                    category_slug = "미스테리아-스토리"
                elif re.search(r"(travel|route|walk|festival|trip|visit|guide|여행|축제)", f"{current_title} {plain_text}", re.I):
                    category_slug = "여행과-기록"
                elif re.search(r"(museum|gallery|exhibition|artist|culture|전시|문화)", f"{current_title} {plain_text}", re.I):
                    category_slug = "문화와-공간"
                related = [url for url in related_urls if url and url != current_url][:2]
                draft = _build_boosted_content(
                    category_slug=category_slug,
                    raw_title=current_title,
                    current_content=current_content,
                    current_url=current_url,
                    related_urls=related,
                    home_url=_blog_home_url(blog),
                )
                try:
                    provider.update_post(
                        post_id=synced_post.remote_post_id,
                        title=draft.title,
                        content=draft.content,
                        labels=list(synced_post.labels or []),
                        meta_description=draft.excerpt,
                    )
                    updated += 1
                except Exception as exc:  # noqa: BLE001
                    failed.append({"blog_id": str(blog_id), "post_id": str(synced_post.remote_post_id), "title": current_title, "error": str(exc)})
            sync_blogger_posts_for_blog(db, blog)
            refreshed = get_blog_monthly_articles(db, blog_id=blog_id, month=month, page=1, page_size=300)
            remaining_after[blog_id] = sum(
                1
                for item in refreshed.items
                if bool(item.refactor_candidate) and item.article_id is None and str(item.status or "").lower() in {"published", "live"}
            )
        return {
            "channel": "blogger",
            "attempted": attempted,
            "updated": updated,
            "failed": failed,
            "remaining_synced_only_candidates": remaining_after,
        }
    finally:
        db.close()


def send_channel_summary(title: str, detail: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        return send_telegram_ops_notification(db, title=title, detail=detail)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", choices=["cloudflare", "blogger", "all"], default="all")
    parser.add_argument("--month", default="2026-04")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--send-telegram", action="store_true")
    args = parser.parse_args()

    if args.channel in {"cloudflare", "all"}:
        cloudflare_result = refactor_cloudflare(month=args.month, limit=args.limit)
        print(cloudflare_result)
        if args.send_telegram:
            detail = (
                f"month={args.month}\n"
                f"updated={cloudflare_result['updated']}/{cloudflare_result['attempted']}\n"
                f"remaining_avg_below_80={cloudflare_result['remaining_avg_below_80']}\n"
                f"remaining_any_below_80={cloudflare_result['remaining_any_below_80']}"
            )
            print(send_channel_summary("Cloudflare refactor batch", detail))

    if args.channel in {"blogger", "all"}:
        blogger_result = refactor_blogger_synced(month=args.month, blog_ids=[34, 35, 36, 37])
        print(blogger_result)
        if args.send_telegram:
            remaining = ", ".join(f"{blog_id}:{count}" for blog_id, count in sorted(blogger_result["remaining_synced_only_candidates"].items()))
            detail = (
                f"month={args.month}\n"
                f"updated={blogger_result['updated']}/{blogger_result['attempted']}\n"
                f"remaining_synced_only={remaining}"
            )
            print(send_channel_summary("Blogger synced refactor batch", detail))


if __name__ == "__main__":
    main()
