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
        "url": "https://donggri-kankoku.blogspot.com/2026/04/1.html",
        "post_id": "7450156347681773408",
        "title": "ソウル屋台グルメ市場めぐり：広蔵・通仁・望遠を1日で楽しむ実用ルート",
        "labels": ["Food", "グルメ・カフェ", "ソウルグルメ", "広蔵市場", "旅行・お祭り", "望遠市場", "通仁市場", "韓国屋台"],
        "block": """
<section class="bloggent-quality-addition">
  <h2>市場を三つ回る日の判断メモ</h2>
  <h3>食べる順番を決めてから移動する</h3>
  <p>広蔵市場、通仁市場、望遠市場を同じ日に入れるなら、最初に決めるべきなのは店名ではなく食べる量です。広蔵市場でしっかり食べる日なら、通仁市場は軽い買い食いにして、望遠市場では持ち帰りや飲み物を中心にすると胃も時間も無理がありません。</p>
  <p>市場巡りで失敗しやすいのは、到着するたびに名物を全部試そうとすることです。行列に並ぶ料理、立って食べる料理、座って休む料理を分けると、食べ疲れを防げます。同行者がいる場合は、一人一品ずつではなく分けて食べる前提にすると、最後まで楽しく回れます。</p>
  <h3>支払いと席の探し方</h3>
  <p>韓国の市場ではカードが使える店も増えていますが、小さな屋台では現金があると安心です。席が少ない店では、注文前に座れる場所を確認してください。混雑している時間は、食べる場所を探すだけで体力を使うので、ピークを少し外す判断が大切です。</p>
  <p>望遠市場まで行く日は、帰りの駅方向も先に見ておくと移動が楽になります。食後にカフェへ逃がす、川沿いではなく大通りへ戻る、荷物が増えたらタクシー候補を使うなど、最後の一手を決めておくと一日全体が崩れません。</p>
  <h3>三市場を一日に入れる時の切り替え</h3>
  <p>広蔵市場では観光客向けの活気、通仁市場では軽い食べ歩き、望遠市場では生活感を味わうと役割が分かれます。同じような屋台を続けて選ぶより、温かい料理、軽い甘味、飲み物のように種類を変えると食べ疲れしにくくなります。</p>
  <p>時間が押した場合は、望遠市場を短くするより、通仁市場の滞在を軽くするほうが流れを保ちやすいです。望遠は駅から歩く距離と帰りの判断があるため、最後に余裕を残しておくと満足度が安定します。</p>
  <p>また、市場を移動する日は飲み物の選び方も重要です。甘い飲み物を続けると食事が重く感じられるため、途中で水や温かいお茶を挟むと最後まで歩きやすくなります。買い物をするなら、汁気のある食品を早い時間に買わず、帰る直前に選ぶほうが安全です。</p>
  <p>初めての人は、広蔵で活気を見て、通仁で軽く試し、望遠で地元の買い物風景を見るという流れにすると違いが分かりやすくなります。同じ市場でも、観光、軽食、生活感という役割を分ければ、単なる食べ歩きではなくソウルの一日として記憶に残ります。</p>
  <p>最後に、屋台市場の日は匂い、音、人の流れが強いので、途中で静かな場所へ抜ける時間も必要です。食べる量だけでなく休む場所まで考えておくと、初めての市場でも焦らず楽しめます。</p>
</section>
""",
    },
    {
        "url": "https://donggri-kankoku.blogspot.com/2026/04/2025_01397035302.html",
        "post_id": "7782519899871247228",
        "title": "2025年春川タッカルビ祭り回顧：交通・グルメ・初訪問の実用ポイント",
        "labels": ["Chuncheon", "Cultural Events", "Dakgalbi Festival", "Korea Travel", "Local Food", "Transport Tips", "Travel", "旅行・お祭り"],
        "block": """
<section class="bloggent-quality-addition">
  <h2>春川タッカルビ祭りを次回に活かす見方</h2>
  <h3>交通は料理より先に決める</h3>
  <p>春川のタッカルビ祭りは、食べる内容だけでなく移動の組み方で満足度が変わります。ソウルから向かう場合、行きは勢いで動けても、帰りの列車やバスが読めないと最後に疲れが残ります。祭り会場へ入る前に、帰る時間帯と駅までの戻り方を決めておくべきです。</p>
  <p>タッカルビは焼き時間がある料理なので、混雑時は席に着いてからも時間がかかります。短い滞在なら、人気店にこだわるより回転が早い店を選ぶ判断も現実的です。地元感を味わいたい日は、会場中心から少し外れた店を候補に入れると落ち着いて食べられます。</p>
  <h3>初訪問者が見落としやすい点</h3>
  <p>祭りの雰囲気を楽しむなら、昼の食事だけで帰るより、周辺を少し歩く時間を残すと印象が深くなります。ただし湖やカフェまで欲張ると移動が増えるので、食事を主役にする日と観光を足す日は分けて考えてください。</p>
  <h3>回顧記事として見るべきポイント</h3>
  <p>2025年の様子を参考にする時は、開催場所や日程が翌年も同じとは限らない点に注意が必要です。参考にすべきなのは、混雑が強くなる時間帯、食事にかかる待ち時間、駅から会場までの体感距離です。これらは年度が変わっても旅程づくりに使えます。</p>
  <p>初訪問なら、会場で食べる一食を主役にし、追加の食べ歩きは一つまでに絞ると楽です。春川はタッカルビ以外にもカフェや散歩場所がありますが、全部を入れるより、帰りの交通に余裕を残す方が失敗しにくくなります。</p>
  <p>春川まで移動する日は、到着してすぐ食べるか、先に会場を軽く見るかで印象が変わります。空腹で長く歩くと判断が雑になりやすいので、混雑が強い時間なら軽い間食を先に入れるのも有効です。食事を急がないだけで、祭りの雰囲気を落ち着いて見られます。</p>
  <p>次回の旅行計画に活かすなら、店の名前だけでなく、駅からの距離、席の回転、会場周辺の歩きやすさを記録しておくと便利です。春川は日帰りでも行けますが、食事と移動が重なるため、余白を持たせた予定のほうが満足しやすくなります。</p>
</section>
""",
    },
    {
        "url": "https://donggri-kankoku.blogspot.com/2026/04/2025_0240658009.html",
        "post_id": "4698953971936580677",
        "title": "2025年光州世界キムチ祭りの旅行メモ：食事、交通、予約の実用ガイド",
        "labels": ["Culture", "KTX", "ライフスタイル", "光州世界キムチ祭り", "光州旅行", "旅行のコツ", "韓国グルメ", "韓国文化"],
        "block": """
<section class="bloggent-quality-addition">
  <h2>光州キムチ祭りで現地判断を楽にする方法</h2>
  <h3>試食と食事を同じ扱いにしない</h3>
  <p>キムチ祭りでは、試食、販売、体験、食事が同じ場所に集まりやすいため、何を目的にするかを決めずに歩くと疲れます。最初に展示や体験を見て、次に試食、最後に食事や買い物へ移る流れにすると、荷物も胃の負担も増えにくくなります。</p>
  <p>遠方から光州へ行く場合は、祭り会場に長くいることより、帰りのKTXやバスに遅れないことを優先してください。食べ物のイベントは予定より滞在が伸びやすいので、購入や体験は終了時間から逆算して決める必要があります。</p>
  <h3>文化イベントとして見る視点</h3>
  <p>光州のキムチ祭りは単なるグルメイベントではなく、地域の食文化をまとめて見る機会です。味の違い、発酵の説明、家庭ごとの食べ方を少し意識すると、短い滞在でも記憶に残ります。写真だけで終わらせず、気になった味や食材名をメモしておくと次の韓国旅行にもつながります。</p>
  <h3>予約と購入で迷わないために</h3>
  <p>体験プログラムがある場合は、現地で空きを探すより事前確認を優先してください。食文化イベントでは、開始直後に人が集まり、午後には人気枠が埋まることがあります。体験を主役にする日は、食事や買い物を後ろへ回すと判断が楽になります。</p>
  <p>キムチを購入するなら、持ち歩く時間と宿泊先の冷蔵環境も考える必要があります。旅行中に長く持ち歩くより、少量を選ぶ、配送可否を確認する、帰る直前に買うなど、実際の移動に合わせて決めると失敗が減ります。</p>
  <p>光州まで足を延ばす価値は、食べることだけでなく、地域ごとの味の違いを知れる点にあります。辛さ、酸味、塩気、発酵の進み方を比べると、普段の韓国料理の見え方も変わります。短時間でも、気に入った味を一つ覚えて帰るだけで十分です。</p>
  <p>会場の外へ出る時間があるなら、周辺の文化施設やカフェを一つだけ足すと旅の密度が上がります。ただし欲張って遠くへ移動すると帰りが慌ただしくなるため、祭り会場から戻りやすい範囲に絞るのが現実的です。</p>
</section>
""",
    },
    {
        "url": "https://donggri-kankoku.blogspot.com/2026/04/20263.html",
        "post_id": "2733161100500218882",
        "title": "延南洞を歩く2026年ガイド：弘大入口3番出口からカフェと路地をめぐる実用ルート",
        "labels": ["Travel", "ソウルカフェ", "延南洞", "弘大", "徒歩ルート", "旅行・お祭り", "韓国ローカル"],
        "block": """
<section class="bloggent-quality-addition">
  <h2>延南洞で歩き疲れないための追加判断</h2>
  <h3>路地に入る前に戻る基準を作る</h3>
  <p>延南洞は小さな店が多く、気になる方向へ進むほど現在地が分かりにくくなります。弘大入口3番出口を基準にして、どの通りまで進んだら戻るかを決めておくと、カフェ探しが長引いても不安が減ります。</p>
  <p>カフェを目的にするなら、最初の一軒を写真で選び、二軒目は席の空きや静けさで選ぶとバランスが取れます。歩きながら全部を比較しようとすると、結局どこにも入りにくくなるので、候補を三つまでに絞るのが現実的です。</p>
  <h3>写真と休憩を分ける歩き方</h3>
  <p>延南洞では、写真を撮りたい路地と実際に休むカフェが同じとは限りません。外観が良い店は混みやすく、静かに座れる店は通りから少し外れていることがあります。写真を先に短く済ませ、休憩は席の落ち着きで選ぶと歩き疲れを防げます。</p>
  <p>弘大方面へ戻るか、延南洞の奥へ進むかは、同行者の体力で決めてください。地図上では近く見えても、細い道を何度も曲がると距離以上に疲れます。最後に駅へ戻る道を一度確認してから、二軒目のカフェや雑貨店を足すのが安全です。</p>
</section>
""",
    },
    {
        "url": "https://donggri-kankoku.blogspot.com/2026/04/20264-4.html",
        "post_id": "7309113819525207336",
        "title": "2026年4月下旬のソウルの森ガイド: 4番出口のチューリップから聖水コーヒー、川辺の締めまで",
        "labels": ["Travel", "ソウル", "ソウルの森", "旅行・お祭り", "漢江", "聖水", "韓国の春"],
        "block": """
<section class="bloggent-quality-addition">
  <h2>4番出口ルートをきれいに終えるための補足</h2>
  <h3>チューリップ、聖水、川辺の役割を分ける</h3>
  <p>このルートでは、ソウルの森を長く歩きすぎると聖水の休憩が短くなり、聖水で店を増やしすぎると川辺へ出る時間がなくなります。チューリップは季節の主役、聖水は休憩、川辺は締めの景色と役割を分けると、半日の流れが整います。</p>
  <p>4月下旬は日中と夕方で体感が変わります。昼は公園の明るさを楽しみ、夕方はコーヒーや軽食で一度座り、最後に水辺へ向かうと無理がありません。写真を優先する日でも、帰りの駅方向を見失わないようにしてください。</p>
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


def _insert_block(content: str, block: str) -> str:
    soup_for_cleanup = BeautifulSoup(content, "html.parser")
    for existing in soup_for_cleanup.select(".bloggent-quality-addition"):
        existing.decompose()
    content = str(soup_for_cleanup)
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
    body = soup.select_one(".bloggent-travel-body") or soup.select_one("section") or soup
    body.append(BeautifulSoup(block, "html.parser"))
    return str(soup)


def _remove_known_repeated_fragments(content: str) -> str:
    repeated_fragments = [
        "予算、地下鉄、時間帯、食べ歩きの注意点を日本語で整理します。",
    ]
    updated = content
    for fragment in repeated_fragments:
        first = updated.find(fragment)
        if first < 0:
            continue
        cursor = first + len(fragment)
        while True:
            nxt = updated.find(fragment, cursor)
            if nxt < 0:
                break
            updated = updated[:nxt] + updated[nxt + len(fragment):]
            cursor = nxt
    return updated


def _remove_detected_repeated_sentences(content: str) -> str:
    updated = content
    for issue in _repeat_issues(updated):
        sentence = str(issue.get("sentence") or "").strip()
        if not sentence:
            continue
        first = updated.find(sentence)
        if first < 0:
            continue
        cursor = first + len(sentence)
        while True:
            nxt = updated.find(sentence, cursor)
            if nxt < 0:
                break
            updated = updated[:nxt] + updated[nxt + len(sentence):]
            cursor = nxt
    return updated


def _validate(content: str) -> dict[str, Any]:
    soup = BeautifulSoup(content, "html.parser")
    r2 = R2_RE.findall(content)
    repeats = _repeat_issues(content)
    row = {
        "h1_count": len(soup.find_all("h1")),
        "h2_count": len(soup.find_all("h2")),
        "h3_count": len(soup.find_all("h3")),
        "table_count": len(soup.find_all("table")),
        "li_count": len(soup.find_all("li")),
        "image_count": len(soup.find_all("img")),
        "r2_unique_image_count": len(set(r2)),
        "body_non_space_chars": _non_space_len(content),
        "repeat_3plus_count": len(repeats),
        "repeat_issues": repeats,
        "forbidden_visible_terms": bool(FORBIDDEN_RE.search(_plain_text(content))),
    }
    row["status"] = "ok" if row["h1_count"] == 1 and row["image_count"] == 4 and row["r2_unique_image_count"] == 4 and row["body_non_space_chars"] >= 3000 and not repeats and not row["forbidden_visible_terms"] else "failed"
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
            updated = _remove_detected_repeated_sentences(_remove_known_repeated_fragments(_insert_block(current, post["block"])))
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
    path = REPORT_ROOT / f"travel-ja-under3000-batch01-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report_path": str(path), "rows": [{"url": r["url"], "before_chars": r["before"]["body_non_space_chars"], "after": r["live_validation"]} for r in rows]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
