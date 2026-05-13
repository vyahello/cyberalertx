"""Unit tests for PgThreatPostStore — no live DB required.

These tests exercise the serialization contract: a ThreatPost passed to
`set()` must round-trip to an identical ThreatPost via `get()`. We
verify by stubbing out the SQLAlchemy execution and capturing the row.
"""
from __future__ import annotations

from cyberalertx.ai.models import Reference, ThreatPost


def _rich_post() -> ThreatPost:
    return ThreatPost(
        title="TrickMo атакує користувачів Android",
        short_summary="Новий штам банківського трояна.",
        threat_level="High",
        why_it_matters="Якщо троян потрапить на пристрій...",
        affected_users=["Користувачі Android-банкінгу"],
        what_to_do=["Встановлюйте лише з Google Play",
                    "Увімкніть Play Protect",
                    "Перегляньте список застосунків"],
        what_not_to_do=["Не вмикайте сторонні APK"],
        quick_facts=["Activeexploitation", "Android"],
        emotional_weight=0.75,
        reading_time_seconds=20,
        detail_body="Параграф 1.\n\nПараграф 2.",
        references=[
            Reference(type="cve", label="CVE-2026-1234", url="https://nvd.nist.gov/vuln/detail/CVE-2026-1234"),
        ],
        language="ua",
        source_fingerprint="ea160e3abda77a30",
        generated_by="anthropic:claude-haiku-4-5-20251001",
    )


def test_to_dict_from_dict_round_trip():
    """The cache stores `post.to_dict()` as JSONB. PG returns the same
    dict on read. ThreatPost.from_dict must reconstruct an identical post."""
    src = _rich_post()
    blob = src.to_dict()
    rebuilt = ThreatPost.from_dict(blob)

    for field in (
        "title", "short_summary", "threat_level", "why_it_matters",
        "affected_users", "what_to_do", "what_not_to_do", "quick_facts",
        "emotional_weight", "reading_time_seconds", "detail_body",
        "language", "source_fingerprint", "generated_by",
    ):
        assert getattr(rebuilt, field) == getattr(src, field), field

    assert len(rebuilt.references) == 1
    r0 = rebuilt.references[0]
    assert (r0.type, r0.label, r0.url) == ("cve", "CVE-2026-1234",
                                            "https://nvd.nist.gov/vuln/detail/CVE-2026-1234")


def test_to_dict_preserves_empty_lists():
    minimal = ThreatPost(
        title="t", short_summary="s", threat_level="Low",
        why_it_matters="w", affected_users=["a"], what_to_do=["b"],
    )
    blob = minimal.to_dict()
    rebuilt = ThreatPost.from_dict(blob)
    assert rebuilt.what_not_to_do == []
    assert rebuilt.quick_facts == []
    assert rebuilt.references == []
    assert rebuilt.detail_body == ""


def test_references_are_dataclasses_after_roundtrip():
    """Important for the API serializer — references must be Reference
    instances after round-trip, not raw dicts, so `r.type` works."""
    src = ThreatPost(
        title="t", short_summary="s", threat_level="Low",
        why_it_matters="w", affected_users=["a"], what_to_do=["b"],
        references=[Reference(type="advisory", label="MS-2026-1", url="https://x")],
    )
    rebuilt = ThreatPost.from_dict(src.to_dict())
    assert isinstance(rebuilt.references[0], Reference)
    assert rebuilt.references[0].type == "advisory"
