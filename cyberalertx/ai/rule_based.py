"""Deterministic, dependency-free ThreatPost generator.

In MVP mode this is the **primary** path — the LLM provider is opt-in. The
goal here is output that reads like a careful human draft: concise, scannable,
mobile-friendly, never robotic.

How variety is achieved without randomness:
  * `why_it_matters` is keyed on (category, urgency_bucket) — a 13×3 grid of
    pre-written one-liners. Same input ⇒ same output (testable); different
    items ⇒ different copy.
  * `what_to_do` / `what_not_to_do` defer to the matched `PromptTemplate.rule_based`
    overrides when present, falling back to per-category defaults. Adding
    audience-aware copy is one dict edit, no code change.
  * `quick_facts` are computed from the actual item state (active exploitation
    detected? patch mentioned? credible source?) so they describe THIS item.

Quality vs LLM: this is the floor, not the ceiling. The LLM path remains
the upgrade — see `cyberalertx/ai/generator.py` for the wiring.
"""
from __future__ import annotations

import re
from typing import Mapping, Sequence

from ..models import NewsItem
from .models import ThreatPost
from .templates import TemplateRegistry, default_template_registry

# Short, descriptive audience labels (kept in sync with audience.AUDIENCES keys).
_HUMAN_AUDIENCE: Mapping[str, str] = {
    "normal_users": "Everyday users",
    "developers": "Developers",
    "sysadmins": "IT / sysadmins",
    "enterprise": "Enterprise IT teams",
    "mobile_users": "Mobile users",
    "crypto_users": "Crypto users",
}

# Why-it-matters copy keyed by (category, urgency_bucket).
# Urgency buckets: "urgent" / "soon" / "fyi".
#
# Each value is a list of 2-3 hand-written variants. The renderer picks
# one deterministically from `item.fingerprint`, so:
#   * the same item always gets the same line (testable, cacheable)
#   * two items in the same bucket usually get different lines
#     (no "10 phishing alerts all say the same thing" fatigue)
#
# Twelve canonical categories × three buckets = many slots; only the ones
# we want hand-tuned are written out. Anything missing falls through to
# the (default, *) row, which always exists.
_WHY_IT_MATTERS: Mapping[tuple[str, str], Sequence[str]] = {
    ("phishing", "urgent"): [
        "Active campaign — if your inbox is the target, it's already there.",
        "Live phishing wave. A second of skepticism saves the account.",
        "Real victims today. Verify the sender before you log in anywhere.",
    ],
    ("phishing", "soon"): [
        "Phishing waves peak fast. A minute spent recognizing the bait pays for itself.",
        "Worth a quick read so you can spot the lure when it lands.",
        "Knowing the playbook is most of the defense.",
    ],
    ("phishing", "fyi"): [
        "Useful pattern to keep in mind the next time something feels off.",
        "Background on a technique you might see referenced again soon.",
    ],
    ("ransomware", "urgent"): [
        "If this gang reaches you, you lose access to your files. Backups and patching are the defense.",
        "Active extortion campaign. Confirm your backups before someone tests them for you.",
        "Real incidents in progress. Now is the moment to verify your recovery plan works.",
    ],
    ("ransomware", "soon"): [
        "Worth checking your backup and patch status now, while there's still time.",
        "If your environment looks like the victim profile, take the mitigations seriously.",
    ],
    ("ransomware", "fyi"): [
        "Context on a group you'll probably hear about again.",
        "Background reading; useful when one of these strains hits closer to home.",
    ],
    ("vulnerability", "urgent"): [
        "Attackers are chasing the patch. The window between 'fix shipped' and 'fix exploited' is shrinking.",
        "Patched flaw, but exploitation has started. Roll out the update before you read about it again.",
    ],
    ("vulnerability", "soon"): [
        "Fix is available. Applying it is the cheapest action you can take.",
        "Patch first, debrief later — the fix exists, and someone will write the exploit shortly.",
        "Quick wins: install the update, audit anywhere the affected component runs.",
    ],
    ("vulnerability", "fyi"): [
        "Heads-up on a flaw to track if you run the affected software.",
        "Worth bookmarking so you can act if it lights up later.",
    ],
    ("exploit", "urgent"): [
        "Working exploit, in the wild, today. Patch or mitigate now.",
        "Live attack code. The grace period is over — apply the vendor fix.",
        "Active exploitation observed. This is the part where waiting starts costing.",
    ],
    ("exploit", "soon"): [
        "Exploit code is circulating. Apply the vendor fix before it becomes ubiquitous.",
        "Public exploit, vendor patch available — close the gap quickly.",
    ],
    ("exploit", "fyi"): [
        "Background on a technique; not yet a fire drill for most users.",
    ],
    ("zero-day", "urgent"): [
        "No patch yet, and attackers are already using it. Apply the vendor's workaround if one exists.",
        "Zero-day, live exploitation. Mitigations now, full patch when it ships.",
    ],
    ("zero-day", "soon"): [
        "A zero-day is more dangerous than the usual CVE. Keep an eye on the vendor advisory.",
        "Worth tracking — no fix yet, and the bug is out there.",
    ],
    ("breach", "urgent"): [
        "If your data was in this breach, treat your credentials as burned.",
        "Active fallout. Change passwords and watch for breach-themed phishing.",
    ],
    ("breach", "soon"): [
        "Worth changing the password here and anywhere you reused it.",
        "Standard breach hygiene: rotate the credential, check breach trackers.",
    ],
    ("breach", "fyi"): [
        "Context on who got hit and what's in the open.",
    ],
    ("data leak", "urgent"): [
        "Records are publicly out there. Phishers will use them this week.",
        "The data is out. Expect targeted lures referencing details from the leak.",
    ],
    ("data leak", "soon"): [
        "Good time to check breach-tracking sites for your accounts.",
    ],
    ("malware", "urgent"): [
        "Real infections, real victims. Worth checking your defenses.",
        "Active campaign in the wild. Defenders should hunt for the indicators.",
    ],
    ("malware", "soon"): [
        "Family-level intel; useful for sharpening detections.",
        "Background you'll want when one of these shows up in your logs.",
    ],
    ("spyware", "urgent"): [
        "Targeted surveillance tooling. Review app permissions and update.",
        "Live spyware activity. If you might be in the targeting profile, act today.",
    ],
    ("spyware", "soon"): [
        "If you might be in the targeting profile, take the article's mitigations seriously.",
    ],
    ("scam", "urgent"): [
        "Active fraud playbook. Slow down before sending money or codes.",
        "Live scam in progress. Time pressure is the lure — don't bite.",
    ],
    ("scam", "soon"): [
        "Pattern worth being able to spot — and worth warning family about.",
        "Tactic to recognize before it lands in your DMs.",
    ],
    ("botnet", "soon"): [
        "If you own consumer routers or IoT, this is what silently recruits them.",
        "Worth a glance at any internet-connected device with default settings.",
    ],
    ("social engineering", "urgent"): [
        "Live pretexting campaign. Verify any urgent request out of band.",
        "Active social engineering. Slow the request down; call back through a known channel.",
    ],
    ("social engineering", "soon"): [
        "Specific con; useful to recognize when your colleague forwards it.",
    ],
    # Catch-alls used when no category-specific line is defined.
    ("default", "urgent"): [
        "Active situation. Attackers are exploiting this before patches are widely deployed.",
        "Worth acting on now — the window for safe response is short.",
    ],
    ("default", "soon"): [
        "A fix or guidance has been published. Applying it soon reduces your exposure.",
        "Not a fire drill, but worth handling this week.",
    ],
    ("default", "fyi"): [
        "Useful context for staying current on threats in your environment.",
        "Background reading; not actionable for most readers yet.",
    ],
}


_DEFAULT_ACTIONS: Mapping[str, list[str]] = {
    "phishing": [
        "Open the service directly in your browser instead of clicking the link",
        "Use a password manager — it won't autofill on lookalike domains",
        "Turn on two-factor authentication on important accounts",
    ],
    "ransomware": [
        "Confirm you have offline backups of important files",
        "Apply security updates as soon as your vendor releases them",
        "Disable Remote Desktop (RDP) if you don't actively need it",
    ],
    "vulnerability": [
        "Update the affected software as soon as a patch is available",
        "Subscribe to your vendor's security advisories",
    ],
    "exploit": [
        "Apply the vendor patch immediately if one is available",
        "Check the article for indicators of compromise (IOCs) to hunt for",
    ],
    "zero-day": [
        "Apply emergency mitigations from the vendor advisory",
        "Watch for the official patch and roll it out as soon as it ships",
    ],
    "malware": [
        "Run a reputable anti-malware scan on suspicious systems",
        "Avoid installing software from unknown sources",
    ],
    "spyware": [
        "Review which apps have microphone, camera, and location access",
        "Update your phone and apps to the latest version",
    ],
    "breach": [
        "Change the password for the affected service",
        "Turn on two-factor authentication if you haven't already",
        "Watch for phishing emails referencing this breach for the next few weeks",
    ],
    "data leak": [
        "Change the password for the affected service",
        "Check haveibeenpwned.com for your email address",
    ],
    "scam": [
        "Slow down — scammers rely on time pressure",
        "Verify any payment request through a second channel",
    ],
    "botnet": [
        "Patch consumer routers and IoT devices",
        "Change default passwords on any internet-connected device",
    ],
    "social engineering": [
        "Pause before responding to urgent or unusual requests",
        "Verify the requester through a known channel before acting",
    ],
}

_DEFAULT_AVOIDS: Mapping[str, list[str]] = {
    "phishing": [
        "Don't enter passwords on links you reached from email or SMS",
        "Don't ignore browser security warnings, even on familiar-looking sites",
    ],
    "ransomware": [
        "Don't pay the ransom — it funds the next attack and rarely restores everything",
    ],
    "scam": [
        "Don't share verification codes by phone or chat",
        "Don't transfer money to people you've only spoken to online",
    ],
    "breach": [
        "Don't reuse the leaked password on other sites",
    ],
    "vulnerability": [
        "Don't skip the patch because the bug 'sounds theoretical'",
    ],
}

# Short labels used in quick_facts in place of "Type: <category>".
# Reads as a noun phrase, which mobile users scan faster than a key:value pair.
_CATEGORY_FACT_LABEL: Mapping[str, str] = {
    "phishing": "Phishing campaign",
    "ransomware": "Ransomware",
    "vulnerability": "Vulnerability",
    "exploit": "Active exploit",
    "zero-day": "Zero-day",
    "breach": "Data breach",
    "data leak": "Data leak",
    "malware": "Malware",
    "spyware": "Spyware",
    "scam": "Scam",
    "botnet": "Botnet",
    "social engineering": "Social engineering",
}


_PATCH_AVAILABLE_RE = re.compile(
    r"\b(patch|fix|update)\s+(is\s+)?(available|released|now\s+available|out)\b",
    flags=re.IGNORECASE,
)
_ACTIVE_EXPLOIT_RE = re.compile(
    r"\b(actively\s+exploited|in\s+the\s+wild|under\s+(active\s+)?attack)\b",
    flags=re.IGNORECASE,
)
# Lines like "By John Doe, May 11, 2026" — common feed prefixes we want to skip.
_BYLINE_RE = re.compile(
    r"^\s*(by\s+\S+|posted\s+by\s+\S+|on\s+\w+\s+\d{1,2},?\s*\d{4})\b",
    flags=re.IGNORECASE,
)


def _urgency_bucket(item: NewsItem) -> str:
    """Map (actionability_level, threat_score) to one of: urgent | soon | fyi."""
    if item.actionability_level == "urgent_action":
        return "urgent"
    if item.actionability_level == "recommended_action":
        return "soon"
    # Informational with a high threat score still benefits from "soon" framing.
    if item.threat_score >= 50:
        return "soon"
    return "fyi"


def _variant_index(fingerprint: str, count: int) -> int:
    """Pick a variant index deterministically from the item's fingerprint.

    Two properties matter:
      * **Stable** — same fingerprint → same index (so cache, tests, and
        repeat renders are reproducible).
      * **Distributed** — different fingerprints distribute uniformly across
        the variant pool, which is what kills template fatigue.

    The fingerprint is a 16-char hex slice (see `NewsItem.fingerprint`); the
    first 8 chars give us 32 bits of effectively-random integer — more than
    enough variety for 2-5 variant pools.
    """
    if count <= 1:
        return 0
    try:
        seed = int(fingerprint[:8], 16)
    except (ValueError, IndexError):
        seed = 0
    return seed % count


def _select_why_it_matters(category: str, bucket: str, fingerprint: str) -> str:
    variants = (
        _WHY_IT_MATTERS.get((category, bucket))
        or _WHY_IT_MATTERS.get(("default", bucket))
        or _WHY_IT_MATTERS[("default", "fyi")]
    )
    return variants[_variant_index(fingerprint, len(variants))]


def _trim_at_word(text: str, limit: int) -> tuple[str, bool]:
    """Trim `text` to at most `limit` chars, breaking on a word boundary.

    Returns (trimmed_text, was_truncated).
    """
    if len(text) <= limit:
        return text, False
    cut = text.rfind(" ", 0, limit)
    if cut < limit * 0.6:  # no clean break point → hard cut
        cut = limit
    return text[:cut].rstrip(",.:;-"), True


# Common cybersecurity acronyms we always preserve at original casing.
# Anything ALL-CAPS not in this set gets sentence-cased when the title is shouting.
_PRESERVED_ACRONYMS: frozenset[str] = frozenset({
    "AI", "API", "APT", "AWS", "BIOS", "CISA", "CVE", "DDoS", "DNS",
    "FBI", "GPU", "HTTP", "HTTPS", "ICS", "IoT", "IP", "JS", "JSON",
    "LDAP", "MFA", "NSA", "OAuth", "OS", "OTP", "PDF", "PHP", "PIN",
    "RAM", "RCE", "RDP", "SDK", "SMS", "SQL", "SSH", "SSL", "TLS",
    "UEFI", "URL", "USB", "VPN", "XML", "XSS", "2FA",
})


def _normalize_shouty_title(title: str) -> str:
    """Gently sentence-case titles dominated by uppercase shouting.

    Real-world feeds occasionally carry titles like
    "URGENT! HACKERS BREACH MAJOR SYSTEM" — clickbaity and hard to scan
    on mobile. We detect the shouting by overall upper:lower ratio and
    apply word-by-word capitalization. Two preservation rules:
      * tokens containing a digit (e.g. "CVE-2026-1234") are identifiers
        and stay verbatim
      * tokens in `_PRESERVED_ACRONYMS` (CVE, AI, RCE, API, …) stay verbatim
    """
    letters = [c for c in title if c.isalpha()]
    if len(letters) < 8:
        return title  # short titles are unlikely to be shouting
    upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
    # Title Case rarely exceeds ~40% uppercase. 70%+ is shouting.
    if upper_ratio < 0.7:
        return title

    def fix(word: str) -> str:
        if any(c.isdigit() for c in word):
            return word  # identifier like "CVE-2026-1234" — keep as-is
        if word in _PRESERVED_ACRONYMS:
            return word
        if word.isupper():
            return word.capitalize()
        return word

    return " ".join(fix(w) for w in title.split())


def _extract_lead(body: str, max_chars: int = 220) -> str:
    """Pick a clean opening sentence-or-two from `body`.

    Strips obvious byline / metadata lines and trims at a word boundary.
    """
    body = body.strip()
    if not body:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", body)
    # Drop leading byline-y sentences.
    while sentences and _BYLINE_RE.match(sentences[0]):
        sentences.pop(0)
    if not sentences:
        return ""

    snippet = sentences[0].strip()
    # On mobile the first sentence is often plenty. Only pull a second one
    # when the first is unhelpfully short.
    if len(snippet) < 100 and len(sentences) > 1:
        snippet = (snippet + " " + sentences[1].strip()).strip()

    trimmed, truncated = _trim_at_word(snippet, max_chars)
    return trimmed + ("…" if truncated else "")


class RuleBasedGenerator:
    """Always-available ThreatPost generator. No network, no LLM, no key required."""

    def __init__(self, template_registry: TemplateRegistry | None = None) -> None:
        # We consult the registry for `rule_based` overrides keyed on
        # (language, category, audience). When no override is defined, the
        # generator's own defaults (above) take over.
        self._templates = template_registry or default_template_registry()

    def generate(self, item: NewsItem) -> ThreatPost:
        language = item.language if item.language in ("en", "uk") else "en"
        audience = item.audience_targets[0] if item.audience_targets else "general"
        overrides = self._lookup_overrides(language, item.category, audience)
        bucket = _urgency_bucket(item)

        return ThreatPost(
            title=self._title(item),
            short_summary=self._summary(item),
            threat_level=self._threat_level(item),
            why_it_matters=self._why_it_matters(item, bucket, overrides),
            affected_users=self._affected_users(item),
            what_to_do=self._what_to_do(item, overrides),
            what_not_to_do=self._what_not_to_do(item, overrides),
            quick_facts=self._quick_facts(item),
            emotional_weight=self._emotional_weight(item),
            reading_time_seconds=self._reading_time(item),
            language=language,
            source_fingerprint=item.fingerprint,
            generated_by="rule_based",
        )

    # ---------- template integration ----------

    def _lookup_overrides(
        self, language: str, category: str, audience: str,
    ) -> Mapping[str, object]:
        template = self._templates.select(language, category, audience)
        return template.rule_based or {}

    # ---------- field derivations ----------

    @staticmethod
    def _title(item: NewsItem) -> str:
        t = _normalize_shouty_title(item.title.strip())
        trimmed, truncated = _trim_at_word(t, 120)
        return trimmed + ("…" if truncated else "")

    @staticmethod
    def _summary(item: NewsItem) -> str:
        lead = _extract_lead(item.raw_content)
        return lead or f"{item.source} reports: {item.title}"

    @staticmethod
    def _threat_level(item: NewsItem) -> str:
        if item.actionability_level == "urgent_action":
            return "Critical" if item.threat_score >= 50 else "High"
        if item.actionability_level == "recommended_action":
            return "High" if item.threat_score >= 50 else "Medium"
        return "Medium" if item.threat_score >= 30 else "Low"

    @staticmethod
    def _why_it_matters(
        item: NewsItem, bucket: str, overrides: Mapping[str, object],
    ) -> str:
        override = overrides.get("why_it_matters")
        if isinstance(override, str) and override.strip():
            return override.strip()
        return _select_why_it_matters(item.category, bucket, item.fingerprint)

    @staticmethod
    def _affected_users(item: NewsItem) -> list[str]:
        out: list[str] = []
        if item.affected_platforms:
            # Natural form: "Windows and Linux users" — not "Windows, Linux users"
            platforms = item.affected_platforms
            if len(platforms) == 1:
                out.append(f"{platforms[0]} users")
            elif len(platforms) == 2:
                out.append(f"{platforms[0]} and {platforms[1]} users")
            else:
                out.append(f"{', '.join(platforms[:-1])}, and {platforms[-1]} users")
        for a in item.audience_targets:
            label = _HUMAN_AUDIENCE.get(a, a.replace("_", " ").capitalize())
            if label not in out:
                out.append(label)
        return out or ["Anyone following cybersecurity news"]

    @staticmethod
    def _what_to_do(
        item: NewsItem, overrides: Mapping[str, object],
    ) -> list[str]:
        override = overrides.get("what_to_do")
        if isinstance(override, (list, tuple)) and override:
            return [str(s).strip() for s in override if str(s).strip()]
        return list(_DEFAULT_ACTIONS.get(item.category, [
            "Read the source article for specifics",
            "Apply patches and updates as your vendors release them",
        ]))

    @staticmethod
    def _what_not_to_do(
        item: NewsItem, overrides: Mapping[str, object],
    ) -> list[str]:
        override = overrides.get("what_not_to_do")
        if isinstance(override, (list, tuple)):
            return [str(s).strip() for s in override if str(s).strip()]
        return list(_DEFAULT_AVOIDS.get(item.category, []))

    @staticmethod
    def _quick_facts(item: NewsItem) -> list[str]:
        """Mobile-scan bullets. Each fact is a short noun phrase (≤ 30 chars
        whenever possible). Order is fixed for readability — urgency first,
        then platform, then category label, then source provenance — because
        the variety in `why_it_matters` already breaks visual sameness; mixing
        up *fact ordering* would make scanning harder, not easier.
        """
        facts: list[str] = []
        text_lower = (item.title + "\n" + item.raw_content).lower()

        # 1. Most-important urgency fact (at most one of these).
        if _ACTIVE_EXPLOIT_RE.search(text_lower) or item.actionability_level == "urgent_action":
            facts.append("Actively exploited")
        elif _PATCH_AVAILABLE_RE.search(text_lower):
            facts.append("Patch available")

        # 2. Platform impact — phrased naturally instead of "Affects X +1".
        platforms = item.affected_platforms
        if len(platforms) == 1:
            facts.append(f"Affects {platforms[0]}")
        elif len(platforms) == 2:
            facts.append(f"Affects {platforms[0]} & {platforms[1]}")
        elif len(platforms) >= 3:
            facts.append("Multi-platform")

        # 3. Category label — noun phrase, no "Type:" prefix.
        if item.category and item.category != "other":
            facts.append(_CATEGORY_FACT_LABEL.get(item.category, item.category.capitalize()))

        # 4. Provenance — only when the source genuinely adds confidence.
        if item.source_tier == "trusted" and item.source_credibility_score >= 0.85:
            facts.append(f"{item.source}")

        # Last-resort fallback so the list is never empty.
        if not facts:
            facts.append(item.source)
            facts.append(f"Threat score {item.threat_score:.0f}/100")

        # Dedupe (preserving order), cap at 4 for mobile.
        seen: set[str] = set()
        unique: list[str] = []
        for f in facts:
            if f not in seen:
                seen.add(f)
                unique.append(f)
        return unique[:4]

    @staticmethod
    def _emotional_weight(item: NewsItem) -> float:
        weight = (
            item.actionability_score * 0.6
            + min(item.threat_score / 100.0, 1.0) * 0.3
            + item.source_credibility_score * 0.1
        )
        return round(max(0.0, min(1.0, weight)), 3)

    @staticmethod
    def _reading_time(item: NewsItem) -> int:
        words = len(item.raw_content.split())
        sec = max(15, min(45, words // 3))
        return sec


__all__ = ["RuleBasedGenerator"]
