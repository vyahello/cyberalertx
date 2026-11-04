"""Factual validation: protected-token extraction, source support, cross-locale."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from cyberalertx.ai.fact_check import (
    check_cross_locale,
    check_item,
    check_post,
    extract_tokens,
)
from cyberalertx.ai.fact_sheet import CvssScore, FactSheet
from cyberalertx.models import NewsItem


def _kinds(text: str, **kw: bool) -> set[tuple[str, str]]:
    return {(t.kind, t.norm) for t in extract_tokens(text, **kw)}


# ---------------------------------------------------------------------------
# Extraction and normalization
# ---------------------------------------------------------------------------

def test_cve_ids_normalize_case_and_unicode_hyphens() -> None:
    assert ("cve", "CVE-2026-44338") in _kinds("cve‑2026‑44338 and CVE–2026–44338")
    # The CVE's digits never come back as a number or a date.
    assert {k for k, _ in _kinds("CVE-2026-44338")} == {"cve"}


@pytest.mark.parametrize("text,score", [
    ("CVSS 9.8", "9.8"),
    ("CVSS v3.1 base score of 9.8", "9.8"),
    ("CVSS 3.1 base 6.5", "6.5"),
    ("Under CVSS 3.1, a 9.9 score implies", "9.9"),
    ("rated 9.8/10", "9.8"),
    ("9.8 out of 10", "9.8"),
    ("оцінка CVSS 9,8 бала", "9.8"),
    ("9,8 за CVSS", "9.8"),
    ("CVSS score of 10", "10.0"),
])
def test_cvss_forms_normalize_to_one_decimal(text: str, score: str) -> None:
    found = {n for k, n in _kinds(text) if k == "cvss"}
    assert found == {score}


def test_a_cvss_version_label_is_not_a_score() -> None:
    assert not [t for t in extract_tokens("scored under CVSS 4.0") if t.kind == "cvss"]
    assert not [t for t in extract_tokens("CVSS 9+ on both") if t.kind == "cvss"]
    # The "v3.1" never comes back as a software version either.
    assert not [t for t in extract_tokens("CVSS v3.1 base score 9.8") if t.kind == "version"]


def test_vector_strings_are_not_scores() -> None:
    assert not [t for t in extract_tokens("CVSS:3.1/AV:N/AC:L/PR:N/UI:N") if t.kind == "cvss"]


def test_versions_ips_hashes_domains() -> None:
    k = _kinds(
        "Update to 2.4.59 (v2.4.60-rc1). Block 8.8.8.8, bind to 127.0.0.1, "
        "drop evil[.]com and hxxps://login.evil-site.ru/a?b=1. "
        "Hash d41d8cd98f00b204e9800998ecf8427e."
    )
    assert ("version", "2.4.59") in k and ("version", "2.4.60-rc1") in k
    assert ("ip", "8.8.8.8") in k
    assert ("private_ip", "127.0.0.1") in k        # generic advice, soft only
    assert ("domain", "evil.com") in k              # defanged
    assert ("domain", "login.evil-site.ru") in k    # host kept, path dropped
    assert ("hash", "d41d8cd98f00b204e9800998ecf8427e") in k


def test_ipv6_is_extracted_and_times_are_not() -> None:
    k = _kinds("C2 at 2001:db8::1 contacted at 12:30:00")
    assert ("private_ip", "2001:db8::1") in k  # documentation range
    assert not [n for kind, n in k if kind in ("ip", "private_ip") and n.startswith("12")]


def test_four_part_versions_are_not_ips() -> None:
    k = _kinds("Chrome 126.0.6478.114")
    assert ("version", "126.0.6478.114") in k
    assert not [x for x in k if x[0] in ("ip", "private_ip")]


@pytest.mark.parametrize("text,expected", [
    ("on November 1, 2026", {"2026-11-01"}),
    ("on 2 November", {"-----11-02"}),
    ("Nov. 3", {"-----11-03"}),
    ("2026-11-02", {"2026-11-02"}),
    ("02.11.2026", {"2026-11-02"}),
    ("2 листопада 2026 року", {"2026-11-02"}),
    ("12-13 липня", {"-----07-12", "-----07-13"}),
    ("July 12-13", {"-----07-12", "-----07-13"}),
    # A clock time is not a day: "28 August 20:57" is 28 August only.
    ("opened 28 August 20:57", {"-----08-28"}),
])
def test_dates_in_both_languages(text: str, expected: set[str]) -> None:
    assert {n for k, n in _kinds(text) if k == "date"} == expected


def test_numbers_with_units_and_separators() -> None:
    k = _kinds("1.26 million records, $39 million, 70% of 300,000 customers within 4 hours")
    nums = {n for kind, n in k if kind == "number"}
    assert {"1260000", "39000000", "70%", "300000", "4"} <= nums


def test_ukrainian_decimal_comma_and_scale_words() -> None:
    nums = {n for k, n in _kinds("1,26 млн записів і 39 мільйонів доларів") if k == "number"}
    assert {"1260000", "39000000"} <= nums


def test_years_and_bare_small_numbers_are_not_figures() -> None:
    assert not [t for t in extract_tokens("in 2025 року, step 3 of the guide") if t.kind == "number"]


def test_latin_names_are_entities_in_prose() -> None:
    names = {n for k, n in _kinds("The Cerber family, linked to LockBit, hit hospitals.",
                                  entities=True) if k == "entity"}
    assert {"cerber", "lockbit"} <= names
    # Month names and sentence-initial grammar words are not names.
    assert not {n for k, n in _kinds("In July the patch shipped.", entities=True) if k == "entity"}


# ---------------------------------------------------------------------------
# Checking a post against its source
# ---------------------------------------------------------------------------

SOURCE_TITLE = "PraisonAI auth bypass exploited within hours"
SOURCE_BODY = ("Threat actors began exploiting CVE-2026-44338, a missing authentication flaw "
               "in PraisonAI with a CVSS score of 7.3, four hours after disclosure on "
               "November 1. Version 2.4.59 fixes it. 1,260 servers are exposed.")


def _post(**fields: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "PraisonAI servers are being hijacked",
        "short_summary": "The Hacker News reports CVE-2026-44338, CVSS 7.3, in PraisonAI.",
    }
    base.update(fields)
    return base


def test_a_supported_post_passes() -> None:
    report = check_post(
        _post(quick_facts=["Fixed in 2.4.59", "Exploited 4 hours after disclosure",
                           "About 1.3 thousand servers exposed", "Disclosed 1 November"]),
        source_title=SOURCE_TITLE, source_body=SOURCE_BODY,
    )
    assert report.ok
    assert not [f for f in report.soft if f.kind in ("number", "date", "version")], report.soft


def test_an_invented_cve_or_cvss_is_a_hard_violation() -> None:
    report = check_post(
        _post(detail_body="It is related to CVE-2023-22518 (CVSS 9.1)."),
        source_title=SOURCE_TITLE, source_body=SOURCE_BODY,
    )
    assert not report.ok
    assert {(f.kind, f.value) for f in report.hard} == {("cve", "CVE-2023-22518"), ("cvss", "9.1")}
    assert report.failure_message().startswith("fact check:")


def test_invented_hash_and_public_ip_are_hard_but_private_ip_is_soft() -> None:
    report = check_post(
        _post(what_to_do=["Block `45.13.22.9`", "Bind it to `127.0.0.1`",
                          "Hunt for e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"]),
        source_title=SOURCE_TITLE, source_body=SOURCE_BODY,
    )
    assert {f.kind for f in report.hard} == {"ip", "hash"}
    assert "private_ip" in {f.kind for f in report.soft}


def test_soft_findings_record_without_rejecting() -> None:
    report = check_post(
        _post(quick_facts=["Fixed in 2.4.61", "5,000 servers exposed", "Disclosed 2 November"],
              detail_body="Unlike the Cerber operators, nobody has a decryptor."),
        source_title=SOURCE_TITLE, source_body=SOURCE_BODY,
    )
    assert report.ok
    assert {f.kind for f in report.soft} >= {"version", "number", "date", "entity"}


def test_the_fact_sheet_supports_soft_tokens_but_not_unsourced_hard_ones() -> None:
    sheet = FactSheet(summary="Exploited by the Storm-9 crew", cvss_scores=[CvssScore(score=7.3)])
    report = check_post(
        _post(detail_body="The Storm-9 crew is behind it."),
        source_title=SOURCE_TITLE, source_body=SOURCE_BODY, sheet=sheet,
    )
    assert report.ok and not [f for f in report.soft if f.value == "Storm-9"]
    # The sheet's free text never vouches for a hard identifier.
    sheet2 = FactSheet(summary="Also tracked as CVE-2026-99999")
    report2 = check_post(_post(detail_body="Also CVE-2026-99999."),
                         source_title=SOURCE_TITLE, source_body=SOURCE_BODY, sheet=sheet2)
    assert not report2.ok


def test_publication_date_is_noted_but_not_accepted() -> None:
    item = NewsItem(title=SOURCE_TITLE, source="The Hacker News", url="https://thn.test/a",
                    published_at=datetime(2026, 11, 2, 9, tzinfo=timezone.utc),
                    raw_content=SOURCE_BODY, language="en")
    report = check_item(_post(quick_facts=["Attack began 2 November"]), item)
    finding = next(f for f in report.soft if f.kind == "date")
    assert "publication date" in finding.message


def test_item_metadata_vouches_for_the_source_name() -> None:
    item = NewsItem(title=SOURCE_TITLE, source="The Hacker News", url="https://thn.test/a",
                    published_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
                    raw_content=SOURCE_BODY, language="en")
    report = check_item(_post(), item)
    assert not [f for f in report.soft if f.kind == "entity"]


# ---------------------------------------------------------------------------
# Cross-locale consistency
# ---------------------------------------------------------------------------

def test_a_date_that_moved_between_editions_is_a_major_conflict() -> None:
    en = {"short_summary": "Attack on November 1 hit CVE-2026-44338."}
    ua = {"short_summary": "Атака 2 листопада вразила CVE-2026-44338."}
    findings = check_cross_locale(en, ua)
    assert [(f.kind, f.severity) for f in findings] == [("date", "major")]
    assert "November 1" in findings[0].value and "2 листопада" in findings[0].value


def test_matching_editions_produce_no_findings() -> None:
    en = {"short_summary": "CVE-2026-44338 (CVSS 7.3) hit 1.26 million users on May 12."}
    ua = {"short_summary": "CVE-2026-44338 (CVSS 7,3) зачепила 1,26 млн користувачів 12 травня."}
    assert check_cross_locale(en, ua) == []


def test_an_omission_is_minor_and_a_cve_conflict_is_major() -> None:
    en = {"short_summary": "CVE-2026-1111 and CVE-2026-2222 are fixed."}
    ua = {"short_summary": "Виправлено CVE-2026-1111."}
    assert [(f.kind, f.severity) for f in check_cross_locale(en, ua)] == [("cve", "minor")]
    ua2 = {"short_summary": "Виправлено CVE-2026-3333."}
    assert [(f.kind, f.severity) for f in check_cross_locale(
        {"short_summary": "CVE-2026-1111 is fixed."}, ua2)] == [("cve", "major")]


def test_number_words_count_across_editions() -> None:
    en = {"short_summary": "Exploited four hours after disclosure."}
    ua = {"short_summary": "Атаки почалися через 4 години після розкриття."}
    assert check_cross_locale(en, ua) == []
