"""Tests for the AI journalist rendering layer.

What we pin here:

  * **Asymmetric multilingual rendering** — UK-sourced items render UK
    ONLY (we do not auto-translate Ukrainian news to English). EN-sourced
    items render BOTH en and uk so the UK page can surface high-signal
    English threat intel via locale-aware metadata.

  * **Validation** rejects AI sludge (clichés, chatbot disclaimers,
    Russian grammar in UK output, duplicate recommendations, title
    echoed in summary, hallucinated threat_level).

  * **Validation pass** lets clean journalist-style copy through.

The provider itself is not exercised here (network-dependent); we use a
stub provider that returns whatever ThreatPostResponse the test wants.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cyberalertx.ai.cache import ThreatPostCache
from cyberalertx.ai.generator import ContentGenerator
from cyberalertx.ai.models import ThreatPostResponse
from cyberalertx.ai.validation import (
    ValidationFailure,
    validate_journalist_response,
)
from cyberalertx.models import NewsItem


# --------------------- fixtures --------------------------------------------

def _good_response(**overrides) -> ThreatPostResponse:
    """A response that passes every validation check. Tests mutate one
    field at a time to confirm exactly which check fires."""
    base = dict(
        title="Storm-1124 phishing kit targets US school staff",
        short_summary=(
            "A phishing kit nicknamed Storm-1124 sends fake Microsoft "
            "sign-in pages from compromised university mailboxes. "
            "Victims include school staff in eight US states."
        ),
        threat_level="High",
        why_it_matters=(
            "If attackers got into a school M365 inbox they can read "
            "every 2FA code that gets delivered there."
        ),
        affected_users=["Microsoft 365 admins", "US school staff"],
        what_to_do=[
            "Open security.microsoft.com → Sign-in activity",
            "Switch the account from SMS to Authenticator-app 2FA",
            "Revoke OAuth permissions for any unfamiliar third-party app",
        ],
        what_not_to_do=[
            "Don't approve a 2FA prompt you did not just trigger",
        ],
        quick_facts=["Actively exploited", "Microsoft 365"],
        emotional_weight=0.7,
        reading_time_seconds=25,
    )
    base.update(overrides)
    return ThreatPostResponse(**base)


def _item(language: str = "en", url: str = "https://e.test/x") -> NewsItem:
    return NewsItem(
        title="Storm-1124 phishing kit targets US school staff",
        source="BleepingComputer",
        url=url,
        published_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        raw_content="Body of the article.",
        language=language,
        category="phishing",
        affected_platforms=["Microsoft 365"],
        audience_targets=["enterprise"],
        actionability_level="urgent_action",
        actionability_score=0.9,
        threat_score=70.0,
        source_tier="trusted",
        source_credibility_score=0.85,
    )


# --------------------- validation: GOOD passes ----------------------------

def test_good_response_passes_validation():
    validate_journalist_response(_good_response(), source_title=_item().title)


# --------------------- validation: bad-content rejections -----------------

def test_empty_summary_rejected():
    with pytest.raises(ValidationFailure, match="empty short_summary"):
        validate_journalist_response(_good_response(short_summary="   "),
                                     source_title="anything")


def test_empty_why_it_matters_rejected():
    with pytest.raises(ValidationFailure, match="empty why_it_matters"):
        validate_journalist_response(_good_response(why_it_matters=""),
                                     source_title="anything")


def test_empty_what_to_do_rejected():
    with pytest.raises(ValidationFailure, match="empty what_to_do"):
        validate_journalist_response(_good_response(what_to_do=[]),
                                     source_title="anything")


def test_hallucinated_threat_level_rejected():
    # Pydantic's Literal catches bad enums at construction, so to exercise
    # our defensive enum-check we have to bypass Pydantic validation. This
    # mirrors what would happen if a future provider returned partially
    # parsed data, or if the schema constraint were ever relaxed.
    data = _good_response().model_dump()
    data["threat_level"] = "Catastrophic"
    bad = ThreatPostResponse.model_construct(**data)
    with pytest.raises(ValidationFailure, match="hallucinated threat_level"):
        validate_journalist_response(bad, source_title="anything")


def test_duplicate_what_to_do_rejected():
    dup = _good_response(what_to_do=[
        "Open security.microsoft.com → Sign-in activity",
        "Open security.microsoft.com → Sign-in activity.",  # same modulo period
        "Revoke OAuth permissions",
    ])
    with pytest.raises(ValidationFailure, match="duplicate entries in what_to_do"):
        validate_journalist_response(dup, source_title="anything")


def test_duplicate_what_not_to_do_rejected():
    dup = _good_response(what_not_to_do=[
        "Don't approve unexpected 2FA prompts",
        "DON'T APPROVE UNEXPECTED 2FA PROMPTS!",  # same modulo case + punct
    ])
    with pytest.raises(ValidationFailure, match="duplicate entries in what_not_to_do"):
        validate_journalist_response(dup, source_title="anything")


def test_ai_cliche_rejected_en():
    bad = _good_response(
        why_it_matters="This highlights the evolving threat landscape and the need for a robust security posture.",
    )
    with pytest.raises(ValidationFailure, match="AI cliché"):
        validate_journalist_response(bad, source_title="anything")


def test_chatbot_disclaimer_rejected():
    bad = _good_response(
        short_summary="As an AI, I cannot fully judge this incident, but I can say that...",
    )
    with pytest.raises(ValidationFailure, match="AI cliché"):
        validate_journalist_response(bad, source_title="anything")


def test_russism_in_uk_output_rejected():
    """If the UA render leaks Russian grammar ('обнаружено', 'путем'), we
    reject — better to fall back to the rule-based UA copy than ship
    machine-translation tone. The validator now uses the russism-stem
    list in `ai/uk_glossary.py`, so this fires with a `Russism stem`
    error rather than the older `AI cliché` bucket.

    Title and summary are deliberately in Ukrainian so the new target-
    language gate (Cyrillic ratio) passes and we reach the russism check.
    """
    bad = _good_response(
        title="Шахрайська кампанія фішингу проти користувачів M365",
        short_summary=(
            "Дослідники зафіксували нову хвилю фішингових листів, що "
            "імітують сторінку входу Microsoft 365 та крадуть облікові "
            "дані співробітників університетів у восьми штатах США."
        ),
        why_it_matters="Обнаружено новую кампанию шахрайства путем фишинга.",
    )
    with pytest.raises(ValidationFailure, match="Russism stem"):
        validate_journalist_response(
            bad, source_title="anything", language="ua",
        )


def test_summary_echoing_title_rejected():
    title = "Storm-1124 phishing kit targets US school staff with M365 lure"
    bad = _good_response(short_summary=title)
    with pytest.raises(ValidationFailure, match="echoes title"):
        validate_journalist_response(bad, source_title=title)


# --------------------- target-language gate ------------------------------

def test_english_title_on_ua_target_rejected():
    """Real failure mode the user reported: AI returned a UA-target response
    where summary/why are Ukrainian but title is fully English (e.g.
    'TrickMo Android banking trojan uses TON blockchain'). The russism /
    foreign-script gates pass — Latin letters are allowed in UA output for
    brand names. The language gate catches this so the post falls back to
    rule_based instead of shipping a hybrid-language card.
    """
    bad = _good_response(
        title="TrickMo Android banking trojan uses TON blockchain for command",
        short_summary=(
            "Дослідники Cleafy зафіксували нову версію банківського трояна "
            "TrickMo, який маскується під легітимні застосунки і викрадає "
            "облікові дані з банківських застосунків на Android."
        ),
        why_it_matters=(
            "Якщо троян потрапив на пристрій, він читає SMS з кодами "
            "двофакторної автентифікації та може спустошити рахунок."
        ),
        affected_users=["Користувачі Android-банкінгу"],
        what_to_do=[
            "Встановлюйте застосунки лише з Google Play",
            "Увімкніть Play Protect у налаштуваннях Google",
            "Перевірте список встановлених застосунків на незнайомі іконки",
        ],
    )
    with pytest.raises(ValidationFailure, match="not in target language 'ua'"):
        validate_journalist_response(
            bad, source_title="anything", language="ua",
        )


def test_brand_heavy_ua_title_passes():
    """Brand-name-heavy UA headlines must still pass — they have enough
    native fill to clear the 30% Cyrillic threshold. This test guards
    against the gate getting too aggressive and rejecting legitimate UA
    coverage of foreign vendors."""
    ok = _good_response(
        title="Microsoft закриває критичну уразливість RCE у Windows Server",
        short_summary=(
            "Microsoft випустила позаплановий патч для активно "
            "експлуатованої уразливості у компоненті аутентифікації "
            "Windows Server 2019/2022."
        ),
        why_it_matters=(
            "Якщо ваш домен-контролер не оновлений, зловмисник з "
            "мережі може отримати права адміністратора без пароля."
        ),
        affected_users=["Адміністратори Windows Server"],
        what_to_do=[
            "Застосуйте KB5040000 на всіх контролерах домену сьогодні",
            "Перегляньте журнали входу за останні 14 днів",
            "Обмежте RDP-доступ ззовні до часу патчу",
        ],
        what_not_to_do=["Не відкладайте патч до планового вікна обслуговування"],
    )
    validate_journalist_response(ok, source_title="anything", language="ua")


def test_ukrainian_title_on_en_target_rejected():
    """Symmetric guard for the EN feed — if the AI somehow returned a
    Cyrillic title on an EN-target render, reject it. We don't auto-
    translate UA→EN today, so this is defensive, but the test pins the
    behavior in case the asymmetric-render rule changes later."""
    bad = _good_response(
        title="Кібератака зачепила великий український банк",
        short_summary=(
            "Researchers documented a phishing campaign that targets "
            "Ukrainian retail bank customers via Viber messages."
        ),
    )
    with pytest.raises(ValidationFailure, match="not in target language 'en'"):
        validate_journalist_response(
            bad, source_title="anything", language="en",
        )


# --------------------- asymmetric multilingual render ----------------------

class _StubProvider:
    """Stand-in for AnthropicProvider — returns a good response every time
    and records what languages it was asked to produce.

    Returns a UA-localized payload when the system prompt asks for UA so
    the target-language gate (Cyrillic ratio on title + summary) passes.
    Without this, the EN-source asymmetric-render test fails because the
    UA branch falls back to rule_based.
    """

    name = "stub"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def generate_post(self, system: str, user: str):  # noqa: ARG002
        # Crude language detection on the system prompt — fine for a stub.
        lang = "ua" if "OUTPUT_LANGUAGE: ua" in system else "en"
        self.calls.append((lang, user[:30]))
        if lang == "ua":
            return _good_response(
                title="Фішинговий набір Storm-1124 атакує співробітників шкіл США",
                short_summary=(
                    "Фішинговий набір Storm-1124 надсилає підроблені сторінки "
                    "входу Microsoft 365 зі зламаних університетських поштових "
                    "скриньок. Серед жертв — працівники шкіл у восьми штатах США."
                ),
                why_it_matters=(
                    "Якщо зловмисник потрапить у скриньку M365, він читатиме "
                    "кожен код двофакторної автентифікації, який туди приходить."
                ),
                affected_users=["Адміністратори Microsoft 365", "Працівники шкіл"],
                what_to_do=[
                    "Відкрийте security.microsoft.com → Sign-in activity",
                    "Переведіть акаунт із SMS на Authenticator-додаток",
                    "Відкличте OAuth-дозволи для незнайомих застосунків",
                ],
                what_not_to_do=[
                    "Не схвалюйте 2FA-запит, який ви не ініціювали",
                ],
            )
        return _good_response()


def test_asymmetric_render_uk_source_renders_uk_only(tmp_path):
    """UK-sourced item → UK translation only, never EN."""
    from cyberalertx.api.app import _PostService
    provider = _StubProvider()
    cache = ThreatPostCache(tmp_path / "posts.json")
    gen = ContentGenerator(provider=provider, cache=cache)
    svc = _PostService(generator=gen)
    item = _item(language="ua", url="https://itc.ua/article/123")
    rendered = svc.render(item)
    assert rendered["source_language"] == "ua"
    assert rendered["available_locales"] == ["ua"]
    assert set(rendered["translations"].keys()) == {"ua"}
    # The stub must NOT have been asked to render EN.
    langs_called = {c[0] for c in provider.calls}
    assert "en" not in langs_called


def test_asymmetric_render_en_source_renders_both(tmp_path):
    """EN-sourced item → BOTH en and uk so the UK page can surface
    high-signal English threat intel with localized metadata."""
    from cyberalertx.api.app import _PostService
    provider = _StubProvider()
    cache = ThreatPostCache(tmp_path / "posts.json")
    gen = ContentGenerator(provider=provider, cache=cache)
    svc = _PostService(generator=gen)
    item = _item(language="en")
    rendered = svc.render(item)
    assert rendered["source_language"] == "en"
    assert set(rendered["available_locales"]) == {"en", "ua"}
    assert set(rendered["translations"].keys()) == {"en", "ua"}
    langs_called = {c[0] for c in provider.calls}
    assert langs_called == {"en", "ua"}


# --------------------- validation failure → rule-based fallback ----------

def test_validation_failure_falls_back_to_rule_based(tmp_path):
    """If the AI returns sludge, the generator must NOT raise — it must
    quietly render via rule-based instead. We confirm both by the post's
    `generated_by` field and by the absence of a cached AI output."""

    class _CliCheProvider:
        name = "stub"

        def generate_post(self, system: str, user: str):  # noqa: ARG002
            return _good_response(
                why_it_matters=(
                    "This incident highlights the evolving threat "
                    "landscape, reinforcing the need for a robust "
                    "security posture."
                ),
            )

    cache = ThreatPostCache(tmp_path / "posts.json")
    gen = ContentGenerator(provider=_CliCheProvider(), cache=cache)
    item = _item(language="en")
    post = gen.generate(item, language="en")
    assert post.generated_by == "rule_based"
    # Rule-based output must NOT be cached — we want a fresh AI attempt
    # next time. The cache file should have no entry for this item.
    assert cache.get(item.fingerprint, "en") is None
