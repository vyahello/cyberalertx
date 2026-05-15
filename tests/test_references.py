"""Deterministic reference extraction from article bodies."""
from __future__ import annotations

import pytest

from cyberalertx.ai.models import Reference
from cyberalertx.ai.references import (
    drop_source_host_refs,
    drop_unverified_id_refs,
    extract_references,
    merge_references,
)


def test_extracts_cve_with_nvd_link():
    refs = extract_references("A flaw tracked as CVE-2026-1234 was disclosed.")
    assert len(refs) == 1
    r = refs[0]
    assert r.type == "cve"
    assert r.label == "CVE-2026-1234"
    assert "nvd.nist.gov" in r.url
    assert "CVE-2026-1234" in r.url


def test_extracts_multiple_cves_deduped():
    body = "Issues CVE-2026-1234 and CVE-2026-5678. Also CVE-2026-1234 mentioned again."
    refs = extract_references(body)
    labels = [r.label for r in refs]
    assert labels == ["CVE-2026-1234", "CVE-2026-5678"]


def test_extracts_cert_ua_tag():
    refs = extract_references("Tracked as CERT-UA#18329 by the Ukrainian CERT.")
    cert = next((r for r in refs if r.type == "cert"), None)
    assert cert is not None
    assert "CERT-UA#18329" in cert.label
    assert cert.url.endswith("/article/18329")


def test_extracts_cisa_advisory_id():
    refs = extract_references("CISA published AA26-001A this morning.")
    cisa = next((r for r in refs if r.type == "advisory"), None)
    assert cisa is not None
    assert "AA26-001A" in cisa.label


def test_extracts_microsoft_msrc_advisory():
    refs = extract_references("Microsoft confirmed ADV230001 the same week.")
    msrc = next((r for r in refs if r.type == "vendor"), None)
    assert msrc is not None
    assert "ADV230001" in msrc.label


def test_no_refs_returns_empty_list():
    assert extract_references("Phishing campaign targets users.") == []
    assert extract_references("") == []


def test_merge_references_dedupes_across_sources():
    cve_from_text = Reference(type="cve", label="CVE-2026-1234", url="https://nvd.nist.gov/x")
    cve_from_ai = Reference(type="cve", label="CVE-2026-1234", url="https://ai-source/x")
    extra_ai = Reference(type="vendor", label="ADV1", url="https://msrc/x")
    merged = merge_references([cve_from_text], [cve_from_ai, extra_ai])
    # Deterministic first → its URL wins on duplicate.
    assert len(merged) == 2
    assert merged[0].url == "https://nvd.nist.gov/x"
    assert merged[1].label == "ADV1"


def test_case_insensitive_cve_match():
    """CVE IDs in article bodies sometimes leak through as `cve-...`."""
    refs = extract_references("Patched flaw: cve-2026-5555 disclosed today.")
    assert any(r.label == "CVE-2026-5555" for r in refs)


def test_drop_same_host_ref():
    """The exact regression: AI emits a `news` ref pointing at the source's
    own root (`bleepingcomputer.com`); "Read on source" already covers it."""
    src = "https://www.bleepingcomputer.com/news/security/some-article/"
    refs = [
        Reference(type="news", label="BleepingComputer: ...", url="https://www.bleepingcomputer.com"),
        Reference(type="cve", label="CVE-2026-1234", url="https://nvd.nist.gov/x"),
    ]
    kept = drop_source_host_refs(refs, src)
    assert len(kept) == 1
    assert kept[0].type == "cve"


def test_drop_same_host_normalizes_www_prefix():
    """`www.example.com` and `example.com` are the same host for dedup."""
    src = "https://example.com/article"
    refs = [Reference(type="news", label="x", url="https://www.example.com/other")]
    assert drop_source_host_refs(refs, src) == []


def test_drop_same_host_keeps_cross_site_refs():
    """A CISA advisory linked from a Krebs article is legit — different host."""
    src = "https://krebsonsecurity.com/2026/05/post/"
    refs = [Reference(type="advisory", label="CISA AA26-001A", url="https://www.cisa.gov/x")]
    kept = drop_source_host_refs(refs, src)
    assert len(kept) == 1


def test_drop_same_host_empty_source_is_noop():
    refs = [Reference(type="cve", label="CVE-2026-1", url="https://nvd.nist.gov/x")]
    assert drop_source_host_refs(refs, "") == refs
    assert drop_source_host_refs(refs, "not a url") == refs


def test_drop_unverified_cisco_advisory_root():
    """The exact regression: label promises 'Cisco Security Advisory
    CVE-2026-20182' but the URL is the advisories index root — clicking it
    lands on a useless landing page."""
    refs = [
        Reference(
            type="vendor",
            label="Cisco Security Advisory CVE-2026-20182",
            url="https://tools.cisco.com/security/center/content/CiscoSecurityAdvisory",
        ),
    ]
    assert drop_unverified_id_refs(refs) == []


def test_drop_unverified_cisa_kev_landing():
    """The KEV catalog landing has no per-CVE deep link, so a label that
    names a specific CVE pointing at the catalog root is dead weight."""
    refs = [
        Reference(
            type="advisory",
            label="CISA KEV Catalog - CVE-2026-20182",
            url="https://www.cisa.gov/known-exploited-vulnerabilities",
        ),
    ]
    assert drop_unverified_id_refs(refs) == []


def test_keep_cve_ref_with_id_in_url():
    refs = [
        Reference(
            type="cve",
            label="CVE-2026-20182",
            url="https://nvd.nist.gov/vuln/detail/CVE-2026-20182",
        ),
    ]
    assert drop_unverified_id_refs(refs) == refs


def test_keep_cert_ua_ref_with_numeric_tail_in_url():
    """CERT-UA's URL convention is /article/NNNN — the '#' prefix from the
    label is intentionally absent from the URL. Must not be dropped."""
    refs = [
        Reference(
            type="cert",
            label="CERT-UA#18329",
            url="https://cert.gov.ua/article/18329",
        ),
    ]
    assert drop_unverified_id_refs(refs) == refs


def test_keep_cisa_advisory_with_aa_tag_in_url():
    """`AA26-001A` ↔ URL `/aa26-001a` — case-insensitive substring match."""
    refs = [
        Reference(
            type="advisory",
            label="CISA AA26-001A",
            url="https://www.cisa.gov/news-events/cybersecurity-advisories/aa26-001a",
        ),
    ]
    assert drop_unverified_id_refs(refs) == refs


def test_keep_freeform_label_with_no_known_id():
    """A news-type ref with no recognized ID in its label is passed through
    (we can't verify deep-linking against a non-spec'd URL shape)."""
    refs = [
        Reference(
            type="news",
            label="Talos Intelligence post-mortem",
            url="https://blog.talosintelligence.com/2026/05/sd-wan-exploit",
        ),
    ]
    assert drop_unverified_id_refs(refs) == refs


def test_drop_unverified_keeps_other_refs_in_list():
    """Mixed list: verified CVE survives, bogus Cisco-root is dropped."""
    good = Reference(
        type="cve",
        label="CVE-2026-20182",
        url="https://nvd.nist.gov/vuln/detail/CVE-2026-20182",
    )
    bad = Reference(
        type="vendor",
        label="Cisco Security Advisory CVE-2026-20182",
        url="https://tools.cisco.com/security/center/content/CiscoSecurityAdvisory",
    )
    assert drop_unverified_id_refs([good, bad]) == [good]


def test_drop_unverified_requires_all_named_ids_in_url():
    """If the label names two CVEs but the URL only links to one, the ref
    is honest-but-incomplete — drop to avoid misleading the reader."""
    ref = Reference(
        type="cve",
        label="CVE-2026-1234 and CVE-2026-5678",
        url="https://nvd.nist.gov/vuln/detail/CVE-2026-1234",
    )
    assert drop_unverified_id_refs([ref]) == []
