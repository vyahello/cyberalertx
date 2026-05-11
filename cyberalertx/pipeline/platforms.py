"""Affected-platform extraction.

Contract:
    extract_platforms(text) -> list[str]  (sorted, deduped, canonical)

Design notes:
  * The PLATFORMS dict maps a canonical display name → list of aliases.
    This is the only place "iPhone" becomes "iOS" or "k8s" becomes "Kubernetes",
    so the rest of the pipeline (UI filters, AI prompts, dashboards) can
    rely on a small, stable vocabulary.
  * Word-boundary matching prevents false positives like "linux" matching
    inside "salinux". Multi-word aliases are matched as substrings.
  * Pure function — easy to unit-test, easy to swap for an NER model later.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Mapping, Sequence

from ..models import NewsItem

# Canonical → aliases. Keep aliases lowercase.
# Tip when extending: prefer the most common public name as the canonical key
# (it's what the UI will display). Aliases should cover spellings, abbreviations,
# product variants, and common typos seen in the wild.
PLATFORMS: Mapping[str, Sequence[str]] = {
    "Windows": ("windows", "win10", "win11", "windows server", "microsoft windows"),
    "Linux": ("linux", "ubuntu", "debian", "redhat", "rhel", "centos", "fedora", "alpine"),
    "macOS": ("macos", "mac os", "osx", "os x"),
    "Android": ("android",),
    "iOS": ("ios", "iphone", "ipad", "ipados"),
    "Chrome": ("chrome", "chromium", "google chrome"),
    "Firefox": ("firefox",),
    "Safari": ("safari",),
    "Edge": ("microsoft edge", "msedge"),
    "Gmail": ("gmail",),
    "Outlook": ("outlook", "outlook.com"),
    "Microsoft 365": ("microsoft 365", "office 365", "o365", "m365"),
    "Telegram": ("telegram",),
    "WhatsApp": ("whatsapp",),
    "Signal": ("signal messenger",),
    "Slack": ("slack",),
    "Zoom": ("zoom",),
    "Banking": ("bank", "banking", "fintech", "swift network", "wire transfer", "online banking"),
    "Cloud (AWS)": ("aws", "amazon web services", "amazon s3", "amazon ec2"),
    "Cloud (Azure)": ("azure", "microsoft azure"),
    "Cloud (GCP)": ("gcp", "google cloud", "google cloud platform"),
    "Docker": ("docker",),
    "Kubernetes": ("kubernetes", "k8s"),
    "WordPress": ("wordpress",),
    "Cisco": ("cisco",),
    "Fortinet": ("fortinet", "fortigate"),
    "VMware": ("vmware", "vsphere", "esxi"),
}


def _alias_matchers() -> list[tuple[str, re.Pattern[str]]]:
    """Build a (canonical, regex) list once.

    Single-word aliases are word-boundary matched; multi-word aliases are
    substring matched after collapsing whitespace.
    """
    matchers: list[tuple[str, re.Pattern[str]]] = []
    for canonical, aliases in PLATFORMS.items():
        for alias in aliases:
            alias_clean = alias.strip().lower()
            if not alias_clean:
                continue
            if " " in alias_clean:
                pattern = re.compile(re.escape(alias_clean))
            else:
                pattern = re.compile(rf"(?<![\w]){re.escape(alias_clean)}(?![\w])")
            matchers.append((canonical, pattern))
    return matchers


# Precomputed at import — these regexes never change at runtime.
_MATCHERS = _alias_matchers()


def extract_platforms(text: str) -> List[str]:
    if not text:
        return []
    haystack = text.lower()
    found: set[str] = set()
    for canonical, pattern in _MATCHERS:
        if canonical in found:
            continue
        if pattern.search(haystack):
            found.add(canonical)
    return sorted(found)


def extract_for_item(item: NewsItem) -> NewsItem:
    """In-place enrichment: populate affected_platforms."""
    item.affected_platforms = extract_platforms(
        f"{item.title}\n{item.raw_content}"
    )
    return item


def extract_all(items: Iterable[NewsItem]) -> List[NewsItem]:
    return [extract_for_item(i) for i in items]
