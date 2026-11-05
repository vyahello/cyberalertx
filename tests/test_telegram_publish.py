"""Tests for the Telegram publishing layer.

Everything is injected — no real Telegram I/O, no disk beyond `tmp_path`.
Covers the selection bar, HTML formatting/escaping, the JSONL ledger's
dedup + persistence, and the end-to-end `publish_once` orchestration
(tier filter, language gate, dedup, uncached-skip, dry-run, live send).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from cyberalertx.models import NewsItem
from cyberalertx.publish.config import TelegramSettings
from cyberalertx.publish.format import deep_link, quality_problem, render_message
from cyberalertx.publish.ledger import PublishLedger
from cyberalertx.publish.service import publish_once, qualifies
from cyberalertx.publish.telegram import TelegramError


# --------------------- helpers --------------------------------------------

def _item(url_id: str, *, language: str = "en", tier: str = "trusted",
          published: datetime | None = None) -> NewsItem:
    return NewsItem(
        title=f"story {url_id}",
        source="BleepingComputer",
        url=f"https://e.test/{url_id}",
        published_at=published or datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
        raw_content="",
        language=language,
        source_tier=tier,
    )


def _payload(item: NewsItem, locale: str, *, level: str = "High",
             actionability: str = "informational",
             title: str = "Title", summary: str = "A summary.",
             plain: str = "",
             actions: list[str] | None = None,
             facts: list[str] | None = None,
             source: str = "BleepingComputer") -> dict[str, Any]:
    return {
        "id": item.fingerprint,
        "source": source,
        "threat_level": level,
        "actionability_level": actionability,
        "translations": {
            locale: {
                "title": title,
                "short_summary": summary,
                "plain_summary": plain,
                "what_to_do": actions or [],
                "quick_facts": facts or [],
            }
        },
    }


def _settings(**overrides: Any) -> TelegramSettings:
    base: dict[str, Any] = dict(
        bot_token="test-token",
        channels={"en": "@cax_en", "ua": "@cax_ua"},
        min_level="High",
        limit=5,
        send_delay_seconds=0.0,  # no sleeping in tests
        public_base_url="https://cyberalertx.com",
    )
    base.update(overrides)
    return TelegramSettings(**base)


class _FakeService:
    """Stand-in for _PostService — fixed items + a (fingerprint,locale)→payload map."""

    def __init__(self, items: list[NewsItem],
                 rendered: dict[tuple[str, str], dict[str, Any]]) -> None:
        self._items = items
        self._rendered = rendered

    def list_items(self) -> list[NewsItem]:
        return list(self._items)

    def render_if_cached(self, item: NewsItem, *, required_locale: str | None = None):
        return self._rendered.get((item.fingerprint, required_locale))


class _FakePublisher:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self._next_id = 1000

    def send_message(self, chat_id: str, text: str, **_kw: Any) -> int:
        self._next_id += 1
        self.sent.append((chat_id, text))
        return self._next_id

    def close(self) -> None:
        pass


class _FailingPublisher:
    """Always raises a given TelegramError; counts how many sends were tried."""

    def __init__(self, error: TelegramError) -> None:
        self._error = error
        self.attempts = 0

    def send_message(self, chat_id: str, text: str, **_kw: Any) -> int:
        self.attempts += 1
        raise self._error

    def close(self) -> None:
        pass


# --------------------- qualifies (the selection bar) ----------------------

def test_qualifies_severity_bar() -> None:
    s = _settings(min_level="High")
    assert qualifies({"threat_level": "Critical"}, s) is True
    assert qualifies({"threat_level": "High"}, s) is True
    assert qualifies({"threat_level": "Medium"}, s) is False
    assert qualifies({"threat_level": "Low"}, s) is False


def test_qualifies_urgent_overrides_low_severity() -> None:
    s = _settings(min_level="High")
    # A Medium that's under active exploitation still qualifies on urgency.
    assert qualifies(
        {"threat_level": "Medium", "actionability_level": "urgent_action"}, s
    ) is True


# --------------------- formatting -----------------------------------------



def test_plain_summary_leads_then_the_specifics_follow() -> None:
    """Plain language leads, and the technical line follows when it adds facts.

    The message used to render `plain_summary` alone. But that field's
    contract forbids CVE ids, vendor acronyms and attribution, so it names no
    product and no number on the overwhelming majority of cached posts — a
    subscriber read "хакери зламують сервери через популярну програмну
    складову" while the cache already held the named library. Both lines ship
    now: the everyday sentence first, the specifics second.
    """
    item = _item("plain")
    payload = _payload(
        item, "en",
        title="Apple ships emergency iPhone fix",
        summary="Apple reports a zero-click CoreText flaw, CVE-2026-1, exploited in the wild.",
        plain="A booby-trapped text can take over your iPhone — update now.",
    )
    msg = render_message(payload, locale="en", base_url="https://cyberalertx.com")
    plain_at = msg.index("A booby-trapped text can take over your iPhone")
    detail_at = msg.index("CoreText")
    assert plain_at < detail_at, "the everyday sentence must come first"
    assert "CVE-2026-1" in msg


def test_second_paragraph_is_dropped_when_it_adds_nothing() -> None:
    """A `short_summary` that names no product, actor or number the plain lead
    lacks is a restatement, and restating the lead in different words wastes
    the reader's attention."""
    item = _item("dup")
    payload = _payload(
        item, "en",
        title="Router bug",
        summary="Attackers can take over the device remotely.",
        plain="Attackers can take over the device remotely.",
    )
    msg = render_message(payload, locale="en", base_url="https://cyberalertx.com")
    assert msg.count("take over the device remotely") == 1


def test_render_message_escapes_html() -> None:
    item = _item("b")
    payload = _payload(item, "en", title="A <script> & B",
                       summary="x < y & z > w")
    msg = render_message(payload, locale="en", base_url="https://cyberalertx.com")
    assert "<script>" not in msg
    assert "&lt;script&gt;" in msg
    assert "&amp;" in msg






def test_render_message_missing_translation_raises() -> None:
    item = _item("d")
    payload = _payload(item, "en")
    with pytest.raises(ValueError):
        render_message(payload, locale="ua", base_url="https://cyberalertx.com")


def test_source_is_named_once() -> None:
    """The outlet is named, because nothing else in the message names it.

    This used to be omitted on the reasoning that the AI summary already
    carried the outlet. That holds for `short_summary`, but the message leads
    with `plain_summary`, whose contract forbids an attribution clause, and
    the link preview is pinned to our own deep link — so an unattributed
    claim was reaching subscribers.
    """
    item = _item("s")
    payload = _payload(item, "en", source="Krebs on Security")
    msg = render_message(payload, locale="en", base_url="https://cyberalertx.com")
    assert "Source: Krebs on Security" in msg




# --------------------- pre-send quality gate ------------------------------

def test_quality_problem_passes_good_post() -> None:
    item = _item("g")
    payload = _payload(item, "ua", title="Критична вразливість у ABB",
                       summary="CISA повідомляє про серйозну проблему.")
    assert quality_problem(payload, locale="ua") is None


def test_quality_problem_flags_missing_translation() -> None:
    item = _item("g")
    payload = _payload(item, "en")
    assert quality_problem(payload, locale="ua") is not None


def test_quality_problem_flags_wrong_script_summary() -> None:
    item = _item("g")
    # UA title but an English summary body — the half-translated case render()
    # doesn't catch (it only script-checks the title).
    payload = _payload(
        item, "ua",
        title="Критична вразливість у системі керування ABB AC500",
        summary="CISA reports a critical remote code execution vulnerability "
                "affecting industrial controllers worldwide right now.",
    )
    assert quality_problem(payload, locale="ua") is not None


def test_publish_once_skips_invalid_post(tmp_path: Path) -> None:
    item = _item("u", language="ua")
    # Wrong-script summary → should be gated out, not sent.
    payload = _payload(
        item, "ua", level="Critical",
        title="Критична вразливість у промисловому контролері ABB AC500 V3",
        summary="A long English sentence that clearly is not Ukrainian text "
                "at all and should trip the wrong-script summary guard here.",
    )
    svc = _FakeService([item], {(item.fingerprint, "ua"): payload})
    led = PublishLedger(tmp_path / "pub.jsonl")
    pub = _FakePublisher()
    result = publish_once(
        settings=_settings(channels={"ua": "@cax_ua"}),
        service=svc, ledger=led, publisher=pub,
    )
    assert result.sent == 0
    assert result.skipped_invalid == 1
    assert pub.sent == []


# --------------------- ledger ---------------------------------------------

def test_ledger_records_and_dedups(tmp_path: Path) -> None:
    led = PublishLedger(tmp_path / "pub.jsonl")
    assert led.is_published("fp1", "en") is False
    led.record(fingerprint="fp1", locale="en", channel="@c", message_id=7)
    assert led.is_published("fp1", "en") is True
    # Different locale of the same item is independent.
    assert led.is_published("fp1", "ua") is False


def test_ledger_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "pub.jsonl"
    led = PublishLedger(path)
    led.record(fingerprint="fp1", locale="en", channel="@c", message_id=7)
    led.record(fingerprint="fp2", locale="ua", channel="@d", message_id=8)
    reloaded = PublishLedger(path)
    assert reloaded.is_published("fp1", "en") is True
    assert reloaded.is_published("fp2", "ua") is True
    assert len(reloaded) == 2


def test_ledger_tolerates_corrupt_line(tmp_path: Path) -> None:
    path = tmp_path / "pub.jsonl"
    path.write_text('{"fingerprint":"ok","locale":"en"}\nnot json\n', encoding="utf-8")
    led = PublishLedger(path)
    assert led.is_published("ok", "en") is True
    assert len(led) == 1


# --------------------- publish_once (orchestration) -----------------------

def test_publish_once_dry_run_sends_nothing(tmp_path: Path) -> None:
    item = _item("a")
    svc = _FakeService([item], {(item.fingerprint, "en"): _payload(item, "en")})
    led = PublishLedger(tmp_path / "pub.jsonl")
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=svc, ledger=led, dry_run=True,
    )
    assert result.sent == 1
    assert result.dry_run is True
    # Dry-run must not touch the ledger.
    assert len(led) == 0


def test_publish_once_sends_and_records(tmp_path: Path) -> None:
    item = _item("a")
    svc = _FakeService(
        [item],
        {(item.fingerprint, "en"): _payload(item, "en", level="Critical")},
    )
    led = PublishLedger(tmp_path / "pub.jsonl")
    pub = _FakePublisher()
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=svc, ledger=led, publisher=pub,
    )
    assert result.sent == 1
    assert len(pub.sent) == 1
    assert pub.sent[0][0] == "@cax_en"
    assert led.is_published(item.fingerprint, "en") is True


def test_publish_once_skips_already_published(tmp_path: Path) -> None:
    item = _item("a")
    svc = _FakeService([item], {(item.fingerprint, "en"): _payload(item, "en")})
    led = PublishLedger(tmp_path / "pub.jsonl")
    led.record(fingerprint=item.fingerprint, locale="en", channel="@cax_en", message_id=1)
    pub = _FakePublisher()
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=svc, ledger=led, publisher=pub,
    )
    assert result.sent == 0
    assert result.skipped_already == 1
    assert pub.sent == []


def test_publish_once_skips_uncached(tmp_path: Path) -> None:
    item = _item("a")
    svc = _FakeService([item], {})  # nothing rendered
    led = PublishLedger(tmp_path / "pub.jsonl")
    pub = _FakePublisher()
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=svc, ledger=led, publisher=pub,
    )
    assert result.sent == 0
    assert result.skipped_uncached == 1


def test_publish_once_filters_low_severity(tmp_path: Path) -> None:
    item = _item("a")
    svc = _FakeService(
        [item], {(item.fingerprint, "en"): _payload(item, "en", level="Low")},
    )
    led = PublishLedger(tmp_path / "pub.jsonl")
    pub = _FakePublisher()
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=svc, ledger=led, publisher=pub,
    )
    assert result.sent == 0
    assert result.skipped_filtered == 1


def test_publish_once_excludes_unverified_tier(tmp_path: Path) -> None:
    item = _item("a", tier="unverified")
    svc = _FakeService(
        [item], {(item.fingerprint, "en"): _payload(item, "en", level="Critical")},
    )
    led = PublishLedger(tmp_path / "pub.jsonl")
    pub = _FakePublisher()
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=svc, ledger=led, publisher=pub,
    )
    # Tier-filtered before render — it never reaches the send path.
    assert result.sent == 0
    assert pub.sent == []


def test_publish_once_language_gate_ua_item_not_on_en_channel(tmp_path: Path) -> None:
    ua_item = _item("u", language="ua")
    en_item = _item("e", language="en")
    # UA payloads need real Ukrainian text or the pre-send quality gate
    # (wrong-script guard) would correctly drop them — this test is about
    # channel routing, not content quality.
    ua_text = dict(title="Критична вразливість у системі ABB AC500",
                   summary="CISA повідомляє про серйозну загрозу безпеці.")
    svc = _FakeService(
        [ua_item, en_item],
        {
            (ua_item.fingerprint, "ua"): _payload(ua_item, "ua", level="High", **ua_text),
            (en_item.fingerprint, "en"): _payload(en_item, "en", level="High"),
            (en_item.fingerprint, "ua"): _payload(en_item, "ua", level="High", **ua_text),
        },
    )
    led = PublishLedger(tmp_path / "pub.jsonl")
    pub = _FakePublisher()
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en", "ua": "@cax_ua"}),
        service=svc, ledger=led, publisher=pub,
    )
    # EN channel: only the EN-source item. UA channel: both (EN-source renders
    # in UA too). So 1 (en) + 2 (ua) = 3 sends.
    assert result.by_channel.get("en") == 1
    assert result.by_channel.get("ua") == 2
    assert result.sent == 3


def test_publish_once_respects_limit(tmp_path: Path) -> None:
    items = [_item(f"i{n}", published=datetime(2026, 5, n + 1, tzinfo=timezone.utc))
             for n in range(5)]
    rendered = {
        (it.fingerprint, "en"): _payload(it, "en", level="Critical") for it in items
    }
    svc = _FakeService(items, rendered)
    led = PublishLedger(tmp_path / "pub.jsonl")
    pub = _FakePublisher()
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=svc, ledger=led, publisher=pub, limit=2,
    )
    assert result.sent == 2
    assert len(pub.sent) == 2


def test_publish_once_no_channels_is_noop(tmp_path: Path) -> None:
    svc = _FakeService([], {})
    led = PublishLedger(tmp_path / "pub.jsonl")
    result = publish_once(settings=_settings(channels={}), service=svc, ledger=led)
    assert result.sent == 0


# --------------------- error classification + early-abort -----------------

def test_telegram_error_channel_fatal_classification() -> None:
    assert TelegramError("x", status_code=403,
                         description="bot is not a member").is_channel_fatal
    assert TelegramError("x", status_code=401,
                         description="Unauthorized").is_channel_fatal
    assert TelegramError("x", status_code=400,
                         description="Bad Request: chat not found").is_channel_fatal
    # A generic 400 (e.g. a bad message body) is NOT channel-fatal — it's
    # item-specific, so the run should move on to the next post.
    assert not TelegramError("x", status_code=400,
                             description="message text is empty").is_channel_fatal
    assert not TelegramError("x", status_code=429,
                             description="Too Many Requests").is_channel_fatal


def test_publish_once_aborts_channel_on_chat_not_found(tmp_path: Path) -> None:
    """A 'chat not found' must stop after ONE attempt, not retry every item —
    this is the retry-storm guard."""
    items = [_item(f"i{n}", published=datetime(2026, 5, n + 1, tzinfo=timezone.utc))
             for n in range(20)]
    rendered = {
        (it.fingerprint, "en"): _payload(it, "en", level="Critical") for it in items
    }
    svc = _FakeService(items, rendered)
    led = PublishLedger(tmp_path / "pub.jsonl")
    pub = _FailingPublisher(
        TelegramError("nope", status_code=400, description="chat not found")
    )
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=svc, ledger=led, publisher=pub,
    )
    assert pub.attempts == 1          # aborted immediately, did NOT hammer all 20
    assert result.errors == 1
    assert result.sent == 0


def test_publish_once_continues_past_item_level_error(tmp_path: Path) -> None:
    """A non-fatal (item-specific) error skips that post but keeps going."""
    items = [_item(f"i{n}", published=datetime(2026, 5, n + 1, tzinfo=timezone.utc))
             for n in range(3)]
    rendered = {
        (it.fingerprint, "en"): _payload(it, "en", level="Critical") for it in items
    }
    svc = _FakeService(items, rendered)
    led = PublishLedger(tmp_path / "pub.jsonl")
    pub = _FailingPublisher(
        TelegramError("nope", status_code=429, description="Too Many Requests")
    )
    result = publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=svc, ledger=led, publisher=pub, limit=5,
    )
    # Not channel-fatal → it tries every candidate (3), all fail, none abort.
    assert pub.attempts == 3
    assert result.errors == 3
    assert result.sent == 0


# ------------------- message design (v0.5) --------------------------------

def test_notification_is_reserved_for_critical_and_urgent() -> None:
    """A channel that buzzes for every routine advisory gets muted, and a
    muted channel can't deliver the alert that mattered."""
    from cyberalertx.publish.format import notify

    item = _item("n")
    assert notify(_payload(item, "en", level="Critical")) is True
    # `urgent_action` on its own is NOT enough. That flag is a keyword score
    # over the English source article, and a single "in the wild" clears the
    # threshold — it pushed a Medium post whose first action read "Звичайним
    # абонентам робити нічого не треба". A push that opens with "nothing to
    # do" is how a channel gets muted. The severity has to agree.
    assert notify(_payload(item, "en", level="Medium",
                           actionability="urgent_action")) is False
    assert notify(_payload(item, "en", level="High",
                           actionability="urgent_action")) is True
    assert notify(_payload(item, "en", level="High")) is False
    assert notify(_payload(item, "en", level="Low")) is False












def test_quality_gate_checks_the_field_the_message_actually_leads_with() -> None:
    """render_message leads with plain_summary; the gate used to inspect
    short_summary only, so an English plain-language line shipped to the
    Ukrainian channel."""
    item = _item("q", language="ua")
    payload = _payload(
        item, "ua",
        title="Критична вразливість у Chrome",
        summary="Оновіть браузер якнайшвидше.",
        plain="Update your browser right now, this is being exploited.",
    )
    assert quality_problem(payload, locale="ua") is not None


def test_quality_gate_rejects_stray_foreign_script() -> None:
    # A real cached post carried "攻擊穿過автентифікацію" — the Cyrillic-vs-
    # Latin ratio check scores CJK as neither, so it slipped through.
    item = _item("cjk", language="ua")
    payload = _payload(
        item, "ua",
        title="Обхід автентифікації",
        summary="攻擊穿過автентифікацію дозволяє обійти вхід.",
    )
    assert quality_problem(payload, locale="ua") is not None


def test_quality_gate_passes_a_clean_ukrainian_payload() -> None:
    item = _item("ok", language="ua")
    payload = _payload(
        item, "ua",
        title="Критична вразливість у Chrome",
        summary="Оновіть браузер якнайшвидше.",
        plain="Оновіть браузер зараз — цю дірку вже використовують.",
        actions=["Оновіть Chrome через меню довідки."],
    )
    assert quality_problem(payload, locale="ua") is None


def test_send_pins_the_preview_to_our_own_page() -> None:
    """The body linkifies CVE ids before our read-more link, so without an
    explicit preview url Telegram builds the card from nvd.nist.gov."""
    item = _item("prev")
    payload = _payload(item, "en", level="Critical", title="CVE-2026-1 in Foo",
                       summary="Patch now.")
    captured: dict[str, Any] = {}

    class _CapturingPublisher:
        def send_message(self, chat_id: str, text: str, **kw: Any) -> int:
            captured.update(kw)
            captured["chat_id"] = chat_id
            return 1

        def close(self) -> None:
            pass

    ledger = PublishLedger(Path("/tmp") / "cax-test-preview.jsonl")
    ledger._path.unlink(missing_ok=True)  # noqa: SLF001
    ledger = PublishLedger(ledger._path)  # noqa: SLF001

    publish_once(
        settings=_settings(channels={"en": "@cax_en"}),
        service=_FakeService([item], {(item.fingerprint, "en"): payload}),
        ledger=ledger,
        publisher=_CapturingPublisher(),
    )

    assert captured["preview_url"] == deep_link(
        "https://cyberalertx.com", "en", item.fingerprint,
    )
    # Critical → the phone should buzz.
    assert captured["disable_notification"] is False










# --------------------- the single action block -----------------------------


# --------------------- message layout (Nov 2026 editorial format) -------------

def _rich(item: NewsItem, locale: str = "en", **kw: Any) -> dict[str, Any]:
    p = _payload(item, locale, **kw)
    p["source_url"] = "https://www.bleepingcomputer.com/news/security/x/"
    p["category"] = "vulnerability"
    p["affected_platforms"] = ["Windows", "Chrome", "Linux"]
    p["evidence"] = {"exploitation": "confirmed", "campaign": "", "compromise": "", "unknowns": []}
    p["translations"][locale]["why_it_matters"] = (
        "Attackers already use it against unpatched servers. Patching closes the hole.")
    return p


def test_layout_headline_what_why_status_source_and_link() -> None:
    item = _item("lay")
    msg = render_message(_rich(item, title="RCE in Foo", plain="Attackers can take over Foo servers.",
                               summary="BleepingComputer reports CVE-2026-1111 in Foo 4.2 is exploited."),
                         locale="en", base_url="https://cyberalertx.com")
    lines = msg.split("\n")
    assert lines[0] == "<b>RCE in Foo</b>"                       # plain bold headline, no emoji
    assert "Attackers can take over Foo servers." in msg
    assert "<b>Why it matters:</b> Attackers already use it against unpatched servers." in msg
    assert "Patching closes the hole" not in msg                 # one sentence only
    assert "Severity: High · exploitation confirmed" in msg      # severity and evidence side by side
    assert '<a href="https://www.bleepingcomputer.com/news/security/x/">BleepingComputer</a>' in msg
    assert f'Read more: <a href="{deep_link("https://cyberalertx.com", "en", item.fingerprint)}">' in msg
    assert "✅" not in msg and "🔴" not in msg and "🔗" not in msg


def test_severity_never_reads_as_exploitation() -> None:
    item = _item("sev")
    p = _rich(item, level="Critical")
    p["evidence"] = {"exploitation": "not_reported", "unknowns": ["exploitation_unconfirmed"]}
    msg = render_message(p, locale="en", base_url="https://x.test")
    assert "Severity: Critical" in msg and "exploitation confirmed" not in msg
    assert "Not yet known" not in msg            # inferred from silence: never printed
    p["category"] = "breach"
    p["evidence"] = {"exploitation": "not_reported", "compromise": "not_confirmed",
                     "unknowns": ["exposure_unconfirmed"]}
    msg = render_message(p, locale="en", base_url="https://x.test")
    assert "exposure not confirmed" in msg and "Not yet known: whether data was taken." in msg


def test_exposure_status_only_where_exposure_is_the_story() -> None:
    item = _item("exp")
    p = _rich(item)
    p["evidence"] = {"exploitation": "confirmed", "compromise": "confirmed", "unknowns": []}
    assert "exposure confirmed" not in render_message(p, locale="en", base_url="https://x.test")
    p["category"] = "breach"
    assert "data exposure confirmed" in render_message(p, locale="en", base_url="https://x.test")


def test_actions_only_when_actionable_and_at_most_two() -> None:
    item = _item("act")
    p = _rich(item, level="Medium", actions=["Install the vendor patch.", "Reboot the server.", "Audit exposed hosts."])
    p["evidence"] = {"exploitation": "not_reported", "unknowns": []}
    assert "What to do" not in render_message(p, locale="en", base_url="https://x.test")   # nothing justifies it
    p["evidence"] = {"exploitation": "confirmed", "unknowns": []}
    msg = render_message(p, locale="en", base_url="https://x.test")
    assert "<b>What to do:</b>\n• Install the vendor patch.\n• Reboot the server." in msg
    assert "Audit exposed hosts." not in msg
    p["translations"]["en"]["what_to_do"] = ["Install the vendor patch."]
    assert "<b>What to do:</b> Install the vendor patch." in render_message(p, locale="en", base_url="https://x.test")


def test_cve_ids_are_linkified_in_body_and_actions() -> None:
    item = _item("cve")
    p = _rich(item, "ua", summary="Критична вразливість CVE-2025-15467 дозволяє RCE.",
              plain="Зловмисники можуть захопити пристрій.", actions=["Оновіть прошивку, що усуває cve-2025-41691."],
              actionability="urgent_action")
    msg = render_message(p, locale="ua", base_url="https://cyberalertx.com")
    assert '<a href="https://nvd.nist.gov/vuln/detail/CVE-2025-15467">CVE-2025-15467</a>' in msg
    assert '<a href="https://nvd.nist.gov/vuln/detail/CVE-2025-41691">cve-2025-41691</a>' in msg


def test_ukrainian_post_uses_ukrainian_furniture_only() -> None:
    item = _item("ua", language="ua")
    p = _rich(item, "ua", title="Заголовок", plain="Що сталося.", summary="Подробиці.", actions=["Оновіть."],
              actionability="recommended_action")
    p["translations"]["ua"]["why_it_matters"] = "Це зачіпає багатьох користувачів."
    msg = render_message(p, locale="ua", base_url="https://cyberalertx.com")
    for ua in ("Чому це важливо:", "Рівень: Високий", "експлуатацію підтверджено", "Що робити:", "Джерело:",
               "Детальніше:", "повний розбір на CyberAlertX"):
        assert ua in msg
    for en in ("Why it matters", "Severity", "Source:", "Read more", "What to do"):
        assert en not in msg
    assert f"/ua/threat/{item.fingerprint}" in msg


def test_why_it_matters_is_dropped_when_it_repeats_the_summary() -> None:
    item = _item("dup")
    p = _rich(item, plain="Attackers already use it against unpatched servers.")
    msg = render_message(p, locale="en", base_url="https://x.test")
    assert "Why it matters" not in msg


def test_other_outlets_are_named_and_tags_are_few() -> None:
    item = _item("out")
    p = _rich(item)
    p["corroborating_sources"] = ["CISA", "The Hacker News"]
    msg = render_message(p, locale="en", base_url="https://x.test")
    assert "Also reported by CISA, The Hacker News" in msg
    assert msg.rstrip().split("\n")[-1] == "#vulnerability #Windows"


def test_source_without_a_url_is_named_without_a_link() -> None:
    item = _item("nourl")
    p = _payload(item, "en", source="Krebs on Security")
    msg = render_message(p, locale="en", base_url="https://x.test")
    assert "Source: Krebs on Security" in msg and "<a href=\"\"" not in msg


def test_caption_fits_the_limit_and_keeps_headline_source_and_link() -> None:
    from cyberalertx.publish.format import CAPTION_LIMIT, render_caption, visible_length
    item = _item("cap")
    p = _rich(item, plain="A" * 580, summary="Foo 4.2 " + "B" * 560, actions=["C" * 300, "D" * 300],
              actionability="urgent_action")
    cap = render_caption(p, locale="en", base_url="https://x.test")
    assert visible_length(cap) <= CAPTION_LIMIT
    assert cap.startswith("<b>Title</b>") and "Source:" in cap and "Read more:" in cap


def test_html_in_fields_is_escaped() -> None:
    item = _item("esc")
    p = _rich(item, title="<script>x</script> & co", plain="1 < 2 & 3 > 2")
    msg = render_message(p, locale="en", base_url="https://x.test")
    assert "&lt;script&gt;x&lt;/script&gt; &amp; co" in msg and "1 &lt; 2 &amp; 3 &gt; 2" in msg
