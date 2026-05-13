"""Article body cleanup before AI rendering / storage.

These tests pin what kinds of feed pollution the cleanup pass strips.
The patterns are intentionally narrow — we delete content only when
its shape is unambiguously junk, not whenever a phrase happens to
contain "subscribe" inside a real sentence.
"""
from __future__ import annotations

import pytest

from cyberalertx.pipeline.normalize import clean_article_body, normalize_item
from cyberalertx.models import NewsItem
from datetime import datetime, timezone


# --------------------- pure clean_article_body ---------------------------

def test_strips_newsletter_subscribe_prompt():
    body = (
        "A new ransomware strain hits hospital networks. "
        "Subscribe to our newsletter for daily updates."
    )
    cleaned = clean_article_body(body)
    assert "Subscribe to our newsletter" not in cleaned
    assert "hospital networks" in cleaned


def test_strips_social_share_block():
    body = (
        "Researchers disclosed a new attack technique. "
        "Share this on Facebook Twitter LinkedIn."
    )
    cleaned = clean_article_body(body)
    assert "Share this on Facebook" not in cleaned
    assert "attack technique" in cleaned


def test_strips_read_more_callouts():
    body = (
        "The vulnerability was patched in 2.0.4.\n"
        "Read also: how to patch Apache.\n"
        "Continue reading on our blog."
    )
    cleaned = clean_article_body(body)
    assert "Read also" not in cleaned
    assert "Continue reading" not in cleaned
    assert "vulnerability was patched" in cleaned


def test_strips_advertising_markers():
    body = (
        "Advertisement\n"
        "A new RAT family has been observed in the wild.\n"
        "Sponsored by Acme Corp."
    )
    cleaned = clean_article_body(body)
    assert "Advertisement" not in cleaned
    assert "Sponsored by Acme Corp" not in cleaned
    assert "RAT family" in cleaned


def test_strips_copyright_tail():
    body = (
        "Microsoft published an advisory.\n"
        "© 2026 The Hacker News. All rights reserved."
    )
    cleaned = clean_article_body(body)
    assert "©" not in cleaned
    assert "All rights reserved" not in cleaned
    assert "Microsoft published" in cleaned


def test_strips_tags_categories_metadata():
    body = (
        "A new infostealer was found.\n"
        "Tags: malware, infostealer, security\n"
        "Categories: Threats, Research"
    )
    cleaned = clean_article_body(body)
    assert "Tags:" not in cleaned
    assert "Categories:" not in cleaned
    assert "infostealer was found" in cleaned


def test_strips_ukrainian_newsletter_prompts():
    body = (
        "Українські дослідники виявили нову вразливість. "
        "Підпишіться на наш Telegram-канал, щоб не пропустити новини."
    )
    cleaned = clean_article_body(body)
    assert "Підпишіться" not in cleaned
    assert "виявили нову вразливість" in cleaned


def test_strips_ukrainian_read_more():
    body = (
        "Розкрито подробиці кампанії UAC-0001. "
        "Читайте також інші матеріали про CERT-UA."
    )
    cleaned = clean_article_body(body)
    assert "Читайте також" not in cleaned
    assert "Розкрито подробиці" in cleaned


# --------------------- idempotency + safety ------------------------------

def test_cleanup_is_idempotent():
    body = (
        "A ransomware gang breached a hospital. "
        "Subscribe to our newsletter."
    )
    once = clean_article_body(body)
    twice = clean_article_body(once)
    assert once == twice


def test_cleanup_does_not_eat_real_content_about_subscriptions():
    """If 'subscribe' appears inside a real sentence (not as a CTA), it
    should survive. The patterns anchor to known CTA forms, not the word
    'subscribe' in isolation."""
    body = (
        "Attackers tricked victims into subscribing to a fake VPN service "
        "and harvested their credentials."
    )
    cleaned = clean_article_body(body)
    assert "subscribing to a fake VPN" in cleaned


def test_cleanup_collapses_whitespace_from_removed_content():
    body = (
        "First sentence.\n"
        "Subscribe to our newsletter for updates.\n"
        "Second sentence."
    )
    cleaned = clean_article_body(body)
    # No giant gap where the newsletter line used to live.
    assert "  " not in cleaned  # collapse double-spaces
    assert "First sentence" in cleaned and "Second sentence" in cleaned


def test_cleanup_caps_oversized_bodies():
    body = "Real sentence." + " filler" * 2000
    cleaned = clean_article_body(body)
    assert len(cleaned) <= 3050  # _MAX_BODY_CHARS + small slack


def test_empty_body_returns_empty_string():
    assert clean_article_body("") == ""
    assert clean_article_body("   ") == ""


# --------------------- integration with normalize_item -------------------

def test_normalize_item_applies_cleanup():
    """`normalize_item` must run the cleanup pass — that's the only entry
    point the orchestrator uses, so a regression here would silently
    let pollution back into the AI input."""
    item = NewsItem(
        title="Phishing campaign discovered",
        source="t",
        url="https://example.test/x",
        published_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        raw_content=(
            "Researchers found a phishing kit. "
            "Subscribe to our newsletter for daily security updates."
        ),
    )
    normalize_item(item)
    assert "Subscribe to our newsletter" not in item.raw_content
    assert "phishing kit" in item.raw_content
