from app.services.ops.openai_policy_drift_service import OFFICIAL_OPENAI_POLICY_URLS, build_openai_policy_drift_payload


def test_openai_policy_drift_payload_contains_official_docs_and_repo_policy() -> None:
    payload = build_openai_policy_drift_payload()

    assert payload["official_docs"] == list(OFFICIAL_OPENAI_POLICY_URLS)
    assert payload["repo_policy"]["topic_model"] == "gpt-5.4-2026-03-05"
    assert payload["repo_policy"]["article_model"] == "gpt-5.4-mini-2026-03-17"
    assert payload["repo_policy"]["default_image_prompt_model"] == "gpt-5.4-mini-2026-03-17"
    assert payload["repo_policy"]["travel_image_prompt_model"] == "gpt-4.1-mini"
    assert payload["repo_policy"]["image_model"] == "gpt-image-1"
    assert "image_probe_model" not in payload["repo_policy"]


def test_openai_policy_drift_payload_is_clean_after_prompt_sync() -> None:
    payload = build_openai_policy_drift_payload()

    assert payload["drift"]["channel_model_violations"] == []
    assert payload["drift"]["three_step_file_block_violations"] == []
    assert payload["drift"]["prompt_sync_mismatches"] == []
