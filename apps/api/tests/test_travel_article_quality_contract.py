from app.services.content import article_service


def test_travel_quality_check_blocks_duplicate_sentence() -> None:
    html = "<p>同じ判断文をここで繰り返します。</p><p>同じ判断文をここで繰り返します。</p>"

    payload = article_service._travel_content_quality_check(
        title="新しいルート判断",
        meta_description="駅から食事までの流れを整理します。",
        excerpt="混雑を避ける短い判断軸をまとめます。",
        html_article=html,
    )

    assert payload["passed"] is False
    assert "duplicate_sentence" in payload["issues"]


def test_travel_quality_check_blocks_irrelevant_water_template() -> None:
    html = "<p>公園から市場へ向かうだけのルートなのに、川沿いの余韻を強調しています。</p>"

    payload = article_service._travel_content_quality_check(
        title="Boramae Park to Sillim",
        meta_description="公園と食事動線を整理します。",
        excerpt="駅から近い順に判断します。",
        html_article=html,
    )

    assert payload["passed"] is False
    assert "route_irrelevant_water_template" in payload["issues"]


def test_travel_quality_check_allows_real_water_route() -> None:
    html = "<p>NodeulからIchonへ向かう漢江沿いの夕方ルートでは、風と橋の見え方で歩く時間を選びます。</p>"

    payload = article_service._travel_content_quality_check(
        title="Nodeul to Ichon Hangang sunset route",
        meta_description="漢江沿いの夕方動線を整理します。",
        excerpt="NodeulとIchonの間で休憩を選びます。",
        html_article=html,
    )

    assert "route_irrelevant_water_template" not in payload["issues"]
