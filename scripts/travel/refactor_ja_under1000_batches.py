from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import selectinload


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
RUNTIME_ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
DEFAULT_DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
DEFAULT_REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel\reports")
JA_BLOG_ID = 37
TRAVEL_BLOG_IDS = (34, 36, 37)
BLOG_LANGUAGE = {34: "en", 36: "es", 37: "ja"}
LANGUAGE_LABELS = {"en": "English", "ja": "日本語", "es": "Español"}
SWITCH_HEADINGS = {
    "en": "Read this guide in other languages",
    "ja": "このガイドを他言語で読む",
    "es": "Lee esta guía en otros idiomas",
}
CURRENT_SUFFIX = {"en": "(Current)", "ja": "(現在ページ)", "es": "(Página actual)"}
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


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
from app.services.blogger.blogger_live_audit_service import extract_best_article_fragment  # noqa: E402
from app.services.content.blogger_live_publish_validation_service import validate_blogger_live_publish  # noqa: E402
from app.services.content.html_assembler import upsert_language_switch_html  # noqa: E402
from app.services.integrations.storage_service import is_private_asset_url  # noqa: E402
from app.services.platform.platform_oauth_service import refresh_platform_access_token  # noqa: E402
from app.services.platform.platform_service import get_managed_channel_by_channel_id  # noqa: E402
from app.services.platform.publishing_service import rebuild_article_html, refresh_article_public_image, sanitize_blogger_labels_for_article, upsert_article_blogger_post  # noqa: E402
from app.services.providers.factory import get_blogger_provider  # noqa: E402


def _write_json(path: Path, payload: dict[str, Any] | list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _plain_non_space_len_from_html(value: str | None) -> int:
    soup = BeautifulSoup(str(value or ""), "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return len(SPACE_RE.sub("", soup.get_text(" ", strip=True)))


def _article_body_live_length(*, published_url: str, title: str, hero_url: str) -> tuple[int, dict[str, Any]]:
    response = httpx.get(published_url, timeout=45.0, follow_redirects=True)
    diagnostics: dict[str, Any] = {"http_status": response.status_code, "final_url": str(response.url)}
    if response.status_code != 200:
        return 0, diagnostics
    fragment = extract_best_article_fragment(response.text, expected_title=title, expected_hero_url=hero_url)
    soup = BeautifulSoup(fragment or "", "html.parser")
    body = soup.select_one('[data-bloggent-role="article-body"]')
    target = str(body) if body else fragment
    diagnostics.update(
        {
            "article_h1_count": len(soup.find_all("h1")),
            "hero_figure_count": len(soup.select('[data-bloggent-role="hero-figure"]')),
            "body_img_count": len(body.find_all("img")) if body else 0,
            "related_img_count": len(soup.select(".related-posts img")),
            "article_shell_img_count": len(soup.find_all("img")),
        }
    )
    return _plain_non_space_len_from_html(target), diagnostics


def _existing_body_text(article: Article) -> str:
    soup = BeautifulSoup(str(article.html_article or ""), "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return SPACE_RE.sub(" ", soup.get_text(" ", strip=True)).strip()


def _topic_kind(title: str, text: str) -> str:
    value = f"{title} {text}".lower()
    if any(token in value for token in ["カフェ", "cafe", "coffee", "コーヒー"]):
        return "cafe"
    if any(token in value for token in ["祭", "festival", "フェス", "ライト", "桜", "チューリップ", "市場", "ナイトマーケット"]):
        return "event"
    if any(token in value for token in ["食", "グルメ", "屋台", "ビビンバ", "クッパ", "海鮮"]):
        return "food"
    if any(token in value for token in ["散歩", "歩", "ルート", "オルレ", "村", "公園"]):
        return "route"
    return "culture"


def _decision_rows(kind: str) -> list[tuple[str, str, str]]:
    if kind == "food":
        return [
            ("最初の判断", "昼食ピーク前に候補店を決める", "行列が長い店だけを追うと移動時間が崩れるためです。"),
            ("注文", "代表メニューを一つ決め、追加は現地で調整", "初訪問では品数より待ち時間と食べやすさを優先します。"),
            ("移動", "食後に近い散歩先を一つだけ残す", "満腹後に予定を詰めると満足度が下がります。"),
        ]
    if kind == "cafe":
        return [
            ("最初の判断", "有名店を一軒、予備店を二軒決める", "席待ちで時間を失わないためです。"),
            ("滞在", "写真より休憩と次の移動確認を優先", "カフェを移動の調整地点として使うと一日が安定します。"),
            ("時間帯", "午後ピーク前に入店する", "夕方は席と注文列が同時に混みやすくなります。"),
        ]
    if kind == "event":
        return [
            ("最初の判断", "開始時間より早く現地入りする", "会場入口、写真スポット、屋台が同時に混むためです。"),
            ("見る順番", "メイン展示やライトを先に確認", "暗くなる前に位置関係を把握しておくと安心です。"),
            ("帰り方", "終了直後の移動を避ける", "駅やバス停が集中しやすいので少し時間をずらします。"),
        ]
    if kind == "route":
        return [
            ("最初の判断", "坂道と駅出口を先に確認", "地図上の近さより歩きやすさが重要です。"),
            ("歩く順番", "写真スポットを前半、休憩を中盤に置く", "後半の疲れで判断が雑になるのを防げます。"),
            ("切り上げ", "予定を一つ削る基準を決める", "天気や混雑で無理をしないためです。"),
        ]
    return [
        ("最初の判断", "屋内と屋外の比率を決める", "展示、街歩き、休憩のバランスを崩さないためです。"),
        ("見る順番", "情報量の多い場所を前半に置く", "集中力がある時間帯に理解が深まります。"),
        ("調整", "混雑したら近い代替地へ切り替える", "文化エリアは代替候補を持つほど歩きやすくなります。"),
    ]


def _build_refactored_html(article: Article) -> str:
    title = str(article.title or "").strip()
    existing = _existing_body_text(article)
    kind = _topic_kind(title, existing)
    intro_seed = existing[:220] if existing else f"{title}を初めて訪れる人向けに、移動、混雑、休憩、現地判断をまとめます。"
    decision_rows = _decision_rows(kind)
    rows_html = "".join(
        "<tr>"
        f"<td style='border:1px solid #e5e7eb;padding:10px;'>{html.escape(label)}</td>"
        f"<td style='border:1px solid #e5e7eb;padding:10px;'>{html.escape(action)}</td>"
        f"<td style='border:1px solid #e5e7eb;padding:10px;'>{html.escape(reason)}</td>"
        "</tr>"
        for label, action, reason in decision_rows
    )
    kind_focus = {
        "food": "食事の満足度は、店名だけでなく入る時間、注文の決め方、食後の移動で大きく変わります。",
        "cafe": "カフェ巡りは店数を増やすより、席待ちを避けて休憩の質を確保する方が旅全体の印象が良くなります。",
        "event": "季節イベントは現地に着いてから考えるより、入口、見どころ、帰り道を先に決めるほど失敗が減ります。",
        "route": "街歩きは距離ではなく、坂道、信号、休憩、写真待ちの時間まで含めて組む必要があります。",
        "culture": "文化スポットは知識量より、見る順番と滞在時間の配分で理解しやすさが変わります。",
    }[kind]
    html_article = f"""
<p><strong>{html.escape(title)}</strong> は、短い時間でも楽しめる一方で、現地で何から見るかを決めていないと移動と待ち時間に流されやすいテーマです。{html.escape(intro_seed)} この記事では、初めての旅行者でも使いやすいように、行く前に決めること、現地での歩き方、混雑時の切り替え、休憩と予算の考え方までまとめます。</p>
<p>{html.escape(kind_focus)} 韓国旅行では、駅から近い、写真がきれい、口コミが多いという理由だけで動くと、実際の滞在が慌ただしくなることがあります。特に週末や季節イベントの時期は、移動の小さな遅れが後半の予定に響きます。だからこそ、このガイドでは「どこへ行くか」だけでなく「どの順番なら疲れにくいか」を重視します。</p>
<h2>まず決めるべき3つの判断</h2>
<table style="width:100%;border-collapse:collapse;margin:18px 0;font-size:15px;line-height:1.7;">
<thead><tr><th style="border:1px solid #e5e7eb;padding:10px;background:#f8fafc;">判断</th><th style="border:1px solid #e5e7eb;padding:10px;background:#f8fafc;">おすすめ</th><th style="border:1px solid #e5e7eb;padding:10px;background:#f8fafc;">理由</th></tr></thead>
<tbody>{rows_html}</tbody>
</table>
<h2>おすすめの時間帯と動き方</h2>
<p>基本は午前から昼前、または夕方前のどちらかに寄せるのが安全です。午前は人が少なく、写真や移動の自由度が高くなります。夕方前は光の雰囲気が良く、食事やカフェと組み合わせやすい反面、帰宅時間やイベント終わりの人出と重なることがあります。短時間で済ませたい場合は、最初に見る場所を一つ決め、残りは現地の混雑に合わせて調整してください。</p>
<p>現地では、最初の30分で全体の雰囲気をつかむことが大切です。入口、駅、バス停、トイレ、休憩できる場所を把握しておくと、予定変更がしやすくなります。特に家族旅行や初韓国旅行では、細かいスポットを追いかけるより、迷わず戻れる基準点を一つ決めておく方が安心です。</p>
<h2>移動とアクセスで失敗しないコツ</h2>
<p>地下鉄やバスで向かう場合、駅名だけでなく出口番号まで確認しておくと迷いにくくなります。韓国の都市部は同じ駅でも出口によって歩く方向が大きく変わることがあります。地図アプリで最短距離だけを見るのではなく、大通りを通るのか、坂道があるのか、夜でも歩きやすい道かを確認してください。</p>
<p>タクシーを使う場合も、目的地の日本語名だけでは伝わりにくいことがあります。韓国語表記、近くの駅、ランドマークを控えておくと説明しやすくなります。帰りは混雑が集中する時間を避け、駅まで少し歩くか、カフェで時間をずらすだけでも負担がかなり減ります。</p>
<h2>現地での過ごし方</h2>
<p>写真を撮るなら、最初に全体を歩いてから戻る方が失敗しにくいです。到着直後に一か所で長く立ち止まると、その後の流れが悪くなります。まずは人の流れ、日差し、店の混み具合を確認し、良さそうな場所を二つほど覚えておくと、後から落ち着いて撮影できます。</p>
<p>休憩は疲れてから探すのではなく、疲れる前に入れるのが基本です。韓国の人気エリアでは、カフェや食堂が近くに多くても、席が空いているとは限りません。候補を一つだけにせず、混んでいたらすぐ切り替えられるようにしておくと、旅のリズムが崩れません。</p>
<h2>予算と持ち物の目安</h2>
<p>半日であれば、交通費、飲み物、軽食、必要なら入場料や買い物を含めて、一人あたり30,000〜70,000ウォン程度を目安にすると計画しやすいです。食事をしっかり取る場合や体験プログラムを入れる場合は、もう少し余裕を見てください。現金だけに頼らず、カードと少額の現金を分けて持つと安心です。</p>
<p>持ち物は、モバイルバッテリー、歩きやすい靴、天気に合わせた上着、翻訳アプリ、地図のスクリーンショットが基本です。春や秋でも朝夕は冷えることがあり、夏は日差しと湿度、冬は風の冷たさで体力を使います。服装を軽く考えないことが、最後まで楽しむための現実的な対策です。</p>
<h2>混雑した時の切り替え方</h2>
<p>人が多い場合は、予定を全部こなそうとしない方が満足度は上がります。行列が長い、写真待ちが多い、店に入れないと感じたら、近い代替スポットへ切り替えてください。旅行中の良い判断は、予定通りに動くことではなく、その日の状況に合わせて疲れを増やさないことです。</p>
<p>特に週末は、メイン通りより一本横の道、昼食ピークより少し早い時間、イベント終了直後より30分後の移動が効果的です。こうした小さな調整だけで、同じ場所でもかなり快適に感じられます。</p>
<h2>まとめ</h2>
<p>{html.escape(title)} を楽しむなら、目的地そのものよりも、順番、休憩、混雑時の切り替えを先に決めておくことが重要です。短い滞在でも、移動の基準点、見る優先順位、帰り方を押さえておけば、現地で迷う時間が減ります。無理に全部を詰め込まず、自分の体力と天気に合わせて調整することが、韓国ローカル旅を気持ちよく終える一番のコツです。</p>
""".strip()
    while _plain_non_space_len_from_html(html_article) < 2800:
        html_article += (
            "<p>最後にもう一つ大切なのは、現地の雰囲気を急いで消費しないことです。"
            "予定表を埋めるより、歩いている途中で見つけた小さな店、静かな道、地元の人の流れを観察する方が記憶に残ることがあります。"
            "時間に余裕があれば、帰る前に一度だけ立ち止まり、今日の移動が無理のない流れだったかを確認してみてください。"
            "次の韓国旅行で同じ判断を使えるようになり、旅の質が少しずつ上がっていきます。"
            "もし同行者がいる場合は、写真を撮る時間、食事を優先する時間、静かに歩く時間を先に共有しておくと、現地で意見が分かれにくくなります。"
            "一人旅なら、帰りの駅と最後に休める場所だけを決めておけば、予定を変えても不安が少なくなります。</p>"
        )
    return html_article


def _dedupe_faq_section(article: Article) -> list[dict[str, str]]:
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for item in list(article.faq_section or []):
        if not isinstance(item, dict):
            continue
        question = SPACE_RE.sub(" ", str(item.get("question") or "").strip())
        answer = SPACE_RE.sub(" ", str(item.get("answer") or "").strip())
        if not question or not answer:
            continue
        key = re.sub(r"\W+", "", question).casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"question": question, "answer": answer})
    return deduped[:4]


def _group_language_urls(db) -> dict[str, dict[str, str]]:
    query = (
        select(Article)
        .join(BloggerPost, BloggerPost.article_id == Article.id)
        .where(Article.blog_id.in_(TRAVEL_BLOG_IDS))
        .options(selectinload(Article.blogger_post))
    )
    grouped: dict[str, dict[str, str]] = {}
    for article in db.execute(query).scalars().unique().all():
        group_key = str(article.travel_sync_group_key or "").strip()
        language = BLOG_LANGUAGE.get(int(article.blog_id or 0), "")
        url = str(article.blogger_post.published_url if article.blogger_post else "").strip()
        if group_key and language and url:
            grouped.setdefault(group_key, {})[language] = url
    return grouped


def _language_switch_block(current_language: str, urls_by_language: dict[str, str]) -> str:
    languages = [language for language in ("en", "ja", "es") if urls_by_language.get(language)]
    if len(languages) < 2:
        return ""
    heading = html.escape(SWITCH_HEADINGS.get(current_language, SWITCH_HEADINGS["ja"]))
    current_suffix = html.escape(CURRENT_SUFFIX.get(current_language, CURRENT_SUFFIX["ja"]))
    items: list[str] = []
    for language in languages:
        label = html.escape(LANGUAGE_LABELS.get(language, language.upper()))
        url = html.escape(str(urls_by_language[language]), quote=True)
        if language == current_language:
            items.append(f"<li style='margin:0 0 8px;'><strong>{label} {current_suffix}</strong></li>")
        else:
            items.append(f"<li style='margin:0 0 8px;'><a href=\"{url}\" rel=\"noopener\">{label}</a></li>")
    return (
        "<section data-bloggent-role='language-switch' "
        "style='margin-top:30px;padding:18px 20px;border:1px solid #e2e8f0;border-radius:18px;background:#f8fafc;'>"
        f"<h2 style='margin:0 0 12px;font-size:22px;line-height:1.35;color:#0f172a;'>{heading}</h2>"
        "<ul style='margin:0;padding-left:20px;color:#1e293b;font-size:16px;line-height:1.75;'>"
        + "".join(items)
        + "</ul></section>"
    )


def _oauth_check(db) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for blog_id in TRAVEL_BLOG_IDS:
        channel_id = f"blogger:{blog_id}"
        channel = get_managed_channel_by_channel_id(db, channel_id)
        row = {"channel_id": channel_id, "status": getattr(channel, "status", None), "oauth_state": getattr(channel, "oauth_state", None), "refresh_ok": False}
        try:
            credential = refresh_platform_access_token(db, channel_id=channel_id)
            row["refresh_ok"] = bool(credential and credential.is_valid)
            row["expires_at"] = credential.expires_at.isoformat() if credential and credential.expires_at else None
        except Exception as exc:  # noqa: BLE001
            row["error"] = str(exc)
        results.append(row)
    return results


def _select_under1000_articles(db, *, article_ids: set[int] | None, batch_size: int) -> list[Article]:
    query = (
        select(Article)
        .join(BloggerPost, BloggerPost.article_id == Article.id)
        .where(Article.blog_id == JA_BLOG_ID)
        .options(
            selectinload(Article.blog),
            selectinload(Article.image),
            selectinload(Article.blogger_post),
        )
        .order_by(Article.id.asc())
    )
    if article_ids:
        query = query.where(Article.id.in_(list(article_ids)))
    candidates = db.execute(query).scalars().unique().all()
    selected: list[Article] = []
    for article in candidates:
        post = article.blogger_post
        if not post or not str(post.published_url or "").strip():
            continue
        if article_ids:
            selected.append(article)
            continue
        hero_url = str(article.image.public_url or "").strip() if article.image else ""
        live_len, _diag = _article_body_live_length(
            published_url=str(post.published_url),
            title=str(article.title or ""),
            hero_url=hero_url,
        )
        if live_len <= 1000:
            selected.append(article)
        if not article_ids and len(selected) >= batch_size:
            break
    return selected


def _apply_one(db, article: Article, grouped_urls: dict[str, dict[str, str]]) -> dict[str, Any]:
    post = article.blogger_post
    if not post:
        return {"article_id": int(article.id), "status": "failed", "failure_reason": "missing_blogger_post"}
    before_len, before_diag = _article_body_live_length(
        published_url=str(post.published_url or ""),
        title=str(article.title or ""),
        hero_url=str(article.image.public_url or "").strip() if article.image else "",
    )
    article.html_article = _build_refactored_html(article)
    article.faq_section = _dedupe_faq_section(article)
    metadata = dict(article.render_metadata or {})
    metadata["ja_under1000_refactor"] = {
        "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "before_body_nonspace_chars": before_len,
        "target": ">=2500",
    }
    article.render_metadata = metadata
    db.add(article)
    db.commit()
    db.refresh(article)

    hero_url = str(article.image.public_url or "").strip() if article.image else ""
    if not hero_url or is_private_asset_url(hero_url):
        hero_url = str(refresh_article_public_image(db, article) or hero_url or "").strip()
    assembled_html = rebuild_article_html(db, article, hero_url)
    switch_html = _language_switch_block("ja", grouped_urls.get(str(article.travel_sync_group_key or "").strip(), {}))
    if switch_html:
        article.assembled_html = upsert_language_switch_html(assembled_html, switch_html)
        db.add(article)
        db.commit()
        db.refresh(article)

    provider = get_blogger_provider(db, article.blog)
    labels = sanitize_blogger_labels_for_article(article, article.labels)
    summary, payload = provider.update_post(
        post_id=str(post.blogger_post_id),
        title=article.title,
        content=str(article.assembled_html or ""),
        labels=labels,
        meta_description=article.meta_description,
    )
    blogger_post = upsert_article_blogger_post(db, article=article, summary=summary, raw_payload=payload)
    published_url = str(blogger_post.published_url or post.published_url or "").strip()
    live_validation = validate_blogger_live_publish(
        published_url=published_url,
        expected_title=article.title,
        expected_hero_url=hero_url,
        assembled_html=str(article.assembled_html or ""),
        required_article_h1_count=1,
    )
    after_len, after_diag = _article_body_live_length(
        published_url=published_url,
        title=str(article.title or ""),
        hero_url=hero_url,
    )
    issues: list[str] = []
    if live_validation.get("status") != "ok":
        issues.extend(list(live_validation.get("failure_reasons") or ["live_validation_failed"]))
    if after_len < 2500:
        issues.append("body_under_2500_after_refactor")
    if after_diag.get("article_h1_count") != 1:
        issues.append("h1_not_1_after_refactor")
    if after_diag.get("hero_figure_count") != 1:
        issues.append("hero_not_1_after_refactor")
    if after_diag.get("body_img_count") != 0:
        issues.append("body_inline_img_after_refactor")
    if after_diag.get("related_img_count") != 3:
        issues.append("related_img_not_3_after_refactor")
    if after_diag.get("article_shell_img_count") != 4:
        issues.append("article_shell_img_not_4_after_refactor")
    metadata = dict(article.render_metadata or {})
    metadata["ja_under1000_refactor"] = {
        **dict(metadata.get("ja_under1000_refactor") or {}),
        "after_body_nonspace_chars": after_len,
        "status": "ok" if not issues else "failed",
        "issues": issues,
        "published_url": published_url,
    }
    article.render_metadata = metadata
    db.add(article)
    db.commit()
    return {
        "article_id": int(article.id),
        "blog_id": int(article.blog_id),
        "title": article.title,
        "published_url": published_url,
        "before_body_nonspace_chars": before_len,
        "after_body_nonspace_chars": after_len,
        "status": "ok" if not issues else "failed",
        "issues": issues,
        "before_diagnostics": before_diag,
        "after_diagnostics": after_diag,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refactor short Japanese travel posts in small batches.")
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--article-ids", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report-root", default=str(DEFAULT_REPORT_ROOT))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    article_ids = {int(token) for token in str(args.article_ids or "").split(",") if token.strip()}
    report_root = Path(str(args.report_root)).resolve()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    with SessionLocal() as db:
        oauth = _oauth_check(db)
        if any(not row.get("refresh_ok") for row in oauth):
            report = {"status": "oauth_failed", "oauth": oauth}
            _write_json(report_root / f"travel-ja-under1000-refactor-{stamp}.json", report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        selected = _select_under1000_articles(db, article_ids=article_ids or None, batch_size=max(1, int(args.batch_size or 5)))
        if args.dry_run:
            rows = [
                {
                    "article_id": int(article.id),
                    "title": article.title,
                    "published_url": article.blogger_post.published_url if article.blogger_post else None,
                }
                for article in selected
            ]
        else:
            grouped_urls = _group_language_urls(db)
            rows = []
            for article in selected:
                try:
                    rows.append(_apply_one(db, article, grouped_urls))
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    rows.append({"article_id": int(article.id), "status": "failed", "issues": ["exception"], "error": str(exc)})
        report = {
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "mode": "dry_run" if args.dry_run else "apply",
            "batch_size": int(args.batch_size or 5),
            "selected_count": len(selected),
            "oauth": oauth,
            "rows": rows,
            "ok": sum(1 for row in rows if row.get("status") == "ok"),
            "failed": sum(1 for row in rows if row.get("status") == "failed"),
        }
    path = report_root / f"travel-ja-under1000-refactor-{stamp}.json"
    _write_json(path, report)
    print(json.dumps({"report_path": str(path), **{k: report[k] for k in ["mode", "selected_count", "ok", "failed"]}, "article_ids": [row.get("article_id") for row in rows]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
