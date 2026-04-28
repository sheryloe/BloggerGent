from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import selectinload


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
RUNTIME_ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
DEFAULT_REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel\reports")
TRAVEL_BLOG_IDS = (34, 36, 37)
BLOG_LANGUAGE = {34: "en", 36: "es", 37: "ja"}
LANGUAGE_BLOG = {value: key for key, value in BLOG_LANGUAGE.items()}
LANGUAGE_LABELS = {"en": "English", "ja": "日本語", "es": "Español"}
SWITCH_HEADINGS = {
    "en": "Read this guide in other languages",
    "ja": "このガイドを他言語で読む",
    "es": "Lee esta guía en otros idiomas",
}
CURRENT_SUFFIX = {"en": "(Current)", "ja": "(現在ページ)", "es": "(Página actual)"}
LANGUAGE_SWITCH_START = "<!--BLOGGENT_LANGUAGE_SWITCH_START-->"
LANGUAGE_SWITCH_END = "<!--BLOGGENT_LANGUAGE_SWITCH_END-->"
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")

TITLE_RECOMMENDATIONS = {
    108: "Bukchon Hanok Village Without Mistakes: Etiquette, Photo Spots, and a Calm Walking Route",
    163: "Yeouido Cherry Blossoms at Night: Best Timing, Riverside Cafes, and Crowd-Smart Route",
    181: "Gwangjin Cherry Blossom Evening Walk: Market Detours and Quiet Local Stops",
    199: "Bucheon Sosa-dong Cherry Blossom Walk: Evening Route, Market Stops, and Timing Tips",
    691: "Gyeongbokgung sin perderte: ruta, detalles Joseon y decisiones para una primera visita",
    693: "Bukchon como barrio vivo: cómo caminar, mirar y respetar los hanok de Seúl",
    303: "延南洞を迷わず歩くなら？カフェ通りと静かな路地をつなぐ半日ルート",
    304: "海雲台を地下鉄で動くなら？駅から海辺まで迷わない釜山半日ルート",
    305: "水原華城を初めて歩くなら？城郭ルートと駅移動を外さない順番",
    337: "ソウル春の桜散歩はどこが楽？混雑を避ける徒歩ルートと休憩順",
    339: "韓国春カフェで何を頼む？伝統風メニューと失敗しない選び方",
    340: "春のソウルでカフェ巡りするなら？地元ルートと休憩の組み方",
    341: "延南洞の隠れカフェを歩くなら？弘大からつなぐ静かな午後ルート",
    350: "延南洞から弘大カフェへ：歩きやすい順番と混雑を避ける休憩術",
    351: "延南洞で文化と今を感じるなら？伝統小物と現代カフェの歩き方",
    626: "西村の4月桜夕散歩：混雑前に歩く順番とカフェ休憩のコツ",
}


def _load_runtime_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


_load_runtime_env(RUNTIME_ENV_PATH)
os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL") or os.environ.get("BLOGGENT_DATABASE_URL") or DEFAULT_DATABASE_URL
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Article, BloggerPost  # noqa: E402
from app.services.content.blogger_live_publish_validation_service import validate_blogger_live_publish  # noqa: E402
from app.services.content.html_assembler import upsert_language_switch_html  # noqa: E402
from app.services.integrations.storage_service import is_private_asset_url  # noqa: E402
from app.services.platform.platform_oauth_service import refresh_platform_access_token  # noqa: E402
from app.services.platform.platform_service import get_managed_channel_by_channel_id  # noqa: E402
from app.services.platform.publishing_service import refresh_article_public_image, sanitize_blogger_labels_for_article, upsert_article_blogger_post  # noqa: E402
from app.services.providers.factory import get_blogger_provider  # noqa: E402


@dataclass(frozen=True, slots=True)
class LoadedArticle:
    article: Article
    published_url: str
    blogger_post_id: str
    language: str


def _now_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S")


def _write_json(path: Path, payload: dict[str, Any] | list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _slug_like(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")


def _contains_any(text: str, items: list[str]) -> bool:
    lowered = str(text or "").lower()
    return any(item.lower() in lowered for item in items)


def title_ctr_score(article: Article, title: str | None = None) -> tuple[int, list[str]]:
    candidate_title = str(title if title is not None else article.title or "").strip()
    language = BLOG_LANGUAGE.get(int(article.blog_id or 0), "")
    score = 100
    reasons: list[str] = []
    char_count = len(candidate_title)

    if language == "en":
        if char_count < 45:
            score -= 12
            reasons.append("short")
        if char_count > 105:
            score -= 10
            reasons.append("long")
        if not _contains_any(
            candidate_title,
            ["2026", "2025", "how", "where", "when", "booking", "route", "tips", "guide", "best", "first-time", "avoid", "schedule", "transport"],
        ):
            score -= 12
            reasons.append("weak_intent")
        if candidate_title.lower().startswith(("2026 ", "2025 ")) and ":" not in candidate_title:
            score -= 8
            reasons.append("flat_year_prefix")
        if "travel guide" in candidate_title.lower():
            score -= 10
            reasons.append("generic_guide")
    elif language == "es":
        if char_count < 45:
            score -= 12
            reasons.append("short")
        if char_count > 115:
            score -= 10
            reasons.append("long")
        if not _contains_any(
            candidate_title,
            ["2026", "2025", "cómo", "dónde", "cuándo", "ruta", "consejos", "horario", "reserva", "transporte", "guía", "evitar", "mejor"],
        ):
            score -= 12
            reasons.append("weak_intent")
        if _contains_any(candidate_title, ["guía de viaje", "korea travel guide"]):
            score -= 10
            reasons.append("generic_guide")
    elif language == "ja":
        if char_count < 22:
            score -= 12
            reasons.append("short")
        if char_count > 70:
            score -= 8
            reasons.append("long")
        if not _contains_any(
            candidate_title,
            ["2026", "2025", "どう", "なぜ", "どこ", "いつ", "予約", "行き方", "混雑", "半日", "日帰り", "失敗", "順番", "歩き方", "攻略", "完全"],
        ):
            score -= 12
            reasons.append("weak_intent")
        if _contains_any(candidate_title, ["Korea Travel Guide", "Guide |"]):
            score -= 18
            reasons.append("english_template_leak")

    article_slug = _slug_like(article.slug)
    title_slug = _slug_like(candidate_title)
    if article_slug and title_slug and SequenceMatcher(a=title_slug, b=article_slug).ratio() > 0.92:
        score -= 12
        reasons.append("raw_slug_like")
    if _contains_any(candidate_title, ["Guide | Korea Travel Guide"]) or candidate_title.endswith("Korea Travel Guide"):
        score -= 18
        reasons.append("template_suffix")
    if candidate_title.lower().startswith(("exploring", "navigating", "experience", "last year", "last-year", "a guide to")):
        score -= 6
        reasons.append("repetitive_opener")
    return max(0, min(100, score)), reasons


def recommended_title_for(article: Article) -> str:
    mapped = TITLE_RECOMMENDATIONS.get(int(article.id))
    if mapped:
        return mapped
    title = str(article.title or "").strip()
    language = BLOG_LANGUAGE.get(int(article.blog_id or 0), "")
    if language == "ja":
        cleaned = re.sub(r"\s*\|?\s*Korea Travel Guide\s*$", "", title, flags=re.IGNORECASE).strip()
        if not re.search(r"[ぁ-んァ-ン一-龯]", cleaned):
            cleaned = "韓国ローカル旅で外さない歩き方"
        return f"{cleaned}：混雑を避ける順番と現地判断"
    if language == "es":
        return title if "cómo" in title.lower() else f"{title}: ruta, horarios y decisiones prácticas"
    return title if re.search(r"\b(how|where|when|tips|route|booking)\b", title, re.IGNORECASE) else f"{title}: Route, Timing, and Local Tips"


def _plain_non_space_len(value: str | None) -> int:
    return len(SPACE_RE.sub("", TAG_RE.sub(" ", str(value or ""))).strip())


def _load_articles(db, *, article_ids: set[int] | None = None) -> list[LoadedArticle]:
    query = (
        select(Article)
        .join(BloggerPost, BloggerPost.article_id == Article.id)
        .where(Article.blog_id.in_(TRAVEL_BLOG_IDS))
        .options(
            selectinload(Article.blog),
            selectinload(Article.image),
            selectinload(Article.blogger_post),
        )
        .order_by(Article.blog_id.asc(), Article.id.asc())
    )
    if article_ids:
        query = query.where(Article.id.in_(list(article_ids)))
    loaded: list[LoadedArticle] = []
    for article in db.execute(query).scalars().unique().all():
        post = article.blogger_post
        if not post:
            continue
        published_url = str(post.published_url or "").strip()
        blogger_post_id = str(post.blogger_post_id or "").strip()
        language = BLOG_LANGUAGE.get(int(article.blog_id or 0), "")
        if published_url and blogger_post_id and language:
            loaded.append(LoadedArticle(article=article, published_url=published_url, blogger_post_id=blogger_post_id, language=language))
    return loaded


def _group_language_urls(items: list[LoadedArticle]) -> dict[str, dict[str, str]]:
    grouped: dict[str, dict[str, str]] = {}
    for item in items:
        group_key = str(item.article.travel_sync_group_key or "").strip()
        if not group_key:
            continue
        grouped.setdefault(group_key, {})[item.language] = item.published_url
    return grouped


def _language_switch_block(current_language: str, urls_by_language: dict[str, str]) -> str:
    languages = [language for language in ("en", "ja", "es") if urls_by_language.get(language)]
    if len(languages) < 2:
        return ""
    heading = html.escape(SWITCH_HEADINGS.get(current_language, SWITCH_HEADINGS["en"]))
    current_suffix = html.escape(CURRENT_SUFFIX.get(current_language, CURRENT_SUFFIX["en"]))
    list_items: list[str] = []
    for language in languages:
        label = html.escape(LANGUAGE_LABELS.get(language, language.upper()))
        url = html.escape(str(urls_by_language[language]), quote=True)
        if language == current_language:
            list_items.append(f"<li style='margin:0 0 8px;'><strong>{label} {current_suffix}</strong></li>")
        else:
            list_items.append(f"<li style='margin:0 0 8px;'><a href=\"{url}\" rel=\"noopener\">{label}</a></li>")
    return (
        "<section data-bloggent-role='language-switch' "
        "style='margin-top:30px;padding:18px 20px;border:1px solid #e2e8f0;border-radius:18px;background:#f8fafc;'>"
        f"<h2 style='margin:0 0 12px;font-size:22px;line-height:1.35;color:#0f172a;'>{heading}</h2>"
        "<ul style='margin:0;padding-left:20px;color:#1e293b;font-size:16px;line-height:1.75;'>"
        + "".join(list_items)
        + "</ul></section>"
    )


def _hero_url(article: Article) -> str:
    image = article.image
    if not image:
        return ""
    return str(image.public_url or "").strip()


def _fetch_live_html(url: str) -> tuple[int | None, str]:
    try:
        response = httpx.get(url, timeout=45.0, follow_redirects=True)
        return response.status_code, response.text
    except httpx.HTTPError:
        return None, ""


def _validate_language_switch_live(url: str, current_url: str, alternate_urls: dict[str, str]) -> dict[str, Any]:
    status_code, live_html = _fetch_live_html(url)
    expected_other_urls = [value for value in alternate_urls.values() if value and value != current_url]
    missing = [value for value in expected_other_urls if value not in live_html]
    current_links = len(re.findall(rf"<a\b[^>]+href=['\"]{re.escape(current_url)}['\"]", live_html, flags=re.IGNORECASE))
    return {
        "http_status": status_code,
        "expected_other_url_count": len(expected_other_urls),
        "missing_alternate_urls": missing,
        "current_url_anchor_count": current_links,
        "status": "ok" if status_code == 200 and not missing and current_links == 0 else "failed",
    }


def _oauth_check(db) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for blog_id in TRAVEL_BLOG_IDS:
        channel_id = f"blogger:{blog_id}"
        channel = get_managed_channel_by_channel_id(db, channel_id)
        result = {
            "channel_id": channel_id,
            "status": getattr(channel, "status", None),
            "oauth_state": getattr(channel, "oauth_state", None),
            "refresh_ok": False,
            "error": None,
        }
        try:
            credential = refresh_platform_access_token(db, channel_id=channel_id)
            result["refresh_ok"] = bool(credential and credential.is_valid)
            result["expires_at"] = credential.expires_at.isoformat() if credential and credential.expires_at else None
        except Exception as exc:  # noqa: BLE001
            result["error"] = str(exc)
        rows.append(result)
    return rows


def audit_language_switch(items: list[LoadedArticle], grouped_urls: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        group_key = str(item.article.travel_sync_group_key or "").strip()
        urls = grouped_urls.get(group_key, {}) if group_key else {}
        alternate_urls = {language: url for language, url in urls.items() if url}
        switch_html = _language_switch_block(item.language, alternate_urls)
        rows.append(
            {
                "article_id": int(item.article.id),
                "blog_id": int(item.article.blog_id),
                "language": item.language,
                "published_url": item.published_url,
                "sync_group_key": group_key,
                "alternate_urls": alternate_urls,
                "language_switch_status": "eligible" if switch_html else "single_language_or_missing_group",
                "existing_switch_filled": "data-bloggent-role='language-switch'" in str(item.article.assembled_html or ""),
            }
        )
    return rows


def audit_ctr_titles(items: list[LoadedArticle]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        before_score, before_reasons = title_ctr_score(item.article)
        recommended = recommended_title_for(item.article) if before_score < 80 else str(item.article.title or "")
        after_score, after_reasons = title_ctr_score(item.article, recommended)
        rows.append(
            {
                "article_id": int(item.article.id),
                "blog_id": int(item.article.blog_id),
                "language": item.language,
                "published_url": item.published_url,
                "sync_group_key": str(item.article.travel_sync_group_key or "").strip(),
                "before_title": item.article.title,
                "after_title": recommended,
                "ctr_score_before": before_score,
                "ctr_reasons_before": before_reasons,
                "ctr_score_after": after_score,
                "ctr_reasons_after": after_reasons,
                "needs_update": before_score < 80,
            }
        )
    return rows


def apply_language_switch(db, items: list[LoadedArticle], grouped_urls: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        try:
            article = item.article
            group_key = str(article.travel_sync_group_key or "").strip()
            alternate_urls = grouped_urls.get(group_key, {}) if group_key else {}
            switch_html = _language_switch_block(item.language, alternate_urls)
            row = {
                "article_id": int(article.id),
                "blog_id": int(article.blog_id),
                "language": item.language,
                "published_url": item.published_url,
                "sync_group_key": group_key,
                "alternate_urls": alternate_urls,
                "language_switch_status": "skipped_single_language_or_missing_group",
                "live_validation_status": None,
            }
            if not switch_html:
                rows.append(row)
                continue

            pre_live = _validate_language_switch_live(item.published_url, item.published_url, alternate_urls)
            if pre_live["status"] == "ok":
                row["language_switch_status"] = "already_live_ok"
                row["live_validation"] = pre_live
                row["live_validation_status"] = "ok"
                rows.append(row)
                continue

            assembled_html = str(article.assembled_html or article.html_article or "")
            updated_html = upsert_language_switch_html(assembled_html, switch_html)
            if updated_html == assembled_html and "data-bloggent-role='language-switch'" in assembled_html:
                row["language_switch_status"] = "already_present"
            else:
                article.assembled_html = updated_html
                metadata = dict(article.render_metadata or {})
                metadata["language_switch"] = {
                    "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "alternate_urls": alternate_urls,
                }
                article.render_metadata = metadata
                db.add(article)
                db.commit()
                db.refresh(article)
                row["language_switch_status"] = "db_updated"

            provider = get_blogger_provider(db, article.blog)
            labels = sanitize_blogger_labels_for_article(article, article.labels)
            summary, payload = provider.update_post(
                post_id=item.blogger_post_id,
                title=article.title,
                content=str(article.assembled_html or ""),
                labels=labels,
                meta_description=article.meta_description,
            )
            blogger_post = upsert_article_blogger_post(db, article=article, summary=summary, raw_payload=payload)
            published_url = str(blogger_post.published_url or item.published_url or "").strip()
            live = _validate_language_switch_live(published_url, published_url, alternate_urls)
            row["published_url"] = published_url
            row["live_validation"] = live
            row["live_validation_status"] = live["status"]
            metadata = dict(article.render_metadata or {})
            metadata["language_switch"] = {**dict(metadata.get("language_switch") or {}), "live_validation": live}
            article.render_metadata = metadata
            db.add(article)
            db.commit()
            rows.append(row)
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "article_id": int(item.article.id),
                    "blog_id": int(item.article.blog_id),
                    "language": item.language,
                    "published_url": item.published_url,
                    "sync_group_key": str(item.article.travel_sync_group_key or "").strip(),
                    "alternate_urls": grouped_urls.get(str(item.article.travel_sync_group_key or "").strip(), {}),
                    "language_switch_status": "failed_exception",
                    "live_validation_status": "failed",
                    "error": str(exc),
                }
            )
            db.rollback()
    return rows


def apply_ctr_titles(db, items: list[LoadedArticle]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        try:
            article = item.article
            before_title = str(article.title or "")
            before_score, before_reasons = title_ctr_score(article)
            if before_score >= 80:
                continue
            after_title = recommended_title_for(article)
            after_score, after_reasons = title_ctr_score(article, after_title)
            row = {
                "article_id": int(article.id),
                "blog_id": int(article.blog_id),
                "language": item.language,
                "published_url": item.published_url,
                "sync_group_key": str(article.travel_sync_group_key or "").strip(),
                "before_title": before_title,
                "after_title": after_title,
                "ctr_score_before": before_score,
                "ctr_reasons_before": before_reasons,
                "ctr_score_after": after_score,
                "ctr_reasons_after": after_reasons,
                "live_validation_status": None,
            }
            article.title = after_title
            metadata = dict(article.render_metadata or {})
            metadata["ctr_title_rewrite"] = {
                "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "before_title": before_title,
                "after_title": after_title,
                "score_before": before_score,
                "score_after": after_score,
            }
            article.render_metadata = metadata
            db.add(article)
            db.commit()
            db.refresh(article)

            # Rebuild the article shell with the new title while preserving the existing body and language switch.
            hero_url = _hero_url(article)
            if not hero_url or is_private_asset_url(hero_url):
                hero_url = str(refresh_article_public_image(db, article) or hero_url or "").strip()
            from app.services.platform.publishing_service import rebuild_article_html  # local import avoids circular startup surprises

            assembled_html = rebuild_article_html(db, article, hero_url)
            group_urls = {}
            if article.travel_sync_group_key:
                for other in items:
                    if str(other.article.travel_sync_group_key or "") == str(article.travel_sync_group_key or ""):
                        group_urls[other.language] = other.published_url
            switch_html = _language_switch_block(item.language, group_urls)
            if switch_html:
                article.assembled_html = upsert_language_switch_html(assembled_html, switch_html)
                db.add(article)
                db.commit()
                db.refresh(article)

            provider = get_blogger_provider(db, article.blog)
            labels = sanitize_blogger_labels_for_article(article, article.labels)
            summary, payload = provider.update_post(
                post_id=item.blogger_post_id,
                title=article.title,
                content=str(article.assembled_html or ""),
                labels=labels,
                meta_description=article.meta_description,
            )
            blogger_post = upsert_article_blogger_post(db, article=article, summary=summary, raw_payload=payload)
            published_url = str(blogger_post.published_url or item.published_url or "").strip()
            live_validation = validate_blogger_live_publish(
                published_url=published_url,
                expected_title=article.title,
                expected_hero_url=hero_url,
                assembled_html=str(article.assembled_html or ""),
                required_article_h1_count=1,
            )
            live_html_status, live_html = _fetch_live_html(published_url)
            title_live_present = article.title in live_html
            row["published_url"] = published_url
            row["live_validation"] = live_validation
            row["live_title_present"] = title_live_present
            row["live_validation_status"] = "ok" if live_validation.get("status") == "ok" and title_live_present and live_html_status == 200 else "failed"
            rows.append(row)
        except Exception as exc:  # noqa: BLE001
            rows.append(
                {
                    "article_id": int(item.article.id),
                    "blog_id": int(item.article.blog_id),
                    "language": item.language,
                    "published_url": item.published_url,
                    "sync_group_key": str(item.article.travel_sync_group_key or "").strip(),
                    "live_validation_status": "failed",
                    "error": str(exc),
                }
            )
            db.rollback()
    return rows


def _select_canary_language_items(items: list[LoadedArticle], grouped_urls: dict[str, dict[str, str]]) -> list[LoadedArticle]:
    selected: list[LoadedArticle] = []
    seen: set[int] = set()
    complete_group = next((key for key, urls in grouped_urls.items() if len(urls) >= 3), "")
    partial_group = next((key for key, urls in grouped_urls.items() if len(urls) == 2), "")
    for key in [complete_group, partial_group]:
        if not key:
            continue
        group_items = [item for item in items if str(item.article.travel_sync_group_key or "") == key]
        for item in group_items[: min(3, len(group_items))]:
            if int(item.article.id) not in seen:
                selected.append(item)
                seen.add(int(item.article.id))
    return selected


def _select_canary_ctr_items(items: list[LoadedArticle]) -> list[LoadedArticle]:
    for item in items:
        if title_ctr_score(item.article)[0] < 80:
            return [item]
    return []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply travel multilingual links and CTR title fixes.")
    parser.add_argument("--mode", choices=["audit", "apply"], default="audit")
    parser.add_argument("--target", choices=["language", "ctr", "both"], default="both")
    parser.add_argument("--canary", action="store_true")
    parser.add_argument("--article-ids", default="")
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report_root = Path(str(args.report_root)).resolve()
    stamp = _now_stamp()
    article_ids = {int(token) for token in str(args.article_ids or "").split(",") if token.strip()}
    with SessionLocal() as db:
        oauth = _oauth_check(db)
        if any(not item.get("refresh_ok") for item in oauth):
            report = {"status": "oauth_failed", "oauth": oauth}
            _write_json(report_root / f"travel-oauth-check-{stamp}.json", report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1

        all_items = _load_articles(db, article_ids=None)
        grouped_urls = _group_language_urls(all_items)
        items = [item for item in all_items if int(item.article.id) in article_ids] if article_ids else all_items
        if args.canary and not article_ids:
            language_items = _select_canary_language_items(items, grouped_urls)
            ctr_items = _select_canary_ctr_items(items)
        else:
            language_items = items
            ctr_items = items

        output: dict[str, Any] = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "mode": args.mode, "target": args.target, "canary": bool(args.canary), "oauth": oauth}
        if args.mode == "audit":
            if args.target in {"language", "both"}:
                language_rows = audit_language_switch(items, grouped_urls)
                _write_json(report_root / f"travel-language-switch-audit-{stamp}.json", {"rows": language_rows})
                output["language"] = {
                    "total": len(language_rows),
                    "eligible": sum(1 for row in language_rows if row["language_switch_status"] == "eligible"),
                    "single_or_missing": sum(1 for row in language_rows if row["language_switch_status"] != "eligible"),
                }
            if args.target in {"ctr", "both"}:
                ctr_rows = audit_ctr_titles(items)
                low_rows = [row for row in ctr_rows if row["needs_update"]]
                _write_json(report_root / f"travel-ctr-title-audit-{stamp}.json", {"rows": ctr_rows, "low_rows": low_rows})
                output["ctr"] = {
                    "total": len(ctr_rows),
                    "under80": len(low_rows),
                    "under80_article_ids": [row["article_id"] for row in low_rows],
                }
        else:
            if args.target in {"language", "both"}:
                language_apply_rows = apply_language_switch(db, language_items, grouped_urls)
                _write_json(report_root / f"travel-language-switch-apply-{stamp}.json", {"rows": language_apply_rows})
                output["language"] = {
                    "total": len(language_apply_rows),
                    "ok": sum(1 for row in language_apply_rows if row.get("live_validation_status") == "ok"),
                    "failed": sum(1 for row in language_apply_rows if row.get("live_validation_status") == "failed"),
                    "skipped": sum(1 for row in language_apply_rows if str(row.get("language_switch_status") or "").startswith("skipped")),
                }
            if args.target in {"ctr", "both"}:
                ctr_apply_rows = apply_ctr_titles(db, ctr_items)
                _write_json(report_root / f"travel-ctr-title-apply-{stamp}.json", {"rows": ctr_apply_rows})
                output["ctr"] = {
                    "total": len(ctr_apply_rows),
                    "ok": sum(1 for row in ctr_apply_rows if row.get("live_validation_status") == "ok"),
                    "failed": sum(1 for row in ctr_apply_rows if row.get("live_validation_status") == "failed"),
                    "article_ids": [row["article_id"] for row in ctr_apply_rows],
                }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
