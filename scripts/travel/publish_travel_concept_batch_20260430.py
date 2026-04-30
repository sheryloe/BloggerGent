from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from PIL import Image as PILImage
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload


REPO_ROOT = Path(__file__).resolve().parents[2]
API_ROOT = REPO_ROOT / "apps" / "api"
RUNTIME_ENV_PATH = REPO_ROOT / "env" / "runtime.settings.env"
REPORT_ROOT = Path(r"D:\Donggri_Runtime\BloggerGent\storage\travel\reports")
DATABASE_URL = "postgresql://bloggent:bloggent@127.0.0.1:15432/bloggent"

BLOG_LANGS = {34: "en", 36: "es", 37: "ja"}
LANG_BLOGS = {"en": 34, "es": 36, "ja": 37}
PATTERN_VERSION = 1
PATTERN_VERSION_KEY = "travel-pattern-v1"
R2_RE = re.compile(r"https://api\.dongriarchive\.com/assets/travel-blogger/[^\"'<>\s)]+?\.webp", re.I)
SPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")
SENTENCE_RE = re.compile(r"(?<=[.!?。！？])\s+")
FORBIDDEN_RE = re.compile(
    r"\b(?:SEO|GEO|CTR|Lighthouse|PageSpeed|article_pattern|pattern_key|travel-0[1-5]|hidden-path-route|cultural-insider|local-flavor-guide|seasonal-secret|smart-traveler-log)\b",
    re.I,
)


IMAGE_SOURCES = {
    "seoul-ddp-heunginjimun-night-design-walk": Path(
        r"C:\Users\wlflq\.codex\generated_images\019d99c8-804f-7561-8393-2fda7a6136bb\ig_0722eef2b733fb6e0169f36b3b41188191a759b4d6a21673ef.png"
    ),
    "incheon-songdo-central-park-sunset-route": Path(
        r"C:\Users\wlflq\.codex\generated_images\019d99c8-804f-7561-8393-2fda7a6136bb\ig_0722eef2b733fb6e0169f36bfe41b4819190d134275c418591.png"
    ),
    "haneul-park-nanji-hangang-sunset-walk": Path(
        r"C:\Users\wlflq\.codex\generated_images\019d99c8-804f-7561-8393-2fda7a6136bb\ig_0722eef2b733fb6e0169f36c4feb148191b50c1228a35d9b05.png"
    ),
}


TOPICS: list[dict[str, Any]] = [
    {
        "slug": "seoul-ddp-heunginjimun-night-design-walk",
        "group_key": "travel-seoul-ddp-heunginjimun-night-design-walk-20260430",
        "keyword": "Seoul DDP and Heunginjimun Night Design Walk",
        "category_key": "travel",
        "image_anchors": "DDP curve, Heunginjimun gate, late-night food/rest stop",
        "image_prompt": "Photorealistic editorial route collage, Seoul DDP silver curve, Heunginjimun gate at blue hour, late-night Dongdaemun food or quiet rest stop, transit and walking decisions, 4x3 12-panel grid.",
        "patterns": {
            "en": "travel-01-hidden-path-route",
            "es": "travel-02-cultural-insider",
            "ja": "travel-05-smart-traveler-log",
        },
        "en": {
            "title": "DDP to Heunginjimun at Night: A Seoul Design Walk That Actually Flows",
            "meta": "Plan a Seoul night walk from DDP to Heunginjimun with timing, route order, rest stops, and clear skip decisions for a smoother Dongdaemun evening.",
            "excerpt": "This is a practical blue-hour route for seeing DDP and Heunginjimun without turning the night into a random Dongdaemun wander.",
            "labels": ["Travel", "Seoul Travel", "DDP", "Dongdaemun", "Night Walk", "Korea Route"],
            "start": "Dongdaemun History and Culture Park station area",
            "sequence": "DDP plaza, design curve viewpoint, Heunginjimun gate, short market edge, rest stop",
            "timing": "about 90 to 140 minutes after sunset",
            "rest": "a simple late-night snack or warm drink before the last subway decision",
            "skip": "the full shopping maze if your goal is architecture and night photos",
            "backup": "stay around the DDP plaza if rain or wind makes the gate crossing unpleasant",
            "not_for": "travelers who want a quiet old-Seoul walk with no traffic or neon",
            "why": "The two landmarks are close, but the order matters because DDP feels best while there is still a little sky color and Heunginjimun becomes stronger once the gate lighting takes over.",
        },
        "es": {
            "title": "DDP y Heunginjimun de noche: la ruta de diseño que sí funciona en Seúl",
            "meta": "Organiza una caminata nocturna por DDP y Heunginjimun con orden claro, tiempos reales, pausas y decisiones para evitar una vuelta confusa.",
            "excerpt": "La zona de Dongdaemun puede sentirse caótica si llegas sin plan; esta ruta une diseño, puerta histórica y pausa local con criterio.",
            "labels": ["Viajes", "Seúl", "DDP", "Dongdaemun", "Ruta nocturna", "Corea"],
            "start": "la zona de la estación Dongdaemun History and Culture Park",
            "sequence": "plaza del DDP, curva principal, puerta Heunginjimun, borde de mercado, pausa corta",
            "timing": "entre 90 y 140 minutos después del atardecer",
            "rest": "un snack sencillo o una bebida caliente antes de decidir el regreso",
            "skip": "el laberinto completo de compras si buscas arquitectura y fotos nocturnas",
            "backup": "quedarte en la plaza del DDP si hay lluvia o viento fuerte",
            "not_for": "quien quiera una noche silenciosa sin tráfico ni luces de barrio comercial",
            "why": "DDP funciona mejor cuando todavía queda color en el cielo, mientras que Heunginjimun gana fuerza cuando la iluminación de la puerta ya domina la escena.",
        },
        "ja": {
            "title": "DDPから興仁之門へ夜に歩くなら: 写真と帰り道で失敗しない順番",
            "meta": "DDPから興仁之門まで夜に歩くルートを、混雑、写真時間、休憩、帰り道の判断まで含めて初めてでも迷いにくく整理します。",
            "excerpt": "東大門の夜は近い場所ほど迷いやすいので、DDP、興仁之門、休憩、帰り道を先に決めて歩くのが楽です。",
            "labels": ["Travel", "ソウル旅行", "DDP", "東大門", "夜散歩", "韓国旅行"],
            "start": "東大門歴史文化公園駅周辺",
            "sequence": "DDP広場、曲線の撮影ポイント、興仁之門、市場の外側、短い休憩",
            "timing": "日没後90分から140分ほど",
            "rest": "終電やタクシーを決める前の軽い夜食か温かい飲み物",
            "skip": "建築と夜景が目的なら買い物ビルの奥まで入る動き",
            "backup": "雨や風が強い日はDDP周辺だけで終える判断",
            "not_for": "静かな古い街歩きだけを期待する人",
            "why": "DDPは空に少し色が残る時間、興仁之門はライトが強くなる時間に見ると印象が変わります。",
        },
    },
    {
        "slug": "incheon-songdo-central-park-sunset-route",
        "group_key": "travel-incheon-songdo-central-park-sunset-route-20260430",
        "keyword": "Incheon Songdo Central Park Sunset Route",
        "category_key": "travel",
        "image_anchors": "canal sunset, Tri-bowl/culture stop, subway/taxi return decision",
        "image_prompt": "Photorealistic editorial route collage, Songdo Central Park canal sunset, Tri-bowl modern culture stop, Incheon subway or taxi return choice after dark, 4x3 12-panel grid.",
        "patterns": {
            "en": "travel-04-seasonal-secret",
            "es": "travel-01-hidden-path-route",
            "ja": "travel-02-cultural-insider",
        },
        "en": {
            "title": "Songdo Central Park at Sunset: The Incheon Route I Would Keep Slow",
            "meta": "Use this Songdo Central Park sunset route to time the canal, Tri-bowl area, cafe pause, and return decision without overpacking the evening.",
            "excerpt": "Songdo is not a place I would rush; the payoff comes from choosing one sunset line, one culture stop, and a clean way back.",
            "labels": ["Travel", "Incheon Travel", "Songdo", "Central Park", "Sunset Walk", "Korea Route"],
            "start": "Central Park station or the main park entrance closest to your hotel",
            "sequence": "canal edge, open park view, Tri-bowl area, cafe or rest stop, return route",
            "timing": "start 60 to 80 minutes before sunset and leave after the lights settle",
            "rest": "a cafe pause near the park instead of trying to add another district",
            "skip": "crossing the whole district if the sky is already dark and you are tired",
            "backup": "switch to a taxi if the wind picks up or your next stop is not near a subway line",
            "not_for": "travelers who need dense street food or old-market atmosphere in the same evening",
            "why": "Songdo works when the skyline, canal, and park paths have room to breathe; the route loses its charm if you treat it like a checklist.",
        },
        "es": {
            "title": "Atardecer en Songdo Central Park: la ruta tranquila que merece la pena",
            "meta": "Planifica una tarde por Songdo Central Park con canal, Tri-bowl, pausa de café y decisión clara entre metro y taxi al regresar.",
            "excerpt": "Songdo se disfruta mejor sin correr; el truco está en elegir bien el borde del canal, la hora de luz y la salida.",
            "labels": ["Viajes", "Incheon", "Songdo", "Central Park", "Atardecer", "Corea"],
            "start": "Central Park Station o la entrada del parque más cercana a tu alojamiento",
            "sequence": "borde del canal, vista abierta del parque, zona de Tri-bowl, pausa de café, salida",
            "timing": "empezar 60 a 80 minutos antes del atardecer y salir cuando las luces ya estén firmes",
            "rest": "una pausa de café cerca del parque en vez de sumar otro barrio",
            "skip": "cruzar todo el distrito si ya oscureció y el viento se nota",
            "backup": "cambiar a taxi si tu siguiente destino no queda bien conectado por metro",
            "not_for": "quien busque mercados antiguos, comida callejera intensa o ruido urbano clásico",
            "why": "El canal y los edificios modernos necesitan una ruta lenta; si lo conviertes en lista de paradas, Songdo pierde su mejor parte.",
        },
        "ja": {
            "title": "仁川・松島セントラルパーク夕景ルート: 運河、Tri-bowl、帰り方の決め方",
            "meta": "松島セントラルパークの夕景を、運河沿い、Tri-bowl周辺、休憩、地下鉄かタクシーの帰り方まで整理します。",
            "excerpt": "松島は予定を詰めるより、夕方の光と帰り道を先に決めたほうが満足度が高い場所です。",
            "labels": ["Travel", "仁川旅行", "松島", "セントラルパーク", "夕景", "韓国旅行"],
            "start": "Central Park駅または宿泊先から近い公園入口",
            "sequence": "運河沿い、広い公園ビュー、Tri-bowl周辺、カフェ休憩、帰り道",
            "timing": "日没60分から80分前に入り、暗くなり始めたら帰路を決める",
            "rest": "公園近くのカフェで一度座ってから地下鉄かタクシーを選ぶ",
            "skip": "暗くなってから地区全体を無理に横断する動き",
            "backup": "風が強い日や乗り換えが悪い日はタクシーに切り替える判断",
            "not_for": "市場や屋台の密度を同じ夜に求める人",
            "why": "松島は景色の余白が魅力なので、文化施設と帰り方を先に決めると歩きすぎを防げます。",
        },
    },
    {
        "slug": "haneul-park-nanji-hangang-sunset-walk",
        "group_key": "travel-haneul-park-nanji-hangang-sunset-walk-20260430",
        "keyword": "Haneul Park and Nanji Hangang Sunset Walk",
        "category_key": "travel",
        "image_anchors": "Haneul slope/reed view, Nanji riverside, return route/food rest",
        "image_prompt": "Photorealistic editorial route collage, Haneul Park reed slope at sunset, Nanji Hangang riverside path, return route and simple food/rest stop after blue hour, 4x3 12-panel grid.",
        "patterns": {
            "en": "travel-05-smart-traveler-log",
            "es": "travel-03-local-flavor-guide",
            "ja": "travel-04-seasonal-secret",
        },
        "en": {
            "title": "Haneul Park to Nanji Hangang: A Sunset Walk With a Real Exit Plan",
            "meta": "Plan Haneul Park and Nanji Hangang as one sunset route with slope timing, riverside choice, food/rest stop, and a realistic return plan.",
            "excerpt": "This route can be beautiful and tiring at the same time, so I would decide the hill, river section, and return before arriving.",
            "labels": ["Travel", "Seoul Travel", "Haneul Park", "Nanji Hangang", "Sunset Walk", "Korea Route"],
            "start": "World Cup Stadium station or the nearest practical approach to Haneul Park",
            "sequence": "Haneul Park slope, reed viewpoint, descent choice, Nanji Hangang edge, rest and return",
            "timing": "enter before sunset and leave the riverside before the return options thin out",
            "rest": "a simple meal or convenience-store break after the descent, not before the hill",
            "skip": "pushing both a long park loop and a long Hangang walk on the same tired evening",
            "backup": "stay at Haneul Park only if the descent or river section feels too much",
            "not_for": "travelers with sore knees, tight shoes, or no patience for a slope before sunset",
            "why": "The view is worth it, but the route becomes better when you respect the hill and treat Nanji as an optional second act.",
        },
        "es": {
            "title": "Haneul Park y Nanji Hangang al atardecer: ruta, descanso y regreso sin agotarte",
            "meta": "Combina Haneul Park y Nanji Hangang con subida, juncos, pausa local y decisión de regreso para que el atardecer no termine pesado.",
            "excerpt": "La ruta es bonita, pero no conviene improvisarla; primero decide la subida, luego la ribera y finalmente cómo volver.",
            "labels": ["Viajes", "Seúl", "Haneul Park", "Nanji Hangang", "Atardecer", "Corea"],
            "start": "World Cup Stadium Station o el acceso más práctico a Haneul Park",
            "sequence": "subida a Haneul, mirador de juncos, bajada, zona de Nanji Hangang, descanso y regreso",
            "timing": "entrar antes del atardecer y salir de la zona del Han antes de que el regreso se vuelva incómodo",
            "rest": "una comida sencilla o parada de conveniencia después de bajar, no antes de la cuesta",
            "skip": "sumar un circuito largo del parque y una caminata larga por Hangang en la misma tarde",
            "backup": "quedarte solo en Haneul si la bajada o la ribera ya se sienten demasiado",
            "not_for": "quien tenga rodillas cansadas, calzado incómodo o poco margen antes de la noche",
            "why": "El valor está en combinar vista, descanso y salida; si solo persigues distancia, la ruta se vuelve más dura que memorable.",
        },
        "ja": {
            "title": "ハヌル公園から蘭芝漢江へ夕方歩くなら: 坂道、休憩、帰り道の現実的な順番",
            "meta": "ハヌル公園と蘭芝漢江を夕方に歩くときの坂道、すすき景色、休憩、帰り道の判断を初めてでも使いやすく整理します。",
            "excerpt": "ハヌル公園はきれいですが体力を使うので、坂道と漢江側の距離を欲張らない順番が大事です。",
            "labels": ["Travel", "ソウル旅行", "ハヌル公園", "蘭芝漢江", "夕景", "韓国旅行"],
            "start": "ワールドカップ競技場駅、またはハヌル公園へ入りやすい入口",
            "sequence": "ハヌル公園の坂道、すすきの展望、下り道、蘭芝漢江、休憩と帰り道",
            "timing": "日没前に上がり、漢江側は暗くなりすぎる前に距離を決める",
            "rest": "坂を下りたあとに軽食かコンビニ休憩を入れてから帰路を選ぶ",
            "skip": "疲れている日に公園一周と漢江沿いの長距離歩きを両方入れる動き",
            "backup": "体力や風が気になる日はハヌル公園だけで終える判断",
            "not_for": "膝が不安な人、靴が合わない人、夜の帰り道を急ぎたい人",
            "why": "季節の景色は強いですが、坂道と帰り道を甘く見ると満足より疲れが残ります。",
        },
    },
]


def _stdout_utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _load_env() -> None:
    os.environ.setdefault("DATABASE_URL", DATABASE_URL)
    if RUNTIME_ENV_PATH.exists():
        for raw in RUNTIME_ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(API_ROOT))


def _plain_text(html: str) -> str:
    return SPACE_RE.sub(" ", TAG_RE.sub(" ", html or "")).strip()


def _non_space_len(html_or_text: str) -> int:
    return len(SPACE_RE.sub("", _plain_text(html_or_text)))


def _visible_text_from_soup(soup: BeautifulSoup) -> str:
    clone = BeautifulSoup(str(soup), "html.parser")
    for tag in clone(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return SPACE_RE.sub(" ", clone.get_text(" ", strip=True)).strip()


def _repeated_sentence_count(text: str) -> int:
    rows = [SPACE_RE.sub(" ", item).strip() for item in SENTENCE_RE.split(text) if len(SPACE_RE.sub(" ", item).strip()) >= 28]
    counts = Counter(rows)
    return sum(1 for count in counts.values() if count >= 3)


def _word_key(pattern_key: str) -> str:
    return str(pattern_key).replace("travel-01-", "").replace("travel-02-", "").replace("travel-03-", "").replace("travel-04-", "").replace("travel-05-", "")


def _title_ctr_score(title: str, lang: str) -> int:
    score = 60
    length = len(title.strip())
    if 42 <= length <= 92:
        score += 12
    elif 30 <= length <= 115:
        score += 7
    action_terms = {
        "en": ("route", "walk", "plan", "skip", "timing", "guide"),
        "es": ("ruta", "guia", "guía", "regreso", "atardecer", "noche"),
        "ja": ("順番", "ルート", "帰り道", "歩く", "夕方", "夜"),
    }
    specificity_terms = {
        "en": ("DDP", "Heunginjimun", "Songdo", "Haneul", "Nanji", "Hangang"),
        "es": ("DDP", "Heunginjimun", "Songdo", "Haneul", "Nanji", "Hangang"),
        "ja": ("DDP", "興仁之門", "松島", "ハヌル", "蘭芝", "漢江"),
    }
    lowered = title.lower()
    if any(term.lower() in lowered for term in action_terms[lang]):
        score += 10
    if any(term.lower() in lowered for term in specificity_terms[lang]):
        score += 10
    if ":" in title:
        score += 5
    if re.search(r"\b(ultimate|must-visit|perfect)\b", title, re.I):
        score -= 12
    return max(0, min(100, score))


def _force_pattern_metadata(article: Any, pattern: str) -> None:
    article.article_pattern_id = pattern
    article.article_pattern_key = pattern
    article.article_pattern_version = PATTERN_VERSION
    article.article_pattern_version_key = PATTERN_VERSION_KEY


def _image_contract(topic: dict[str, Any]) -> str:
    return (
        f"ONE single flattened final image, 4 columns x 3 rows visible editorial collage, exactly 12 distinct visible panels, "
        f"thin white gutters, no text, no logos, no watermark, do not generate 12 separate images, do not generate one single hero shot without panel structure. "
        f"Photorealistic editorial route collage. Visual anchors: {topic['image_anchors']}. {topic['image_prompt']}"
    )


def _body_en(topic: dict[str, Any], data: dict[str, Any], pattern: str) -> str:
    word_key = _word_key(pattern)
    return f"""
<section>
  <p><strong>Updated April 30, 2026.</strong> {data['why']} I would use this route when the evening has one clear purpose: see the place at its best, keep the walking logical, and leave before the return becomes annoying.</p>
  <p>The mistake I see most often is trying to add every nearby stop because the map looks compact. This guide keeps the route narrow on purpose, with enough room for photos, a real pause, and one backup decision if the weather or crowd changes.</p>
</section>
<section>
  <h2>Start with the decision, not the landmark</h2>
  <p>The first decision is whether you want a view-first walk or a low-friction evening. For this plan, I would start from {data['start']} and let the route move through {data['sequence']} instead of circling randomly. That order gives you the strongest visual change with the least backtracking.</p>
  <p>The reader-facing point is simple: every stop needs to earn its place. If a turn adds distance without improving the light, food, or exit, I would skip it and keep the walk cleaner.</p>
  <h3>Access and first step</h3>
  <p>Arrive with your map already loaded and choose the first viewpoint before you leave the station area. Standing outside while comparing routes is the fastest way to lose the best light and join the slowest part of the crowd.</p>
  <h3>Where the route should turn around</h3>
  <p>The turnaround point is not the farthest landmark. It is the moment when the next stop would make the return harder than the view is worth. I would set that point before starting, then treat the rest stop as the reset button.</p>
</section>
<section>
  <h2>Timing table: how I would run the evening</h2>
  <table><thead><tr><th>Window</th><th>Best move</th><th>What to avoid</th></tr></thead><tbody>
    <tr><td>Before peak light</td><td>Get to {data['start']} and choose the first photo line.</td><td>Starting with food before the route has momentum.</td></tr>
    <tr><td>Main light window</td><td>Follow {data['sequence']} and keep stops short.</td><td>Crossing into unrelated shopping or side streets just because they are nearby.</td></tr>
    <tr><td>After the best view</td><td>Use {data['rest']} and check the return route.</td><td>Waiting until everyone leaves at once and the transit choice gets worse.</td></tr>
  </tbody></table>
  <p>The useful timing for this route is {data['timing']}. If you arrive later than that, I would shorten the middle section first, not rush the opening view.</p>
</section>
<section>
  <h2>The route I would actually walk</h2>
  <p>I would keep the first half visual and the second half practical. Start with the anchor view, move only when the next scene is clearly different, then slow down for one local detail instead of collecting weak photos from every corner.</p>
  <p>If you are short on time, choose the landmark and the rest stop rather than trying to complete the whole loop. A smaller route done in the right order feels better than a longer route finished with tired decisions.</p>
</section>
<section>
  <h2>What I would skip and when to reroute</h2>
  <p>I would skip {data['skip']}. That choice does not make the evening smaller; it keeps the route from turning into a vague wander. If the crowd is heavier than expected, reroute around the widest pedestrian space and protect the final transit choice.</p>
  <p>The backup is straightforward: {data['backup']}. The point is not to force the plan. The point is to leave with one strong memory instead of three average stops and a messy ride back.</p>
</section>
<section>
  <h2>Food or rest pairing that does not ruin the route</h2>
  <p>The best rest pairing is {data['rest']}. I would not make dinner the main event unless that was your reason for coming. Keep the food choice simple, close to the route, and easy to abandon if the line looks slow.</p>
  <p>For me, the practical test is whether the stop helps the return. If it gives you a seat, a bathroom break, and a moment to check subway or taxi timing, it belongs. If it sends you fifteen minutes away from the exit, it does not.</p>
</section>
<section>
  <h2>Not for everyone: who should skip this plan</h2>
  <p>This route is not for everyone. It does not suit {data['not_for']}. It also does not suit travelers who want a dense all-night itinerary, because the route works by leaving space between decisions.</p>
  <p>If you need a faster plan, take only the first anchor and the return decision. If you need a longer night, add food after the route, not in the middle of the best timing window.</p>
</section>
<section>
  <h2>Checklist before leaving</h2>
  <ul>
    <li>Load the map and decide the first viewpoint before arrival.</li>
    <li>Check the last comfortable subway or taxi option before you start walking.</li>
    <li>Choose one rest stop and one backup stop, not five possibilities.</li>
    <li>Skip the section that adds distance without a different view.</li>
    <li>Keep one hand free for stairs, slopes, crossings, or night crowds.</li>
  </ul>
</section>
<section>
  <h2>Final call</h2>
  <p>I would choose this route when the evening needs to feel intentional rather than busy. It gives you a clean start, a few strong visual anchors, a sensible pause, and a return plan that does not depend on luck.</p>
</section>
""".strip()


def _body_es(topic: dict[str, Any], data: dict[str, Any], pattern: str) -> str:
    word_key = _word_key(pattern)
    return f"""
<section>
  <p><strong>Actualizado el 30 de abril de 2026.</strong> {data['why']} Para mí, esta ruta funciona cuando aceptas una idea simple: no se trata de caminar más, sino de decidir mejor.</p>
  <p>La zona puede parecer fácil en el mapa, pero sin orden acaba siendo una mezcla de fotos rápidas, pausas mal puestas y regreso incómodo. Yo lo haría así: una escena fuerte, una decisión de ruta, una pausa útil y una salida clara.</p>
</section>
<section>
  <h2>Primero decide el tipo de tarde que quieres</h2>
  <p>Si tienes poco tiempo, empieza en {data['start']} y sigue esta secuencia: {data['sequence']}. El orden importa porque evita cruces innecesarios y deja la mejor luz para el punto que más la necesita.</p>
  <p>En lenguaje de blog, cada parada debe resolver una duda concreta. Si no mejora la vista, el descanso o el regreso, no merece la pena si tu energía ya va justa.</p>
  <h3>Entrada y primera mirada</h3>
  <p>Llega con el mapa preparado. No recomiendo salir de la estación y decidir allí mismo, porque ese minuto de duda se convierte rápido en una ruta menos limpia.</p>
  <h3>El punto donde conviene cambiar de ritmo</h3>
  <p>El giro de la ruta no debería ser el punto más lejano. Mejor cambia el orden si notas que la siguiente parada complica el regreso más de lo que mejora la experiencia.</p>
</section>
<section>
  <h2>Tabla de tiempos y decisiones</h2>
  <table><thead><tr><th>Momento</th><th>Qué haría</th><th>Qué evitaría</th></tr></thead><tbody>
    <tr><td>Antes de la mejor luz</td><td>Llegar a {data['start']} y fijar la primera foto.</td><td>Empezar con comida antes de que la ruta tenga dirección.</td></tr>
    <tr><td>Momento principal</td><td>Seguir {data['sequence']} sin abrir demasiados desvíos.</td><td>Meter calles o compras que no aportan a la ruta.</td></tr>
    <tr><td>Después de la escena fuerte</td><td>Hacer {data['rest']} y revisar el regreso.</td><td>Esperar hasta que todos salgan al mismo tiempo.</td></tr>
  </tbody></table>
  <p>La ventana útil es {data['timing']}. Si llegas tarde, recorta la parte intermedia y conserva el cierre con calma.</p>
</section>
<section>
  <h2>La ruta que yo seguiría</h2>
  <p>Yo lo haría así: primero la escena más clara, luego el tramo que cambia el ambiente y después una pausa cercana. Ese ritmo evita que la tarde se convierta en una lista sin personalidad.</p>
  <p>Si quieres fotos, no corras entre puntos. Si quieres descanso, no lo pongas antes de la parte más bonita. La ruta mejora cuando cada decisión tiene una función.</p>
</section>
<section>
  <h2>Qué saltaría sin culpa</h2>
  <p>Saltaría {data['skip']}. No es perder contenido; es proteger la parte buena del paseo. Si el ambiente está más lleno de lo esperado, evita el tramo estrecho y busca la salida más amplia.</p>
  <p>El plan B es claro: {data['backup']}. Me parece mejor volver con una escena fuerte que insistir en tres paradas medianas solo porque estaban en el mapa.</p>
</section>
<section>
  <h2>Pausa local sin romper el recorrido</h2>
  <p>La pausa que encaja es {data['rest']}. No haría una cena larga en medio de la ventana principal, salvo que la comida sea el objetivo real del día.</p>
  <p>Mi consejo es medir la pausa por su utilidad: asiento, baño, agua, revisión del metro o taxi. Si la parada te aleja demasiado del regreso, cambia de opción.</p>
</section>
<section>
  <h2>No es para todos</h2>
  <p>Esta ruta no es para todos. No la elegiría para {data['not_for']}. Tampoco funciona si esperas una noche llena de paradas, porque su gracia está en caminar menos y decidir mejor.</p>
  <p>Si vas con cansancio, reduce la ruta a la escena principal y la salida. Si vas con margen, añade comida al final, no durante el tramo que depende de la luz.</p>
</section>
<section>
  <h2>Checklist antes de salir</h2>
  <ul>
    <li>Guarda el mapa y la primera parada antes de llegar.</li>
    <li>Decide de antemano si volverás en metro o taxi.</li>
    <li>Elige una pausa útil y una alternativa, no una lista larga.</li>
    <li>Evita el desvío que solo suma distancia.</li>
    <li>Revisa clima, calzado y batería antes de empezar.</li>
  </ul>
</section>
<section>
  <h2>Mi conclusión práctica</h2>
  <p>Elegiría esta ruta cuando quieras una tarde con criterio, no una carrera. Tiene una imagen principal, decisiones concretas, una pausa real y un regreso que no depende de improvisar tarde.</p>
</section>
""".strip()


def _body_ja(topic: dict[str, Any], data: dict[str, Any], pattern: str) -> str:
    word_key = _word_key(pattern)
    return f"""
<section>
  <p><strong>Updated: 2026年4月30日。</strong>{data['why']} 私なら、このルートは「どこまで歩くか」よりも「どこで切り上げるか」を先に決めてから行きます。</p>
  <p>地図だけを見ると近く感じても、夕方以降は写真、休憩、帰り道の判断が遅れるほど疲れます。この記事では、{data['sequence']}という流れを基準に、無理に増やさない歩き方で整理します。</p>
</section>
<section>
  <h2>先に決めること: 目的を一つに絞る</h2>
  <p>最初の判断は、景色を優先するのか、移動を楽にするのかです。{data['start']}から入り、{data['sequence']}の順で歩くと、戻りの負担を増やさずに印象の違う場面を拾えます。</p>
  <p>読者に必要なのは専門用語ではありません。必要なのは、どこで写真を撮り、どこで休み、どこで帰り道へ切り替えるかです。</p>
  <h3>最初の一歩</h3>
  <p>駅や入口に着いてから検索を始めると、夕方の一番良い時間を失います。地図は先に保存し、最初に立つ場所だけでも決めておくと迷いが減ります。</p>
  <h3>切り上げる場所</h3>
  <p>一番遠い場所まで行くことが正解ではありません。次の移動で帰りが重くなるなら、その手前で休憩か帰路に切り替えるほうが満足度は高くなります。</p>
</section>
<section>
  <h2>時間帯別の判断表</h2>
  <table><thead><tr><th>時間帯</th><th>おすすめの動き</th><th>避けたいこと</th></tr></thead><tbody>
    <tr><td>到着直後</td><td>{data['start']}で最初の撮影位置を決める。</td><td>入口で長く迷って光の良い時間を失う。</td></tr>
    <tr><td>主役の時間</td><td>{data['sequence']}を短い停止でつなぐ。</td><td>目的と関係ない横道を増やしすぎる。</td></tr>
    <tr><td>暗くなった後</td><td>{data['rest']}を入れて帰り方を確認する。</td><td>人が一斉に動く時間まで判断を残す。</td></tr>
  </tbody></table>
  <p>目安は{data['timing']}です。遅れて到着した日は、中央の寄り道を減らして、主役の景色と帰り道を守るのが現実的です。</p>
</section>
<section>
  <h2>迷ったらこの順番で歩く</h2>
  <p>迷ったらこの順番です。まず主役の景色、次に雰囲気が変わる短い移動、最後に休憩と帰路確認。個人的に、この順番なら写真だけで終わらず、夜の移動も崩れにくいです。</p>
  <p>欲張るなら最後に足すほうが安全です。途中で予定を増やすと、休憩が遅れ、帰り道も雑になります。特に初めての場所では、短くても判断が明確なルートのほうが楽です。</p>
  <p>写真を優先する場合も、全方向を狙うより一つの主役を決めたほうが失敗しません。人が多い場所では立ち止まる時間を短くし、少し離れた位置から全体を見るほうが安全です。逆に人が少ない時間でも、暗い細道へ無理に入る必要はありません。</p>
  <p>同行者がいるなら、先に休憩の合図を決めておくと動きやすくなります。疲れてから相談すると、次の移動も食事も帰り方も中途半端になりがちです。私なら、主役の場所を見終えた時点で一度立ち止まり、続けるか戻るかを確認します。</p>
</section>
<section>
  <h2>混雑と写真の判断</h2>
  <p>混雑している日は、正面から近づくより横から入るほうが流れに乗りやすいです。写真は人が完全に消える瞬間を待つより、歩く人を避けやすい角度を探すほうが現実的です。待ちすぎると、休憩と帰り道の時間が削られます。</p>
  <p>暗くなってからは、画面の明るさより足元と出口を優先してください。きれいな景色をもう一枚撮りたくなる時間ほど、駅やタクシー乗り場までの距離を忘れやすいです。ここで無理をしないことが、夜の満足度を保つ一番のコツです。</p>
</section>
<section>
  <h2>帰り道を崩さないための小さな判断</h2>
  <p>帰り道は最後に考えるものではなく、歩き始める前に持っておく保険です。地下鉄で帰るなら改札に近い方向、タクシーを使うなら車が入りやすい大きな通りを意識しておくと、暗くなってから慌てません。</p>
  <p>もう少し歩けると思っても、休憩前に距離を伸ばすのはおすすめしません。休んだあとで続けるか決めれば、体力の残り方がはっきりします。無理をしてから戻るより、判断を一度挟むほうが旅の印象はよくなります。</p>
</section>
<section>
  <h2>現地で予定を修正する場面</h2>
  <p>実際に歩くと、予定どおりに進まない場面は必ずあります。人が多い、風が強い、写真の列が長い、思ったより足が疲れる。そういう時は、{data['sequence']}を全部こなすことより、主役の場面と帰りやすさを残すほうを選んでください。</p>
  <p>私なら、最初の景色を見終えた段階で一度スマホをしまい、体力、明るさ、帰りの方向を確認します。この確認を入れるだけで、その後の寄り道が必要かどうか判断しやすくなります。特に初めての韓国旅行では、情報量より迷わない動線のほうが大事です。</p>
  <p>天気が良い日は、写真を増やしたくなります。ただし、似た角度の写真を何枚も撮るより、少し離れて全体を入れる一枚、近くで質感を見る一枚、帰り道に向かう途中の一枚を決めたほうが整理しやすいです。撮影に集中しすぎると、休憩のタイミングが遅れます。</p>
  <p>同行者がいる場合は、誰か一人が疲れ始めた時点で予定を軽くするほうが安全です。まだ歩ける人に合わせると、帰り道で全員が黙ってしまうことがあります。短く切り上げても、休憩と帰路がスムーズならその日の満足度は十分残ります。</p>
</section>
<section>
  <h2>避けるべき動き</h2>
  <p>避けるべき動きは、{data['skip']}です。行ける距離と楽しめる距離は違います。人が多い日や風が強い日は、広い道、明るい場所、帰りやすい方向を優先してください。</p>
  <p>代替案は{data['backup']}です。予定を削ることは失敗ではなく、疲れた状態で余計な移動を増やさないための判断です。</p>
</section>
<section>
  <h2>休憩と食事の入れ方</h2>
  <p>休憩は{data['rest']}が合います。先に重い食事を入れるより、歩いたあとに短く座って、地下鉄かタクシーかを決めるほうが動きやすいです。</p>
  <p>私なら、休憩場所は有名さよりも出口との近さで選びます。席があり、水分を取れて、帰り道を確認できるなら十分です。遠い店を目的化すると、ルート全体が崩れます。</p>
  <p>食事を足すなら、移動の途中ではなく最後に寄せるのが楽です。途中で店を探し始めると、光の良い時間や主役の景色を逃しやすくなります。逆に、最後なら待ち時間が長そうな店を見てすぐ別案に変えても、ルート全体への影響は小さく済みます。</p>
  <p>予算面でも、ここでは特別な店を無理に入れる必要はありません。軽く座れる場所、温かい飲み物、簡単な軽食だけでも、次の判断には十分です。大事なのは店名より、歩いたあとに落ち着いて帰り道を選べることです。</p>
</section>
<section>
  <h2>このルートが向かない人</h2>
  <p>このルートは、{data['not_for']}には向きません。さらに、予定を細かく詰めたい人よりも、夕方の景色と帰りやすさを優先したい人に合います。</p>
  <p>体力に不安がある日は、主役の場所だけに絞ってください。時間に余裕がある日は、食事やカフェを最後に足すと、途中の判断が乱れません。</p>
</section>
<section>
  <h2>出発前チェックリスト</h2>
  <ul>
    <li>最初に立つ場所を地図で保存する。</li>
    <li>帰りは地下鉄かタクシーか、先に候補を持つ。</li>
    <li>休憩場所は一つ、代替案も一つに絞る。</li>
    <li>景色が変わらない遠回りは入れない。</li>
    <li>靴、上着、スマホ残量を確認してから歩く。</li>
  </ul>
</section>
<section>
  <h2>最後の判断</h2>
  <p>このコースは、長く歩くためではなく、夕方の良い場面を崩さずに拾うためのルートです。先に決めること、避けるべき動き、迷ったらこの順番を守れば、無理の少ない夜になります。最後にもう一つだけ加えるなら、予定を全部こなすより、帰ってから疲れすぎていない状態を残すほうが旅としては成功です。</p>
</section>
""".strip()


def _build_body(lang: str, topic: dict[str, Any], pattern: str) -> str:
    data = topic[lang]
    if lang == "en":
        return _body_en(topic, data, pattern)
    if lang == "es":
        return _body_es(topic, data, pattern)
    return _body_ja(topic, data, pattern)


def _faq(lang: str, data: dict[str, Any]) -> list[dict[str, str]]:
    if lang == "en":
        return [
            {"question": "How long should I allow for this route?", "answer": f"Plan for {data['timing']}, then shorten the middle section if you arrive late."},
            {"question": "What should I skip first?", "answer": f"Skip {data['skip']} before cutting the main viewpoint or the return plan."},
        ]
    if lang == "es":
        return [
            {"question": "Cuanto tiempo conviene reservar?", "answer": f"Reserva {data['timing']} y recorta el tramo intermedio si llegas tarde."},
            {"question": "Que saltaria primero?", "answer": f"Saltaria {data['skip']} antes de sacrificar la escena principal o el regreso."},
        ]
    return [
        {"question": "どのくらい時間を見ればいいですか?", "answer": f"{data['timing']}を目安にし、遅れた日は途中の寄り道を減らすのが安全です。"},
        {"question": "先に削るならどこですか?", "answer": f"まず{data['skip']}を削り、主役の景色と帰り道は残すのがおすすめです。"},
    ]


def _build_output(lang: str, topic: dict[str, Any], pattern: str):
    from app.schemas.ai import ArticleGenerationOutput

    data = topic[lang]
    return ArticleGenerationOutput(
        title=data["title"],
        meta_description=data["meta"],
        labels=data["labels"],
        slug=topic["slug"] if lang == "ja" else topic["slug"],
        excerpt=data["excerpt"],
        html_article=_build_body(lang, topic, pattern),
        faq_section=_faq(lang, data),
        image_collage_prompt=_image_contract(topic),
        inline_collage_prompt="",
        article_pattern_id=pattern,
        article_pattern_version=PATTERN_VERSION,
        article_pattern_key=pattern,
        article_pattern_version_key=PATTERN_VERSION_KEY,
    )


def _validate_local_output(lang: str, output: Any) -> dict[str, Any]:
    body = output.html_article
    text = _plain_text(body)
    return {
        "language": lang,
        "title": output.title,
        "body_chars": _non_space_len(body),
        "h2": body.lower().count("<h2"),
        "h3": body.lower().count("<h3"),
        "tables": body.lower().count("<table"),
        "li": body.lower().count("<li"),
        "body_h1": body.lower().count("<h1"),
        "repeat_3plus": _repeated_sentence_count(text),
        "forbidden": bool(FORBIDDEN_RE.search(text)),
    }


def _fallback_related(db, blog_id: int, limit: int = 3) -> list[dict[str, Any]]:
    from app.models.entities import SyncedBloggerPost

    rows = db.execute(
        select(SyncedBloggerPost)
        .where(SyncedBloggerPost.blog_id == blog_id, SyncedBloggerPost.url.is_not(None))
        .order_by(SyncedBloggerPost.published_at.desc().nullslast(), SyncedBloggerPost.id.desc())
        .limit(30)
    ).scalars().all()
    selected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_thumbs: set[str] = set()
    for row in rows:
        url = str(row.url or "").strip()
        thumb = str(row.thumbnail_url or "").strip()
        if not url or url in seen_urls or not R2_RE.search(thumb):
            continue
        if thumb in seen_thumbs:
            continue
        seen_urls.add(url)
        seen_thumbs.add(thumb)
        selected.append(
            {
                "title": row.title,
                "excerpt": row.excerpt_text or "",
                "thumbnail": thumb,
                "link": url,
                "source": "synced_fallback",
                "score": 0.1,
            }
        )
        if len(selected) >= limit:
            break
    return selected


def _validate_live(url: str, hero_url: str, lang: str) -> dict[str, Any]:
    from scripts.travel.audit_travel_concept_scores import _score_document

    with httpx.Client(timeout=30.0, follow_redirects=True, headers={"User-Agent": "BloggerGentPublishValidation/1.0"}) as client:
        response = client.get(url)
        status_code = response.status_code
        response.raise_for_status()
        html = response.text
    soup = BeautifulSoup(html, "html.parser")
    article = soup.select_one("article[data-bloggent-article='canonical']") or soup.select_one("article") or soup
    body = article.select_one("section[data-bloggent-role='article-body']") or article
    text = _visible_text_from_soup(body)
    r2_images = R2_RE.findall(str(article))
    hero_figures = article.select("figure[data-bloggent-role='hero-figure'] img")
    related_links = article.select(".related-posts a[href]")
    concept = _score_document(lang, url, html)
    return {
        "url": url,
        "http_status": status_code,
        "h1_count": len(article.find_all("h1")),
        "body_h1_count": len(body.find_all("h1")),
        "hero_count": len(hero_figures),
        "hero_url_present": hero_url in html,
        "image_count": len(r2_images),
        "unique_image_count": len(set(r2_images)),
        "related_count": len(related_links),
        "body_chars": len(SPACE_RE.sub("", text)),
        "repeat_sentence_3plus": _repeated_sentence_count(text),
        "internal_terms": bool(FORBIDDEN_RE.search(text)),
        "concept_score": concept["score"],
        "concept_status": concept["quality_status"],
        "validation_passed": (
            status_code == 200
            and len(article.find_all("h1")) == 1
            and len(body.find_all("h1")) == 0
            and len(hero_figures) == 1
            and hero_url in html
            and len(r2_images) == 4
            and len(set(r2_images)) == 4
            and len(related_links) == 3
            and len(SPACE_RE.sub("", text)) >= 3000
            and _repeated_sentence_count(text) == 0
            and not bool(FORBIDDEN_RE.search(text))
            and concept["score"] >= 90
        ),
    }


def _extract_feed_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("$t") or "").strip()
    return str(value or "").strip()


def _find_existing_remote_post_from_feed(
    *,
    blog_url: str,
    candidate_titles: set[str],
    image_url: str,
) -> tuple[dict, dict] | None:
    if not blog_url:
        return None
    feed_url = f"{blog_url.rstrip('/')}/feeds/posts/default"
    response = httpx.get(
        feed_url,
        params={"alt": "json", "max-results": "50"},
        timeout=30.0,
        follow_redirects=True,
    )
    response.raise_for_status()
    payload = response.json()
    entries = payload.get("feed", {}).get("entry", []) or []
    for entry in entries:
        title = _extract_feed_text(entry.get("title"))
        content = _extract_feed_text(entry.get("content")) or _extract_feed_text(entry.get("summary"))
        if title not in candidate_titles or image_url not in content:
            continue
        raw_id = _extract_feed_text(entry.get("id"))
        match = re.search(r"post-(\d+)", raw_id)
        post_id = match.group(1) if match else raw_id
        url = ""
        for link in entry.get("link", []) or []:
            if isinstance(link, dict) and str(link.get("rel") or "") == "alternate":
                url = str(link.get("href") or "")
                break
        summary = {
            "id": post_id,
            "url": url,
            "published": _extract_feed_text(entry.get("published")),
            "isDraft": False,
            "postStatus": "published",
            "scheduledFor": None,
        }
        return summary, entry
    return None


def _find_existing_remote_post(
    provider: Any,
    *,
    blog_url: str,
    candidate_titles: set[str],
    image_url: str,
) -> tuple[dict, dict] | None:
    url = f"https://www.googleapis.com/blogger/v3/blogs/{provider.blog_id}/posts"
    params = {
        "maxResults": "50",
        "fetchBodies": "true",
        "status": "LIVE",
        "orderBy": "published",
    }
    for attempt in range(3):
        try:
            response = httpx.get(url, headers=provider._auth_headers(), params=params, timeout=60.0)
            response.raise_for_status()
            payload = response.json()
            for item in payload.get("items", []) or []:
                title = str(item.get("title") or "").strip()
                content = str(item.get("content") or "")
                if title in candidate_titles and image_url in content:
                    raw_status = str(item.get("status", "")).upper()
                    summary = {
                        "id": str(item.get("id") or ""),
                        "url": str(item.get("url") or ""),
                        "published": item.get("published"),
                        "isDraft": raw_status == "DRAFT",
                        "postStatus": "published",
                        "scheduledFor": None,
                    }
                    return summary, item
            return None
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500 or attempt == 2:
                break
            time.sleep(1.5 * (attempt + 1))
    return _find_existing_remote_post_from_feed(blog_url=blog_url, candidate_titles=candidate_titles, image_url=image_url)


def _cleanup_stale_partial_rows(db) -> list[dict[str, Any]]:
    from app.models.entities import (
        AnalyticsArticleFact,
        Article,
        AuditLog,
        BloggerPost,
        Image,
        Job,
        PublishQueueItem,
    )

    keywords = [f"{topic['keyword']} [{lang}]" for topic in TOPICS for lang in ("en", "es", "ja")]
    rows = db.execute(
        select(Article.id, Article.job_id, Article.title)
        .join(Job, Article.job_id == Job.id)
        .outerjoin(BloggerPost, BloggerPost.article_id == Article.id)
        .where(Job.keyword_snapshot.in_(keywords), BloggerPost.id.is_(None))
    ).all()
    cleaned: list[dict[str, Any]] = []
    for article_id, job_id, title in rows:
        db.execute(delete(PublishQueueItem).where(PublishQueueItem.article_id == article_id))
        db.execute(delete(AnalyticsArticleFact).where(AnalyticsArticleFact.article_id == article_id))
        db.execute(delete(Image).where(Image.article_id == article_id))
        db.execute(delete(AuditLog).where(AuditLog.job_id == job_id))
        db.execute(delete(Article).where(Article.id == article_id))
        db.execute(delete(Job).where(Job.id == job_id))
        cleaned.append({"article_id": article_id, "job_id": job_id, "title": title})
    orphan_jobs = db.execute(
        select(Job.id, Job.keyword_snapshot)
        .outerjoin(Article, Article.job_id == Job.id)
        .where(Job.keyword_snapshot.in_(keywords), Article.id.is_(None))
    ).all()
    for job_id, keyword in orphan_jobs:
        db.execute(delete(AuditLog).where(AuditLog.job_id == job_id))
        db.execute(delete(Job).where(Job.id == job_id))
        cleaned.append({"article_id": None, "job_id": job_id, "title": keyword})
    if cleaned:
        db.flush()
    return cleaned


def _upsert_topic(db, blog_id: int, lang: str, topic: dict[str, Any]):
    from app.models.entities import Topic

    keyword = f"{topic['keyword']} [{lang}]"
    existing = db.execute(select(Topic).where(Topic.blog_id == blog_id, Topic.keyword == keyword)).scalar_one_or_none()
    if existing:
        return existing
    created = Topic(
        blog_id=blog_id,
        keyword=keyword,
        reason="Codex travel concept batch 2026-04-30",
        trend_score=90.0,
        source="codex",
        locale=lang,
        topic_cluster_label=topic["keyword"],
        topic_angle_label="route decision blog guide",
        editorial_category_key=topic["category_key"],
        editorial_category_label="Travel",
        distinct_reason="No direct duplicate found in the current travel sitemap audit.",
    )
    db.add(created)
    db.flush()
    return created


def _upload_topic_image(db, topic: dict[str, Any]) -> dict[str, Any]:
    from app.services.integrations.storage_service import save_public_binary

    source = IMAGE_SOURCES[topic["slug"]]
    if not source.exists():
        raise FileNotFoundError(str(source))
    object_key = f"assets/travel-blogger/travel/{topic['slug']}.webp"
    with PILImage.open(source) as image:
        width, height = image.size
    file_path, public_url, delivery = save_public_binary(
        db,
        subdir=f"images/travel/{topic['slug']}",
        filename=f"{topic['slug']}.webp",
        content=source.read_bytes(),
        object_key=object_key,
        provider_override="cloudflare_r2",
    )
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(public_url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
    if "image/webp" not in content_type.lower():
        raise RuntimeError(f"uploaded_image_not_webp:{public_url}:{content_type}")
    return {
        "source_path": str(source),
        "file_path": file_path,
        "public_url": public_url,
        "delivery": delivery,
        "width": width,
        "height": height,
        "content_type": content_type,
        "object_key": object_key,
    }


def _publish_one(db, *, topic: dict[str, Any], lang: str, image_info: dict[str, Any], source_article_id: int | None):
    from app.models.entities import Article, Blog, Job, JobStatus, PublishMode
    from app.services.content.article_service import save_article
    from app.services.content.content_ops_service import compute_seo_geo_scores
    from app.services.content.html_assembler import assemble_article_html
    from app.services.content.related_posts import find_related_articles
    from app.services.providers.factory import get_blogger_provider
    from app.tasks.pipeline import _upsert_blogger_post, _upsert_image
    from app.services.ops.analytics_service import upsert_article_fact

    blog_id = LANG_BLOGS[lang]
    blog = db.execute(select(Blog).where(Blog.id == blog_id)).scalar_one()
    pattern = topic["patterns"][lang]
    db_topic = _upsert_topic(db, blog_id, lang, topic)
    output = _build_output(lang, topic, pattern)
    local_check = _validate_local_output(lang, output)
    if local_check["body_chars"] < 3000 or local_check["body_h1"] or local_check["repeat_3plus"] or local_check["forbidden"]:
        raise RuntimeError(f"local_validation_failed:{local_check}")

    duplicate = db.execute(
        select(Job)
        .join(Job.article)
        .where(Job.blog_id == blog_id, Job.keyword_snapshot == db_topic.keyword)
        .options(selectinload(Job.article).selectinload(Article.blogger_post))
    ).scalars().first()
    if duplicate and duplicate.article and duplicate.article.blogger_post and duplicate.article.blogger_post.published_url:
        article = duplicate.article
        _force_pattern_metadata(article, pattern)
        render_metadata = dict(article.render_metadata or {})
        score_payload = compute_seo_geo_scores(
            title=article.title,
            html_body=article.html_article,
            excerpt=article.excerpt,
            faq_section=list(article.faq_section or []),
        )
        title_score = int(score_payload.get("ctr_score") or _title_ctr_score(article.title, lang))
        render_metadata["travel_quality_scores"] = {
            **dict(render_metadata.get("travel_quality_scores") or {}),
            "seo_score": int(score_payload.get("seo_score") or 0),
            "geo_score": int(score_payload.get("geo_score") or 0),
            "ctr_title_score": title_score,
            "ctr_breakdown": dict(score_payload.get("ctr_breakdown") or {}),
            "lighthouse_status": "unmeasured_external_only",
            "lighthouse_source": "google_pagespeed_or_chrome_devtools_export_required",
        }
        article.render_metadata = render_metadata
        article.quality_seo_score = int(score_payload.get("seo_score") or 0)
        article.quality_geo_score = int(score_payload.get("geo_score") or 0)
        article.quality_ctr_score = float(title_score)
        article.quality_lighthouse_score = None
        article.quality_lighthouse_payload = {
            "status": "unmeasured_external_only",
            "source": "google_pagespeed_or_chrome_devtools_export_required",
        }
        db.add(article)
        db.flush()
        live = _validate_live(article.blogger_post.published_url, image_info["public_url"], lang)
        upsert_article_fact(db, article.id, commit=False)
        return {
            "language": lang,
            "blog_id": blog_id,
            "article_id": article.id,
            "job_id": duplicate.id,
            "post_id": article.blogger_post.blogger_post_id,
            "url": article.blogger_post.published_url,
            "title": article.title,
            "pattern": article.article_pattern_key,
            "body_chars": live["body_chars"],
            "concept_score": live["concept_score"],
            "seo": article.quality_seo_score,
            "geo": article.quality_geo_score,
            "ctr": None,
            "ctr_title_score": title_score,
            "lighthouse_status": "unmeasured_external_only",
            "lighthouse_score": None,
            "image_url": image_info["public_url"],
            "related_count": live["related_count"],
            "image_count": live["image_count"],
            "unique_image_count": live["unique_image_count"],
            "validation": live,
            "skipped": "already_published",
        }

    job = Job(
        blog_id=blog_id,
        topic_id=db_topic.id,
        keyword_snapshot=db_topic.keyword,
        status=JobStatus.PUBLISHING,
        publish_mode=PublishMode.PUBLISH,
        start_time=datetime.now(UTC),
        raw_prompts={
            "source": "codex_travel_concept_batch_20260430",
            "travel_sync": {
                "group_key": topic["group_key"],
                "source_language": "en",
                "target_language": lang,
                "source_article_id": source_article_id or 0,
            },
            "image_prompt_contract": _image_contract(topic),
        },
        raw_responses={"article": output.model_dump(mode="json")},
    )
    db.add(job)
    db.flush()
    job.blog = blog
    article = save_article(db, job=job, topic=db_topic, output=output, commit=False, upsert_fact=False)
    article.blog = blog
    _force_pattern_metadata(article, pattern)
    article.travel_sync_group_key = topic["group_key"]
    article.travel_sync_role = "source" if lang == "en" else "translation"
    if source_article_id:
        article.travel_sync_source_article_id = source_article_id
    render_metadata = dict(article.render_metadata or {})
    score_payload = compute_seo_geo_scores(
        title=article.title,
        html_body=article.html_article,
        excerpt=article.excerpt,
        faq_section=list(article.faq_section or []),
    )
    title_score = int(score_payload.get("ctr_score") or _title_ctr_score(article.title, lang))
    render_metadata["travel_quality_scores"] = {
        **dict(render_metadata.get("travel_quality_scores") or {}),
        "seo_score": int(score_payload.get("seo_score") or 0),
        "geo_score": int(score_payload.get("geo_score") or 0),
        "ctr_title_score": title_score,
        "ctr_breakdown": dict(score_payload.get("ctr_breakdown") or {}),
        "lighthouse_status": "unmeasured_external_only",
        "lighthouse_source": "google_pagespeed_or_chrome_devtools_export_required",
    }
    article.render_metadata = render_metadata
    article.quality_seo_score = int(score_payload.get("seo_score") or 0)
    article.quality_geo_score = int(score_payload.get("geo_score") or 0)
    article.quality_ctr_score = float(title_score)
    article.quality_lighthouse_score = None
    article.quality_lighthouse_payload = {
        "status": "unmeasured_external_only",
        "source": "google_pagespeed_or_chrome_devtools_export_required",
    }
    db.add(article)
    db.flush()
    image = _upsert_image(
        db,
        job_id=job.id,
        article_id=article.id,
        prompt=_image_contract(topic),
        file_path=image_info["file_path"],
        public_url=image_info["public_url"],
        provider="codex_builtin_imagegen_r2",
        meta={
            "width": image_info["width"],
            "height": image_info["height"],
            "delivery": image_info["delivery"],
            "source_path": image_info["source_path"],
            "object_key": image_info["object_key"],
        },
        commit=False,
    )
    article.image = image
    related = find_related_articles(db, article, limit=3)
    if len(related) < 3:
        related = (related + _fallback_related(db, blog_id, limit=3))[:3]
    if len(related) != 3:
        raise RuntimeError(f"related_count_invalid:{blog_id}:{len(related)}")
    article.assembled_html = assemble_article_html(article, image_info["public_url"], related, language_switch_html="")
    db.add(article)
    db.flush()
    provider = get_blogger_provider(db, blog)
    if provider.__class__.__name__.lower().startswith("mock"):
        raise RuntimeError(f"blogger_provider_not_live:{blog_id}")
    publish_title = article.title
    if lang == "ja":
        publish_title = topic["keyword"]
    existing_remote = _find_existing_remote_post(
        provider,
        blog_url=str(blog.blogger_url or ""),
        candidate_titles={article.title, publish_title, topic["keyword"]},
        image_url=image_info["public_url"],
    )
    if existing_remote:
        existing_summary, _existing_payload = existing_remote
        summary, raw_payload = provider.update_post(
            post_id=str(existing_summary.get("id") or ""),
            title=article.title,
            content=article.assembled_html,
            labels=list(article.labels or []),
            meta_description=article.meta_description,
        )
    else:
        summary, raw_payload = provider.publish(
            title=publish_title,
            content=article.assembled_html,
            labels=list(article.labels or []),
            meta_description=article.meta_description,
            slug=article.slug,
            publish_mode=PublishMode.PUBLISH,
        )
        if lang == "ja":
            summary, raw_payload = provider.update_post(
                post_id=str(summary.get("id") or ""),
                title=article.title,
                content=article.assembled_html,
                labels=list(article.labels or []),
                meta_description=article.meta_description,
            )
    post = _upsert_blogger_post(
        db,
        job_id=job.id,
        blog_id=blog_id,
        article_id=article.id,
        summary=summary,
        raw_payload=raw_payload,
        commit=False,
    )
    article.blogger_post = post
    job.status = JobStatus.COMPLETED
    job.end_time = datetime.now(UTC)
    db.add(job)
    db.flush()
    live = _validate_live(str(summary.get("url") or ""), image_info["public_url"], lang)
    if not live["validation_passed"]:
        raise RuntimeError(f"live_validation_failed:{live}")
    upsert_article_fact(db, article.id, commit=False)
    return {
        "language": lang,
        "blog_id": blog_id,
        "job_id": job.id,
        "article_id": article.id,
        "post_id": post.blogger_post_id,
        "url": post.published_url,
        "title": article.title,
        "pattern": article.article_pattern_key,
        "body_chars": live["body_chars"],
        "concept_score": live["concept_score"],
        "seo": article.quality_seo_score,
        "geo": article.quality_geo_score,
        "ctr": None,
        "ctr_title_score": title_score,
        "lighthouse_status": "unmeasured_external_only",
        "lighthouse_score": None,
        "image_url": image_info["public_url"],
        "related_count": live["related_count"],
        "image_count": live["image_count"],
        "unique_image_count": live["unique_image_count"],
        "validation": live,
    }


def _update_language_switches(db, group_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from app.models.entities import Article, Blog
    from app.services.content.html_assembler import upsert_language_switch_html
    from app.services.content.multilingual_bundle_service import build_language_switch_block
    from app.services.providers.factory import get_blogger_provider
    from app.tasks.pipeline import _upsert_blogger_post

    urls_by_language = {record["language"]: record["url"] for record in group_records if record.get("url")}
    updates: list[dict[str, Any]] = []
    for record in group_records:
        article = db.execute(
            select(Article)
            .where(Article.id == int(record["article_id"]))
            .options(selectinload(Article.blogger_post), selectinload(Article.blog))
        ).scalar_one()
        blog = db.execute(select(Blog).where(Blog.id == article.blog_id)).scalar_one()
        block = build_language_switch_block(current_language=record["language"], urls_by_language=urls_by_language)
        article.assembled_html = upsert_language_switch_html(article.assembled_html or "", block)
        db.add(article)
        db.flush()
        provider = get_blogger_provider(db, blog)
        summary, raw_payload = provider.update_post(
            post_id=article.blogger_post.blogger_post_id,
            title=article.title,
            content=article.assembled_html,
            labels=list(article.labels or []),
            meta_description=article.meta_description,
        )
        _upsert_blogger_post(
            db,
            job_id=article.job_id,
            blog_id=article.blog_id,
            article_id=article.id,
            summary=summary,
            raw_payload=raw_payload,
            commit=False,
        )
        html = httpx.get(record["url"], timeout=30.0, follow_redirects=True).text
        missing = [url for lang, url in urls_by_language.items() if lang != record["language"] and url not in html]
        updates.append({"language": record["language"], "url": record["url"], "missing_alternates": missing, "passed": not missing})
    return updates


def run(*, execute: bool) -> dict[str, Any]:
    _load_env()
    from app.db.session import SessionLocal
    from app.models.entities import Blog
    from app.services.blogger.blogger_sync_service import sync_blogger_posts_for_blog

    dry_rows: list[dict[str, Any]] = []
    for topic in TOPICS:
        for lang in ("en", "es", "ja"):
            dry_rows.append(_validate_local_output(lang, _build_output(lang, topic, topic["patterns"][lang])))
    if not execute:
        return {"mode": "dry_run", "local_validation": dry_rows}

    report_rows: list[dict[str, Any]] = []
    language_switch_updates: list[dict[str, Any]] = []
    image_uploads: dict[str, dict[str, Any]] = {}
    stale_cleanups: list[dict[str, Any]] = []
    with SessionLocal() as db:
        stale_cleanups = _cleanup_stale_partial_rows(db)
        for topic in TOPICS:
            image_uploads[topic["slug"]] = _upload_topic_image(db, topic)
            group_records: list[dict[str, Any]] = []
            source_article_id: int | None = None
            for lang in ("en", "es", "ja"):
                record = _publish_one(db, topic=topic, lang=lang, image_info=image_uploads[topic["slug"]], source_article_id=source_article_id)
                if lang == "en":
                    source_article_id = int(record["article_id"])
                group_records.append(record)
                report_rows.append({**record, "topic": topic["keyword"], "sync_group_key": topic["group_key"]})
            language_switch_updates.extend(_update_language_switches(db, group_records))
            db.commit()
        for blog_id in (34, 36, 37):
            blog = db.execute(select(Blog).where(Blog.id == blog_id)).scalar_one()
            sync_blogger_posts_for_blog(db, blog)
        db.commit()

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "execute",
        "total": len(report_rows),
        "passed": sum(1 for row in report_rows if row.get("validation", {}).get("validation_passed")),
        "stale_cleanups": stale_cleanups,
        "image_uploads": image_uploads,
        "language_switch_updates": language_switch_updates,
        "rows": report_rows,
    }
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    path = REPORT_ROOT / f"travel-concept-batch-publish-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    payload["report_path"] = str(path)
    return payload


def main() -> int:
    _stdout_utf8()
    parser = argparse.ArgumentParser(description="Publish the 2026-04-30 travel concept reinforcement batch.")
    parser.add_argument("--execute", action="store_true", help="Publish to Blogger. Without this flag only local validation is run.")
    args = parser.parse_args()
    result = run(execute=args.execute)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
