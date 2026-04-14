from app.services.content.html_assembler import (
    LANGUAGE_SWITCH_END_MARKER,
    LANGUAGE_SWITCH_START_MARKER,
    upsert_language_switch_html,
)


def test_upsert_language_switch_html_replaces_existing_block() -> None:
    source = (
        "<article>"
        f"{LANGUAGE_SWITCH_START_MARKER}<section>old</section>{LANGUAGE_SWITCH_END_MARKER}"
        "</article>"
    )
    updated = upsert_language_switch_html(source, "<section>new</section>")

    assert "<section>old</section>" not in updated
    assert "<section>new</section>" in updated


def test_upsert_language_switch_html_inserts_block_when_missing() -> None:
    source = "<article><p>body</p></article>"
    updated = upsert_language_switch_html(source, "<section>links</section>")

    assert LANGUAGE_SWITCH_START_MARKER in updated
    assert LANGUAGE_SWITCH_END_MARKER in updated
    assert "<section>links</section>" in updated
