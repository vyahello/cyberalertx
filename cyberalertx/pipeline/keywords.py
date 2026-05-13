"""Single source of truth for keyword sets and relevance scoring.

Filter and ranker share these so we don't get drift between "what counts as
relevant" and "what bumps the score". Keeping them as plain frozensets makes
unit testing trivial and lets a future ML classifier replace them piecewise.

Keyword syntax:
  * "phishing"        — exact token match
  * "zero-day"        — phrase / substring match (contains space or hyphen)
  * "фішинг*"         — stem/prefix match against tokens (Slavic inflection)

Scoring model (see filter.py):
  * STRONG_*   → +3 per match. Unambiguous cyber terms. One alone usually
                 carries an article over the threshold.
  * MEDIUM_*   → +2 per match. Strong cyber-context but can appear in
                 general news ("hack" used colloquially, "scam" in finance).
  * WEAK_*     → +1 per match. Cyber-adjacent but ambiguous on its own —
                 "password", "credentials", and the UK "вразлив*" which
                 also means "physically fragile". Needs supporting signal.
  * NEGATIVE_* → −2 per match. Categories that historically generate false
                 positives: clean-tech, war coverage, politics, sports,
                 entertainment, business/funding announcements.

Threshold is enforced by `filter.is_relevant()`; this module exports only
the data.
"""
from __future__ import annotations

from typing import Iterable, Mapping


def count_keyword_hits(
    keywords: Iterable[str],
    text_lower: str,
    tokens: set[str],
) -> int:
    """Shared keyword-matching primitive.

    Used across the pipeline so the matching semantics (exact / phrase /
    stem) stay consistent. Counts each KEYWORD at most once per article;
    a story with 12 occurrences of "phishing" still scores like one.
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


# =========================================================================
# STRONG cyber tokens (+3) — unambiguous. One match alone earns relevance.
# =========================================================================
STRONG_CYBER_TOKENS: frozenset[str] = frozenset({
    # --- English ---
    "phishing", "smishing", "vishing", "spear-phishing", "spear phishing",
    "ransomware", "malware", "spyware", "stalkerware",
    "infostealer", "stealer", "loader", "dropper",
    "exploit", "exploited", "exploits", "exploitation",
    "zero-day", "zero day", "0-day", "0day",
    "cve", "cve-", "rce", "remote code execution",
    "backdoor", "trojan", "rootkit", "worm", "botnet",
    "ddos", "denial of service",
    "data breach", "data leak", "leaked database", "exposed database",
    "credential theft", "credential stuffing", "credential harvesting",
    "account takeover", "ato attack", "session hijack",
    "double extortion", "ransom note", "extortion campaign",
    "command-and-control", "c2 server", "c&c server",
    "indicator of compromise", "iocs", "ioc",
    "apt", "advanced persistent threat",
    "cyberattack", "cyber attack", "cyber-attack",
    "supply chain attack", "supply-chain attack",
    "lockbit", "blackcat", "alphv", "conti", "clop", "lazarus",
    # --- English: consumer scams (everyday-user vector) ---
    # The fraud vocabulary the average reader meets in the wild — gift-card
    # scams, romance scams, tech-support scams, refund fraud. Keep these
    # STRONG so a "phishing-adjacent" article about, say, a Telegram giveaway
    # scam clears the gate without needing a CVE in the same paragraph.
    "gift card scam", "romance scam", "tech support scam",
    "refund scam", "refund fraud", "imposter scam",
    "sim swap", "sim-swap", "sim swapping",
    "qr code phishing", "quishing",
    "deepfake voice", "voice cloning", "ai voice scam",
    "fake invoice", "invoice fraud", "wire fraud",
    "crypto drainer", "wallet drainer", "rug pull",
    "fake browser update", "fake captcha",
    # --- Ukrainian (stems for Slavic inflection) ---
    "кібер*",                # кіберзагроза, кіберзлочин, кіберпростір, кібератака, кібербезпек*
    "фішинг*", "смішинг*", "вішинг*",
    "вимагач*", "програма-вимагач", "шифрувальник*",
    "експлойт*", "експлуат*",  # експлойт / експлуатація
    "троян*", "руткіт*", "бекдор*",
    "ботнет",
    "ddos-атак*",
    "стілер*", "інфостілер*",
    "ШПЗ", "шпз",            # standard UA tag for malware
    "уac-",                  # threat-actor naming (UAC-NNNN)
    # --- Ukrainian: consumer scams (drives feed coverage for normal users) ---
    # The everyday Ukrainian fraud surface: SIM-swap, fake bank apps,
    # Telegram / Viber scams, fake "Діи" / "Дія" sign-ups, prize scams,
    # gift-card / "розіграш" fraud, OLX/AliExpress scam links.
    "сім-карт*", "підміна сім", "підміни сім", "swap сім",
    "qr-код*", "куар-код*",   # QR-phishing → "quishing"
    "фейков* банк*",          # фейковий банкомат / банківський додаток
    "фішинг-сайт*",
    "телеграм-шахрай*", "вайбер-шахрай*", "viber-шахрай*",
    "шахрайськ* схем*", "шахрайськ* дзвінк*",
    "фейков* діі", "фейкова дія", "фейкова \"дія\"",
    "розіграш-шахрай*", "фейков* розіграш*",
    "фейков* інвестиц*",      # invesment scams
    "фейков* олх*", "фейкові olx", "фейкові оголошен*",
    "мобільн* шахрай*",
    "крипто-шахрай*", "крипто-дрейн*",
    "соціальна інженерія",    # promoted from MEDIUM — high-signal in UA media
    "діпфейк*", "дипфейк*",   # deepfake (both transliterations seen)
})


# =========================================================================
# MEDIUM cyber tokens (+2) — strong context, occasional general-news use.
# =========================================================================
MEDIUM_CYBER_TOKENS: frozenset[str] = frozenset({
    # --- English ---
    "hack", "hacked", "hacker", "hackers", "hacking",
    "breach", "breached", "compromised", "compromise",
    "exfiltration", "exfiltrated", "stolen data",
    "advisory", "advisories",
    "scam", "scams", "scammer", "fraud", "fraudulent",
    "patch", "patched", "out-of-band patch",
    "vulnerability", "vulnerabilities", "vuln", "flaw",  # mostly clean in EN
    "attacker", "attackers", "threat actor", "threat actors",
    "encryption", "decryption", "decrypt",
    "social engineering", "pretexting", "impersonation",
    "business email compromise", "bec",
    # --- Ukrainian ---
    "хакер*", "хакерськ*",
    "злам*",
    "шахрай*", "шахрайств*",  # шахрайство / шахраї / шахрайські
    "афер*",                  # афера, аферисти
    "обман*",                 # обманювати / обманом / обманні дзвінки
    "обдури*",                # обдурили / обдурювали
    "шкідлив*",              # шкідливе ПЗ, шкідливе програмне забезпечення
    "соцінженерія",
    "загроз*",               # for "кіберзагроза" already covered, but loosely
    "крадіжк*",              # крадіжка даних / коштів
    "виманюва*", "виманили", # виманити кошти — classic UA scam coverage
    "фейков*",               # general "fake" stem — usually paired with cyber context
})


# =========================================================================
# WEAK cyber tokens (+1) — ambiguous; need supporting signal to pass.
# =========================================================================
WEAK_CYBER_TOKENS: frozenset[str] = frozenset({
    # --- English ---
    "password", "passwords", "credentials",
    "two-factor", "2fa", "mfa", "multi-factor",
    "session token", "auth token",
    # --- Ukrainian ---
    "пароль", "паролі", "паролів",
    # `вразлив*` ALSO means physically fragile in everyday Ukrainian
    # ("вразливі контакти" = fragile contacts). Strictly weak here; the
    # filter requires it to co-occur with stronger signal.
    "вразлив*", "уразлив*",
    "захист даних", "захищеність",
    "шифрування",
})


# =========================================================================
# NEGATIVE tokens (−2) — non-cyber tech, war, politics, sports, business.
# Each match subtracts; multiple matches in a non-cyber piece quickly
# push the article below the relevance threshold.
# =========================================================================
NEGATIVE_TOKENS: frozenset[str] = frozenset({
    # --- English: corporate / marketing / non-cyber tech ---
    "series a", "series b", "series c", "raises $", "raise $",
    "funding round", "ipo", "acquires", "acquisition of",
    "appoints", "named ceo", "named cto", "names ceo", "names cto",
    "partnership", "partners with",
    "best antivirus", "best vpn", "top 10",
    "webinar", "white paper", "ebook",
    "earnings", "quarterly results",
    "renewable energy", "wind turbine", "solar panel",
    "electric vehicle", "battery",
    "rocket launch", "satellite launch",
    "gadget", "smartphone launch",
    # --- Ukrainian: war / kinetic / military ---
    # tsn.ua-style coverage is the worst false-positive driver for UK feeds.
    "обстріл*", "обстріли", "обстрілу",
    "вибух*",
    "повітрян* тривог*", "тривог*",
    "ракетн*", "ракетного удару", "ракети",
    "шахед*", "дрон*",        # dual-use; mostly military in UA media
    "вбит*", "поранен*", "загиб*",
    "війн* в україні", "війна",
    "фронт*", "позиц*",
    # --- Ukrainian: politics / governance fluff ---
    "президент*", "міністр*", "депутат*",
    "вибори", "виборч*",
    "законопроєкт*",
    # --- Ukrainian: entertainment / sport / lifestyle ---
    "співачк*", "співак", "шоу-бізнес*",
    "футбол*", "чемпіонат*", "матч",
    "коронавірус*", "covid",
    "пляж*", "туриз*",
    # --- Ukrainian: clean-tech / non-cyber innovation (wind-turbine bucket) ---
    "вітров*", "сонячн*", "турбін*",
    "акумулятор*", "електромобіл*",
    "індуктивн*", "бездротова зарядк*", "бездротову зарядк*",
    "кораб*", "судн*", "суднобуд*",
    "екологі*", "клімат*",
    "стартап*", "інвестиц*", "інновац*",  # general-tech buzzwords
    "венчурн*",
    "освіт*",                # дев.ua's "education programs" — not cyber
})


# Threshold the filter compares against. Calibrated so:
#   * ONE strong match alone (e.g. "phishing")        → score 3 → pass
#   * ONE medium + ONE weak  (e.g. "hack" + "password") → score 3 → pass
#   * ONE weak alone (e.g. "вразлив*")                → score 1 → drop
#   * weak + negative (вразлив + турбін)              → score -1 → drop
RELEVANCE_THRESHOLD: int = 3


# ----- Legacy aliases (kept for back-compat with tests / external imports) -
# Historically the pipeline exposed a single RELEVANCE_KEYWORDS set used by
# both filter and ranker. They now consult the weighted tables directly.
# The aliases keep the old names alive as a derived union for any external
# code that only cares about "is this a cyber token of any strength".
RELEVANCE_KEYWORDS: frozenset[str] = (
    STRONG_CYBER_TOKENS | MEDIUM_CYBER_TOKENS | WEAK_CYBER_TOKENS
)
EXCLUSION_KEYWORDS: frozenset[str] = NEGATIVE_TOKENS


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
