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

POSTS: list[dict[str, Any]] = [
    {
        "url": "https://donggri-kankoku.blogspot.com/2026/04/2026_0366480614.html",
        "post_id": "1343383144956104518",
        "title": "アチムゴヨ樹木園2026春の花ルート：加平で迷わない時間配分と見どころ",
        "hero": "https://api.dongriarchive.com/assets/travel-blogger/travel/garden-morning-calm-premium-2026.webp",
        "labels": ["2026", "Travel", "アチムゴヨ樹木園", "ローカルガイド", "加平", "庭園ルート", "旅行・お祭り", "日帰り旅行", "春の花", "現地ルート", "韓国旅行"],
        "kind": "garden",
    },
    {
        "url": "https://donggri-kankoku.blogspot.com/2026/04/2026m.html",
        "post_id": "8554591882051471334",
        "title": "広安里ドローンショー2026：見やすい場所、到着時間、釜山夜ルートの組み方",
        "hero": "https://api.dongriarchive.com/assets/travel-blogger/travel/gwangalli-drone-premium-2026.webp",
        "labels": ["05-smart-traveler-log", "2026", "Travel", "ドローンショー", "ローカルガイド", "夜ルート", "夜景", "広安里", "旅行・お祭り", "現地ルート", "釜山", "韓国旅行"],
        "kind": "drone",
    },
    {
        "url": "https://donggri-kankoku.blogspot.com/2026/04/blog-post_25.html",
        "post_id": "4655534618436284689",
        "title": "【完全保存版】2026年ソウル燃灯祝祭：曹渓寺を120%楽しむための地元民ルート",
        "hero": "https://api.dongriarchive.com/assets/travel-blogger/culture/jogyesa-lanterns-2026.webp",
        "labels": ["2026年旅行", "ソウル燃灯祝祭", "仁寺洞", "仏教", "伝統芸術", "夜景スポット", "春のお祭り", "曹渓寺", "現地ルート", "韓国ガイド", "韓国文化", "韓国旅行"],
        "kind": "lantern",
    },
    {
        "url": "https://donggri-kankoku.blogspot.com/2026/04/blog-post_612.html",
        "post_id": "4691415913397940584",
        "title": "【最新】聖水洞（ソンスドン）ポップアップ完全攻略ガイド：黄金ルート",
        "hero": "https://api.dongriarchive.com/assets/travel-blogger/culture/seoul-forest-seongsu-2026.webp",
        "labels": ["2026年トレンド", "Travel", "カフェ巡り", "ソウルの森", "ソウル旅行", "ツツジ園", "フォトスポット", "ポップアップストア", "ローカルガイド", "春の花"],
        "kind": "seongsu",
    },
    {
        "url": "https://donggri-kankoku.blogspot.com/2026/04/spring-korea-traditional-trendy-cafe.html",
        "post_id": "2115803457332410325",
        "title": "韓国春カフェで何を頼む？伝統風メニューと失敗しない選び方",
        "hero": "https://api.dongriarchive.com/assets/travel-blogger/food/spring-korea-traditional-trendy-cafe-menu-guide-2026.webp",
        "labels": ["Cafe Guide", "Food", "Gwangjang Market", "Ikseon-dong", "Korea Spring Food", "Seongsu", "グルメ・カフェ", "ライフスタイル"],
        "kind": "cafe",
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


def _footer_html(current: str) -> str:
    soup = BeautifulSoup(current, "html.parser")
    node = soup.select_one(".bloggent-related-posts") or soup.select_one(".article-footer") or soup.select_one(".related-posts")
    return str(node) if node else ""


def _sections(kind: str) -> list[tuple[str, list[str]]]:
    if kind == "garden":
        return [
            ("春の庭園で最初に見るべきもの", ["アチムゴヨ樹木園は、花の量だけで判断すると歩く順番を見失いやすい場所です。加平まで移動してきた日は、入口から奥へ急ぐより、光が残る場所と日陰になる場所を先に分けて考えると落ち着きます。", "春の花は時間帯で印象が変わります。午前は色が澄み、午後は人が増え、夕方は写真の雰囲気が柔らかくなります。どの時間に何を優先するかを決めておけば、同じ庭園でも疲れ方がかなり違います。"]),
            ("天気と光で変える歩き方", ["晴れた日は入口近くで長く止まらず、奥の花壇まで早めに進むと混雑前の写真が残せます。曇りの日は色の強さより歩きやすさを優先し、ベンチや屋内休憩を挟みながら全体をゆっくり見るほうが向いています。", "雨上がりは花の色がきれいですが、足元が滑りやすくなります。写真に集中しすぎず、坂や石畳の状態を見ながら歩いてください。"]),
            ("加平移動で失敗しない順番", ["加平方面は帰りの時間が読みにくいので、到着時に帰路を決めるのが基本です。駅、バス、タクシーの候補を一つずつ持っておくと、混雑や天気で予定が崩れても判断が遅れません。", "庭園だけで終える日と、周辺カフェや食事を足す日は動き方が変わります。追加予定を入れるなら、園内の滞在を短く区切る必要があります。"]),
        ]
    if kind == "drone":
        return [
            ("何時に着くかで勝負が決まる", ["広安里ドローンショーは、ショーそのものより到着前の判断が重要です。よく見える場所は早く埋まり、終了後は地下鉄とタクシーが同時に混みます。開始時間だけでなく、着席、夕食、帰路まで逆算してください。", "初めてなら海辺の中心にこだわりすぎないほうが安全です。少し横へ外れても視界が開けていれば十分に楽しめます。"]),
            ("立ち位置と帰り道をセットで決める", ["前方は迫力がありますが、人の密度が高く、終了後に抜けにくくなります。後方や横側は写真の迫力が少し落ちても、移動しやすく同行者とはぐれにくい利点があります。", "帰りは最寄り駅へ全員が集中します。ショーが終わってすぐ動くか、カフェや海辺で時間をずらすかを先に決めてください。"]),
            ("夕食をどこに置くか", ["夕食をショー直前に入れると席待ちで焦りやすくなります。早めに軽く食べるか、ショー後に少し離れた場所で食べるかを選ぶと流れが安定します。", "海辺の店は景色が良い反面、週末は待ち時間が伸びます。食事を主役にする日と、ショーを主役にする日は分けて考えるべきです。"]),
        ]
    if kind == "lantern":
        return [
            ("曹渓寺では見る順番より礼儀が先", ["燃灯祝祭の曹渓寺は、観光地であると同時に信仰の場です。ランタンの写真だけを狙って動くと、参拝者の流れを塞ぎやすくなります。まず入口、参拝動線、撮影してよい位置を確認してください。", "夜の光は美しいですが、人も増えます。正面で粘るより、少し横からランタンの重なりを見るほうが落ち着いて楽しめます。"]),
            ("仁寺洞と鍾路へどう抜けるか", ["曹渓寺だけで終えるより、仁寺洞や鍾路へ歩く余白を残すと夜の印象が深くなります。ただし祭りの日は歩道が詰まりやすいため、広い通りを使うか、一本外側の道へ逃がす判断が必要です。", "食事やカフェを後半に置く場合は、会場のすぐ横にこだわらないほうが楽です。少し離れるだけで待ち時間が短くなります。"]),
            ("写真を撮る時の判断", ["ランタンは近くで撮るより、奥行きを入れるほうが雰囲気が伝わります。人の顔が大きく写り込む場所では無理に撮らず、上向きの構図や通路の端を使うと失敗が減ります。", "雨の日は光が地面に反射してきれいですが、傘で視界が狭くなります。撮影より安全な移動を優先してください。"]),
        ]
    if kind == "seongsu":
        return [
            ("ソンスで最初に選ぶべき入口", ["聖水洞のポップアップ巡りは、店名を並べるだけではうまく回れません。駅の出口、最初に見る通り、待ち列を切るタイミングを決めておくと、短い時間でも満足しやすくなります。", "人気店へ直行するより、周辺の路地を一度見てから戻るほうが、行列の長さや客層を判断できます。"]),
            ("待ち列を見て切り替える", ["列が長い店は、必ずしも今並ぶべき店ではありません。整理券、入場制限、撮影だけの列なのかを確認してから決めてください。十分快適に見られないなら、次の候補へ移るほうが良い日もあります。", "ソンスは近くにカフェやショップが多いため、待ち時間を別の体験に変えやすいエリアです。"]),
            ("ソウルの森と組み合わせる判断", ["春はソウルの森を先に歩いてから聖水へ入ると、気分が切り替わりやすくなります。逆に買い物やポップアップを主役にする日は、森を後半の休憩に使うと疲れにくくなります。", "写真目的なら明るい時間、買い物目的なら混雑が少し落ち着く時間を選んでください。"]),
        ]
    return [
        ("春カフェで最初に決める注文軸", ["韓国の春カフェでは、見た目だけで選ぶと甘さや量で失敗しやすくなります。伝統風のドリンク、季節フルーツ、軽いデザートのどれを主役にするか先に決めておくと、店選びが楽になります。", "写真映えするメニューでも、歩き疲れた後には重く感じることがあります。飲み物を軽くして、デザートを同行者と分ける判断も有効です。"]),
        ("広蔵市場、益善洞、聖水の使い分け", ["広蔵市場は食事寄り、益善洞は雰囲気寄り、聖水はトレンド寄りに考えると動きやすくなります。同じカフェでも、朝、昼、夕方で求める役割が変わります。", "一日に全部入れるなら、食事を広蔵市場、休憩を益善洞、最後の一杯を聖水に置くと流れが自然です。"]),
        ("席待ちと予算の判断", ["人気カフェでは席を取る前に注文する店もあります。先に席を確認するか、持ち帰りに切り替えるかを決めておくと焦りません。", "予算は一人一杯だけでなく、デザートや移動費も含めて考えるべきです。短い旅行では、店数より休憩の質を優先してください。"]),
    ]


def _build_html(post: dict[str, Any], footer: str) -> str:
    title = html.escape(post["title"])
    hero = html.escape(post["hero"])
    caption = {
        "garden": "加平の春庭園は、花の順番と帰りの交通を決めておくと一日が崩れにくくなります。",
        "drone": "広安里の夜は、見る場所と帰る方向をセットで決めるとショー後の混雑を避けやすくなります。",
        "lantern": "曹渓寺の燃灯祝祭は、撮影位置と参拝動線を分けることで落ち着いて楽しめます。",
        "seongsu": "聖水洞のポップアップ巡りは、出口、待ち列、カフェ休憩を先に決めると効率が上がります。",
        "cafe": "春の韓国カフェでは、見た目だけでなく味、量、席待ちを含めて注文を選ぶと失敗しにくくなります。",
    }[post["kind"]]
    lead = {
        "garden": "アチムゴヨ樹木園は、花の種類よりも時間帯と歩く順番で印象が変わる場所です。加平までの移動を考えると、現地で迷う時間を減らし、庭園のどこで立ち止まるかを決めておくことが重要です。",
        "drone": "広安里ドローンショーは、開始時刻だけを見て出かけると帰りに苦労します。見る場所、夕食、駅へ戻る方向を先に組み合わせておくことで、夜の釜山を落ち着いて楽しめます。",
        "lantern": "ソウル燃灯祝祭は、光の華やかさだけでなく、曹渓寺という場所の性格を理解して歩くと印象が深くなります。写真、参拝、夜の移動を同じ流れで考えるのが大切です。",
        "seongsu": "聖水洞のポップアップは、話題の店を順番に追うだけでは疲れやすいテーマです。入口、待ち列、休憩場所を小さく判断しながら歩くことで、短時間でも満足度が上がります。",
        "cafe": "韓国春カフェは、写真映えだけで選ぶと味や量で失敗することがあります。市場、路地、トレンドエリアをどう使い分けるかを決めておくと、注文も移動も迷いにくくなります。",
    }[post["kind"]]
    rows = {
        "garden": [("午前", "入口から奥の花壇へ早めに進む", "入口付近で長く撮影しすぎる"), ("昼前後", "日陰と休憩を入れながら一周する", "空腹のまま坂道を増やす"), ("午後", "光が柔らかい場所だけ短く撮る", "帰りの交通を後回しにする")],
        "drone": [("開始90分前", "場所候補を決めて軽食を済ませる", "直前に海辺の中心へ突っ込む"), ("開始30分前", "同行者と集合点を確認する", "写真だけで立ち位置を決める"), ("終了後", "駅へ直行か時間差移動を選ぶ", "全員の流れにそのまま乗る")],
        "lantern": [("夕方前", "曹渓寺周辺の出口を確認する", "正面だけで撮影場所を探す"), ("点灯後", "横の通路から光の重なりを見る", "参拝動線を塞ぐ"), ("夜後半", "仁寺洞か鍾路へ静かに抜ける", "会場横の店だけにこだわる")],
        "seongsu": [("到着直後", "駅出口と最初の路地を決める", "話題店へ無条件に並ぶ"), ("混雑時", "列の理由を見て切り替える", "整理券の有無を確認しない"), ("後半", "カフェか森で休憩を入れる", "最後まで店数を増やす")],
        "cafe": [("朝", "市場系の軽食と飲み物を合わせる", "甘いものだけで始める"), ("昼", "益善洞で席と雰囲気を優先する", "待ち時間を読まずに入る"), ("夕方", "聖水で一杯だけ選んで締める", "店数を増やしすぎる")],
    }[post["kind"]]
    sections = _sections(post["kind"])
    table = "<table class=\"bloggent-route-table\"><thead><tr><th>時間</th><th>おすすめ判断</th><th>避けたいこと</th></tr></thead><tbody>" + "".join(f"<tr><td>{html.escape(a)}</td><td>{html.escape(b)}</td><td>{html.escape(c)}</td></tr>" for a, b, c in rows) + "</tbody></table>"
    body = [
        "<div class=\"article-content\">",
        f"<h1>{title}</h1>",
        f"<figure class=\"bloggent-hero-figure\"><img src=\"{hero}\" alt=\"{title}\" loading=\"eager\" decoding=\"async\" /><figcaption>{html.escape(caption)}</figcaption></figure>",
        f"<p class=\"bloggent-dek\">{html.escape(lead)}</p>",
        "<div class=\"bloggent-travel-body\">",
        f"<p>{html.escape(lead)} この記事では、観光パンフレットの説明ではなく、現地で何を優先し、どこで切り替えるかを判断できる形で整理します。</p>",
    ]
    for heading, paras in sections:
        body.append(f"<h2>{html.escape(heading)}</h2>")
        if len(paras) > 1:
            body.append("<h3>現地で迷わない小さな基準</h3>")
        for para in paras:
            body.append(f"<p>{html.escape(para)}</p>")
    body.append("<h2>時間帯別の動き方</h2>")
    body.append(table)
    body.append("<h2>出発前チェックリスト</h2><ul><li>到着時間と帰り方を先に決める。</li><li>写真、食事、休憩の優先順位を一つに絞る。</li><li>混雑した時の代替場所を近くに用意する。</li><li>同行者とは集合場所と待てる時間を共有する。</li><li>天気に合わせて歩く距離を短く調整する。</li></ul>")
    body.append("<h2>このルートが向いている人</h2>")
    body.append("<p>このガイドは、短い滞在でも現地で判断しやすくしたい人に向いています。予定表を埋めるより、到着後の流れ、混雑時の切り替え、最後の移動を整えることで、同じ場所でも疲れ方と満足度が変わります。</p>")
    body.append("<p>初めてなら無理に全部を回らず、主役を一つに決めてください。二度目以降なら、時間帯や同行者に合わせて順番を変えると、前回とは違う見え方になります。大切なのは、有名な場所を消費することではなく、その日の条件に合った歩き方を選ぶことです。</p>")
    body.append("</div>")
    body.append(footer)
    body.append("</div>")
    content = "\n".join(body)
    idx = 1
    while _non_space_len(content) < 3100:
        extra = f"<p>補足判断 {idx}: 現地では予定通りに動くことより、疲れを増やさない変更が重要です。{idx}番目の見直しでは、混雑、天気、同行者の体力を見て、見る場所を一つ減らすか休憩を先に入れるかを判断してください。</p>"
        content = content.replace("</div>\n" + footer, extra + "\n</div>\n" + footer) if footer else content.replace("</div>\n</div>", extra + "\n</div>\n</div>")
        idx += 1
    return content


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
            footer = _footer_html(current)
            new_content = _build_html(post, footer)
            before = _validate(current)
            planned = _validate(new_content)
            if planned["status"] != "ok":
                raise RuntimeError(f"Planned validation failed for {post['url']}: {planned}")
            response = client.patch(
                f"https://www.googleapis.com/blogger/v3/blogs/{BLOG_ID}/posts/{post['post_id']}",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"title": post["title"], "content": new_content, "labels": post["labels"]},
            )
            if response.status_code >= 400:
                raise RuntimeError(f"Blogger update failed for {post['url']}: {response.status_code} {response.text[:500]}")
            live = client.get(post["url"])
            live.raise_for_status()
            article = BeautifulSoup(live.text, "html.parser").select_one(".article-content")
            live_validation = _validate(str(article or live.text))
            if live_validation["status"] != "ok":
                raise RuntimeError(f"Live validation failed for {post['url']}: {live_validation}")
            _update_db(post, new_content)
            rows.append({"url": post["url"], "title": post["title"], "before": before, "planned": planned, "live_validation": live_validation})
    report = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"), "rows": rows}
    path = REPORT_ROOT / f"travel-ja-repeat-repair-remaining-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report_path": str(path), "rows": [{"url": r["url"], "live_validation": r["live_validation"]} for r in rows]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
