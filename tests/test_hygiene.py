"""Content-hygiene tests.

The cases marked "REPORTED" are the exact strings that shipped to the
Ukrainian Telegram channel and the website and were flagged by the product
owner. They are pinned verbatim so a future prompt or regex change cannot
quietly bring them back.
"""
from __future__ import annotations

import pytest

from cyberalertx.ai.hygiene import (
    clean_localized_content,
    is_absence_fact,
    is_null_action,
    is_null_check,
    is_weak_severity_reason,
)


# ---------------------------------------------------------------------------
# Null checks — `am_i_affected`
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    # REPORTED: rendered under the heading "Перевірте, чи це вас стосується",
    # which promises a check and then says no check exists.
    "Ця новина про метод атаки. Технічної перевірки для вашого пристрою немає.",
    # REPORTED: tells the reader they are powerless.
    "Ви звичайний абонент: діяти нічого не можете, це на боці оператора.",
    "Перевірити це неможливо без доступу до обладнання оператора.",
    "There is no technical check for your device.",
    "Nothing you can check — this is handled on the carrier's side.",
])
def test_null_checks_are_dropped(text: str) -> None:
    assert is_null_check(text, "ua") or is_null_check(text, "en")


@pytest.mark.parametrize("text", [
    # An exclusion that names concrete commands IS a check: the reader
    # recalls whether they ran them and reaches a verdict.
    "Якщо ви ніколи не запускали yay чи paru, вас це не стосується.",
    "Перевірте, чи є у вас сервіси, доступні з інтернету. Немає — вас це не стосується.",
    "Якщо ви не працюєте з промисловим обладнанням, вас це не стосується.",
    "Відкрийте меню Chrome > Довідка > Про Google Chrome. Нижче 126.0.6478 — вас це стосується.",
    "Виконайте 'uname -r'. Ядра 6.1-6.7 уражені.",
    "Якщо адмініструєте корпоративну мережу, перегляньте журнали входів за останні тижні.",
    "Open Chrome menu > Help > About Google Chrome. Below 126.0.6478 means you are affected.",
])
def test_real_checks_and_concrete_exclusions_survive(text: str) -> None:
    assert not is_null_check(text, "ua")
    assert not is_null_check(text, "en")


# ---------------------------------------------------------------------------
# Null actions — `what_to_do`
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    # REPORTED: consumed one of only two bullets Telegram renders.
    "Звичайним абонентам робити нічого не треба, виправлення ставить оператор.",
    # This exact sentence was requested by the prompt itself until the
    # contract was rewritten.
    "Нічого робити не треба, якщо ви не адмініструєте власний сервер.",
    "Нічого робити не треба, якщо ви приватний користувач.",
    "Нічого робити не треба. Це експериментальний проєкт, а не атака.",
    "Nothing to do if you don't run your own web server.",
    "No action is required for ordinary users.",
])
def test_null_actions_are_dropped(text: str) -> None:
    assert is_null_action(text, "ua") or is_null_action(text, "en")


@pytest.mark.parametrize("text", [
    "Увімкніть двофакторний вхід у Telegram: Налаштування > Конфіденційність > Хмарний пароль.",
    "Встановіть ядро 6.7.9 або новіше і перезавантажте.",
    "Запитайте у постачальника ядра 4G/5G, чи стосуються його ці 84 вразливості.",
    "Install kernel 6.7.9 or later, then reboot.",
])
def test_real_actions_survive(text: str) -> None:
    assert not is_null_action(text, "ua")
    assert not is_null_action(text, "en")


# ---------------------------------------------------------------------------
# Absence-as-fact — `quick_facts`
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "IOC та список жертв не оприлюднені",
    "Технічних деталей і CVE не названо",
    "Конкретний перелік пакетів не оприлюднено",
    "Угрупування, що стоїть за атакою, не назване",
    "Threat actor not named",
])
def test_absence_facts_are_dropped(text: str) -> None:
    assert is_absence_fact(text, "ua") or is_absence_fact(text, "en")


@pytest.mark.parametrize("text", [
    # An absence that changes a defender's decision stays. "No public PoC"
    # and "no patch yet" both move patch urgency; "data not leaked yet"
    # is the single most reassuring thing a breach post can tell a reader.
    "Публічного PoC не помічено",
    "Патча ще немає",
    "Масового сканування не зафіксовано",
    "Дані ще не оприлюднені, лише погроза",
    "No public PoC observed",
    "Not yet leaked, only threatened",
])
def test_decision_relevant_absences_survive(text: str) -> None:
    assert not is_absence_fact(text, "ua")
    assert not is_absence_fact(text, "en")


# ---------------------------------------------------------------------------
# Weak severity rationales — `severity_reason`
# ---------------------------------------------------------------------------

def test_reported_severity_reason_is_blanked() -> None:
    # REPORTED verbatim. Explains the rating by (a) the reader needing no
    # action and (b) what the source omitted — neither is a property of the
    # threat.
    text = (
        "Середній рівень, бо звичайному користувачеві прямої дії не потрібно, "
        "а деталей про конкретні жертви й спосіб проникнення джерело не наводить."
    )
    assert is_weak_severity_reason(text, "ua")


@pytest.mark.parametrize("text", [
    "Critical due to the severity of the vulnerability.",
    "Medium because ordinary users don't need to act.",
    "Low because the source does not describe the attack chain.",
])
def test_weak_severity_reasons_en(text: str) -> None:
    assert is_weak_severity_reason(text, "en")


@pytest.mark.parametrize("text", [
    "Критично, бо атаки вже тривають, пароль не потрібен, а кожен неоновлений сервер доступний з інтернету.",
    "Високий рівень, бо медичні платіжні дані 1,26 млн людей уже в руках зловмисників.",
    "Середній рівень, бо зараження потребує вашої дії — самостійного завантаження і запуску файлу.",
    "Critical because attackers are already using it and no password is needed.",
])
def test_good_severity_reasons_survive(text: str) -> None:
    assert not is_weak_severity_reason(text, "ua")
    assert not is_weak_severity_reason(text, "en")


# ---------------------------------------------------------------------------
# The whole-payload pass
# ---------------------------------------------------------------------------

def test_clean_localized_content_filters_every_field() -> None:
    content = {
        "title": "Дослідники знайшли 84 вразливості в ядрах мереж 4G і 5G",
        "am_i_affected": [
            "Ви звичайний абонент: діяти нічого не можете, це на боці оператора.",
            "Адмініструєте приватну 5G-мережу: запитайте у вендора ядра статус виправлень.",
        ],
        "what_to_do": [
            "Звичайним абонентам робити нічого не треба, виправлення ставить оператор.",
            "Запитайте у постачальника ядра 4G/5G, чи стосуються його ці 84 вразливості.",
        ],
        "what_not_to_do": [],
        "quick_facts": ["IOC не опубліковано", "84 вразливості у ядрах 4G/5G"],
        "severity_reason": "Середній рівень, бо звичайному користувачеві прямої дії не потрібно.",
    }
    out = clean_localized_content(content, "ua")

    assert out["am_i_affected"] == [
        "Адмініструєте приватну 5G-мережу: запитайте у вендора ядра статус виправлень.",
    ]
    assert out["what_to_do"] == [
        "Запитайте у постачальника ядра 4G/5G, чи стосуються його ці 84 вразливості.",
    ]
    assert out["quick_facts"] == ["84 вразливості у ядрах 4G/5G"]
    assert out["severity_reason"] == ""
    # Untouched fields pass through.
    assert out["title"] == content["title"]


def test_clean_localized_content_does_not_mutate_input() -> None:
    content = {"what_to_do": ["Нічого робити не треба, якщо ви приватний користувач."]}
    before = list(content["what_to_do"])
    clean_localized_content(content, "ua")
    assert content["what_to_do"] == before


def test_missing_fields_normalize_to_empty_lists() -> None:
    """A sparse payload (older cache entry) must not raise."""
    out = clean_localized_content({"title": "x"}, "ua")
    assert out["am_i_affected"] == []
    assert out["what_to_do"] == []
    assert out["quick_facts"] == []
    assert out["severity_reason"] == ""


def test_any_verb_of_not_saying_about_our_sourcing_is_weak() -> None:
    """The verb list was enumerated and the model reached for one that
    wasn't on it.

    "Цілями стали сотні компаній одразу, але наслідки для конкретних жертв
    джерело не описує" survived a full re-render because «описує» was
    missing from the list. The SUBJECT is what makes this a defect — it
    rates our sourcing rather than the threat — so the subject is matched
    and the verb is left open.
    """
    for text in (
        "Цілями стали сотні компаній, але наслідки для жертв джерело не описує.",
        "Середній рівень, бо деталей про жертви джерело не наводить.",
        "Стаття не містить технічних деталей, тож оцінка приблизна.",
        "Публікація не розкриває масштабу.",
    ):
        assert is_weak_severity_reason(text, "ua"), text


def test_widened_rule_still_keeps_real_explanations() -> None:
    for text in (
        "Перехоплення сесії абонента — серйозна шкода, але виконати атаку може "
        "лише той, хто вже має доступ до мережі оператора.",
        "Медичні платіжні дані 1,26 млн людей уже в руках зловмисників.",
        "Шкідливий код виконується з правами користувача, але зачіпає лише тих, "
        "хто ставить пакети з AUR.",
        "Крадіжка криптовалюти незворотна, а скрипт роздавався через рекламну "
        "платформу багатьом сайтам.",
    ):
        assert not is_weak_severity_reason(text, "ua"), text
