from __future__ import annotations

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
REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel\reports")
DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"
BLOG_ID = "2205773967728946989"

SPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？])\s*")
R2_RE = re.compile(r"https://api\.dongriarchive\.com/assets/travel-blogger/[^\"'<>\s)]+?\.webp", re.I)
FORBIDDEN_RE = re.compile(
    r"\b(?:SEO|GEO|CTR|Lighthouse|PageSpeed|article_pattern|pattern_key|travel-0[1-5]|hidden-path-route|cultural-insider|local-flavor-guide|seasonal-secret|smart-traveler-log)\b",
    re.I,
)


POSTS = [
    {
        "url": "https://donggri-kankoku.blogspot.com/2026/04/2026_01008096812.html",
        "post_id": "7709220712247508119",
        "title": "釜山甘川文化村の歩き方2026：坂道、壁画、写真時間の実用ガイド",
        "labels": ["Travel", "写真スポット", "壁画村", "徒歩ルート", "旅行・お祭り", "甘川文化村", "釜山", "韓国旅行"],
        "block": """
<section class="bloggent-quality-addition">
  <h2>坂道の街で疲れないための追加判断</h2>
  <h3>写真より先に帰り道を決める</h3>
  <p>甘川文化村は、写真スポットが多い一方で坂道と階段が続く場所です。到着直後は壁画や展望に目が行きますが、最初に考えるべきなのは帰る方向です。上へ進むほど景色は良くなりますが、同じ道を戻るのか、別の出口へ抜けるのかで体力の使い方が変わります。</p>
  <p>初めてなら、入口付近で地図を確認し、写真を撮る場所を三つまでに絞ると歩きやすくなります。壁画を全部追うより、展望、路地、カフェ休憩のように役割を分けると、短い滞在でも記憶に残ります。</p>
  <h3>坂道と休憩の入れ方</h3>
  <p>坂を上りながら写真を撮り続けると、気づかないうちに疲れます。十分钟歩いたら一度立ち止まり、次に進むか戻るかを判断してください。人が多い日は狭い道で立ち止まるより、少し開けた場所で休むほうが安全です。</p>
  <p>夕方に訪れる場合は、光が柔らかく写真はきれいですが、暗くなる前にバス停や大通りへ戻る必要があります。カフェで長く休むなら、その後にさらに奥へ進まず、帰路に近い場所を選ぶと失敗しにくくなります。</p>
</section>
""",
    },
    {
        "url": "https://donggri-kankoku.blogspot.com/2026/04/2026_01013925573.html",
        "post_id": "669020671490169993",
        "title": "韓国ソルラル2026：文化行事、交通、宿泊を失敗しない実用ガイド",
        "labels": ["Culture", "ソルラル", "ライフスタイル", "交通ガイド", "宿泊ガイド", "文化", "旧正月", "韓国旅行"],
        "block": """
<section class="bloggent-quality-addition">
  <h2>ソルラル旅行で最初に固定すべきこと</h2>
  <h3>営業日より移動日を先に見る</h3>
  <p>ソルラル時期の韓国旅行は、観光地の営業情報だけで判断すると移動でつまずきます。KTX、高速バス、空港鉄道、都市間移動の混雑が強くなるため、まず出発日と帰国日を固定し、その間に何を入れられるかを考えるべきです。</p>
  <p>地方へ移動する場合は、名節前後のピークを避けるだけで体験が大きく変わります。ソウルに滞在する場合でも、休業する店や短縮営業の施設があるので、食事と文化行事の候補をそれぞれ二つ用意しておくと安心です。</p>
  <h3>宿泊と食事の現実的な選び方</h3>
  <p>宿は安さより交通の戻りやすさを優先してください。駅から遠い宿を選ぶと、名節期間のタクシー不足やバス本数の変化で動きにくくなります。特に家族旅行では、駅近くで休憩しやすい宿の方が結果的に楽です。</p>
  <p>食事は有名店だけに頼らず、ホテル周辺、駅周辺、営業中のチェーン店も候補に入れてください。ソルラルは休みの店が増えるため、食べたい料理より営業している確実性が重要になる日があります。</p>
  <p>文化行事を入れる場合も、午前に一つ、午後に一つ以上は増やさないほうが安定します。名節期間は移動そのものが読みにくいため、博物館、宮殿、伝統公演のような候補を近い範囲で組み、遠いエリアをまたぐ計画は避けると失敗が減ります。</p>
</section>
""",
    },
    {
        "url": "https://donggri-kankoku.blogspot.com/2026/04/2026_0107528024.html",
        "post_id": "4086555829707430202",
        "title": "2026年鎮海軍港祭: 混雑回避と屋台ごはんの動きを整える実用ガイド",
        "labels": ["Changwon Travel", "Cherry blossom Korea", "Jinhae Gunhangje", "Korea Festival Guide", "Korea Food Stalls", "Spring Travel Korea", "Travel", "旅行・お祭り"],
        "block": """
<section class="bloggent-quality-addition">
  <h2>鎮海軍港祭で混雑を味方にする動き方</h2>
  <h3>桜を見る順番を先に決める</h3>
  <p>鎮海軍港祭は、街全体が桜の会場になるため、到着してから行き先を決めると移動に時間を使います。駅周辺、余佐川、慶和駅のような定番を全部回るより、午前に一つ、午後に一つと決める方が現実的です。</p>
  <p>写真を優先するなら早い時間、屋台や祭りの雰囲気を楽しむなら昼以降が向いています。ただし昼以降は歩道が詰まりやすいので、写真を撮る場所と食べる場所を同じ通りに集中させないことが大切です。</p>
  <h3>屋台ごはんと移動の切り替え</h3>
  <p>屋台は見つけた順に食べるとすぐ満腹になり、後半の移動が重くなります。最初は軽いもの、昼に主食、最後に飲み物や甘いものという順番にすると歩きやすくなります。列が長い店は、味だけでなく回転の速さも見て判断してください。</p>
  <p>帰りは多くの人が同じ駅へ向かいます。終了間際まで中心部に残るより、少し早めに駅方向へ戻るか、混雑が引くまで近くで休むかを選ぶと疲れが減ります。</p>
  <h3>写真時間を短く区切る</h3>
  <p>鎮海では、桜の密度が高い場所ほど人も集まります。良い場所を見つけたら長く粘るのではなく、広い写真、近い花、同行者の写真の三つだけ撮って次へ進むと流れが止まりません。人が多い時は、真正面より少し横から撮る方が背景が整理されます。</p>
  <p>小さな子どもや年配の同行者がいる場合は、撮影場所を増やすより休憩点を増やしてください。祭りの日は歩道が混み、短い距離でも疲れます。座れる場所、飲み物を買える場所、帰り方向へ戻れる道を早めに確認しておくと安心です。</p>
  <p>屋台ごはんを楽しむなら、手が汚れにくいもの、歩きながら食べやすいもの、座って食べたいものを分けて選ぶと楽です。混雑した通りで熱い料理を持ち歩くと危ないので、食べる場所を見つけてから買う判断も大切です。</p>
</section>
""",
    },
    {
        "url": "https://donggri-kankoku.blogspot.com/2026/04/2026_01138857906.html",
        "post_id": "6908529600051031704",
        "title": "城北洞さくら通り祭り2026: 地元の空気を味わう夕方散歩ガイド",
        "labels": ["Cherry Blossom Festival", "Evening blossom viewing", "Korea Local Events", "Seongbuk-dong", "Seongbuk-gu Guide", "Seoul spring travel", "Travel", "旅行・お祭り"],
        "block": """
<section class="bloggent-quality-addition">
  <h2>城北洞を夕方に歩く時の追加メモ</h2>
  <h3>大きな祭りではなく近所の春として見る</h3>
  <p>城北洞の桜は、派手な演出を期待するより、住宅街と坂道の間に残る春の空気を味わう方が合っています。夕方は光がやわらかく、カフェの明かりや路地の静けさも加わるため、短い散歩でも印象が残ります。</p>
  <p>ただし坂道があるため、歩く範囲を広げすぎると帰りが重くなります。最初にバス停や駅方向を確認し、桜を見る区間、カフェで休む区間、帰る区間を分けておくと無理がありません。</p>
  <h3>カフェを入れるタイミング</h3>
  <p>カフェは最後に探すより、歩き始める前に候補を一つ決めておくと安心です。夕方の人気店は席が埋まりやすいので、入れなければ別の通りへ切り替える判断も必要です。桜を見ながら歩く日ほど、休憩を予定の一部として扱うべきです。</p>
  <p>写真を撮るなら、桜だけを大きく写すより、坂道、門、カフェの外観を少し入れると城北洞らしさが出ます。暗くなる前に帰る方向へ戻ることも忘れないでください。</p>
</section>
""",
    },
    {
        "url": "https://donggri-kankoku.blogspot.com/2026/04/2026_01176259820.html",
        "post_id": "2244734083864501463",
        "title": "2026年春のソウル歴史博物館で初回訪問者が優先して見るべきもの",
        "labels": ["Travel", "ソウルの春", "ソウル旅行", "ソウル歴史博物館", "初めての韓国旅行", "旅行・お祭り", "韓国の博物館", "韓国文化ガイド"],
        "block": """
<section class="bloggent-quality-addition">
  <h2>初回訪問者が展示で迷わないための見方</h2>
  <h3>全部を見るより流れをつかむ</h3>
  <p>ソウル歴史博物館では、展示を細かく全部読むより、ソウルという都市がどう広がってきたかを大きくつかむ方が初回訪問には向いています。古い地図、街の模型、生活道具のように、視覚的に分かる展示を先に見ると理解しやすくなります。</p>
  <p>春の旅行で入れるなら、屋外を歩く時間と博物館で休む時間を組み合わせるのが便利です。景福宮や光化門周辺を歩いた後に入ると、街で見た景色と展示の内容がつながりやすくなります。</p>
  <h3>周辺文化コースとの組み合わせ</h3>
  <p>博物館だけで一日を使うより、周辺の宮殿、広場、カフェを一つだけ足すと旅程が整います。展示を見た後にすぐ遠くへ移動するより、近くで少し休み、見た内容を整理する時間を作ると記憶に残ります。</p>
  <p>雨の日や寒い日にも使いやすい場所ですが、入館前に閉館時間と特別展示の有無を確認してください。初めてなら、常設展示を中心にして、特別展示は時間に余裕がある時だけ足すのが安全です。</p>
</section>
""",
    },
]


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
    counter: Counter[str] = Counter()
    original: dict[str, str] = {}
    for sentence in SENTENCE_SPLIT_RE.split(_plain_text(value)):
        sentence = SPACE_RE.sub(" ", sentence).strip()
        if len(sentence) < 24:
            continue
        key = sentence.casefold()
        counter[key] += 1
        original.setdefault(key, sentence)
    return [{"count": count, "sentence": original[key]} for key, count in counter.items() if count >= 3]


def _fetch_content(post: dict[str, Any]) -> str:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for start in (1, 101):
            response = client.get(
                "https://donggri-kankoku.blogspot.com/feeds/posts/default",
                params={"alt": "json", "start-index": start, "max-results": 100},
            )
            response.raise_for_status()
            for entry in response.json().get("feed", {}).get("entry", []) or []:
                href = next((str(link.get("href") or "") for link in entry.get("link") or [] if link.get("rel") == "alternate"), "")
                if href == post["url"]:
                    return str((entry.get("content") or {}).get("$t") or "")
    raise RuntimeError(f"Target post not found: {post['url']}")


def _remove_detected_repeated_sentences(content: str) -> str:
    updated = content
    for issue in _repeat_issues(updated):
        sentence = str(issue.get("sentence") or "").strip()
        first = updated.find(sentence)
        if not sentence or first < 0:
            continue
        cursor = first + len(sentence)
        while True:
            nxt = updated.find(sentence, cursor)
            if nxt < 0:
                break
            updated = updated[:nxt] + updated[nxt + len(sentence):]
            cursor = nxt
    return updated


def _insert_block(content: str, block: str) -> str:
    soup = BeautifulSoup(content, "html.parser")
    for existing in soup.select(".bloggent-quality-addition"):
        existing.decompose()
    content = str(soup)
    markers = [
        "<section class=\"bloggent-language-switch\"",
        "<section class=\"article-language-switch\"",
        "<section class=\"bloggent-related-posts\"",
        "<div class=\"article-footer\"",
        "<section class=\"related-posts\"",
    ]
    positions = [content.find(marker) for marker in markers if content.find(marker) >= 0]
    if positions:
        idx = min(positions)
        return content[:idx].rstrip() + "\n" + block.strip() + "\n" + content[idx:].lstrip()
    soup = BeautifulSoup(content, "html.parser")
    target = soup.select_one(".bloggent-travel-body") or soup.select_one("section") or soup
    target.append(BeautifulSoup(block, "html.parser"))
    return str(soup)


def _validate(content: str) -> dict[str, Any]:
    soup = BeautifulSoup(content, "html.parser")
    r2_urls = R2_RE.findall(content)
    repeats = _repeat_issues(content)
    row = {
        "h1_count": len(soup.find_all("h1")),
        "h2_count": len(soup.find_all("h2")),
        "h3_count": len(soup.find_all("h3")),
        "table_count": len(soup.find_all("table")),
        "li_count": len(soup.find_all("li")),
        "image_count": len(soup.find_all("img")),
        "r2_unique_image_count": len(set(r2_urls)),
        "body_non_space_chars": _non_space_len(content),
        "repeat_3plus_count": len(repeats),
        "repeat_issues": repeats,
        "forbidden_visible_terms": bool(FORBIDDEN_RE.search(_plain_text(content))),
    }
    row["status"] = "ok" if row["h1_count"] == 1 and row["image_count"] == 4 and row["r2_unique_image_count"] == 4 and row["body_non_space_chars"] >= 3400 and not repeats and not row["forbidden_visible_terms"] else "failed"
    return row


def _access_token() -> str:
    if str(API_ROOT) not in sys.path:
        sys.path.insert(0, str(API_ROOT))
    os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL") or DATABASE_URL
    from app.db.session import SessionLocal  # noqa: PLC0415
    from app.services.blogger.blogger_oauth_service import get_valid_blogger_access_token  # noqa: PLC0415
    with SessionLocal() as db:
        return str(get_valid_blogger_access_token(db)).strip()


def _update_db(post: dict[str, Any], content: str) -> None:
    if str(API_ROOT) not in sys.path:
        sys.path.insert(0, str(API_ROOT))
    os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL") or DATABASE_URL
    from app.db.session import SessionLocal  # noqa: PLC0415
    with SessionLocal() as db:
        db.execute(text("""
            update synced_blogger_posts
               set title=:title, labels=cast(:labels as jsonb), content_html=:content_html,
                   excerpt_text=:excerpt_text, updated_at_remote=now(), synced_at=now()
             where blog_id=37 and remote_post_id=:remote_post_id
        """), {
            "title": post["title"],
            "labels": json.dumps(post["labels"], ensure_ascii=False),
            "content_html": content,
            "excerpt_text": _plain_text(content)[:480],
            "remote_post_id": post["post_id"],
        })
        db.commit()


def main() -> int:
    _stdout_utf8()
    _load_env()
    token = _access_token()
    rows = []
    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        for post in POSTS:
            current = _fetch_content(post)
            updated = _remove_detected_repeated_sentences(_insert_block(current, post["block"]))
            before = _validate(current)
            planned = _validate(updated)
            if planned["status"] != "ok":
                raise RuntimeError(f"Planned validation failed for {post['url']}: {planned}")
            response = client.patch(
                f"https://www.googleapis.com/blogger/v3/blogs/{BLOG_ID}/posts/{post['post_id']}",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"title": post["title"], "content": updated, "labels": post["labels"]},
            )
            if response.status_code >= 400:
                raise RuntimeError(f"Blogger update failed for {post['url']}: {response.status_code} {response.text[:500]}")
            live = client.get(post["url"])
            live.raise_for_status()
            article = BeautifulSoup(live.text, "html.parser").select_one(".article-content")
            live_validation = _validate(str(article or live.text))
            if live_validation["status"] != "ok":
                raise RuntimeError(f"Live validation failed for {post['url']}: {live_validation}")
            _update_db(post, updated)
            rows.append({"url": post["url"], "title": post["title"], "before": before, "planned": planned, "live_validation": live_validation})
    report = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "rows": rows}
    path = REPORT_ROOT / f"travel-ja-under3000-batch02-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report_path": str(path), "rows": [{"url": r["url"], "after": r["live_validation"]} for r in rows]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
