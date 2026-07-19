"""Tests for context filtering and PII stripping."""

from server.sanitize import (
    REDACTED,
    anonymize_participant,
    context_to_prompt_block,
    sanitize_context,
    scrub_text,
)
from server.schemas import UIContext, UIMetric, UISection


def test_unknown_keys_are_dropped_by_schema():
    ctx = UIContext.model_validate(
        {
            "page": "dashboard",
            "auth_token": "should-not-survive",
            "raw_imu_stream": [1, 2, 3],
            "visible_sections": [
                {"id": "a", "label": "A", "description": "d", "internal_notes": "secret"}
            ],
        }
    )
    dumped = ctx.model_dump()
    assert "auth_token" not in dumped
    assert "raw_imu_stream" not in dumped
    assert "internal_notes" not in dumped["visible_sections"][0]


def test_scrub_removes_token_like_strings():
    text = "key AQ0Ab8RN6JS2JHUq1JFI4MvSZZ9NadSmVl3drzbrJp44Cm is here"
    cleaned = scrub_text(text)
    assert "AQ0Ab8RN6JS2JHUq1JFI4Mv" not in cleaned
    assert REDACTED in cleaned


def test_scrub_removes_auth_fragments():
    assert "Bearer" not in scrub_text("Authorization: Bearer abc123") or REDACTED in scrub_text(
        "Authorization: Bearer abc123"
    )
    assert REDACTED in scrub_text("api_key=sk-something")


def test_scrub_removes_emails():
    cleaned = scrub_text("contact mary.smith@example.com for help")
    assert "mary.smith@example.com" not in cleaned
    assert REDACTED in cleaned


def test_scrub_keeps_normal_ui_text():
    text = "Shows the most recent standardized path-tracing attempt."
    assert scrub_text(text) == text


def test_anonymize_participant_names():
    text = "Latest session for Margaret shows improvement"
    cleaned = anonymize_participant(text, {"Margaret"})
    assert "Margaret" not in cleaned
    assert "the participant" in cleaned


def test_sanitize_context_scrubs_all_text_fields():
    ctx = UIContext(
        page="dashboard",
        page_title="Dashboard for mary.smith@example.com",
        visible_sections=[
            UISection(id="s1", label="Sessions", description="token=abcdefghijklmnopqrstuvwxyz123456")
        ],
        visible_metrics=[
            UIMetric(label="Accuracy", value="82.0", help_text="normal help text")
        ],
    )
    clean = sanitize_context(ctx)
    assert "mary.smith@example.com" not in clean.page_title
    assert "abcdefghijklmnopqrstuvwxyz123456" not in clean.visible_sections[0].description
    # Legitimate fields survive.
    assert clean.visible_metrics[0].label == "Accuracy"
    assert clean.visible_metrics[0].value == "82.0"
    assert clean.visible_metrics[0].help_text == "normal help text"


def test_prompt_block_contains_only_expected_content():
    ctx = UIContext(
        page="dashboard",
        page_title="RehabTrace Dashboard",
        visible_sections=[UISection(id="s", label="Sessions", description="List of sessions")],
        visible_metrics=[UIMetric(label="Accuracy", value="82.0", help_text="closeness to path")],
    )
    block = context_to_prompt_block(ctx)
    assert "Page: dashboard" in block
    assert "Sessions — List of sessions" in block
    assert "Accuracy: 82.0 (closeness to path)" in block


def test_prompt_block_handles_empty_context():
    block = context_to_prompt_block(UIContext())
    assert "Page: unknown" in block
