from app.services.content.faq_hygiene import (
    filter_generic_faq_items,
    strip_generic_faq_leak_html,
    strip_generic_faq_leak_html_with_stats,
)


def test_filter_generic_faq_items_removes_english_boilerplate() -> None:
    items = [
        {
            "question": "What should readers know about Yeonnam-dong?",
            "answer": "This section summarizes the essential context, expectations, and constraints around Yeonnam-dong so readers can act with confidence.",
        },
        {
            "question": "What time should I visit Yeonnam-dong?",
            "answer": "Early evening is usually best for a quieter walk and cafe stops.",
        },
    ]

    filtered = filter_generic_faq_items(items)

    assert len(filtered) == 1
    assert filtered[0]["question"] == "What time should I visit Yeonnam-dong?"


def test_strip_generic_faq_leak_html_removes_static_faq_block_with_hangul() -> None:
    source = """
<h2>Frequently Asked Questions</h2>
<p>What should readers know about 덕수궁 석조전 야간 투어 예약과 문화 코스 계획법?</p>
<p>How can readers apply 덕수궁 석조전 야간 투어 예약과 문화 코스 계획법 effectively?</p>
<h2>Trip Plan</h2>
<p>Keep this section.</p>
""".strip()

    cleaned = strip_generic_faq_leak_html(source)

    assert "Frequently Asked Questions" not in cleaned
    assert "What should readers know about" not in cleaned
    assert "How can readers apply" not in cleaned
    assert "<h2>Trip Plan</h2>" in cleaned
    assert "Keep this section." in cleaned


def test_strip_generic_faq_leak_html_removes_generic_faq_block_without_hangul() -> None:
    source = """
<h2>Frequently Asked Questions</h2>
<p>What should readers know about Deoksugung night tour?</p>
<p>This section summarizes the essential context, expectations, and constraints around Deoksugung night tour so readers can act with confidence.</p>
<h2>After FAQ</h2>
<p>This should remain.</p>
""".strip()

    cleaned = strip_generic_faq_leak_html(source)

    assert "Frequently Asked Questions" not in cleaned
    assert "What should readers know about" not in cleaned
    assert "This section summarizes the essential context" not in cleaned
    assert "<h2>After FAQ</h2>" in cleaned


def test_strip_generic_faq_leak_html_preserves_details_faq() -> None:
    source = """
<details>
  <summary>What should readers know about 덕수궁 석조전 야간 투어 예약과 문화 코스 계획법?</summary>
  <p>Inside details block must be preserved.</p>
</details>
<p>Regular paragraph stays.</p>
""".strip()

    cleaned = strip_generic_faq_leak_html(source)

    assert "<details>" in cleaned
    assert "What should readers know about" in cleaned
    assert "Inside details block must be preserved." in cleaned
    assert "Regular paragraph stays." in cleaned


def test_strip_generic_faq_leak_html_with_stats_reports_counts() -> None:
    source = """
<h2>Frequently Asked Questions</h2>
<p>What should readers know about 덕수궁 석조전 야간 투어 예약과 문화 코스 계획법?</p>
<p>How can readers apply 덕수궁 석조전 야간 투어 예약과 문화 코스 계획법 effectively?</p>
<details>
  <summary>What should readers know about 덕수궁 석조전 야간 투어 예약과 문화 코스 계획법?</summary>
  <p>Preserve this details content.</p>
</details>
""".strip()

    cleaned, stats = strip_generic_faq_leak_html_with_stats(source)

    assert "Frequently Asked Questions" not in cleaned
    assert stats["faq_static_block_removed_count"] == 1
    assert stats["question_line_removed_count"] >= 2
    assert stats["details_preserved_count"] == 1
