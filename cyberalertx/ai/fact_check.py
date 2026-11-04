"""Deterministic factual validation of a rendered brief against its source.

The audit behind this module found briefs printing CVE ids, CVSS scores,
versions, dates and figures that the source article never contained — the
feeds ship 175-400 character teasers, and the model filled the gap from
memory. Nothing checked. This module extracts every *protected token* from
the rendered text and asks one question per token: does the source (title +
body) or the story's fact sheet contain it?

PROTECTED TOKENS

  hard  — CVE ids, file hashes (MD5 / SHA-1 / SHA-256), public IP addresses,
          CVSS scores. A reader copies these into a scanner, a blocklist or a
          patch ticket; an invented one is worse than none. Any hard token the
          source does not contain fails the render (`ValidationFailure` in the
          generator → the existing rule-based fallback).
  soft  — version strings, dates, numbers with units / percentages, domains,
          private or loopback addresses, and Latin-script names in the prose
          fields. These are recorded on the post (and lower the scorecard) but
          never reject on their own: the matching is approximate, and "four
          hours" in the source versus "4 hours" in the brief must not cost a
          post.

WHAT COUNTS AS SUPPORT

  * Hard tokens: the source text, plus the fact sheet's `cve_ids` and
    `cvss_scores` — which `fact_sheet.sanitize_fact_sheet` has already
    filtered to values present in the source. The sheet's free text never
    vouches for a hard token: the sheet was written by a model from the same
    teaser, so a CVE that only the sheet knows is a hallucination twice over.
  * Soft tokens: the source text, the whole fact sheet, and the item's own
    metadata (source name, URL host, platforms).

Matching is deliberately lenient on the source side, because a false hard
violation costs a whole post: a CVSS score is supported if the decimal occurs
anywhere in the source; a number is supported if a source number equals it or
rounds to it; a date matches on month and day (and year when both give one).

Normalization: case, Unicode hyphens and en dashes, non-breaking and thin
spaces, thousands separators, decimal commas, defanged indicators
(`evil[.]com`, `hxxp://`), "CVSS 9.8" vs "9.8/10" vs "9,8 за CVSS".

`check_cross_locale` compares the EN and UA renders of one story with the same
extractors, so a UA brief that moved the attack from 1 to 2 November is caught
when the second locale is written.
"""
from __future__ import annotations

import ipaddress
import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable, Sequence
from urllib.parse import urlparse

if TYPE_CHECKING:  # import cycle: fact_sheet uses the extractors below
    from .fact_sheet import FactSheet

HARD_KINDS: frozenset[str] = frozenset({"cve", "hash", "ip", "cvss"})
SOFT_KINDS: frozenset[str] = frozenset(
    {"version", "date", "number", "domain", "private_ip", "entity"}
)

#: Every text field a reader can see, in reading order.
TEXT_FIELDS: tuple[str, ...] = (
    "title", "plain_summary", "short_summary", "why_it_matters", "detail_body",
    "severity_reason", "quick_facts", "affected_users", "am_i_affected",
    "what_to_do", "what_not_to_do", "if_already_affected",
)
#: Fields where unattributed background knowledge shows up. UI paths in the
#: action lists ("Settings > Privacy") are not names and are not scanned.
_ENTITY_FIELDS: frozenset[str] = frozenset({
    "title", "plain_summary", "short_summary", "why_it_matters", "detail_body",
    "severity_reason", "quick_facts",
})


# ===========================================================================
# Data
# ===========================================================================

@dataclass(frozen=True)
class Token:
    """One protected token found in a text."""

    kind: str
    raw: str
    norm: str
    field: str = ""
    value: float | None = None          # numbers, CVSS
    date: tuple[int | None, int, int] | None = None   # (year, month, day)


@dataclass(frozen=True)
class Finding:
    """A token the source does not support, or a cross-locale mismatch."""

    kind: str
    value: str
    field: str
    severity: str            # "hard" | "soft" | "major" | "minor"
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "kind": self.kind, "value": self.value, "field": self.field,
            "severity": self.severity, "message": self.message,
        }


@dataclass
class FactCheckReport:
    hard: list[Finding] = field(default_factory=list)
    soft: list[Finding] = field(default_factory=list)
    checked: int = 0
    supported: int = 0
    source_available: bool = True

    @property
    def ok(self) -> bool:
        return not self.hard

    def failure_message(self) -> str:
        """The `ValidationFailure` text. Prefix is stable: metrics route on it."""
        parts = [f"{f.kind} {f.value} ({f.field})" for f in self.hard[:4]]
        return "fact check: not in source or fact sheet: " + ", ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hard": [f.to_dict() for f in self.hard],
            "soft": [f.to_dict() for f in self.soft],
            "checked": self.checked,
            "supported": self.supported,
            "source_available": self.source_available,
        }


# ===========================================================================
# Normalization
# ===========================================================================

# Hyphen-like characters folded to "-". The em dash (U+2014) is punctuation
# in prose and is left alone.
_HYPHENS = dict.fromkeys(map(ord, "‐‑‒–−﹣－"), "-")
_SPACES = dict.fromkeys(map(ord, "     "), " ")
_DEFANG = (
    (re.compile(r"\[\s*\.\s*\]|\(\s*\.\s*\)|\{\s*\.\s*\}|\[dot\]", re.I), "."),
    (re.compile(r"\bhxxp", re.I), "http"),
    (re.compile(r"\[:\]"), ":"),
)


def normalize_text(text: str) -> str:
    out = (text or "").translate(_HYPHENS).translate(_SPACES)
    for pattern, repl in _DEFANG:
        out = pattern.sub(repl, out)
    return out.replace("`", " ")


def _mask(text: str, start: int, end: int) -> str:
    return text[:start] + " " * (end - start) + text[end:]


# ===========================================================================
# Extractors
# ===========================================================================

_URL_RE = re.compile(r"\bhttps?://[^\s<>\"')\]]+", re.I)
_CVE_RE = re.compile(r"\bCVE-(\d{4})-(\d{4,7})\b", re.I)
_HASH_RE = re.compile(r"(?<![0-9A-Za-z])([0-9a-fA-F]{64}|[0-9a-fA-F]{40}|[0-9a-fA-F]{32})(?![0-9A-Za-z])")
_IPV4_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d{1,3}){3})(?:/\d{1,2})?(?![\w]|\.\d)")
_IPV6_RE = re.compile(r"(?<![\w:.])((?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4})(?![\w:])")
_CVSS_VECTOR_RE = re.compile(r"CVSS:\d\.\d(?:/[A-Za-z]{1,3}:[A-Za-z]{1,2})+")
_CVSS_WORD_RE = re.compile(r"\bCVSS(?:v\d(?:\.\d)?)?\b", re.I)
_CVSS_VERSION_PREFIX_RE = re.compile(
    r"^\s*(?:v\s?\d(?:\.\d)?|version\s+\d(?:\.\d)?|\d\.\d(?=\s+(?:base\s+)?score))", re.I,
)
_SCORE_NUM_RE = re.compile(r"(?<![\d.,])(\d{1,2}(?:[.,]\d)?)(?![\d+]|[.,]\d)")
#: Numbers that, right after "CVSS", are the standard's version, not a score.
_CVSS_VERSIONS = frozenset({"2", "2.0", "3", "3.0", "3.1", "4", "4.0"})
_CVSS_OUT_OF_RE = re.compile(
    r"(?<![\d.,])(\d{1,2}[.,]\d)\s*(?:/\s*10\b|out\s+of\s+10\b|з\s+10\b|із\s+10\b|бал\w*\s+з\s+10)", re.I,
)
_CVSS_SUFFIX_RE = re.compile(r"(?<![\d.,])(\d{1,2}[.,]\d)\s+(?:за\s+(?:шкалою\s+)?)?CVSS\b", re.I)

_EN_MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4, "May": 5, "June": 6,
    "July": 7, "August": 8, "September": 9, "October": 10, "November": 11,
    "December": 12, "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "Jun": 6, "Jul": 7,
    "Aug": 8, "Sep": 9, "Sept": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}
_UA_MONTHS = {
    "січня": 1, "лютого": 2, "березня": 3, "квітня": 4, "травня": 5,
    "червня": 6, "липня": 7, "серпня": 8, "вересня": 9, "жовтня": 10,
    "листопада": 11, "грудня": 12,
}
_EN_MONTH_ALT = "|".join(sorted(_EN_MONTHS, key=len, reverse=True))
_UA_MONTH_ALT = "|".join(_UA_MONTHS)
_ISO_DATE_RE = re.compile(r"\b((?:19|20)\d{2})-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b")
_DOTTED_DATE_RE = re.compile(r"\b(0?[1-9]|[12]\d|3[01])\.(0?[1-9]|1[0-2])\.((?:19|20)\d{2})\b")
# Ranges ("July 12-13", "12-13 липня", "3 and 4 May") yield both days.
_DAY_RANGE = r"(?:\s*(?:-|to|and|through|і|та|й|по)\s*(\d{1,2})(?:st|nd|rd|th)?)?"
_EN_MD_RE = re.compile(
    rf"\b({_EN_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?!:\d){_DAY_RANGE}"
    rf"(?:,?\s+((?:19|20)\d{{2}}))?"
)
_EN_DM_RE = re.compile(
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?{_DAY_RANGE}\s+(?:of\s+)?({_EN_MONTH_ALT})\b\.?"
    rf"(?:,?\s+((?:19|20)\d{{2}}))?"
)
_UA_DM_RE = re.compile(
    rf"(?<![\d:])(\d{{1,2}})(?:-?го)?{_DAY_RANGE}\s+({_UA_MONTH_ALT})(?:\s+((?:19|20)\d{{2}}))?",
    re.I,
)

_VERSION_V_RE = re.compile(r"(?<![\w.])v(\d+(?:\.\d+)+(?:-[0-9A-Za-z.]+)?)(?![\w])(?!\.\d)", re.I)
_VERSION_3_RE = re.compile(
    r"(?<![\w.\-/])(\d+(?:\.\d+){2,}(?:-(?:rc|beta|alpha|pre|patch|build|b|p)[0-9A-Za-z.]*)?)(?![\w])(?!\.\d)",
    re.I,
)
_VERSION_KEYWORD_RE = re.compile(
    r"(?:\bversions?|\bbuild|\brelease|\bверсі[їяюйєі]\w*|\bвипуск\w*|\bзбірк\w*)\s+(\d+\.\d+)(?![\w.])",
    re.I,
)

_TLDS = (
    "com|net|org|io|ru|ua|info|biz|xyz|top|gov|edu|mil|co|uk|de|fr|nl|it|es|pl|cz|eu|us|ca|"
    "au|jp|kr|cn|in|br|me|app|dev|site|online|shop|store|cc|tk|su|kz|by|ws|pw|live|club|link|"
    "click|cloud|ai|tech|gg|ly|icu|cyou|sbs|space|website|fun|host|pro|mobi|name|tv|asia|ch|"
    "at|be|se|no|fi|dk|ie|pt|ro|hu|gr|tr|il|ir|vn|id|th|my|sg|hk|tw|nz|za|mx|ar|cl|lt|lv|ee|"
    "ge|am|az|uz|bg|sk|si|hr|rs"
)
_DOMAIN_RE = re.compile(
    rf"(?<![\w.\-/\\])((?:[a-z0-9](?:[a-z0-9-]{{0,61}}[a-z0-9])?\.)+(?:{_TLDS}))(?![\w-])(?!\.[a-z0-9])",
    re.I,
)

_SCALES: tuple[tuple[re.Pattern[str], float], ...] = (
    (re.compile(r"^\s*(?:thousand|тис\.?|тисяч\w*|k)\b", re.I), 1e3),
    (re.compile(r"^\s*(?:million|млн\.?|мільйон\w*|m)\b", re.I), 1e6),
    (re.compile(r"^\s*(?:billion|млрд\.?|мільярд\w*|bn)\b", re.I), 1e9),
    (re.compile(r"^\s*(?:trillion|трлн\.?|трильйон\w*)\b", re.I), 1e12),
)
_UNIT_RE = re.compile(
    r"^\s*(?:"
    r"%|percent\b|per\s+cent\b|відсот\w*"
    r"|usd\b|eur\b|uah\b|dollars?\b|euros?\b|долар\w*|євро\b|гривень\b|гривн\w*|грн\b"
    r"|[kmgtp]i?b\b|[кмгтп]б\b|bytes?\b|байт\w*"
    r"|(?:hours?|days?|weeks?|months?|years?|minutes?|seconds?|hrs?)\b"
    r"|(?:годин\w*|дн(?:і|ів|я)\b|доб\w*|тижн\w*|місяц\w*|рок(?:и|ів|у)\b|років\b|хвилин\w*|секунд\w*)"
    r"|(?:users?|customers?|people|persons?|accounts?|records?|devices?|servers?|hosts?|"
    r"organi[sz]ations?|victims?|compan(?:y|ies)|sites?|websites?|domains?|packages?|"
    r"repositor(?:y|ies)|vulnerabilit(?:y|ies)|flaws?|bugs?|patients?|employees?|"
    r"subscribers?|members?|files?|emails?|messages?|apps?|applications?|extensions?|"
    r"instances?|endpoints?|routers?|machines?|systems?|countries|cities|banks?|students?|"
    r"hospitals?|clinics?|schools?|universit(?:y|ies)|agencies|governments?|tokens?|keys?|"
    r"passwords?|credentials?|campaigns?|attacks?|incidents?|samples?|variants?)\b"
    r"|(?:користувач\w*|клієнт\w*|людей\b|осіб\b|особ\w*|облікових\b|записів\b|запис\w*|"
    r"пристро\w*|сервер\w*|організац\w*|жертв\w*|компан\w*|сайт\w*|пакет\w*|репозитор\w*|"
    r"[ув]разливост\w*|пацієнт\w*|працівник\w*|абонент\w*|файл\w*|лист\w*|повідомлен\w*|"
    r"застосун\w*|розширен\w*|машин\w*|систем\w*|країн\w*|міст\w*|банк\w*|студент\w*|"
    r"лікар\w*|шкіл\w*|школ\w*|університет\w*|агентств\w*|токен\w*|ключ\w*|парол\w*|"
    r"кампані\w*|атак\w*|інцидент\w*|зразк\w*)"
    r")",
    re.I,
)
_NUM_RE = re.compile(
    r"(?<![\w.,/:\-])(?P<cur>[$€£₴]\s?)?"
    r"(?P<num>\d{1,3}(?:[, ]\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)"
    r"(?![\w]|[.,]\d)",
)

_EN_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90, "hundred": 100, "dozen": 12, "a dozen": 12,
}
_UA_NUMBER_WORDS = {
    "один": 1, "одна": 1, "одне": 1, "одного": 1, "одній": 1, "два": 2, "дві": 2,
    "двох": 2, "три": 3, "трьох": 3, "чотири": 4, "чотирьох": 4, "п'ять": 5,
    "пʼять": 5, "п’ять": 5, "п'яти": 5, "шість": 6, "шести": 6, "сім": 7, "семи": 7,
    "вісім": 8, "восьми": 8, "дев'ять": 9, "дев'яти": 9, "десять": 10, "десяти": 10,
    "дванадцять": 12, "двадцять": 20, "тридцять": 30, "сорок": 40, "сто": 100,
    "тисяча": 1000, "тисячі": 1000,
}
_NUMBER_WORD_RE = re.compile(
    r"\b(" + "|".join(
        sorted(list(_EN_NUMBER_WORDS) + list(_UA_NUMBER_WORDS), key=len, reverse=True)
    ) + r")\b(\s+(?:thousand|million|billion|тисяч\w*|мільйон\w*|мільярд\w*|млн|млрд))?",
    re.I,
)

# Latin-script name candidates: a capitalised or camel/digit-bearing token.
_ENTITY_RE = re.compile(r"(?<![\w@./\\-])([A-Z][A-Za-z0-9]*(?:[-.][A-Za-z0-9]+)*|[a-z]+[A-Z][A-Za-z0-9]*)(?![\w@-])")
_SENTENCE_START_RE = re.compile(r"(?:^|[.!?:;]\s+|\n\s*|[\"«(—]\s*)$")
_ENTITY_STOP = frozenset(w.lower() for w in (
    # Jargon and acronyms the prompt itself uses.
    "CVE", "CVSS", "RCE", "LPE", "PoC", "IOC", "IOCs", "IoC", "IoCs", "API", "APIs",
    "URL", "URLs", "IP", "IPs", "DNS", "VPN", "VPNs", "MFA", "2FA", "OTP", "SMS",
    "USB", "PDF", "ZIP", "AI", "LLM", "LLMs", "ID", "IDs", "OS", "CPU", "GPU",
    "RAM", "HTTP", "HTTPS", "SSH", "SSL", "TLS", "SQL", "XSS", "SSRF", "CSRF",
    "DoS", "DDoS", "C2", "CI", "CD", "CI/CD", "IT", "EU", "US", "UK", "USA",
    "NVD", "MITRE", "ATT", "CK", "APT", "APTs", "EDR", "XDR", "SIEM", "SOC",
    "TTPs", "TTP", "OAuth", "SSO", "JWT", "RDP", "SMB", "LDAP", "AD", "IAM",
    "KEV", "N-day", "N-days", "Zero-day", "Zero-days", "Zero", "Day", "SaaS",
    "IoT", "OT", "ICS", "SCADA", "NAS", "QR", "PIN", "PINs", "OTPs", "ISP",
    "WAF", "CDN", "JSON", "XML", "HTML", "JavaScript", "Python", "PowerShell",
    "BEC", "UEFI", "BIOS", "MSI", "EXE", "DLL", "ROOT", "Root", "GitHub",
    "Wi-Fi", "WiFi", "Bluetooth", "NFC", "eSIM", "SIM", "UTC", "GMT", "PST",
    "Settings", "Help", "About", "Menu", "Security", "Privacy", "Update",
    "Updates", "General", "Software", "Advanced", "System", "Apps", "Account",
    "Accounts", "Sign", "Start", "Control", "Panel", "Network", "Internet",
    "Options", "Preferences", "Tools", "Extensions", "Devices", "Admin",
    "Console", "Dashboard", "Home", "File", "Edit", "View", "Patch", "Tuesday",
    "Monday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "Critical", "High", "Medium", "Low", "Don't", "Do", "Not", "No", "If",
    "The", "A", "An", "This", "That", "These", "Those", "It", "Its", "In",
    "On", "At", "For", "By", "With", "From", "After", "Before", "When", "While",
    "Run", "Open", "Check", "Install", "Remove", "Block", "Disable", "Enable",
    "Change", "Reset", "Rotate", "Revoke", "Delete", "Review", "Restart",
    "Reboot", "Upgrade", "Apply", "Turn", "Go", "Use", "Ask", "Call",
    "Linux", "Windows", "macOS", "Android", "iOS", "Unix", "Mac",
    "CVEs", "More", "Most", "Many", "Some", "All", "Any", "Both", "Each", "Other",
    *_EN_MONTHS,
))


def _new_token(kind: str, raw: str, norm: str, fieldname: str, **extra: Any) -> Token:
    return Token(kind=kind, raw=raw, norm=norm, field=fieldname, **extra)


def _parse_number(raw: str) -> float | None:
    s = raw.replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", s):
        s = s.replace(",", "")
    elif "," in s and "." not in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _format_value(value: float) -> str:
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.6g}"


def _date_norm(year: int | None, month: int, day: int) -> str:
    return f"{year if year else '----'}-{month:02d}-{day:02d}"


def extract_tokens(text: str, field_name: str = "", *, entities: bool = False) -> list[Token]:
    """Every protected token in `text`, in a fixed extraction order.

    Matched spans are blanked before the next extractor runs, so the digits
    of a CVE id never come back as a number, a CVE's year never as a date,
    and an IP address never as a version.
    """
    s = normalize_text(text)
    out: list[Token] = []
    seen: set[tuple[str, str]] = set()

    def add(tok: Token) -> None:
        key = (tok.kind, tok.norm)
        if key not in seen:
            seen.add(key)
            out.append(tok)

    # URLs: keep the host (domain or IP), blank the rest — paths are full of
    # digits that are not facts.
    for m in list(_URL_RE.finditer(s)):
        try:
            host = (urlparse(m.group(0)).hostname or "").lower()
        except ValueError:
            host = ""
        if host and _is_ip(host):
            add(_ip_token(ipaddress.ip_address(host), host, field_name))
        elif host:
            add(_new_token("domain", host, _domain_norm(host), field_name))
        s = _mask(s, m.start(), m.end())

    for m in list(_CVE_RE.finditer(s)):
        add(_new_token("cve", m.group(0), f"CVE-{m.group(1)}-{m.group(2)}", field_name))
        s = _mask(s, m.start(), m.end())

    for m in list(_HASH_RE.finditer(s)):
        h = m.group(1)
        if re.search(r"[a-fA-F]", h) and re.search(r"\d", h):
            add(_new_token("hash", h, h.lower(), field_name))
            s = _mask(s, m.start(), m.end())

    for m in list(_IPV4_RE.finditer(s)):
        raw = m.group(1)
        if s[max(0, m.start() - 1):m.start()].lower() == "v":
            continue
        try:
            addr = ipaddress.IPv4Address(raw)
        except ValueError:
            continue
        add(_ip_token(addr, raw, field_name))
        s = _mask(s, m.start(), m.end())

    for m in list(_IPV6_RE.finditer(s)):
        raw = m.group(1)
        if not re.search(r"[0-9A-Fa-f]", raw) or (raw.count(":") < 7 and "::" not in raw):
            continue
        try:
            addr6 = ipaddress.IPv6Address(raw)
        except ValueError:
            continue
        add(_ip_token(addr6, raw, field_name))
        s = _mask(s, m.start(), m.end())

    for m in list(_CVSS_VECTOR_RE.finditer(s)):
        s = _mask(s, m.start(), m.end())
    for tok, start, end in _cvss_matches(s, field_name):
        add(tok)
        s = _mask(s, start, end)

    # Day-first before month-first, so "28 August 20:57" is 28 August and
    # never "August 20".
    for pattern, order in (
        (_ISO_DATE_RE, "ymd"), (_DOTTED_DATE_RE, "dmy"), (_EN_DM_RE, "dmy_en"),
        (_EN_MD_RE, "mdy"), (_UA_DM_RE, "dmy_ua"),
    ):
        for m in list(pattern.finditer(s)):
            parsed = _parse_dates(m, order)
            if not parsed:
                continue
            raw = m.group(0).strip().rstrip(".,")
            for year, month, day in parsed:
                add(_new_token("date", raw, _date_norm(year, month, day),
                               field_name, date=(year, month, day)))
            s = _mask(s, m.start(), m.end())

    for pattern in (_VERSION_V_RE, _VERSION_3_RE, _VERSION_KEYWORD_RE):
        for m in list(pattern.finditer(s)):
            raw = m.group(1)
            add(_new_token("version", raw, raw.lower().lstrip("v"), field_name))
            s = _mask(s, m.start(1), m.end(1))

    for m in list(_DOMAIN_RE.finditer(s)):
        raw = m.group(1)
        add(_new_token("domain", raw, _domain_norm(raw), field_name))
        s = _mask(s, m.start(), m.end())

    for tok, start, end in _number_matches(s, field_name):
        add(tok)
        s = _mask(s, start, end)

    if entities:
        # In Ukrainian prose every Latin-script word is a name or a brand. In
        # English a capital at the start of a sentence is grammar, so those
        # are skipped unless the word is CamelCase or carries a digit
        # ("LockBit", "Storm-1124") — mid-sentence names are still caught.
        cyrillic = bool(re.search(r"[А-Яа-яЇїІіЄєҐґ]", s))
        for m in _ENTITY_RE.finditer(s):
            word = m.group(1).rstrip(".")
            # "Hive-encrypted" names Hive; the lowercase tail is grammar.
            word = re.sub(r"-[a-z][a-z-]*$", "", word)
            if len(word) < 3 or word.lower() in _ENTITY_STOP:
                continue
            if word.isupper() and len(word) <= 4:
                continue  # short acronyms carry too little signal
            if (not cyrillic and _at_sentence_start(s, m.start())
                    and not re.search(r"[A-Z]|\d", word[1:])):
                continue
            add(_new_token("entity", word, word.lower(), field_name))
    return out


def _at_sentence_start(s: str, index: int) -> bool:
    before = s[:index].rstrip()
    return not before or before[-1] in ".!?:;\n\"«(—•-"


def _cvss_matches(s: str, field_name: str) -> list[tuple[Token, int, int]]:
    found: list[tuple[Token, int, int]] = []
    for m in _CVSS_WORD_RE.finditer(s):
        window_start = m.end()
        window = s[window_start:window_start + 48]
        prefix = _CVSS_VERSION_PREFIX_RE.match(window)
        offset = prefix.end() if prefix else 0
        rest = window[offset:]
        num = _SCORE_NUM_RE.search(rest)
        if num is None:
            continue
        if (num.group(1).replace(",", ".") in _CVSS_VERSIONS and not prefix
                and not rest[:num.start()].strip(" :")):
            # "CVSS 3.1 base 6.5" / "Under CVSS 4.0, a 9.3 score": the first
            # number names the standard. Take the next one; with no next one
            # the phrase is a version label and carries no score at all.
            nxt = _SCORE_NUM_RE.search(rest, num.end())
            if nxt is None or re.search(r"[.!?;]\s|\n", rest[num.end():nxt.start()]):
                continue
            num = nxt
        gap = rest[:num.start()]
        if re.search(r"[.!?;]\s|\n", gap) or len(gap) > 36:
            continue
        value = _parse_number(num.group(1))
        if value is None or not 0 <= value <= 10:
            continue
        # Mask from the word "CVSS" through the score, so the "v3.1" in
        # "CVSS v3.1 base score of 9.8" never comes back as a version.
        end = window_start + offset + num.end(1)
        found.append((_new_token("cvss", num.group(1), f"{value:.1f}", field_name, value=value),
                      m.start(), end))
    for pattern in (_CVSS_OUT_OF_RE, _CVSS_SUFFIX_RE):
        for m in pattern.finditer(s):
            value = _parse_number(m.group(1))
            if value is None or not 0 <= value <= 10:
                continue
            found.append((_new_token("cvss", m.group(1), f"{value:.1f}", field_name, value=value),
                          m.start(1), m.end(1)))
    return found


def _parse_dates(m: re.Match[str], order: str) -> list[tuple[int | None, int, int]]:
    """One or two (year, month, day) from a date match (two for a range)."""
    g = m.groups()
    year: int | None
    days: list[int]
    try:
        if order == "ymd":
            year, month, days = int(g[0]), int(g[1]), [int(g[2])]
        elif order == "dmy":
            year, month, days = int(g[2]), int(g[1]), [int(g[0])]
        elif order == "mdy":
            month, year = _EN_MONTHS[g[0]], _opt_int(g[3])
            days = [int(g[1])] + ([int(g[2])] if g[2] else [])
        elif order == "dmy_en":
            month, year = _EN_MONTHS[g[2]], _opt_int(g[3])
            days = [int(g[0])] + ([int(g[1])] if g[1] else [])
        else:
            month, year = _UA_MONTHS[g[2].lower()], _opt_int(g[3])
            days = [int(g[0])] + ([int(g[1])] if g[1] else [])
    except (KeyError, ValueError):
        return []
    if not 1 <= month <= 12 or not all(1 <= d <= 31 for d in days):
        return []
    return [(year, month, d) for d in days]


def _opt_int(value: str | None) -> int | None:
    return int(value) if value else None


def _number_matches(s: str, field_name: str) -> list[tuple[Token, int, int]]:
    found: list[tuple[Token, int, int]] = []
    for m in _NUM_RE.finditer(s):
        raw_num = m.group("num")
        value = _parse_number(raw_num)
        if value is None:
            continue
        tail = s[m.end():m.end() + 40]
        end = m.end()
        scale = 1.0
        for pattern, factor in _SCALES:
            sm = pattern.match(tail)
            if sm:
                scale = factor
                end += sm.end()
                tail = s[end:end + 40]
                break
        unit_m = _UNIT_RE.match(tail)
        unit = unit_m.group(0).strip().lower() if unit_m else ""
        has_sep = bool(re.search(r"\d[, ]\d{3}", raw_num))
        currency = bool(m.group("cur"))
        year_unit = not unit or unit.startswith(("рок", "рік", "year"))
        is_year = (1900 <= value <= 2100 and value == int(value) and year_unit
                   and not currency and scale == 1.0)
        if not (unit or currency or scale != 1.0 or has_sep or (value >= 1000 and not is_year)):
            continue
        if is_year:
            continue
        if unit_m:
            end += unit_m.end()
        total = value * scale
        unit_key = "%" if unit.startswith(("%", "percent", "per", "відсот")) else unit
        raw = s[m.start():end].strip()
        found.append((_new_token("number", raw, _format_value(total) + ("%" if unit_key == "%" else ""),
                                 field_name, value=total), m.start(), end))
    return found


def _number_word_values(text: str) -> set[float]:
    values: set[float] = set()
    for m in _NUMBER_WORD_RE.finditer(text):
        word = m.group(1).lower().replace("’", "'").replace("ʼ", "'")
        base = _EN_NUMBER_WORDS.get(word, _UA_NUMBER_WORDS.get(word))
        if base is None:
            continue
        scale_word = (m.group(2) or "").strip().lower()
        factor = 1.0
        if scale_word.startswith(("thousand", "тисяч")):
            factor = 1e3
        elif scale_word.startswith(("million", "мільйон", "млн")):
            factor = 1e6
        elif scale_word.startswith(("billion", "мільярд", "млрд")):
            factor = 1e9
        values.add(float(base) * factor)
    return values


def _ip_token(addr: ipaddress.IPv4Address | ipaddress.IPv6Address, raw: str, field_name: str) -> Token:
    """Public addresses are IOCs (hard). Loopback, private, link-local and
    documentation ranges show up in generic advice ("bind it to 127.0.0.1")
    and are only soft."""
    generic = (addr.is_private or addr.is_loopback or addr.is_link_local
               or addr.is_unspecified or addr.is_reserved or addr.is_multicast)
    return _new_token("private_ip" if generic else "ip", raw, addr.compressed, field_name)


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def _domain_norm(domain: str) -> str:
    d = domain.lower().rstrip(".")
    return d[4:] if d.startswith("www.") else d


# ===========================================================================
# Support corpus
# ===========================================================================

@dataclass
class Support:
    """Everything a brief's tokens may be checked against."""

    text: str
    hard: dict[str, set[str]]
    soft: dict[str, set[str]]
    numbers: set[float]
    dates: list[tuple[int | None, int, int]]
    decimals: set[str]
    available: bool

    def has(self, tok: Token) -> bool:
        if tok.kind in HARD_KINDS:
            if tok.kind == "cvss":
                return tok.norm in self.hard.get("cvss", set()) or tok.norm in self.decimals
            return tok.norm in self.hard.get(tok.kind, set())
        if tok.kind == "number" and tok.value is not None:
            return any(_number_matches_value(tok.value, tok.raw, s) for s in self.numbers)
        if tok.kind == "date" and tok.date is not None:
            return any(_date_matches(tok.date, d) for d in self.dates)
        if tok.kind == "version":
            known = self.soft.get("version", set())
            return (
                tok.norm in known
                or any(v.startswith(tok.norm + ".") or v.startswith(tok.norm + "-") for v in known)
                or _word_in(tok.norm, self.text)
            )
        if tok.kind == "domain":
            known = self.soft.get("domain", set())
            return (
                tok.norm in known
                or any(k.endswith("." + tok.norm) or tok.norm.endswith("." + k) for k in known)
                or tok.norm in self.text
            )
        if tok.kind == "private_ip":
            return tok.norm in self.soft.get("private_ip", set()) or tok.norm in self.text
        if tok.kind == "entity":
            return tok.norm in self.text
        return tok.norm in self.soft.get(tok.kind, set())


def _word_in(needle: str, haystack: str) -> bool:
    return re.search(r"(?<![\w.])" + re.escape(needle) + r"(?![\w]|\.\d)", haystack) is not None


def _sig_digits(raw: str) -> int:
    digits = re.sub(r"\D", "", raw.split()[0] if raw.split() else raw)
    digits = digits.lstrip("0")
    stripped = digits.rstrip("0")
    return max(1, len(stripped))


def _number_matches_value(brief: float, brief_raw: str, source: float) -> bool:
    if math.isclose(brief, source, rel_tol=1e-9, abs_tol=1e-9):
        return True
    if source == 0 or brief == 0:
        return False
    # Rounding: "1.3 million" is a fair rendering of 1,260,000. Round the
    # source to the brief's significant digits and compare.
    digits = _sig_digits(re.sub(r"[^\d.,]", " ", brief_raw).strip() or brief_raw)
    magnitude = math.floor(math.log10(abs(source)))
    rounded = round(source, -magnitude + digits - 1)
    return math.isclose(rounded, brief, rel_tol=1e-6)


def _date_matches(a: tuple[int | None, int, int], b: tuple[int | None, int, int]) -> bool:
    if a[1:] != b[1:]:
        return False
    return a[0] is None or b[0] is None or a[0] == b[0]


def build_support(
    source_title: str,
    source_body: str,
    sheet: "FactSheet | None" = None,
    *,
    extra_text: Sequence[str] = (),
) -> Support:
    """Index the source (and fact sheet) once per check."""
    source_text = normalize_text(f"{source_title}\n{source_body}")
    available = bool((source_title or "").strip() or (source_body or "").strip())
    sheet_text = normalize_text(sheet.support_text()) if sheet is not None else ""
    extra = normalize_text("\n".join(extra_text))

    source_tokens = extract_tokens(source_text, entities=False)
    soft_tokens = extract_tokens(f"{sheet_text}\n{extra}", entities=False) + source_tokens

    hard: dict[str, set[str]] = {k: set() for k in HARD_KINDS}
    for tok in source_tokens:
        if tok.kind in HARD_KINDS:
            hard[tok.kind].add(tok.norm)
    if sheet is not None:
        hard["cve"].update(c.upper() for c in sheet.cve_ids)
        hard["cvss"].update(f"{c.score:.1f}" for c in sheet.cvss_scores)

    soft: dict[str, set[str]] = {}
    numbers: set[float] = set()
    dates: list[tuple[int | None, int, int]] = []
    for tok in soft_tokens:
        soft.setdefault(tok.kind, set()).add(tok.norm)
        if tok.kind == "number" and tok.value is not None:
            numbers.add(tok.value)
        if tok.kind == "date" and tok.date is not None:
            dates.append(tok.date)

    full = f"{source_text}\n{sheet_text}\n{extra}"
    # Every bare number in the corpus counts as support for a number token:
    # the brief may attach a unit the source left implicit ("300,000" vs
    # "300,000 customers").
    for m in _NUM_RE.finditer(full):
        value = _parse_number(m.group("num"))
        if value is not None:
            numbers.add(value)
            for pattern, factor in _SCALES:
                if pattern.match(full[m.end():m.end() + 20]):
                    numbers.add(value * factor)
    numbers |= _number_word_values(full)
    decimals = {
        f"{v:.1f}" for v in (
            _parse_number(x) for x in re.findall(r"(?<![\d.,])\d{1,2}(?:[.,]\d)?(?![\d])", full)
        ) if v is not None and 0 <= v <= 10
    }
    return Support(
        text=full.lower(), hard=hard, soft=soft, numbers=numbers, dates=dates,
        decimals=decimals, available=available,
    )


# ===========================================================================
# Checks
# ===========================================================================

def post_fields(post: Any) -> list[tuple[str, str]]:
    """(field, text) pairs for a ThreatPost / ThreatPostResponse / dict."""
    def get(name: str) -> Any:
        if isinstance(post, dict):
            return post.get(name)
        return getattr(post, name, None)

    out: list[tuple[str, str]] = []
    for name in TEXT_FIELDS:
        value = get(name)
        if isinstance(value, str):
            if value.strip():
                out.append((name, value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    out.append((name, item))
    refs = get("references") or []
    for ref in refs:
        label = ref.get("label") if isinstance(ref, dict) else getattr(ref, "label", "")
        if isinstance(label, str) and label.strip():
            out.append(("references", label))
    return out


def extract_post_tokens(post: Any) -> list[Token]:
    tokens: list[Token] = []
    for name, text in post_fields(post):
        found = extract_tokens(text, name, entities=name in _ENTITY_FIELDS)
        if name == "references":
            found = [t for t in found if t.kind in ("cve", "hash", "ip")]
        tokens.extend(found)
    return tokens


_MESSAGES = {
    "cve": "CVE id not in the source or fact sheet",
    "hash": "file hash not in the source",
    "ip": "public IP address not in the source",
    "cvss": "CVSS score not in the source or fact sheet",
    "version": "version string not found in the source",
    "date": "date not found in the source",
    "number": "figure not found in the source",
    "domain": "domain not found in the source",
    "private_ip": "generic/private address not in the source",
    "entity": "name not mentioned in the source or fact sheet",
}


def check_post(
    post: Any,
    *,
    source_title: str,
    source_body: str,
    sheet: "FactSheet | None" = None,
    extra_support: Sequence[str] = (),
    published_on: tuple[int, int, int] | None = None,
) -> FactCheckReport:
    """Compare every protected token in `post` against the source + sheet.

    `extra_support` is metadata the model was shown (source name, URL,
    platforms); it vouches for soft tokens only. `published_on` (y, m, d) is
    not support — an incident is rarely dated on the day it is reported —
    but a date that matches only the publication day says so in its finding.
    """
    support = build_support(source_title, source_body, sheet, extra_text=extra_support)
    report = FactCheckReport(source_available=support.available)
    reported: set[tuple[str, str]] = set()
    for tok in extract_post_tokens(post):
        report.checked += 1
        if support.has(tok):
            report.supported += 1
            continue
        key = (tok.kind, tok.norm)
        if key in reported:
            continue
        reported.add(key)
        message = _MESSAGES.get(tok.kind, "not found in the source")
        if (tok.kind == "date" and tok.date and published_on
                and _date_matches(tok.date, published_on)):
            message += " (matches the publication date only)"
        finding = Finding(
            kind=tok.kind, value=tok.raw, field=tok.field,
            severity="hard" if tok.kind in HARD_KINDS else "soft",
            message=message,
        )
        (report.hard if finding.severity == "hard" else report.soft).append(finding)
    return report


def check_item(post: Any, item: Any, sheet: "FactSheet | None" = None) -> FactCheckReport:
    """`check_post` with the support pulled from a NewsItem."""
    extra = [str(getattr(item, "source", "") or ""), str(getattr(item, "url", "") or "")]
    extra.extend(str(p) for p in (getattr(item, "affected_platforms", None) or []))
    published = getattr(item, "published_at", None)
    published_on = (published.year, published.month, published.day) if published else None
    return check_post(
        post,
        source_title=str(getattr(item, "title", "") or ""),
        source_body=str(getattr(item, "raw_content", "") or ""),
        sheet=sheet,
        extra_support=extra,
        published_on=published_on,
    )


# ---------------------------------------------------------------------------
# Cross-locale consistency
# ---------------------------------------------------------------------------

#: Kinds compared between the EN and UA renders of one story, and how bad a
#: genuine conflict is. "major" forces review: two editions of one story
#: disagree on a fact a reader acts on.
_CROSS_KINDS: dict[str, str] = {"cve": "major", "cvss": "major", "date": "major", "number": "minor"}


def _same(kind: str, a: Token, b: Token) -> bool:
    if kind == "date" and a.date and b.date:
        return _date_matches(a.date, b.date)
    if kind == "number" and a.value is not None and b.value is not None:
        return (_number_matches_value(a.value, a.raw, b.value)
                or _number_matches_value(b.value, b.raw, a.value))
    return a.norm == b.norm


def check_cross_locale(
    post_a: Any, post_b: Any, *, locale_a: str = "en", locale_b: str = "ua",
) -> list[Finding]:
    """Facts on which two locale renders of ONE story disagree.

    An omission (one edition simply leaves a figure out) is reported as
    "minor". A conflict — each side has a value of the same kind that the
    other lacks, e.g. EN "1 November" vs UA "2 листопада" — is reported at
    the kind's severity. Number words count on both sides ("four hours" =
    "4 години").
    """
    toks_a = [t for t in extract_post_tokens(post_a) if t.kind in _CROSS_KINDS]
    toks_b = [t for t in extract_post_tokens(post_b) if t.kind in _CROSS_KINDS]
    words_a = _number_word_values(" ".join(t for _, t in post_fields(post_a)))
    words_b = _number_word_values(" ".join(t for _, t in post_fields(post_b)))
    findings: list[Finding] = []
    for kind, severity in _CROSS_KINDS.items():
        a = _dedupe([t for t in toks_a if t.kind == kind])
        b = _dedupe([t for t in toks_b if t.kind == kind])
        only_a = [t for t in a if not any(_same(kind, t, u) for u in b)
                  and not (kind == "number" and t.value in words_b)]
        only_b = [t for t in b if not any(_same(kind, t, u) for u in a)
                  and not (kind == "number" and t.value in words_a)]
        if not only_a and not only_b:
            continue
        conflict = bool(only_a) and bool(only_b)
        level = severity if conflict else "minor"
        if conflict:
            msg = (f"{locale_a.upper()} says {', '.join(t.raw for t in only_a[:3])}; "
                   f"{locale_b.upper()} says {', '.join(t.raw for t in only_b[:3])}")
            findings.append(Finding(kind=kind, value=msg, field="cross_locale",
                                    severity=level, message=f"{kind} differs between editions"))
            continue
        side, missing, toks = ((locale_a, locale_b, only_a) if only_a
                               else (locale_b, locale_a, only_b))
        findings.append(Finding(
            kind=kind, value=", ".join(t.raw for t in toks[:3]), field="cross_locale",
            severity=level,
            message=f"only the {side.upper()} edition mentions it ({missing.upper()} omits)",
        ))
    return findings


def _dedupe(tokens: Iterable[Token]) -> list[Token]:
    seen: set[str] = set()
    out: list[Token] = []
    for t in tokens:
        if t.norm not in seen:
            seen.add(t.norm)
            out.append(t)
    return out


__all__ = [
    "FactCheckReport",
    "Finding",
    "HARD_KINDS",
    "SOFT_KINDS",
    "Support",
    "TEXT_FIELDS",
    "Token",
    "build_support",
    "check_cross_locale",
    "check_item",
    "check_post",
    "extract_post_tokens",
    "extract_tokens",
    "normalize_text",
    "post_fields",
]
