"""Threat signal extraction.

Each item gets a small bundle of boolean signals describing the *shape*
of the threat — independent of its category. Signals are:

  * derived deterministically from data already extracted upstream
    (category, platforms, audience, actionability, body keywords)
  * cheap to compute — pure function, no I/O
  * orthogonal where possible — a phishing item can be both
    credential_theft_risk and affects_email_accounts; that's the point.

Signals are NOT stored on the NewsItem. They're recomputed at render
time, which keeps the storage schema stable and lets us iterate on the
derivation rules without invalidating cached items.

Why this layer exists:
  * Powers the "Who should care" / "Potential impact" UI fields.
  * Feeds the homepage ranker (signal-aware multipliers in api/app.py).
  * Foundation for future personalization — "show me crypto-relevant
    threats only" → filter by signals.crypto-related.
  * Surface for analyst-style filtering ("active exploitation only").
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Mapping, Sequence

from ..models import NewsItem


# =========================================================================
# Signal definitions
# =========================================================================

@dataclass(frozen=True)
class ThreatSignals:
    """Boolean signals that describe the *shape* of a threat.

    Field order matches the spec — keep it stable; downstream UI binds
    to these names.
    """
    active_exploitation: bool = False
    credential_theft_risk: bool = False
    financial_risk: bool = False
    enterprise_risk: bool = False
    consumer_risk: bool = False
    requires_immediate_action: bool = False
    affects_email_accounts: bool = False
    steals_sessions: bool = False
    data_exposure_risk: bool = False
    malware_delivery: bool = False

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


# =========================================================================
# Keyword vocabularies (one per signal where keywords are useful)
# =========================================================================

# Phrase matches — substring search on lowercased title+body.
_PHRASES_ACTIVE_EXPLOIT = (
    "actively exploited", "in the wild", "under active attack",
    "exploited in the wild", "exploit in the wild",
    "активно експлуатується", "у дикій природі", "активна експлуатація",
)
_PHRASES_FINANCIAL = (
    "wire transfer", "bank account", "banking trojan", "payment card",
    "credit card", "drained wallet", "crypto theft", "stolen funds",
    "crypto wallet", "stablecoin", "swift fraud", "ach fraud",
    "wallet drainer", "rug pull",
    "крипто-гаманець", "банк-клієнт", "банківський рахунок",
    "крадіжк* коштів", "вкрад* грош",
)
_PHRASES_ENTERPRISE = (
    "active directory", "domain controller", "azure ad", "entra id",
    "vmware esxi", "vmware vsphere", "exchange server",
    "industrial control", "ics network", "scada",
    "kubernetes", "okta", "single sign-on", "sso",
    "edr", "siem", "soc team",
)
_PHRASES_EMAIL = (
    "email account", "mailbox", "inbox", "microsoft 365", "m365",
    "google workspace", "gmail account", "outlook account",
    "exchange online", "imap", "smtp",
    "поштов* скриньк", "email-акаунт", "поштов* акаунт",
)
_PHRASES_SESSION = (
    "session token", "session hijack", "session cookie",
    "cookie theft", "stolen cookies", "auth token", "bearer token",
    "mfa bypass", "2fa bypass", "evilginx", "modlishka",
    "session replay",
    "сесійний токен", "крадіжка сесії", "обхід 2fa", "обхід мфа",
)
_PHRASES_DATA_EXPOSURE = (
    "exposed database", "leaked database", "open elasticsearch",
    "open mongodb", "publicly accessible", "data dump", "leaked records",
    "exposed records", "exfiltrated data", "exfiltration",
    "відкрита база даних", "злив даних", "витік даних", "експозиція даних",
)
_PHRASES_MALWARE_DELIVERY = (
    "infostealer", "stealer family", "loader", "dropper",
    "rat malware", "backdoor", "trojanized installer",
    "malicious installer", "malicious apk", "rogue extension",
    "стілер", "інфостілер", "троянізованої версії", "троянізований",
    "шкідливий apk",
)
# Banking / financial regex catches inflected forms.
_FINANCIAL_REGEX = re.compile(
    r"\b(bank(?:ing)?|fraud|fraudulent|payment card|crypto(?:currenc(?:y|ies))?|wallet)\b",
    flags=re.IGNORECASE,
)

# Audience labels used as inputs.
_ENTERPRISE_AUDIENCES = frozenset({"sysadmins", "enterprise"})
_CONSUMER_AUDIENCES = frozenset({"normal_users", "mobile_users", "crypto_users"})

# Categories that automatically imply each signal.
_CRED_THEFT_CATEGORIES = frozenset({"phishing", "breach", "data leak"})
_DATA_EXPOSURE_CATEGORIES = frozenset({"breach", "data leak"})
_MALWARE_CATEGORIES = frozenset({"malware", "ransomware", "spyware", "botnet"})
_CONSUMER_CATEGORIES = frozenset(
    {"phishing", "scam", "social engineering", "spyware"},
)


# =========================================================================
# Helpers
# =========================================================================

def _contains_any(blob: str, phrases: Sequence[str]) -> bool:
    """Substring match. `blob` is expected lowercased."""
    return any(p in blob for p in phrases)


def _blob(item: NewsItem) -> str:
    """Concatenate title + body for keyword scanning. Lowercased once."""
    return f"{item.title}\n{item.raw_content}".lower()


# =========================================================================
# Public API — signal extraction
# =========================================================================

def extract_signals(item: NewsItem) -> ThreatSignals:
    """Compute the full signal bundle for one item. Pure function.

    Each signal has a small ladder of derivation rules — usually one
    category-based rule + one keyword-based rule + one platform/audience
    rule. ORed together. The aim is high recall; downstream UI / ranker
    handles precision.
    """
    blob = _blob(item)
    category = item.category
    audiences = set(item.audience_targets)
    platforms_lower = {p.lower() for p in item.affected_platforms}

    active = (
        item.actionability_level == "urgent_action"
        or _contains_any(blob, _PHRASES_ACTIVE_EXPLOIT)
    )

    cred_theft = (
        category in _CRED_THEFT_CATEGORIES
        or "credential" in blob
        or "credentials" in blob
        or "password" in blob and category in {"phishing", "scam", "breach"}
    )

    financial = (
        category == "scam"
        or _contains_any(blob, _PHRASES_FINANCIAL)
        or (
            bool(_FINANCIAL_REGEX.search(blob))
            and category in {"scam", "malware", "phishing", "breach"}
        )
        or "crypto_users" in audiences
    )

    enterprise = (
        bool(audiences & _ENTERPRISE_AUDIENCES)
        or _contains_any(blob, _PHRASES_ENTERPRISE)
        or any(
            p in platforms_lower for p in (
                "vmware", "kubernetes", "exchange server", "active directory",
                "azure", "okta", "windows server",
            )
        )
    )

    consumer = (
        bool(audiences & _CONSUMER_AUDIENCES)
        or category in _CONSUMER_CATEGORIES
    )

    immediate = active or item.actionability_level == "urgent_action"

    # `affects_email_accounts` requires EXPLICIT email signal — not just
    # "phishing implies email", because plenty of phishing targets banking
    # or crypto. We trigger only on email-platform mentions or email
    # keywords in the body.
    email = (
        _contains_any(blob, _PHRASES_EMAIL)
        or any(
            p in platforms_lower for p in (
                "microsoft 365", "m365", "outlook", "gmail", "exchange",
            )
        )
    )

    sessions = (
        _contains_any(blob, _PHRASES_SESSION)
        or ("mfa" in blob and "bypass" in blob)
    )

    data_exposure = (
        category in _DATA_EXPOSURE_CATEGORIES
        or _contains_any(blob, _PHRASES_DATA_EXPOSURE)
    )

    malware = (
        category in _MALWARE_CATEGORIES
        or _contains_any(blob, _PHRASES_MALWARE_DELIVERY)
    )

    return ThreatSignals(
        active_exploitation=active,
        credential_theft_risk=cred_theft,
        financial_risk=financial,
        enterprise_risk=enterprise,
        consumer_risk=consumer,
        requires_immediate_action=immediate,
        affects_email_accounts=email,
        steals_sessions=sessions,
        data_exposure_risk=data_exposure,
        malware_delivery=malware,
    )


# =========================================================================
# Derived UX fields — "Who should care", "Potential impact"
# =========================================================================

# Human-friendly platform labels — when the platform name itself is a
# noun phrase a reader would search for. Order matters: first match wins.
_PLATFORM_AUDIENCE_LABELS_EN: Mapping[str, str] = {
    "microsoft 365": "Microsoft 365 users",
    "m365": "Microsoft 365 users",
    "outlook": "Outlook users",
    "gmail": "Gmail users",
    "exchange": "Exchange admins",
    "android": "Android users",
    "ios": "iPhone users",
    "windows": "Windows users",
    "macos": "macOS users",
    "linux": "Linux administrators",
    "chrome": "Chrome users",
    "firefox": "Firefox users",
    "safari": "Safari users",
    "wordpress": "WordPress administrators",
    "vmware": "VMware administrators",
    "kubernetes": "Kubernetes operators",
    "telegram": "Telegram users",
    "discord": "Discord users",
    "whatsapp": "WhatsApp users",
}
_PLATFORM_AUDIENCE_LABELS_UK: Mapping[str, str] = {
    "microsoft 365": "Користувачі Microsoft 365",
    "m365": "Користувачі Microsoft 365",
    "outlook": "Користувачі Outlook",
    "gmail": "Користувачі Gmail",
    "exchange": "Адміністратори Exchange",
    "android": "Користувачі Android",
    "ios": "Користувачі iPhone",
    "windows": "Користувачі Windows",
    "macos": "Користувачі macOS",
    "linux": "Адміністратори Linux",
    "chrome": "Користувачі Chrome",
    "firefox": "Користувачі Firefox",
    "safari": "Користувачі Safari",
    "wordpress": "Адміністратори WordPress",
    "vmware": "Адміністратори VMware",
    "kubernetes": "Оператори Kubernetes",
    "telegram": "Користувачі Telegram",
    "discord": "Користувачі Discord",
    "whatsapp": "Користувачі WhatsApp",
}

# Audience-only fallbacks when the item has no platform but does have an
# audience tag. Less specific than platform names but still concrete.
_AUDIENCE_LABELS_EN: Mapping[str, str] = {
    "normal_users": "Everyday internet users",
    "developers": "Software developers",
    "sysadmins": "IT administrators",
    "enterprise": "Enterprise IT teams",
    "mobile_users": "Mobile device users",
    "crypto_users": "Cryptocurrency users",
}
_AUDIENCE_LABELS_UK: Mapping[str, str] = {
    "normal_users": "Звичайні користувачі інтернету",
    "developers": "Розробники ПЗ",
    "sysadmins": "ІТ-адміністратори",
    "enterprise": "Корпоративні ІТ-команди",
    "mobile_users": "Користувачі мобільних пристроїв",
    "crypto_users": "Користувачі криптовалют",
}

# Signal → impact label. Returned in priority order; the renderer picks
# the top 2-3 so the card doesn't drown in tags.
_IMPACT_LADDER_EN: tuple[tuple[str, str], ...] = (
    ("active_exploitation", "Active exploitation"),
    ("affects_email_accounts", "Email account takeover"),
    ("credential_theft_risk", "Credential compromise"),
    ("financial_risk", "Financial theft"),
    ("steals_sessions", "Session hijacking"),
    ("data_exposure_risk", "Data exposure"),
    ("malware_delivery", "Malware infection"),
)
_IMPACT_LADDER_UK: tuple[tuple[str, str], ...] = (
    ("active_exploitation", "Активна експлуатація"),
    ("affects_email_accounts", "Захоплення поштового акаунта"),
    ("credential_theft_risk", "Крадіжка облікових даних"),
    ("financial_risk", "Фінансова крадіжка"),
    ("steals_sessions", "Перехоплення сесії"),
    ("data_exposure_risk", "Розкриття персональних даних"),
    ("malware_delivery", "Зараження шкідливим ПЗ"),
)


def who_should_care(
    item: NewsItem,
    signals: ThreatSignals,
    *,
    language: str = "en",
) -> str:
    """Return a concise one-line audience label.

    Resolution order — most specific first:
      1. Known platform → "Microsoft 365 users", "Android users", ...
      2. Audience tag    → "IT administrators", "Crypto users", ...
      3. Signal fallback → "Enterprise IT teams" if enterprise_risk,
                           "Everyday users" if consumer_risk,
                           else "Cybersecurity professionals" as the
                           generic safety net.

    Returns at most ONE label — the goal is "instantly answers
    'does this affect me?'", not a comprehensive list.
    """
    platform_labels = _PLATFORM_AUDIENCE_LABELS_UK if language == "ua" else _PLATFORM_AUDIENCE_LABELS_EN
    audience_labels = _AUDIENCE_LABELS_UK if language == "ua" else _AUDIENCE_LABELS_EN

    # Platform match — first item in item.affected_platforms wins.
    for plat in item.affected_platforms:
        label = platform_labels.get(plat.lower())
        if label:
            return label
    # Audience match — first item in item.audience_targets wins.
    for aud in item.audience_targets:
        label = audience_labels.get(aud)
        if label:
            return label
    # Signal-based fallback.
    if signals.enterprise_risk:
        return audience_labels["enterprise"]
    if signals.consumer_risk:
        return audience_labels["normal_users"]
    return "Cybersecurity professionals" if language != "ua" else "Фахівці з кібербезпеки"


def potential_impact(
    signals: ThreatSignals,
    *,
    language: str = "en",
    limit: int = 3,
) -> list[str]:
    """Return a short, ranked list of realistic-impact labels.

    Each entry is a single noun phrase ("Account takeover", "Data exposure").
    We pick the top `limit` signals that fired, in priority order.
    Order is fixed (highest-severity first) so the UI can render with
    predictable visual weight.
    """
    ladder = _IMPACT_LADDER_UK if language == "ua" else _IMPACT_LADDER_EN
    signals_dict = signals.to_dict()
    out: list[str] = []
    for flag_name, label in ladder:
        if signals_dict.get(flag_name) and label not in out:
            out.append(label)
        if len(out) >= limit:
            break
    return out


__all__ = [
    "ThreatSignals",
    "extract_signals",
    "who_should_care",
    "potential_impact",
]
