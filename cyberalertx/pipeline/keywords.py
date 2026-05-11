"""Single source of truth for keyword sets.

Filter and ranker share these so we don't get drift between "what counts as
relevant" and "what bumps the score". Keeping them as plain frozensets makes
unit testing trivial and lets a future ML classifier replace them piecewise.

Keyword syntax:
  * "phishing"        — exact token match
  * "zero-day"        — phrase / substring match (contains space or hyphen)
  * "фішинг*"         — stem/prefix match against tokens (Slavic inflection)
"""
from __future__ import annotations

from typing import Iterable, Mapping


def count_keyword_hits(
    keywords: Iterable[str],
    text_lower: str,
    tokens: set[str],
) -> int:
    """Shared keyword-matching primitive.

    Used by both filter.py and category.py so the matching semantics
    (exact / phrase / stem) stay consistent across the pipeline.
    """
    hits = 0
    for kw in keywords:
        if kw.endswith("*"):
            stem = kw[:-1]
            if stem and any(t.startswith(stem) for t in tokens):
                hits += 1
        elif " " in kw or "-" in kw:
            if kw in text_lower:
                hits += 1
        elif kw in tokens:
            hits += 1
    return hits

# Anything matching one of these = potentially in-scope cybersecurity news.
# English + a Ukrainian seed list (extend as more uk-language feeds are added).
RELEVANCE_KEYWORDS: frozenset[str] = frozenset({
    # --- English ---
    "breach", "breached", "leak", "leaked", "leaks",
    "hack", "hacked", "hacker", "hackers", "hacking",
    "attack", "attacks", "attacker", "attackers",
    "ransomware", "malware", "spyware", "stalkerware", "adware",
    "phishing", "smishing", "vishing", "scam", "scams", "scammer",
    "exploit", "exploited", "exploits", "exploitation",
    "vulnerability", "vulnerabilities", "vuln", "rce", "lfi", "xss", "sqli",
    "zero-day", "zero day", "0-day", "0day",
    "cve", "patch", "patched", "advisory", "advisories",
    "backdoor", "trojan", "rootkit", "worm", "botnet",
    "ddos", "denial of service",
    "credential", "credentials", "password", "passwords",
    "data leak", "data exposed", "stolen data", "exfiltrated", "exfiltration",
    "supply chain", "supply-chain",
    "spy", "spyware", "surveillance",
    "ransom", "extortion",
    # --- Ukrainian (stems with `*` to cover case/number inflections) ---
    "кібератак*", "атак*",
    "злам*", "хакер*",
    "вразлив*", "уразлив*",
    "експлойт*", "експлуат*",
    "витік", "витоку", "витік даних",
    "фішинг*",
    "шахрай*",
    "шкідлив*", "троян*",
    "програма-вимагач", "вимагач*", "шифрувальник*",
    "ботнет",
    "пароль", "паролі",
})

# If a story matches any of these (and nothing strongly threat-y), drop it.
# Goal: kill funding rounds, product launches, "10 best AVs" listicles, etc.
EXCLUSION_KEYWORDS: frozenset[str] = frozenset({
    "series a", "series b", "series c", "raises $", "raise $",
    "funding round", "ipo", "acquires", "acquisition of",
    "appoints", "named ceo", "named cto", "names ceo", "names cto",
    "partnership", "partners with",
    "best antivirus", "best vpn", "top 10",
    "webinar", "white paper", "ebook",
    "earnings", "quarterly results",
})

# Severity multipliers used by the ranker. Higher = more urgent.
SEVERITY_WEIGHTS: Mapping[str, float] = {
    "critical": 4.0,
    "actively exploited": 4.0,
    "in the wild": 3.5,
    "zero-day": 3.5,
    "0-day": 3.5,
    "zero day": 3.5,
    "0day": 3.5,
    "rce": 3.0,
    "remote code execution": 3.0,
    "unauthenticated": 2.5,
    "wormable": 3.0,
    "high severity": 2.0,
    "emergency patch": 3.0,
    "out-of-band": 2.5,
    "exploit in the wild": 4.0,
}
