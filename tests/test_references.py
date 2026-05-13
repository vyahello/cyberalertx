"""Deterministic reference extraction from article bodies."""
from __future__ import annotations

import pytest

from cyberalertx.ai.models import Reference
from cyberalertx.ai.references import extract_references, merge_references


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
