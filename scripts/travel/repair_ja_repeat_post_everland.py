from __future__ import annotations

import html
import json
import os
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import text


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
RUNTIME_ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
DEFAULT_REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel\reports")
DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"

BLOG_ID = "2205773967728946989"
POST_ID = "1500501478243077428"
POST_URL = "https://donggri-kankoku.blogspot.com/2026/04/2026_0227713673.html"
TITLE = "エバーランド・ローズフェスティバル2026：混雑を避ける庭園ルートと写真タイミング"
HERO_URL = "https://api.dongriarchive.com/assets/travel-blogger/culture/everland-rose-2026.webp"
LABELS = [
    "2026",
    "Travel",
    "エバーランド",
    "ローカルガイド",
    "ローズフェスティバル",
    "庭園ルート",
    "旅行・お祭り",
    "現地ルート",
    "韓国の春",
    "韓国旅行",
    "龍仁",
]

SPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？])\s*")
FORBIDDEN_RE = re.compile(
    r"\b(?:SEO|GEO|CTR|Lighthouse|PageSpeed|article_pattern|pattern_key|travel-0[1-5]|hidden-path-route|cultural-insider|local-flavor-guide|seasonal-secret|smart-traveler-log)\b",
    re.I,
)


def _stdout_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _load_env() -> None:
    if not RUNTIME_ENV_PATH.exists():
        return
    for raw in RUNTIME_ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def _plain_text(value: str) -> str:
    return SPACE_RE.sub(" ", TAG_RE.sub(" ", value or "")).strip()


def _non_space_len(value: str) -> int:
    return len(SPACE_RE.sub("", _plain_text(value)))


def _repeat_issues(value: str) -> list[dict[str, Any]]:
    text = _plain_text(value)
    counter: Counter[str] = Counter()
    original: dict[str, str] = {}
    for sentence in SENTENCE_SPLIT_RE.split(text):
        sentence = SPACE_RE.sub(" ", sentence).strip()
        if len(sentence) < 24:
            continue
        key = sentence.casefold()
        counter[key] += 1
        original.setdefault(key, sentence)
    return [{"count": count, "sentence": original[key]} for key, count in counter.items() if count >= 3]


def _extract_related_section(current_html: str) -> str:
    soup = BeautifulSoup(current_html, "html.parser")
    section = soup.select_one(".bloggent-related-posts")
    return str(section) if section else ""


def _fetch_public_content() -> tuple[str, dict[str, Any]]:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for start in (1, 101):
            response = client.get(
                "https://donggri-kankoku.blogspot.com/feeds/posts/default",
                params={"alt": "json", "start-index": start, "max-results": 100},
            )
            response.raise_for_status()
            for entry in response.json().get("feed", {}).get("entry", []) or []:
                href = next((str(link.get("href") or "") for link in entry.get("link") or [] if link.get("rel") == "alternate"), "")
                if href == POST_URL:
                    return str((entry.get("content") or {}).get("$t") or ""), entry
    raise RuntimeError("Target post not found in public feed.")


def _build_body_html(related_html: str) -> str:
    esc_title = html.escape(TITLE)
    esc_hero = html.escape(HERO_URL)
    return f"""
<div class="article-content">
<h1>{esc_title}</h1>
<figure class="bloggent-hero-figure">
  <img src="{esc_hero}" alt="エバーランドのローズガーデンを歩く春の庭園ルート" loading="eager" decoding="async" />
  <figcaption>エバーランドのローズフェスティバルは、到着時間と庭園に入る順番を決めておくと写真も休憩も組みやすくなります。</figcaption>
</figure>
<p class="bloggent-dek">エバーランドのローズフェスティバルは、花だけを見に行くイベントではありません。入園、移動、写真、食事、帰りの交通が同じ日に重なるため、庭園へ入る時間と退く時間を先に決めることが満足度を左右します。</p>
<div class="bloggent-travel-body">
<p>ローズフェスティバルを楽しむコツは、園内を全部回ろうとしないことです。エバーランドは広く、人気アトラクション、動物エリア、レストラン、庭園が離れているため、何も決めずに歩くと花を見る前に体力を使います。まずローズガーデンを主役に置き、その前後に一つだけ休憩や食事を足す形にすると、移動の負担が軽くなります。</p>
<p>2026年に初めて行くなら、午前の入園直後か、午後の光が柔らかくなる時間を狙うのが現実的です。昼のピークは人が多く、写真を撮るにも通路が詰まりやすいので、庭園そのものを味わう時間と、園内で遊ぶ時間を分けて考えてください。</p>

<h2>ローズフェスティバルで最初に決めること</h2>
<p>最初に決めるべきなのは、入園後すぐ庭園へ行くか、夕方に庭園を残すかです。午前型は写真が撮りやすく、混雑前に花を見られるのが強みです。夕方型は光が柔らかく、雰囲気は良くなりますが、帰りの交通と食事の時間が重なるため、予定を詰めすぎると疲れます。</p>
<p>家族連れなら午前型、カップルや写真目的なら午後遅め、アトラクションも少し入れたい人は昼に休憩を挟む形が向いています。どの型でも、ローズガーデンを「ついで」にしないことが大切です。</p>

<h2>園内ルート：入口から庭園までの歩き方</h2>
<h3>人の流れに流されない入口判断</h3>
<p>入園直後は多くの人が人気アトラクションや中心エリアへ向かいます。ローズガーデンを目的にするなら、最初の分岐で人の多い方向にそのまま乗らず、地図で庭園までの最短動線を確認してください。遠回りに見える道でも、階段や混雑を避けられるなら結果的に早いことがあります。</p>
<p>園内では「今いる場所」より「次に休む場所」を見ながら動くと安定します。花のエリアで長く立ち続けると疲れるため、庭園に入る前にトイレ、飲み物、日陰の位置を確認しておくと安心です。</p>
<p>エバーランドは坂と広い通路が多いので、地図上の距離より実際の歩行負担が大きく感じられます。ローズガーデンに着く前に疲れてしまうと、花の前で立ち止まる余裕がなくなります。入園直後は気分が上がって寄り道を増やしがちですが、最初の一時間だけは目的地までの移動を優先したほうが、後半の満足度が高くなります。</p>

<h2>写真を撮る時間帯と立ち位置</h2>
<h3>正面より斜め、満開より余白</h3>
<p>ローズガーデンでは、正面から花だけを大きく撮るより、通路、アーチ、背景の緑を少し入れるとエバーランドらしい写真になります。人が多い時は、花壇の真ん中で待つより、斜めから奥行きを作るほうが撮りやすいです。</p>
<p>昼は色が強く出ますが、影も硬くなります。午後遅めは花の輪郭が柔らかくなり、人物写真も落ち着きます。ただし閉園時間や帰りのバスが近づくので、夕方型にするなら撮影場所を二つまでに絞ってください。</p>
<p>スマートフォンで撮る場合は、花に近づきすぎるより、少し引いて背景の通路やアーチを入れるほうが旅の記録として使いやすくなります。人が写り込むのを完全に避けるのは難しいため、混雑を消そうとするより、人の流れが切れる瞬間を待つほうが現実的です。撮影に時間を使う人は、同行者の待ち時間も先に決めておくと雰囲気が悪くなりません。</p>

<h2>時間帯別のおすすめ行動</h2>
<table class="bloggent-route-table">
  <thead><tr><th>時間帯</th><th>おすすめ行動</th><th>避けたいこと</th></tr></thead>
  <tbody>
    <tr><td>開園直後</td><td>入園後すぐ庭園の方向を確認し、混雑前に主役の花を見る。</td><td>入口周辺で長く迷い、最初の静かな時間を逃す。</td></tr>
    <tr><td>午前後半</td><td>ローズガーデンを一周し、写真と休憩を分けて動く。</td><td>同じ花壇前で何度も撮り直して通路を塞ぐ。</td></tr>
    <tr><td>昼</td><td>食事、屋内休憩、日陰のベンチで体力を戻す。</td><td>暑さと人混みの中で庭園を無理に回り続ける。</td></tr>
    <tr><td>午後遅め</td><td>光が柔らかい場所で短く撮影し、帰りの動線を確認する。</td><td>閉園前に遠いエリアへ移動して帰路を読みにくくする。</td></tr>
    <tr><td>夜前</td><td>出口方向へ戻りながら軽食やショップを選ぶ。</td><td>最後に食事、買い物、写真を全部詰め込む。</td></tr>
  </tbody>
</table>

<h2>混雑を避ける判断ポイント</h2>
<p>混雑日は、庭園の中心に長くいるより、外側の通路を使って一度流れを外すほうが楽です。人が多い場所は写真を一枚だけにして、空いている角度を探す時間に切り替えましょう。ローズフェスティバルでは、花の密度だけでなく、人の少ない背景を選ぶことも写真の質に直結します。</p>
<p>ベビーカーや小さな子どもと一緒なら、階段や狭い通路を避けるだけで疲れ方が変わります。同行者がいる場合は、庭園に入る前に「何時に集合するか」「写真を優先するか休憩を優先するか」を決めてください。園内でその判断を始めると、意外に時間を使います。</p>
<p>天気が暑い日は、花を見る順番を短くして屋内休憩を早めに入れるほうが安全です。雨上がりは花の色がきれいに見えますが、足元が滑りやすくなるため、写真に集中しすぎず通路の状態を見ながら歩いてください。</p>
<p>待ち時間が長くなったら、予定を削る基準を持っておくことも大切です。ローズガーデンを主役にする日は、遠いアトラクションを一つ減らすだけで移動がかなり楽になります。逆にアトラクションを優先する日は、庭園では写真を短く済ませ、雰囲気を味わう時間に切り替えると無理がありません。</p>

<h2>食事と休憩の入れ方</h2>
<p>エバーランドでは、昼食を庭園の直後に置くと流れが作りやすくなります。花を見てから席を探す場合、ピーク時間に重なると待ち時間が長くなるので、軽食でつなぐか、早めの昼食にするかを入園前に決めておくと安心です。</p>
<p>カフェや売店を選ぶ時は、メニューより位置を重視してください。庭園から遠い店へ行くと、戻るだけで疲れます。短い休憩なら、飲み物を買って日陰で座るだけでも十分です。写真目的の日ほど、休憩を削らないほうが表情も歩き方も安定します。</p>
<p>夕方まで滞在する予定なら、昼食を重くしすぎないこともポイントです。園内で長く歩く日は、満腹になる食事より、休憩を兼ねて軽く食べるほうが動きやすくなります。帰りに龍仁やソウル方面で食事を考えているなら、園内では飲み物と軽食にして、出口へ向かう時間を早めに確保してください。</p>

<h2>出発前チェックリスト</h2>
<ul>
  <li>ローズガーデンを午前に見るか夕方に見るか決める。</li>
  <li>帰りのバス、地下鉄連絡、タクシー候補を事前に確認する。</li>
  <li>写真を撮る場所は二つか三つに絞り、通路では長く止まらない。</li>
  <li>暑さ対策として飲み物、帽子、短い休憩時間を用意する。</li>
  <li>同行者とは集合場所と休憩優先度を先に共有する。</li>
</ul>

<h2>このルートが向いている人</h2>
<p>この組み方は、エバーランドで花の写真をしっかり残したい人、アトラクションより季節イベントを優先したい人、混雑の中でも落ち着いて歩きたい人に向いています。反対に、すべてのエリアを一日で回りたい人は、ローズガーデンの滞在を短くするか、別の日にもう一度訪れる前提で計画したほうが無理がありません。</p>
<p>ローズフェスティバルは、花の量だけで満足度が決まるイベントではありません。入園直後の判断、庭園へ入る時間、食事と休憩の置き方、帰りの動線まで整えることで、同じ一日でもかなり軽く感じられます。主役をローズガーデンに決め、ほかの要素を支える役割に回すことが、失敗しにくい楽しみ方です。</p>
<p>初めてなら「午前に庭園、昼に休憩、午後は一つだけ追加」という形が最も安定します。二度目以降なら夕方の光を狙い、写真のために庭園を後半へ残すのも良い選択です。どちらの場合も、最後に出口へ戻る時間を決めておけば、花の余韻を残したまま一日を終えられます。</p>
</div>
{related_html}
</div>
""".strip()


def _validate_html(content: str) -> dict[str, Any]:
    soup = BeautifulSoup(content, "html.parser")
    r2_urls = re.findall(r"https://api\.dongriarchive\.com/assets/travel-blogger/[^\"'<>\s)]+?\.webp", content)
    repeats = _repeat_issues(content)
    body_chars = _non_space_len(content)
    row = {
        "h1_count": len(soup.find_all("h1")),
        "h2_count": len(soup.find_all("h2")),
        "h3_count": len(soup.find_all("h3")),
        "table_count": len(soup.find_all("table")),
        "li_count": len(soup.find_all("li")),
        "image_count": len(soup.find_all("img")),
        "r2_unique_image_count": len(set(r2_urls)),
        "body_non_space_chars": body_chars,
        "repeat_3plus_count": len(repeats),
        "repeat_issues": repeats,
        "forbidden_visible_terms": bool(FORBIDDEN_RE.search(_plain_text(content))),
    }
    row["status"] = "ok" if (
        row["h1_count"] == 1
        and row["image_count"] == 4
        and row["r2_unique_image_count"] == 4
        and row["body_non_space_chars"] >= 3000
        and not row["repeat_issues"]
        and not row["forbidden_visible_terms"]
    ) else "failed"
    return row


def _access_token() -> str:
    if str(API_ROOT) not in sys.path:
        sys.path.insert(0, str(API_ROOT))
    os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL") or DATABASE_URL
    from app.db.session import SessionLocal  # noqa: PLC0415
    from app.services.blogger.blogger_oauth_service import get_valid_blogger_access_token  # noqa: PLC0415

    with SessionLocal() as db:
        return str(get_valid_blogger_access_token(db)).strip()


def _patch_blogger_post(access_token: str, content: str) -> dict[str, Any]:
    response = httpx.patch(
        f"https://www.googleapis.com/blogger/v3/blogs/{BLOG_ID}/posts/{POST_ID}",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        json={"title": TITLE, "content": content, "labels": LABELS},
        timeout=60.0,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Blogger update failed: {response.status_code} {response.text[:500]}")
    return response.json()


def _update_synced_row(content: str) -> None:
    if str(API_ROOT) not in sys.path:
        sys.path.insert(0, str(API_ROOT))
    os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL") or DATABASE_URL
    from app.db.session import SessionLocal  # noqa: PLC0415

    with SessionLocal() as db:
        db.execute(
            text(
                """
                update synced_blogger_posts
                   set title = :title,
                       labels = cast(:labels as jsonb),
                       content_html = :content_html,
                       excerpt_text = :excerpt_text,
                       updated_at_remote = now(),
                       synced_at = now()
                 where blog_id = 37 and remote_post_id = :remote_post_id
                """
            ),
            {
                "title": TITLE,
                "labels": json.dumps(LABELS, ensure_ascii=False),
                "content_html": content,
                "excerpt_text": _plain_text(content)[:480],
                "remote_post_id": POST_ID,
            },
        )
        db.commit()


def main() -> int:
    _stdout_utf8()
    _load_env()
    current_content, _entry = _fetch_public_content()
    related_html = _extract_related_section(current_content)
    new_content = _build_body_html(related_html)
    before = _validate_html(current_content)
    planned = _validate_html(new_content)
    if planned["status"] != "ok":
        raise RuntimeError(f"Planned HTML failed validation: {planned}")
    api_summary = _patch_blogger_post(_access_token(), new_content)
    live = httpx.get(POST_URL, timeout=30.0, follow_redirects=True)
    live.raise_for_status()
    live_article = BeautifulSoup(live.text, "html.parser").select_one(".article-content")
    live_validation = _validate_html(str(live_article or live.text))
    if live_validation["status"] != "ok":
        raise RuntimeError(f"Live validation failed: {live_validation}")
    _update_synced_row(new_content)
    report = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "url": POST_URL,
        "blog_id": 37,
        "remote_post_id": POST_ID,
        "title": TITLE,
        "before": before,
        "planned": planned,
        "live_validation": live_validation,
        "blogger_api_url": api_summary.get("url"),
        "synced_blogger_posts_updated": True,
    }
    path = DEFAULT_REPORT_ROOT / f"travel-ja-repeat-repair-everland-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report_path": str(path), "url": POST_URL, "live_validation": live_validation}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
