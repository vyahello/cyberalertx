"""Deterministic reference extraction from article bodies.

Pulls structured references out of the raw article text — no AI needed
for the common case (CVE-2026-1234, CERT-UA#NNNNN, CISA aliases). The
journalist layer can still ADD references via its structured output;
this layer guarantees a baseline so even rule-based renders carry the
relevant CVE / advisory links.

Why deterministic-first:
  * Free. No API tokens for what regex can find.
  * Verifiable. The label IS in the source text — no hallucination risk.
  * Predictable. Same input always yields the same reference list, which
    makes cache hits stable.
"""
from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urlparse

from .models import Reference


# CVE — strict NVD shape `CVE-YYYY-NNNNNNN`. The 4-7 digit count is the
# spec; we cap at 7 to avoid accidental matches.
_CVE_RE = re.compile(r"\bCVE-(\d{4})-(\d{4,7})\b", flags=re.IGNORECASE)

# CERT-UA bulletin tag — appears in CERT-UA articles as `CERT-UA#NNNNN`.
_CERT_UA_RE = re.compile(r"\bCERT-UA#(\d+)\b", flags=re.IGNORECASE)

# CISA known-exploited / advisory IDs.
# Common patterns: `AA##-NNNa` (alert), `KEV` (known exploited).
_CISA_ADVISORY_RE = re.compile(r"\bAA\d{2}-\d{2,3}[A-Za-z]?\b")

# Microsoft Security Advisory / Update Guide.
_MSRC_RE = re.compile(r"\bADV\d{6}\b", flags=re.IGNORECASE)


def _cve_url(year: str, num: str) -> str:
    return f"https://nvd.nist.gov/vuln/detail/CVE-{year}-{num}"


def _cert_ua_url(article_id: str) -> str:
    # CERT-UA's article-id URL pattern. The bulletin tag and the article
    # ID aren't always the same number; we link to the SEARCH for the tag
    # so the reader lands on the right page even if the IDs diverge.
    return f"https://cert.gov.ua/article/{article_id}"


def _cisa_advisory_url(advisory_id: str) -> str:
    aid = advisory_id.lower()
    return f"https://www.cisa.gov/news-events/cybersecurity-advisories/{aid}"


def _msrc_url(adv_id: str) -> str:
    return f"https://msrc.microsoft.com/update-guide/vulnerability/{adv_id.upper()}"


def extract_references(text: str) -> list[Reference]:
    """Walk the article body and emit a deduped list of `Reference`.

    Currently catches: CVE IDs, CERT-UA bulletin tags, CISA advisory
    IDs, Microsoft Security Advisory IDs. Adding a new shape is one
    regex + one helper here — no schema migration needed.
    """
    if not text:
        return []
    seen: set[tuple[str, str]] = set()
    out: list[Reference] = []

    def add(ref: Reference) -> None:
        key = (ref.type, ref.label.lower())
        if key in seen:
            return
        seen.add(key)
        out.append(ref)

    for year, num in _CVE_RE.findall(text):
        label = f"CVE-{year}-{num}"
        add(Reference(type="cve", label=label, url=_cve_url(year, num)))

    for tag in _CERT_UA_RE.findall(text):
        add(Reference(
            type="cert",
            label=f"CERT-UA#{tag}",
            url=_cert_ua_url(tag),
        ))

    for cisa in _CISA_ADVISORY_RE.findall(text):
        add(Reference(
            type="advisory",
            label=f"CISA {cisa}",
            url=_cisa_advisory_url(cisa),
        ))

    for msrc in _MSRC_RE.findall(text):
        add(Reference(
            type="vendor",
            label=msrc.upper(),
            url=_msrc_url(msrc),
        ))

    return out


def merge_references(*sources: Iterable[Reference]) -> list[Reference]:
    """Union of multiple reference lists, deduped by (type, label).
    Order: first source wins on duplicate. Used to combine the AI's
    `references` field with the regex-extracted baseline."""
    seen: set[tuple[str, str]] = set()
    out: list[Reference] = []
    for src in sources:
        for ref in src:
            key = (ref.type, ref.label.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append(ref)
    return out


def _normalized_host(url: str) -> str:
    """Lowercase host without a leading `www.`. Empty string on parse error."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except (ValueError, AttributeError):
        return ""
    return host.removeprefix("www.")


def drop_source_host_refs(refs: Iterable[Reference], source_url: str) -> list[Reference]:
    """Filter out references whose host matches the source article's host.

    The post already exposes `source_url` via the "Read on source" link, so
    a reference back to the same site is pure noise — either a model
    hallucination (e.g. `news`-type ref pointing at the source homepage) or
    a redundant deterministic match (CISA ID extracted from a CISA-sourced
    article). Cross-site references (different host) are kept as-is.

    No-op when `source_url` is empty/unparseable.
    """
    source_host = _normalized_host(source_url)
    if not source_host:
        return list(refs)
    return [r for r in refs if _normalized_host(r.url) != source_host]


# IDs we expect a URL to deep-link to when the label names one of them.
# Same shapes as the deterministic extractor above — kept in sync on purpose.
_KNOWN_ID_RE = re.compile(
    r"\b(?:CVE-\d{4}-\d{4,7}|ADV\d{6}|AA\d{2}-\d{2,3}[A-Za-z]?|CERT-UA#\d+|KB\d{6,})\b",
    flags=re.IGNORECASE,
)


def _id_url_signature(identifier: str) -> str:
    """The substring of `identifier` we expect to appear in a URL that
    actually points at this specific advisory.

    Different ID families follow different URL conventions:
      * CVE / ADV / AA / KB → URL preserves the full ID literally
        (e.g. `/CVE-2026-1234`, `/aa26-001a`, `/ADV230001`).
      * CERT-UA#NNNN → URL keeps only the numeric tail
        (e.g. `cert.gov.ua/article/18329`).
    """
    if identifier.upper().startswith("CERT-UA#"):
        return identifier.split("#", 1)[1]
    return identifier


def drop_unverified_id_refs(refs: Iterable[Reference]) -> list[Reference]:
    """Drop references whose label names a specific advisory ID but whose
    URL doesn't actually link to that ID.

    The model occasionally emits a reference like
    `"Cisco Security Advisory CVE-2026-20182"` pointing at the vendor's
    advisories index (`tools.cisco.com/.../CiscoSecurityAdvisory`) or
    `"CISA KEV Catalog - CVE-2026-20182"` pointing at the KEV landing page
    — labels promise a specific advisory but the URL is a generic root.
    These links are dead-ends for the reader. Drop them.

    Heuristic: if every known-ID token in the label has its URL signature
    present in `url` (case-insensitive), keep. Otherwise the link doesn't
    deliver on what the label promises — drop.

    Refs whose label contains no recognized ID (free-form news/vendor blog
    titles) are passed through unchanged.
    """
    out: list[Reference] = []
    for r in refs:
        ids = _KNOWN_ID_RE.findall(r.label or "")
        if not ids:
            out.append(r)
            continue
        url_upper = (r.url or "").upper()
        if all(_id_url_signature(i).upper() in url_upper for i in ids):
            out.append(r)
    return out


__all__ = [
    "extract_references",
    "merge_references",
    "drop_source_host_refs",
    "drop_unverified_id_refs",
]
