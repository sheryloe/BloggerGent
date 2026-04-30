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
POST_ID = "4267172847246153771"
POST_URL = "https://donggri-kankoku.blogspot.com/2026/04/2026_01304049192.html"
TITLE = "仏国寺と石窟庵2026：慶州で失敗しにくい寺院ルートと観覧の順番"
HERO_URL = "https://api.dongriarchive.com/assets/travel-blogger/culture/gyeongju-bulguksa-premium-2026.webp"
LABELS = [
    "02-cultural-insider",
    "2026",
    "Travel",
    "ユネスコ",
    "仏国寺",
    "寺院ルート",
    "慶州",
    "文化",
    "文化遺産ガイド",
    "現地ルート",
    "石窟庵",
    "韓国旅行",
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


def _build_body_html(related_html: str) -> str:
    esc_title = html.escape(TITLE)
    esc_hero = html.escape(HERO_URL)
    return f"""
<div class="article-content">
<h1>{esc_title}</h1>
<figure class="bloggent-hero-figure">
  <img src="{esc_hero}" alt="仏国寺と石窟庵を一日で回る慶州文化遺産ルート" loading="eager" decoding="async" />
  <figcaption>仏国寺と石窟庵を同じ日に回るなら、境内の順番と移動時間を先に決めるだけで疲れ方が変わります。</figcaption>
</figure>
<p class="bloggent-dek">仏国寺と石窟庵は、慶州旅行で名前だけを見て組むと移動の負担が出やすい組み合わせです。この記事では、寺院の由来を長く説明するよりも、どの時間に入り、どこで立ち止まり、どの判断で次へ動くかを現地目線で整理します。</p>
<div class="bloggent-travel-body">
<p>仏国寺と石窟庵を一日で見るなら、最初に決めるべきことは「全部を均等に見る」ことではありません。仏国寺では境内の広さと階段の位置、石窟庵ではシャトルや坂道の時間が体力を左右します。午前に仏国寺へ入り、昼前後に石窟庵へ動き、帰りの交通を早めに確保するだけで、同じ慶州でもかなり落ち着いた旅になります。</p>
<p>特に初めての慶州旅行では、文化財の名前を追いかけるより、動線を短く保つことが大切です。写真を撮る場所、静かに見る場所、休憩する場所を分けて考えると、本殿前で長く詰まったり、石窟庵へ向かう時間を読み違えたりする失敗を避けられます。</p>

<h2>最初に決めるべき一日の型</h2>
<p>このルートは、慶州に宿泊している人にも、釜山やソウルから移動してきた人にも使いやすい形です。午前のうちに仏国寺へ入り、境内を一方向に歩き、昼前後に石窟庵へ移る流れを基本にします。午後遅くに仏国寺へ戻る形にすると、写真は柔らかくなりますが、帰りの交通と食事の選択肢が狭くなるので注意が必要です。</p>
<p>寺院巡りでよくある失敗は、入口付近で写真を撮りすぎて奥の時間がなくなることです。青雲橋・白雲橋、紫霞門、大雄殿、多宝塔と釈迦塔を見る順番を先に決め、立ち止まる場所を二つか三つに絞ると、境内の印象が散らばりません。</p>

<h2>仏国寺の歩き方：入口から本殿まで</h2>
<h3>写真を撮る場所と静かに見る場所を分ける</h3>
<p>仏国寺では、入口からすぐに石段と門が目に入ります。ここは写真を撮りたくなる場所ですが、人の流れも止まりやすいので、長く立つより一度横へ抜けて全体を見るほうが落ち着きます。朝の早い時間なら正面から、昼に近い時間なら少し斜めから見たほうが人の重なりを避けやすくなります。</p>
<p>大雄殿前では、建物だけでなく左右の石塔を見比べる時間を残してください。多宝塔は装飾の密度、釈迦塔は余白の美しさが違います。写真を一枚撮って終わるより、少し離れて両方を同じ視界に入れると、仏国寺らしい均衡が伝わります。</p>

<h2>石窟庵へ移る判断：徒歩か車か</h2>
<h3>体力よりも帰りの時間を基準にする</h3>
<p>石窟庵は仏国寺から近く見えても、移動を軽く考えると後半が慌ただしくなります。徒歩ルートを選ぶ場合は、坂道の時間だけでなく、戻りの交通をどうするかまで決めてから出発するべきです。天気が悪い日、荷物が多い日、同行者に子どもや年配の人がいる日は、無理に歩くより車やバスを使うほうが体験の質が上がります。</p>
<p>石窟庵では内部の撮影や滞在時間に制限があるため、長居する場所ではなく、集中して見る場所として考えると失敗しません。入口周辺で時間を使いすぎず、参拝の流れを尊重しながら短く深く見るのが向いています。</p>

<h2>時間帯別のおすすめ行動</h2>
<table class="bloggent-route-table">
  <thead><tr><th>時間帯</th><th>おすすめ行動</th><th>避けたいこと</th></tr></thead>
  <tbody>
    <tr><td>09:00-10:30</td><td>仏国寺へ入り、石段と本殿周辺を先に見る。</td><td>入口で長く撮影して奥の時間を削る。</td></tr>
    <tr><td>10:30-12:00</td><td>大雄殿、石塔、周辺の回廊を落ち着いて確認する。</td><td>人の多い正面だけにこだわる。</td></tr>
    <tr><td>12:00-14:00</td><td>食事または短い休憩を入れてから石窟庵へ移動する。</td><td>空腹のまま坂道や待ち時間に入る。</td></tr>
    <tr><td>14:00-16:00</td><td>石窟庵を短く集中して見て、帰路を早めに確定する。</td><td>帰りのバスやタクシーを現地で初めて探す。</td></tr>
    <tr><td>16:00以降</td><td>慶州市内へ戻り、食事かカフェで余韻を残す。</td><td>疲れた状態でさらに観光地を詰め込む。</td></tr>
  </tbody>
</table>

<h2>混雑と礼儀で失敗しない判断</h2>
<p>寺院では、混雑回避だけでなく礼儀も旅の質に関わります。写真を撮るときは参拝者の正面を塞がないこと、本殿前では声を落とすこと、列ができている場所では短く動くことを意識してください。観光地として有名でも、現地では今も信仰の場として使われています。</p>
<p>団体客が入ってきたら、同じ方向へ急いで進むより、脇の建物や庭の端で数分待つほうが楽です。仏国寺は広いので、混んだ場所を避けても見るものがなくなるわけではありません。むしろ少し外側へ動いたときに、屋根の線、石垣、木陰の静けさがよく見えます。</p>
<p>本殿前で人が詰まっている場合は、正面にこだわらず、回廊側から視線を変えてください。慶州の寺院は、建物を一点で見るより、屋根の重なり、石段の高さ、庭の余白を一緒に見たほうが印象が残ります。混雑時ほど「今すぐ正面写真を撮る」より「五分待って角度を変える」ほうが、結果的に良い写真になります。</p>
<p>石窟庵でも同じで、内部へ入る前に説明板を全部読み切ろうとすると流れに遅れます。先に見るポイントを一つだけ決め、出た後に外の空気の中で内容を整理するほうが落ち着きます。文化財を理解する旅は、現地で情報を詰め込むことではなく、歩く順番と余白を作ることから始まります。</p>

<h2>食事と休憩をどこに置くか</h2>
<p>仏国寺周辺で食事をするなら、寺院の直前より、見学後に出口方向で選ぶほうが動きやすくなります。慶州らしい定食や軽い麺料理を選ぶ場合も、店の有名度だけで決めず、次に乗る交通と逆方向へ歩かないことを優先してください。短い休憩でも、靴を脱がなくてよい席、荷物を置ける席、注文が早い店を選ぶと後半が楽です。</p>
<p>カフェを入れる場合は、石窟庵の前ではなく戻った後がおすすめです。山側で時間を使いすぎると帰りが読みにくくなるため、文化財を見る時間と休む時間を分けたほうが満足度が安定します。</p>
<p>同行者がいる場合は、食事前に「この後もう一か所見るか、今日はここで終えるか」を確認しておくと揉めにくくなります。仏国寺と石窟庵は見どころが強い分、終わった後に疲れが出やすい場所です。余力があれば慶州市内で軽く歩き、疲れていれば早めに宿へ戻る判断も十分に良い選択です。</p>

<h2>出発前チェックリスト</h2>
<ul>
  <li>仏国寺に入る時間と、石窟庵へ移る時間を先に決める。</li>
  <li>帰りのバス、タクシー、駅までの移動候補を二つ用意する。</li>
  <li>階段と坂道に備えて、歩きやすい靴と軽い荷物にする。</li>
  <li>写真を撮る場所は三つまでに絞り、参拝者の動線を塞がない。</li>
  <li>雨や強風の日は徒歩移動を減らし、石窟庵の滞在を短くする。</li>
</ul>

<h2>このルートが向いている人</h2>
<p>この組み方は、慶州の代表的な文化遺産を一日で見たい人、寺院の雰囲気を急がず味わいたい人、写真と移動の両方を無理なく取りたい人に向いています。反対に、細かい解説をすべて読み込みたい人や、徒歩移動を長く楽しみたい人は、仏国寺と石窟庵を別々の日に分けるほうが満足しやすいです。</p>
<p>仏国寺と石窟庵は、数をこなす場所ではなく、順番を整えるほど印象が深くなる場所です。入口、本殿、石塔、石窟庵、帰り道の役割を分けておけば、慶州らしい静けさと文化財の重みを同時に残せます。</p>
<p>最後に覚えておきたいのは、慶州の寺院ルートは早歩きで評価する場所ではないということです。短い旅程でも、入口で急がず、中心で欲張らず、帰り道を早めに決めるだけで、見終わった後の疲労感がかなり違います。初めてなら午前中心、二度目なら夕方の光、家族旅行なら移動を短くする形で調整してください。</p>
</div>
{related_html}
</div>
""".strip()


def _refresh_access_token() -> str:
    try:
        if str(API_ROOT) not in sys.path:
            sys.path.insert(0, str(API_ROOT))
        os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL") or DATABASE_URL
        from app.db.session import SessionLocal  # noqa: PLC0415
        from app.services.blogger.blogger_oauth_service import get_valid_blogger_access_token  # noqa: PLC0415

        with SessionLocal() as db:
            token = get_valid_blogger_access_token(db)
            if str(token or "").strip():
                return str(token).strip()
    except Exception:
        pass

    refresh_token = os.environ.get("BLOGGER_REFRESH_TOKEN", "").strip()
    client_id = os.environ.get("BLOGGER_CLIENT_ID", "").strip()
    client_secret = os.environ.get("BLOGGER_CLIENT_SECRET", "").strip()
    if not refresh_token or not client_id or not client_secret:
        raise RuntimeError("Blogger OAuth env is missing.")
    response = httpx.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=30.0,
    )
    response.raise_for_status()
    access_token = str(response.json().get("access_token") or "").strip()
    if not access_token:
        raise RuntimeError("Blogger OAuth refresh did not return access_token.")
    return access_token


def _fetch_public_content() -> tuple[str, dict[str, Any]]:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for start in (1, 101):
            response = client.get(
                "https://donggri-kankoku.blogspot.com/feeds/posts/default",
                params={"alt": "json", "start-index": start, "max-results": 100},
            )
            response.raise_for_status()
            for entry in response.json().get("feed", {}).get("entry", []) or []:
                links = entry.get("link") or []
                href = next((str(link.get("href") or "") for link in links if link.get("rel") == "alternate"), "")
                if href == POST_URL:
                    return str((entry.get("content") or {}).get("$t") or ""), entry
    raise RuntimeError("Target post not found in public feed.")


def _validate_html(content: str) -> dict[str, Any]:
    soup = BeautifulSoup(content, "html.parser")
    h1_count = len(soup.find_all("h1"))
    image_count = len(soup.find_all("img"))
    r2_urls = re.findall(r"https://api\.dongriarchive\.com/assets/travel-blogger/[^\"'<>\s)]+?\.webp", content)
    body_chars = _non_space_len(content)
    repeats = _repeat_issues(content)
    forbidden = bool(FORBIDDEN_RE.search(_plain_text(content)))
    return {
        "h1_count": h1_count,
        "h2_count": len(soup.find_all("h2")),
        "h3_count": len(soup.find_all("h3")),
        "table_count": len(soup.find_all("table")),
        "li_count": len(soup.find_all("li")),
        "image_count": image_count,
        "r2_unique_image_count": len(set(r2_urls)),
        "body_non_space_chars": body_chars,
        "repeat_3plus_count": len(repeats),
        "repeat_issues": repeats,
        "forbidden_visible_terms": forbidden,
        "status": "ok" if h1_count == 1 and image_count == 4 and len(set(r2_urls)) == 4 and body_chars >= 3000 and not repeats and not forbidden else "failed",
    }


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


def _update_synced_row(content: str, summary: dict[str, Any]) -> None:
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
    report_path = DEFAULT_REPORT_ROOT / f"travel-ja-repeat-repair-bulguksa-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
    current_content, _entry = _fetch_public_content()
    related_html = _extract_related_section(current_content)
    new_content = _build_body_html(related_html)
    before = _validate_html(current_content)
    planned = _validate_html(new_content)
    if planned["status"] != "ok":
        raise RuntimeError(f"Planned HTML failed validation: {planned}")

    access_token = _refresh_access_token()
    api_summary = _patch_blogger_post(access_token, new_content)

    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        live = client.get(POST_URL)
        live.raise_for_status()
    live_validation = _validate_html(str(BeautifulSoup(live.text, "html.parser").select_one(".article-content") or live.text))
    if live_validation["status"] != "ok":
        raise RuntimeError(f"Live validation failed: {live_validation}")

    _update_synced_row(new_content, api_summary)

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
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report_path": str(report_path), "url": POST_URL, "live_validation": live_validation}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
