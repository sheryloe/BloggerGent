from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg2://bloggent:bloggent@127.0.0.1:15432/bloggent")
os.environ.setdefault("SETTINGS_ENCRYPTION_SECRET", "bloggent-dockerdesktop-2026-03-17")
sys.path.insert(0, str(API_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from sqlalchemy import select  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import ContentPlanSlot, SyncedCloudflarePost  # noqa: E402
from app.services.cloudflare.cloudflare_channel_service import (  # noqa: E402
    _integration_data_or_raise,
    _integration_request,
)
from app.services.cloudflare.cloudflare_sync_service import sync_cloudflare_posts  # noqa: E402
from app.services.content.content_ops_service import compute_seo_geo_scores  # noqa: E402


def _strip_leading_h1(content: str) -> str:
    text = (content or "").strip()
    if not text.startswith("# "):
        return text
    parts = text.split("\n", 2)
    if len(parts) == 1:
        return ""
    if len(parts) == 2:
        return parts[1].strip()
    if not parts[1].strip():
        return parts[2].strip()
    return "\n".join(parts[1:]).strip()


def _compose_content(*, title: str, intro_html: str, existing_content: str) -> str:
    existing_body = _strip_leading_h1(existing_content)
    return f"# {title}\n\n{textwrap.dedent(intro_html).strip()}\n\n{existing_body}".strip()


UPDATES: dict[str, dict] = {
    "4b6db3a8-327d-4c8b-9565-5405d61f19fd": {
        "title": "심리 미스터리 단편: 기억과 정체성의 경계 탐험",
        "excerpt": "기억이 진짜인지, 내가 누구인지 흔들리는 순간을 좇는 심리 미스터리 단편이다. 기록과 정황, 해석을 나눠 읽으며 불안과 몰입이 교차하는 지점을 따라간다.",
        "seo_description": "심리 미스터리 단편으로 기억과 정체성의 경계를 따라가며 기록, 정황, 해석을 차분하게 정리한다.",
        "intro_html": """
        <article>
          <section class="fact-box">
            <h2>이 이야기를 먼저 읽어야 하는 이유</h2>
            <p>어떤 사람은 사고 뒤에 자신의 기억을 믿지 못하게 되고, 어떤 사람은 분명히 아는 얼굴 앞에서도 내가 누구였는지 확신하지 못합니다. 이번 글은 초현상보다 심리의 균열에 더 가까운 미스터리입니다. 사건이 커지는 방식보다, 기억이 어떻게 조용히 어긋나고 정체성이 어디에서 흔들리는지를 따라갑니다.</p>
          </section>
          <section class="chat-thread">
            <div><strong>기록:</strong> 처음 이상 신호는 사소했습니다. 익숙한 장소가 낯설어 보이고, 이미 끝낸 일을 처음 겪는 것처럼 느끼는 장면이 반복됐습니다.</div>
            <div><strong>정황:</strong> 주변 사람들의 말과 본인의 기억이 조금씩 어긋나면서, 사실보다 확신이 더 빠르게 무너졌습니다.</div>
            <div><strong>해석:</strong> 이 글은 기억 상실 그 자체보다 기억의 빈칸이 정체성의 감각을 어떻게 흔드는지에 초점을 둡니다.</div>
            <div><strong>현재 추적 상태:</strong> 단정 대신 기록을 남기고, 어디까지가 사실이고 어디부터가 해석인지 한 줄씩 분리해 읽는 방식으로 따라갑니다.</div>
          </section>
        </article>
        """,
    },
    "788bc8b6-d888-41cc-b15c-3ff38774edaa": {
        "title": "일상 속 생산성 향상 팁 2026 | 시간 관리와 집중력 강화법",
        "excerpt": "할 일은 많은데 집중이 자꾸 끊길 때 바로 써먹기 좋은 생산성 루틴을 정리했다. 시간 블록, 메신저 차단, 휴대폰 거리 두기, 저녁 정리 순서까지 생활형으로 풀었다.",
        "seo_description": "시간 관리와 집중력 강화에 바로 써먹기 좋은 생산성 팁을 실전 루틴 중심으로 정리한 2026 가이드.",
        "intro_html": """
        <article>
          <section class="fact-box">
            <h2>생산성이 떨어질 때 먼저 바꿔야 할 것</h2>
            <p>생산성은 의지보다 환경의 영향을 더 많이 받습니다. 하루 계획을 세우는 것보다 먼저 해야 할 일은 집중이 끊기는 지점을 줄이는 것입니다. 이 글은 거창한 시스템보다 실제로 유지되는 시간 관리와 집중력 강화 루틴에 맞춥니다.</p>
          </section>
          <section class="chat-thread">
            <div><strong>핵심 1:</strong> 오전에는 두 시간만이라도 한 가지 작업을 길게 잡고, 메신저와 알림은 작업이 끝난 뒤 묶어서 확인합니다.</div>
            <div><strong>핵심 2:</strong> 할 일을 세분화하기보다 오늘 반드시 끝낼 한 가지와 미뤄도 되는 두 가지를 나눠야 집중이 살아납니다.</div>
            <div><strong>핵심 3:</strong> 휴대폰을 손 닿지 않는 곳에 두고, 저녁에는 다음 날 첫 작업만 미리 정해두면 아침 진입 속도가 빨라집니다.</div>
          </section>
        </article>
        """,
    },
    "f05402b7-d93a-442d-81ac-ae1352762495": {
        "title": "자기계발을 위한 작은 습관 2026 | 꾸준함이 만드는 변화",
        "excerpt": "큰 목표보다 작은 반복이 오래 간다. 하루 10분 정리, 기록 한 줄, 산책 한 바퀴처럼 지치지 않는 자기계발 습관을 생활 리듬에 맞춰 정리했다.",
        "seo_description": "작은 습관을 생활 리듬에 붙여 꾸준함을 만드는 자기계발 실전 루틴을 2026 기준으로 정리했다.",
        "intro_html": """
        <article>
          <section class="fact-box">
            <h2>작은 습관이 오래 남는 이유</h2>
            <p>자기계발이 오래 가지 않는 가장 큰 이유는 목표가 커서가 아니라, 매일 다시 시작하기 어렵기 때문입니다. 이 글은 의욕이 넘치는 날보다 피곤한 날에도 이어갈 수 있는 작은 습관에 집중합니다. 꾸준함은 강한 결심보다 낮은 진입장벽에서 나옵니다.</p>
          </section>
          <section class="chat-thread">
            <div><strong>루틴 1:</strong> 하루를 바꾸려면 1시간 계획보다 10분 정리가 먼저입니다. 책상 하나, 메모 한 줄, 물 한 컵처럼 출발 동작을 짧게 잡아야 합니다.</div>
            <div><strong>루틴 2:</strong> 운동도 공부도 기록도 모두 같은 원리입니다. 양을 늘리기보다 끊기지 않는 빈도를 먼저 만들면 변화가 눈에 보이기 시작합니다.</div>
            <div><strong>루틴 3:</strong> 스스로를 평가하는 시간보다 다음 한 번을 정하는 시간이 더 중요합니다. 오늘 실패해도 내일 다시 붙일 수 있는 습관이 오래 갑니다.</div>
          </section>
        </article>
        """,
    },
    "6878094e-2d5f-4823-893f-e18bca10ddef": {
        "title": "강릉 사천해변 봄 드라이브 가이드 2026 | 한적한 바다 산책, 카페 동선, 주차 팁",
        "excerpt": "복잡한 유명 해변 대신 한 템포 느리게 바다를 보고 싶을 때 강릉 사천해변이 잘 맞는다. 봄철 드라이브 동선, 산책 포인트, 카페 쉬는 타이밍, 주차 팁까지 실제 방문 흐름처럼 정리했다.",
        "seo_description": "강릉 사천해변 봄 드라이브 코스를 한적한 바다 산책, 카페 동선, 주차 팁 중심으로 정리한 2026 가이드.",
        "intro_html": """
        <article>
          <section class="fact-box">
            <h2>사천해변이 봄 드라이브에 잘 맞는 이유</h2>
            <p>강릉에서 유명한 해변은 많지만, 사람에 치이지 않고 바다를 길게 보고 싶다면 사천해변 쪽이 훨씬 편합니다. 차를 세우고 잠깐 걷기 좋고, 바닷바람이 너무 세지 않은 날에는 산책 리듬을 만들기도 쉽습니다. 이번 글은 실제로 도착해서 어디에 세우고, 어느 방향으로 걷고, 언제 카페에 들어가 쉬면 좋은지 순서대로 풀었습니다.</p>
          </section>
          <section class="chat-thread">
            <div><strong>동선:</strong> 먼저 바다를 짧게 보고 카페로 들어가는 것보다, 해변 끝까지 천천히 걸은 뒤 따뜻한 음료로 마무리하는 편이 만족도가 높습니다.</div>
            <div><strong>주차:</strong> 주말 점심 전후에는 가까운 공간이 빨리 차므로 조금 여유 있게 도착해 해변 가까운 구역부터 확인하는 편이 좋습니다.</div>
            <div><strong>현장감:</strong> 사천해변의 장점은 화려함보다 여백입니다. 사진도 넓은 수평선과 낮은 파도선이 잘 살아서 과하게 꾸미지 않아도 분위기가 납니다.</div>
          </section>
        </article>
        """,
    },
    "2d3084d6-d92a-4173-8887-bf4a9a6d8ddd": {
        "title": "아이온큐 흐름 점검 2026-04-12 | 동그리 vs 햄그리 대화로 보는 IONQ 관전 포인트",
        "excerpt": "IonQ를 지금 다시 봐야 하는 이유를 동그리와 햄그리의 대화로 정리했다. 양자컴퓨팅 기대감, 실적 가시성, 밸류에이션 부담, 단기 모멘텀과 중장기 시나리오를 함께 본다.",
        "seo_description": "아이온큐 IONQ의 최근 흐름을 동그리와 햄그리의 대화 형식으로 정리한 미국주식의 흐름 2026-04-12 글.",
        "metadata": {
            "series_variant": "us-stock-dialogue-v1",
            "company_name": "IonQ",
            "ticker": "IONQ",
            "exchange": "NYSE",
            "chart_provider": "tradingview",
            "chart_symbol": "NYSE:IONQ",
            "chart_interval": "1D",
            "viewpoints": ["동그리", "햄그리"],
            "slide_sections": [
                {
                    "title": "오늘 왜 IONQ를 보나",
                    "summary": "양자컴퓨팅 대표 테마주라는 기대와 실제 수주 가시성 사이의 간극을 확인해야 하는 날이다.",
                    "speaker": "동그리",
                    "key_points": ["테마 강도", "밸류에이션", "실적 가시성"],
                },
                {
                    "title": "동그리의 보수적 관점",
                    "summary": "기술 기대는 크지만 단기 실적과 계약의 질을 먼저 확인해야 한다는 입장이다.",
                    "speaker": "동그리",
                    "key_points": ["과열 경계", "현금흐름", "실적 확인"],
                },
                {
                    "title": "햄그리의 공격적 관점",
                    "summary": "테마주 특성상 뉴스 흐름과 시장 관심이 살아 있을 때 강한 추세가 이어질 수 있다는 입장이다.",
                    "speaker": "햄그리",
                    "key_points": ["모멘텀", "뉴스 반응", "변동성 활용"],
                },
                {
                    "title": "서로의 반박",
                    "summary": "과열 우려와 선반영 논리가 충돌하는 구간을 짚는다.",
                    "speaker": "대화",
                    "key_points": ["선반영", "추격매수", "리스크 관리"],
                },
                {
                    "title": "체크포인트",
                    "summary": "다음 실적, 신규 계약, 시장 전체 위험선호가 핵심 변수다.",
                    "speaker": "대화",
                    "key_points": ["실적 발표", "신규 계약", "시장 분위기"],
                },
            ],
        },
        "intro_html": """
        <article>
          <section class="fact-box">
            <h2>오늘 왜 IONQ를 다시 보나</h2>
            <p>아이온큐는 양자컴퓨팅이라는 강한 미래 서사를 타고 움직이는 대표 종목입니다. 하지만 기대감이 강한 만큼 밸류에이션 부담과 실적 가시성 논란도 함께 따라옵니다. 그래서 이 글은 방향을 단정하기보다, 지금 IONQ를 볼 때 어떤 질문을 먼저 던져야 하는지에 맞춥니다.</p>
          </section>
          <section class="chat-thread">
            <div><strong>동그리:</strong> 나는 먼저 계약의 질과 매출 가시성을 봐야 한다고 생각해. 기술 스토리가 강한 종목일수록 실적 확인 전에는 추격 매수가 부담스럽거든.</div>
            <div><strong>햄그리:</strong> 반대로 이런 종목은 뉴스와 관심이 살아 있을 때 흐름이 길게 이어지기도 해. 변동성이 크다는 점을 알고 들어가면 오히려 기회가 빨리 보인다고 봐.</div>
            <div><strong>동그리:</strong> 결국 핵심은 기대와 실적의 간극이야. 다음 분기 발표에서 그 간극이 줄어드는지 확인해야 해.</div>
            <div><strong>햄그리:</strong> 맞아. 그래서 나는 손절 기준과 분할 진입 기준을 먼저 세우고 모멘텀을 따라갈지 판단하겠어.</div>
          </section>
        </article>
        """,
    },
    "2206556b-e286-4ebe-9cbc-0fb630b9ce94": {
        "title": "샌디스크 흐름 점검 2026-04-12 | 동그리 vs 햄그리 대화로 보는 SNDK 관전 포인트",
        "excerpt": "Sandisk를 다시 볼 때 필요한 질문을 동그리와 햄그리의 대화로 정리했다. 낸드 업황, 메모리 가격 사이클, 수익성 회복 속도, 단기 탄력과 보수적 대응 기준을 함께 짚는다.",
        "seo_description": "샌디스크 SNDK의 최근 흐름을 동그리와 햄그리의 대화 형식으로 정리한 미국주식의 흐름 2026-04-12 글.",
        "metadata": {
            "series_variant": "us-stock-dialogue-v1",
            "company_name": "Sandisk",
            "ticker": "SNDK",
            "exchange": "NASDAQ",
            "chart_provider": "tradingview",
            "chart_symbol": "NASDAQ:SNDK",
            "chart_interval": "1D",
            "viewpoints": ["동그리", "햄그리"],
            "slide_sections": [
                {
                    "title": "오늘 왜 SNDK를 보나",
                    "summary": "메모리 가격 사이클과 낸드 업황 회복 기대가 동시에 붙는 시점이기 때문이다.",
                    "speaker": "동그리",
                    "key_points": ["낸드 업황", "가격 회복", "수익성"],
                },
                {
                    "title": "동그리의 보수적 관점",
                    "summary": "업황 회복 초입에서는 숫자로 확인되기 전까지 낙관을 제한해야 한다는 입장이다.",
                    "speaker": "동그리",
                    "key_points": ["실적 확인", "재고", "마진"],
                },
                {
                    "title": "햄그리의 공격적 관점",
                    "summary": "메모리 사이클은 기대가 먼저 움직이는 만큼 초반 탄력을 활용할 수 있다는 입장이다.",
                    "speaker": "햄그리",
                    "key_points": ["사이클", "선행 반응", "추세"],
                },
                {
                    "title": "서로의 반박",
                    "summary": "업황 회복 기대와 실적 확인 사이의 시간차가 핵심 논쟁 포인트다.",
                    "speaker": "대화",
                    "key_points": ["시간차", "선반영", "리스크 관리"],
                },
                {
                    "title": "체크포인트",
                    "summary": "메모리 가격, 재고, 가이던스가 다음 방향을 결정한다.",
                    "speaker": "대화",
                    "key_points": ["가격", "재고", "가이던스"],
                },
            ],
        },
        "intro_html": """
        <article>
          <section class="fact-box">
            <h2>오늘 왜 SNDK를 보나</h2>
            <p>샌디스크 흐름은 메모리 업황 회복 기대와 실적 확인 사이에서 흔들리는 대표 사례로 볼 수 있습니다. 낸드 업황이 살아난다는 기대가 먼저 주가를 움직일 수 있지만, 실제 마진 회복이 늦으면 탄력이 빠르게 꺾일 수도 있습니다. 그래서 이 종목은 낙관과 경계가 동시에 필요한 편입니다.</p>
          </section>
          <section class="chat-thread">
            <div><strong>동그리:</strong> 나는 메모리주는 결국 숫자로 확인될 때 더 편해. 재고와 마진이 안정됐다는 신호가 나오기 전엔 기대만으로 오래 버티기 어렵다고 보거든.</div>
            <div><strong>햄그리:</strong> 그렇지만 업황주는 늘 숫자보다 먼저 움직여. 회복 초입의 기대가 붙을 때 추세가 세게 나오는 경우가 많아서 타이밍을 너무 늦추면 맛있는 구간을 놓칠 수 있어.</div>
            <div><strong>동그리:</strong> 그래서 더더욱 손실 기준이 필요해. 업황 회복이 지연되면 주가도 바로 압박받으니까.</div>
            <div><strong>햄그리:</strong> 동의해. 공격적으로 보더라도 분할 진입과 이벤트 체크는 필수야.</div>
          </section>
        </article>
        """,
    },
}


def main() -> int:
    remote_ids = list(UPDATES.keys())

    with SessionLocal() as db:
        updated_payloads: dict[str, dict] = {}
        for remote_id, spec in UPDATES.items():
            response = _integration_request(db, method="GET", path=f"/api/integrations/posts/{remote_id}", timeout=45.0)
            existing = _integration_data_or_raise(response)
            if not isinstance(existing, dict):
                raise ValueError(f"Invalid Cloudflare post payload for {remote_id}")

            existing_content = str(existing.get("content") or "").strip()
            if not existing_content:
                raise ValueError(f"Cloudflare post content missing for {remote_id}")

            title = str(spec["title"]).strip()
            excerpt = str(spec["excerpt"]).strip()
            seo_description = str(spec["seo_description"]).strip()
            content = _compose_content(
                title=title,
                intro_html=str(spec["intro_html"]),
                existing_content=existing_content,
            )
            tag_names = [
                str(tag.get("name") or "").strip()
                for tag in (existing.get("tags") or [])
                if isinstance(tag, dict) and str(tag.get("name") or "").strip()
            ]
            category = existing.get("category") if isinstance(existing.get("category"), dict) else {}
            category_id = str(category.get("id") or "").strip()
            if not category_id:
                raise ValueError(f"Cloudflare category id missing for {remote_id}")

            payload = {
                "title": title,
                "content": content,
                "excerpt": excerpt,
                "seoTitle": title,
                "seoDescription": seo_description,
                "tagNames": tag_names,
                "categoryId": category_id,
                "status": "published",
                "coverImage": existing.get("coverImage"),
                "coverAlt": existing.get("coverAlt"),
            }
            metadata = spec.get("metadata")
            if isinstance(metadata, dict):
                payload["metadata"] = metadata

            update_response = _integration_request(
                db,
                method="PUT",
                path=f"/api/integrations/posts/{remote_id}",
                json_payload=payload,
                timeout=120.0,
            )
            updated = _integration_data_or_raise(update_response)
            updated_payloads[remote_id] = {
                "title": title,
                "excerpt": excerpt,
                "content": content,
                "metadata": metadata if isinstance(metadata, dict) else {},
                "remote_payload": updated if isinstance(updated, dict) else {},
            }

        sync_cloudflare_posts(db, include_non_published=True)

        synced_rows = (
            db.execute(select(SyncedCloudflarePost).where(SyncedCloudflarePost.remote_post_id.in_(remote_ids)))
            .scalars()
            .all()
        )
        synced_map = {str(row.remote_post_id): row for row in synced_rows}

        for remote_id, applied in updated_payloads.items():
            row = synced_map.get(remote_id)
            if row is None:
                continue
            seo_geo = compute_seo_geo_scores(
                title=applied["title"],
                html_body=applied["content"],
                excerpt=applied["excerpt"],
                faq_section=[],
            )
            row.title = applied["title"]
            row.excerpt_text = applied["excerpt"]
            row.seo_score = float(seo_geo.get("seo_score", 0) or 0)
            row.geo_score = float(seo_geo.get("geo_score", 0) or 0)
            row.ctr = float(seo_geo.get("ctr_score", 0) or 0)
            if applied["metadata"]:
                row.render_metadata = applied["metadata"]
            db.add(row)

        slot_rows = db.execute(select(ContentPlanSlot).where(ContentPlanSlot.id.in_([214, 215, 216]))).scalars().all()
        slot_post_map = {str((slot.result_payload or {}).get("post_id") or ""): slot for slot in slot_rows}
        for remote_id, applied in updated_payloads.items():
            slot = slot_post_map.get(remote_id)
            if slot is None or not isinstance(slot.result_payload, dict):
                continue
            payload = dict(slot.result_payload)
            payload["title"] = applied["title"]
            remote_payload = applied.get("remote_payload") or {}
            public_url = str(remote_payload.get("publicUrl") or payload.get("public_url") or "").strip()
            if public_url:
                payload["public_url"] = public_url
            slot.result_payload = payload
            db.add(slot)

        db.commit()

        for remote_id in remote_ids:
            row = synced_map.get(remote_id)
            if row is None:
                continue
            print(
                f"{remote_id} | {row.title} | SEO={row.seo_score} GEO={row.geo_score} CTR={row.ctr} "
                f"| metadata={'yes' if row.render_metadata else 'no'}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
