"""Cross-source story clustering.

The problem this solves
----------------------
`NewsItem.fingerprint` is `sha256(url)` — it identifies an *article*, not a
*story*. When BleepingComputer, The Hacker News and Krebs all report the same
SharePoint zero-day, we ingest three articles with three fingerprints and the
reader sees the same news three times in the feed and three times in the
Telegram channel.

This module assigns every item a `story_key`: a stable id shared by all
articles covering the same underlying story. The feed, the detail pool and
the publisher then show ONE canonical article per story and surface the rest
as corroboration ("Also reported by The Hacker News, Krebs on Security"),
which turns a duplicate into a trust signal.

Design constraints
------------------
1. **A false merge is much worse than a missed duplicate.** Collapsing two
   genuinely different advisories hides real news from the reader. Every
   threshold below is tuned to be conservative, and the veto rules exist
   specifically to make certain merges impossible rather than unlikely.
2. **Pure Python, no ML.** No embeddings, no vector store, no new dependency.
   Everything here is set arithmetic over tokens the pipeline already has.
3. **Pure functions.** `same_story()` and `cluster_items()` take data and
   return data. No I/O, no globals, so the whole thing is unit-testable and
   can run at ingest time, at read time, or in a backfill CLI unchanged.

The matching rules
------------------
Two articles are the same story when they pass the time window AND satisfy
one of the positive rules, AND trip none of the vetoes.

  TIME WINDOW
      Published within `_WINDOW_DAYS` of each other. Coverage of one event
      lands within a few days; two "Patch Tuesday" stories a month apart are
      different stories that happen to share a headline.

  VETO 1 — disjoint CVEs
      If BOTH articles name CVEs and share NONE of them, they are different
      stories no matter how similar the headlines read. This is what keeps
      the seven separate "CISA Adds One Known Exploited Vulnerability to
      Catalog" advisories — identical titles, different CVEs — from
      collapsing into one and silently deleting six real advisories.

  VETO 2 — one source, one headline, no CVE agreement
      Same source, byte-identical headline, and no positive CVE evidence
      linking them. A newsroom does not publish the same headline twice for
      the same story; advisory feeds, on the other hand, title entries after
      the affected product. CISA ships "Siemens SIMATIC" repeatedly, each
      time for a different advisory. Without this veto, the pair where only
      one entry happens to name a CVE slips past VETO 1 and merges.

  RULE A — identical CVE sets
      Both name exactly the same CVEs. The strongest signal available;
      no textual support required.

  RULE B — overlapping CVEs with textual support
      CVE Jaccard >= 0.5 AND a shared entity AND some title overlap.
      The support requirement is deliberate: a "CISA Adds Two Known
      Exploited Vulnerabilities to Catalog" roundup shares one CVE with a
      vendor story but names no shared entity, so it stays its own item —
      correct, because a KEV catalog addition really is separate news.
      Without this rule a multi-CVE roundup would act as a bridge and
      transitively merge every unrelated story it lists.

  RULE C — distinctive-title match
      No CVEs to compare, so fall back to text. Jaccard over *distinctive*
      tokens only, plus a shared named entity. Generic security vocabulary
      ("critical", "flaw", "exploited", "remote code execution") is stripped
      first — those words are what make two unrelated advisories look alike.
      With them removed, "JetBrains warns of critical TeamCity remote code
      execution flaw" and "Critical ServiceNow AI Platform Flaw Exploited for
      Unauthenticated Code Execution" share nothing and stay apart.

      Both headlines must also carry at least `_MIN_DISTINCTIVE_FOR_TEXT`
      distinctive tokens. A two-word title like "Siemens SIMATIC" names a
      product, not a story, and matching on it alone merges unrelated
      advisories. Real reporting headlines clear the bar easily — the
      narrowest true merge in the production corpus ("VMware fixes three
      critical flaws allowing auth bypass, VM escapes") retains three.

Known limits
------------
Precision is carried by CVE identifiers whenever both articles name one.
Where neither does, RULE C is a bet: two headlines that share this much
distinctive vocabulary within five days are the same story. That bet was
checked against 377 real stored articles (the 200-item live store plus a
177-item earlier snapshot) and produced no false merges, but it is a
heuristic and not a proof. Two outlets writing near-identical CVE-less
headlines about different vendors in the same week would merge incorrectly.

If that starts happening, the fix is inverse-document-frequency weighting —
score shared tokens by how rare they are across the batch, so "firmware"
counts for little and "vBulletin" counts for a lot — rather than more
hand-tuned thresholds. `cluster_items` already sees the whole batch, so the
statistics are available without new infrastructure.

Clustering strategy
-------------------
Single-link union-find would let one weak edge chain unrelated stories
together. Instead we use **anchor-based greedy assignment**: items are
processed in a deterministic order and each one either joins an existing
cluster by matching that cluster's anchor directly, or becomes a new anchor.
Membership is therefore always a direct pairwise decision against one
representative article — chains cannot form.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable, Iterable, Sequence

from ..models import NewsItem

# --------------------------------------------------------------------------
# Tuning knobs. These were calibrated against the live 200-item production
# store: every merge the defaults produce was inspected by hand, and the
# known false-positive pair (TeamCity RCE vs ServiceNow RCE — different
# products, near-identical generic phrasing) stays unmerged.
# --------------------------------------------------------------------------

#: Articles further apart than this are never the same story.
_WINDOW_DAYS = 5

#: RULE B — how much of the two CVE sets must coincide.
_CVE_JACCARD_MIN = 0.5

#: RULE C — primary threshold on distinctive-token Jaccard.
_TITLE_JACCARD_STRONG = 0.45
#: RULE C — relaxed threshold, allowed only with more shared tokens.
_TITLE_JACCARD_WEAK = 0.33
#: Shared distinctive tokens required at each threshold.
_MIN_SHARED_STRONG = 2
_MIN_SHARED_WEAK = 3
#: RULE B — minimum title overlap required to support a partial CVE match.
_TITLE_JACCARD_SUPPORT = 0.20
#: RULE C — a headline this short names a product, not a story. Advisory
#: feeds ("Siemens SIMATIC", "MikroTik RouterOS") sit below the bar; real
#: reporting headlines clear it.
_MIN_DISTINCTIVE_FOR_TEXT = 3

#: RULE 0 — the shortest body we will treat as identifying. Several feeds
#: ship an empty or one-line body, and every one of those would otherwise
#: hash to the same value and merge with all the others.
_MIN_BODY_FOR_IDENTITY = 120

#: RULE D — smallest integer that can act as a story-identifying quantity.
#: Below this a shared number is overwhelmingly coincidence: counts of
#: zero-days, ages, quarters, percentages.
_RARE_QUANTITY_MIN = 100
#: Bare four-digit numbers in this range are dates, not counts.
_QUANTITY_YEAR_LO = 1990
_QUANTITY_YEAR_HI = 2035
#: RULE D — how far past a number we look for the noun it counts.
_QUANTITY_UNIT_WINDOW = 40
#: RULE D — shared subject words required alongside the shared quantity.
#: A count of fixed vulnerabilities is a per-release fingerprint — vendors
#: ship a different number every month — so "398 flaws" plus one shared
#: subject word is decisive. A count of victims, people or organizations is
#: an incidental attribute that two unrelated incidents can share, so it has
#: to bring more of the headline with it.
_MIN_SUBJECT_FOR_ROLLUP = 1
_MIN_SUBJECT_FOR_QUANTITY = 2
#: RULE D — a headline listing this many entities covers several stories.
_MIN_ENTITIES_FOR_ENUMERATION = 3

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[^\W_]+(?:[-.][^\W_]+)*", flags=re.UNICODE)

# RULE D — a bare integer, optionally with thousands separators. The
# lookarounds are the whole point: they refuse any digit run glued to a word
# character or to `. , / : -`, which discards CVSS scores (9.8), product
# versions (3.1), ISO dates (2026-08-11), IP addresses, host:port pairs and
# the numeric halves of identifiers like "UNC6671" or "v7".
_QUANTITY_RE = re.compile(r"(?<![\w.,/:-])(\d{1,3}(?:,\d{3})+|\d+)(?![\w.,/:%-])")
_QUANTITY_WORD_CHARS = "_-'\u2019"
#: Digits either side of a comma, so a thousands separator in "100,000" is
#: not mistaken for a list separator when reading a headline.
_NUMERIC_COMMA_RE = re.compile(r"(?<=\d),(?=\d)")

# Ordinary English/Ukrainian function words. Same list the ranker and the
# credibility analyzer use, kept local so this module has no cross-stage
# import and can be reasoned about on its own.
_STOPWORDS: frozenset[str] = frozenset({
    # English
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "with",
    "is", "are", "was", "were", "be", "been", "by", "as", "at", "from",
    "that", "this", "it", "its", "new", "more", "than", "into", "after",
    "has", "have", "had", "over", "said", "says", "can", "could", "will",
    "would", "may", "might", "but", "not", "all", "how", "why", "what",
    "when", "who", "amid", "via", "out", "off", "up", "down", "now",
    # Ukrainian
    "та", "і", "й", "у", "в", "на", "до", "з", "із", "зі", "для", "про",
    "що", "як", "це", "цей", "ця", "які", "яка", "який", "від", "за",
    "по", "при", "не", "але", "його", "її", "їх", "був", "була", "було",
    "буде", "може", "можуть", "після", "під", "над", "через", "уже", "вже",
})

# Security vocabulary that appears in a large share of all headlines. These
# words carry almost no discriminating power — two completely unrelated
# advisories will both say "critical", "flaw" and "exploited" — so leaving
# them in inflates similarity and causes false merges. Stripped before the
# RULE C comparison.
_GENERIC_SECURITY_TERMS: frozenset[str] = frozenset({
    # English
    "critical", "high", "severe", "serious", "major", "important",
    "flaw", "flaws", "bug", "bugs", "vulnerability", "vulnerabilities",
    "vuln", "vulns", "issue", "issues", "hole", "holes", "weakness",
    "exploit", "exploits", "exploited", "exploiting", "exploitation",
    "attack", "attacks", "attacker", "attackers", "hacker", "hackers",
    "hacked", "hacking", "breach", "breached", "threat", "threats",
    "security", "cyber", "cybersecurity", "infosec",
    "patch", "patches", "patched", "patching", "fix", "fixes", "fixed",
    "update", "updates", "updated", "release", "released", "releases",
    "warn", "warns", "warning", "warned", "alert", "alerts", "advisory",
    "advisories", "disclose", "disclosed", "disclosure", "report",
    "reports", "reported", "reveal", "reveals", "revealed", "confirm",
    "confirms", "confirmed", "detail", "details", "found", "discover",
    "discovers", "discovered", "affect", "affects", "affected", "impact",
    "impacts", "impacted", "target", "targets", "targeted", "targeting",
    "allow", "allows", "allowing", "enable", "enables", "let", "lets",
    "use", "uses", "used", "using", "abuse", "abuses", "abused",
    "remote", "code", "execution", "rce", "unauthenticated", "auth",
    "authentication", "bypass", "privilege", "privileges", "escalation",
    "injection", "overflow", "traversal", "deserialization", "xss", "ssrf",
    "zero", "day", "zeroday", "0day", "poc", "cve", "cvss", "kev",
    "risk", "risks", "danger", "dangerous", "active", "actively",
    "public", "publicly", "million", "millions", "thousand", "thousands",
    "user", "users", "customer", "customers", "system", "systems",
    "server", "servers", "device", "devices", "account", "accounts",
    "data", "access", "malicious", "attacks", "campaign", "campaigns",
    "researcher", "researchers", "vendor", "vendors", "company",
    "companies", "firm", "firms", "team", "teams", "organization",
    "organizations", "organisation", "organisations", "org", "orgs",
    # Malware and attack-category nouns. The list had none of these, and
    # "malware" is the single most frequent distinctive token in the live
    # store — 15 of 200 headlines, ahead of "microsoft". A category name
    # says what KIND of story this is, never WHICH story.
    "malware", "ransomware", "backdoor", "backdoors", "trojan", "trojans",
    "worm", "worms", "spyware", "stealer", "stealers", "infostealer",
    "infostealers", "loader", "loaders", "dropper", "droppers", "rat",
    "rats", "botnet", "botnets", "rootkit", "keylogger", "wiper",
    "phishing", "phish", "phishes", "scam", "scams", "spam",
    # Delivery and action verbs, on the same argument: every campaign
    # delivers, installs, steals or spreads something. "deliver" is the
    # sixth most frequent distinctive token in the store (8 of 200), ahead
    # of "google".
    "deliver", "delivers", "delivered", "delivering", "delivery",
    "steal", "steals", "stealing", "stolen", "theft",
    "install", "installs", "installed", "deploy", "deploys", "deployed",
    "infect", "infects", "infected", "spread", "spreads",
    "push", "pushes", "pushed", "drop", "drops", "dropped",
    "hijack", "hijacks", "hijacked", "compromise", "compromises",
    "compromised", "leak", "leaks", "leaked",
    # Supply-chain vocabulary. Four separate npm stories ran in one week of
    # the live store; "package" and "cross-platform" are what made two of
    # them look like one.
    "package", "packages", "supply-chain", "cross-platform",
    "dependency", "dependencies",
    # Ukrainian equivalents
    "критичн", "критична", "критичний", "вразливість", "вразливості",
    "вразливо", "експлойт", "експлуатація", "атака", "атаки", "атакують",
    "зловмисник", "зловмисники", "хакер", "хакери", "витік", "загроза",
    "загрози", "безпеки", "безпека", "кібербезпеки", "патч", "оновлення",
    "виправлення", "попереджає", "попередження", "повідомляє",
    "виявлено", "виявили", "дослідники", "користувачі", "користувачів",
    "система", "системи", "сервер", "сервери", "дані", "доступ",
})

# Tokens that look like entities but are too common to anchor a merge on.
_ENTITY_BLOCKLIST: frozenset[str] = frozenset({
    "the", "new", "cisa", "cert", "nvd", "mitre", "google", "microsoft",
    "apple", "linux", "windows", "android", "ios", "chrome", "firefox",
    "safari", "edge", "aws", "azure", "cloud", "web", "app", "apps",
    "software", "hardware", "internet", "online", "ai", "llm",
})


def _norm_token(tok: str) -> str:
    """Lowercase and strip a trailing English plural.

    Crude on purpose: "escapes"/"escape" and "flaws"/"flaw" must compare
    equal or a headline pair like "VM escapes" vs "VM escape" scores far
    lower than it should. We only strip a trailing "s" when the stem is
    still substantial and doesn't already end in "s"/"u", which avoids
    mangling "https", "sas", "ios", "cms".
    """
    t = tok.lower()
    if len(t) > 4 and t.endswith("s") and not t.endswith(("ss", "us", "is", "os")):
        return t[:-1]
    return t


# `_norm_token` folds a trailing plural, so the comparison sets hold
# "patche" and "vulnerabilitie" rather than "patches" and "vulnerabilities".
# Listing only the surface forms above therefore leaked both straight back in
# as distinctive tokens AND as named entities — 4 headlines each in the live
# store. Fold the vocabulary the same way it will be looked up.
_GENERIC_SECURITY_TERMS = frozenset(
    _GENERIC_SECURITY_TERMS | {_norm_token(_t) for _t in _GENERIC_SECURITY_TERMS}
)


# --------------------------------------------------------------------------
# RULE D vocabularies. These describe the words AROUND a number, which are
# what decide whether it states a fact about an event or spells part of a
# product's name.
# --------------------------------------------------------------------------

# Words that may introduce a counted quantity even though the number after
# them is followed by capitals. Headlines are title-cased, so without this
# "Microsoft Plugs Nearly 400 Security Holes" reads as a product name.
_QUANTIFIER_CUES: frozenset[str] = frozenset({
    "nearly", "least", "more", "than", "over", "about", "roughly", "around",
    "almost", "approximately", "up", "some", "just", "only", "total", "all",
    "another", "additional", "affecting", "exceeding", "exceeds", "plus",
    "under", "upwards", "fixes", "fixed", "fixing", "patches", "patched",
    "plugs", "addresses", "closes", "remedy", "remedies", "resolves",
    "discloses", "disclosed", "reports", "reported", "exposed", "exposes",
    "affects", "hit", "hits", "leaked", "leaks", "stole", "stolen",
    # Ukrainian
    "до", "понад", "близько", "майже", "приблизно",
    "щонайменше", "більше", "всього", "загалом", "швидкістю",
})

# Words that mark the number after them as an identifier — a port, a
# standard, a model. "port 8999" and "IEC 61850" are as generic as the word
# "firmware" and must never anchor a merge.
_IDENTIFIER_CUES: frozenset[str] = frozenset({
    "port", "ports", "cvss", "version", "versions", "build", "builds", "rev",
    "revision", "rfc", "iso", "iec", "ieee", "ansi", "nist", "model",
    "models", "series", "sha", "md5", "sha1", "sha256", "asn", "bug",
    "issue", "ticket", "case", "chapter", "section", "article", "figure",
    "table", "page", "suite", "no", "sma", "windows", "office", "sp",
    # Ukrainian
    "порт", "версія", "версії", "версію",
})

# Words sitting between a number and the noun it counts. Skipped when
# reading the unit so that "398 security vulnerabilities" and "398 flaws"
# agree, and so that "100 million people" counts people, not millions.
_UNIT_SKIP: frozenset[str] = frozenset({
    "million", "millions", "billion", "billions", "thousand", "thousands",
    "hundred", "hundreds", "total", "separate", "distinct", "unique",
    "known", "different", "additional", "other", "more", "new", "its",
    "their", "such", "security", "malicious", "critical", "affected",
    "vulnerable", "confirmed", "reported", "individual", "further",
    "тис", "млн", "млрд", "більше",
})

# Unit nouns folded onto one representative, so two newsrooms counting the
# same things in different words still agree. Krebs's "398 security
# vulnerabilities" and The Hacker News's "398 Flaws" both count `vuln`;
# "50,000 residents" and "50,000 people" both count `people`.
_UNIT_SYNONYMS: dict[str, str] = {
    "flaw": "vuln", "vulnerability": "vuln", "vulnerabilitie": "vuln",
    "hole": "vuln", "bug": "vuln", "weakness": "vuln", "defect": "vuln",
    "cve": "vuln", "issue": "vuln", "patch": "vuln", "patche": "vuln",
    "fix": "vuln", "вразливостей": "vuln",
    "organization": "org", "organisation": "org", "compan": "org",
    "company": "org", "companie": "org", "firm": "org", "busines": "org",
    "victim": "org", "entitie": "org", "entity": "org",
    "person": "people", "people": "people", "resident": "people",
    "citizen": "people", "customer": "people", "member": "people",
    "employee": "people", "officer": "people", "patient": "people",
    "мешканців": "people", "людей": "people",
}

#: Units whose count identifies a release rather than describing an event.
_ROLLUP_UNITS: frozenset[str] = frozenset({"vuln"})


def extract_cves(text: str) -> frozenset[str]:
    """Uppercased CVE ids found in `text`. Empty set when there are none."""
    return frozenset(m.group(0).upper() for m in _CVE_RE.finditer(text or ""))


def _title_tokens(title: str) -> set[str]:
    """All content tokens from a title (stopwords removed, plurals folded)."""
    return {
        _norm_token(t)
        for t in _TOKEN_RE.findall(title or "")
        if len(t) > 2 and t.lower() not in _STOPWORDS
    }


def _distinctive_tokens(title: str) -> set[str]:
    """Title tokens with generic security vocabulary removed.

    What's left is the part of a headline that actually identifies the
    story: product names, vendor names, malware families, actor names,
    version numbers.
    """
    return {t for t in _title_tokens(title) if t not in _GENERIC_SECURITY_TERMS}


def _entities(title: str) -> set[str]:
    """Tokens that plausibly name a specific product, vendor or malware family.

    Heuristic, and deliberately so: anything that survived the generic-term
    filter and either starts with a capital letter in the original headline
    or contains a digit/hyphen (version strings, "wp2shell", "CVE-like"
    product codes). Ukrainian headlines rarely capitalize products, so we
    also accept any surviving distinctive token of length >= 5 — Ukrainian
    coverage is low-volume and the time window plus title threshold carry
    the safety there.
    """
    found: set[str] = set()
    for raw in _TOKEN_RE.findall(title or ""):
        norm = _norm_token(raw)
        if len(raw) <= 2:
            continue
        if norm in _STOPWORDS or norm in _GENERIC_SECURITY_TERMS:
            continue
        if norm in _ENTITY_BLOCKLIST:
            continue
        if raw.isdigit():
            # A bare number names nothing. The digit clause below is there
            # for "log4j", "wp2shell" and version strings; on its own a
            # number was letting RULE C treat a shared count as a shared
            # product. "Microsoft says 500 organizations breached in
            # Exchange attacks" and "Microsoft warns 500 organizations hit
            # by Teams phishing" share the entity "500" and nothing else.
            continue
        looks_like_entity = (
            raw[0].isupper()
            or any(ch.isdigit() for ch in raw)
            or "-" in raw
            or "." in raw
            or len(raw) >= 5
        )
        if looks_like_entity:
            found.add(norm)
    return found


def _body_digest(text: str | None) -> str:
    """Identity hash of an article body, or "" when the body is too thin.

    Whitespace-collapsed and lowercased so a re-render with different line
    wrapping still matches, but otherwise exact — this is used to assert
    that two entries ARE the same article, so it must not be fuzzy.

    The length floor is load-bearing. Several feeds ship an empty or
    one-line body, and without it every one of those would hash alike and
    merge into a single cluster.
    """
    normalized = " ".join((text or "").split()).lower()
    if len(normalized) < _MIN_BODY_FOR_IDENTITY:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _jaccard(a: set[str] | frozenset[str], b: set[str] | frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# Headlines that describe a bureaucratic action rather than the story.
# CISA's KEV catalog posts are the live example: "CISA Adds One Known
# Exploited Vulnerability to Catalog" is authoritative but tells a reader
# nothing about what was actually found. When such an item clusters with
# real reporting ("Cisco warns of FMC static credential flaw exploited in
# zero-day attacks"), the reporting headline must win — otherwise raw source
# credibility hands the feed its least informative title.
#
# RULE D reuses the list for a second job: a roundup quotes the counts that
# belong to every story it lists, so it must never match on a number.
_INDEX_HEADLINE_RES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\badds?\b.*\bto\b.*\bcatalog\b", re.IGNORECASE),
    re.compile(r"\bknown exploited vulnerabilit(?:y|ies)\b", re.IGNORECASE),
    re.compile(r"\b(?:weekly|monthly|daily)\s+"
               r"(?:recap|roundup|round-up|summary|digest)\b", re.IGNORECASE),
    re.compile(r"\bthreatsday\b", re.IGNORECASE),
    re.compile(r"\+\s*\d+\s+more\s+stories\b", re.IGNORECASE),
    re.compile(r"\bnews\s*#\s*\d+\b", re.IGNORECASE),
    re.compile(r"\bдайджест\b", re.IGNORECASE),
)


def _is_roundup_headline(title: str) -> bool:
    """Does this headline stand for several stories at once?

    Two shapes. The first is the labelled digest that
    `_INDEX_HEADLINE_RES` already knows — a KEV catalog entry, a weekly
    recap, a ThreatsDay bulletin. The second is the unlabelled one: a
    headline that simply lists its subjects, as in "Veeam, Terraform MCP
    and Django Patch 340 Flaws This Week". Its "340" belongs to three
    projects at once, so merging it with any one of them on that number
    would delete a real article.

    Thousands separators are stripped before the commas are counted, or
    "leak info of over 100,000 UK police officers, staff" would read as a
    list. Requiring several entities as well keeps ordinary two-clause
    headlines out: "Microsoft August 2026 Patch Tuesday fixes 400 flaws, 3
    zero-days" has one comma and no "and", and stays a normal headline.
    """
    text = title or ""
    if any(rx.search(text) for rx in _INDEX_HEADLINE_RES):
        return True
    if len(_entities(text)) < _MIN_ENTITIES_FOR_ENUMERATION:
        return False
    commas = _NUMERIC_COMMA_RE.sub("", text).count(",")
    if commas >= 2:
        return True
    return commas >= 1 and re.search(r"\band\b", text, re.IGNORECASE) is not None


def _preceding_word(text: str, start: int) -> str:
    """The word immediately before `text[start]`, or "" if there is none.

    A backwards character scan rather than a regex: it runs once per number
    found, and an anchored regex would rescan the text from the top each
    time.
    """
    i = start - 1
    while i >= 0 and not (text[i].isalnum() or text[i] in _QUANTITY_WORD_CHARS):
        i -= 1
    if i < 0 or text[i].isdigit():
        return ""
    end = i + 1
    while i >= 0 and (text[i].isalnum() or text[i] in _QUANTITY_WORD_CHARS):
        i -= 1
    return text[i + 1:end]


def _is_identifier_slot(text: str, start: int) -> bool:
    """Is the number at `start` naming a thing rather than counting things?

    The discriminator is the word in front of it. Product and standard
    designations follow a proper noun — "Microsoft 365", "SonicWall SMA
    1000", "C-CURE 9000", "Applied Biosystems 3130", "IEC 61850" — while a
    counted quantity follows a verb, a preposition or a quantifier: "at
    least 398", "roughly 50,000", "fixes 400", "зі швидкістю 190".

    Headlines are title-cased, so capitalization alone would also reject
    "Nearly 400"; `_QUANTIFIER_CUES` is the exemption that keeps those.
    """
    word = _preceding_word(text, start)
    if not word:
        return False
    lowered = word.lower()
    if lowered in _IDENTIFIER_CUES:
        return True
    if lowered in _QUANTIFIER_CUES:
        return False
    return word[:1].isupper()


def _quantity_unit(text: str, end: int) -> str:
    """The kind of thing the number ending at `end` counts, or "".

    Reading the unit is what stops one number matching across two different
    facts. "400 flaws" is not "400 organizations" and "615,000 people" is
    not "615 GB", however loudly both sides say the same digits.
    """
    for match in _TOKEN_RE.finditer(text, end):
        if match.start() - end > _QUANTITY_UNIT_WINDOW:
            return ""
        raw = match.group(0)
        if raw.isdigit():
            continue
        tok = _norm_token(raw)
        if tok in _STOPWORDS or tok in _UNIT_SKIP:
            continue
        return _UNIT_SYNONYMS.get(tok, tok)
    return ""


def extract_quantities(text: str) -> frozenset[tuple[int, str]]:
    """Counted quantities in `text`, each paired with the noun it counts.

    "Microsoft released updates to remedy at least 398 security
    vulnerabilities" and "Microsoft Patches 398 Flaws" are the same Patch
    Tuesday, and nothing else in the store counts 398 of anything. That
    agreement is the signal. Every filter below is there to keep out the
    numbers that are not that:

      * the regex refuses digit runs glued to a word character or to
        `. , / : -`, which removes CVSS scores, versions, dates and IPs;
      * `_RARE_QUANTITY_MIN` removes small counts, which are everywhere;
      * four-digit numbers in the calendar range are dates;
      * `_is_identifier_slot` removes product, port and standard numbers;
      * a number whose unit cannot be read is dropped entirely, because
        without one it cannot be compared safely.

    Measured over the 200-item live store: 35 quantities survive across 26
    articles, and exactly five in-window pairs share one.
    """
    clean = _CVE_RE.sub(" ", text or "")
    found: set[tuple[int, str]] = set()
    for match in _QUANTITY_RE.finditer(clean):
        digits = match.group(1).replace(",", "")
        if len(digits) > 1 and digits[0] == "0":
            continue
        value = int(digits)
        if value < _RARE_QUANTITY_MIN:
            continue
        if _QUANTITY_YEAR_LO <= value <= _QUANTITY_YEAR_HI:
            continue
        if _is_identifier_slot(clean, match.start(1)):
            continue
        unit = _quantity_unit(clean, match.end(1))
        if not unit:
            continue
        found.add((value, unit))
    return frozenset(found)


@dataclass(frozen=True)
class StoryFeatures:
    """Everything `same_story` needs about one article, computed once.

    Building these up front turns clustering from O(n^2) tokenizations into
    O(n) tokenizations plus O(n^2) cheap set intersections.
    """

    fingerprint: str
    source: str
    title: str
    published_at: object  # datetime; typed loosely to keep the dataclass import-light
    cves: frozenset[str]
    distinctive: frozenset[str]
    entities: frozenset[str]
    body_digest: str
    #: Counted quantities from title AND body, each with the noun it counts.
    #: Defaulted so that a caller building features by hand keeps working;
    #: RULE D simply never fires for them.
    quantities: frozenset[tuple[int, str]] = frozenset()

    @classmethod
    def from_item(cls, item: NewsItem) -> "StoryFeatures":
        # Scan the whole body for CVE ids, not just the lede. Every CVE we
        # find is a chance for VETO 1 to keep two advisories apart, and
        # `normalize.clean_article_body` already caps bodies at 3000 chars
        # so "whole body" is bounded. Measured on the production corpus:
        # scanning past the lede is what gives the second "ABB Symphony
        # Plus" advisory its own CVE, which is what stops it merging into
        # the first one.
        cve_text = f"{item.title}\n{item.raw_content or ''}"
        return cls(
            fingerprint=item.fingerprint,
            source=item.source,
            title=item.title,
            published_at=item.published_at,
            cves=extract_cves(cve_text),
            distinctive=frozenset(_distinctive_tokens(item.title)),
            entities=frozenset(_entities(item.title)),
            body_digest=_body_digest(item.raw_content),
            # Quantities come from the same title+body text as the CVEs, for
            # the same reason: the number that identifies an event is as
            # likely to sit in the lede as in the headline. Krebs put "398"
            # in its body and "400" in its title of the same Patch Tuesday
            # article; The Hacker News put "398" in its headline.
            quantities=extract_quantities(cve_text),
        )


def _within_window(a: StoryFeatures, b: StoryFeatures, *, days: int) -> bool:
    try:
        delta = abs(a.published_at - b.published_at)  # type: ignore[operator]
    except TypeError:  # pragma: no cover - defensive against naive/aware mix
        return False
    return bool(delta <= timedelta(days=days))


def same_story(
    a: StoryFeatures,
    b: StoryFeatures,
    *,
    window_days: int = _WINDOW_DAYS,
) -> bool:
    """Pairwise "are these the same underlying story?" decision.

    Pure and symmetric: `same_story(a, b) == same_story(b, a)`. See the
    module docstring for the rule table and the reasoning behind each
    threshold.
    """
    if a.fingerprint == b.fingerprint:
        return True
    if not _within_window(a, b, days=window_days):
        return False

    # RULE 0 — the same article text, whatever the URL says.
    #
    # Not a heuristic and not a similarity score: the bodies are the same
    # words. It runs ahead of both vetoes because no amount of contrary
    # metadata can make one article into two.
    #
    # This exists because itc.ua publishes every story under two URLs — a
    # `?p=4717356` permalink and a slug — which produce two fingerprints
    # with identical titles, identical timestamps and identical bodies. Three
    # such pairs were live simultaneously. VETO 2 was actively blocking them:
    # it assumes "a newsroom does not publish the same headline twice for the
    # same story", which is true of the CISA advisory feed it was written for
    # and false for a syndicating outlet.
    #
    # Placing it first also makes it work across sources, which is correct —
    # two outlets carrying one wire story verbatim are one story.
    if a.body_digest and a.body_digest == b.body_digest:
        return True

    both_have_cves = bool(a.cves) and bool(b.cves)
    shared_cves = a.cves & b.cves

    # VETO 1 — both name CVEs and none coincide. Different advisories.
    if both_have_cves and not shared_cves:
        return False

    # RULE A — identical CVE sets.
    if both_have_cves and a.cves == b.cves:
        return True

    shared_entities = a.entities & b.entities
    title_j = _jaccard(a.distinctive, b.distinctive)

    # RULE B — partial CVE overlap, but only with textual support so that a
    # multi-CVE roundup can't bridge unrelated stories.
    if both_have_cves and _jaccard(a.cves, b.cves) >= _CVE_JACCARD_MIN:
        if shared_entities and title_j >= _TITLE_JACCARD_SUPPORT:
            return True

    # VETO 2 — same source republishing one headline, with no CVE agreement
    # to vouch for the match. Product-named advisory entries, not one story.
    if a.source == b.source and a.title.strip().lower() == b.title.strip().lower():
        return False

    long_enough = (
        len(a.distinctive) >= _MIN_DISTINCTIVE_FOR_TEXT
        and len(b.distinctive) >= _MIN_DISTINCTIVE_FOR_TEXT
    )

    # RULE C — text-only match. Always requires a shared named entity, so
    # two stories must at minimum be about the same product or actor.
    #
    # Written as a positive block rather than guard-and-return so that its
    # entity gate no longer short-circuits RULE D below. Behaviour is
    # otherwise unchanged, verified over all 19,900 pairs of the live store
    # with `quantities` emptied.
    if shared_entities and long_enough:
        shared_tokens = len(a.distinctive & b.distinctive)
        if title_j >= _TITLE_JACCARD_STRONG and shared_tokens >= _MIN_SHARED_STRONG:
            return True
        if title_j >= _TITLE_JACCARD_WEAK and shared_tokens >= _MIN_SHARED_WEAK:
            return True

    # RULE D — the same counted quantity, about the same subject.
    #
    # The one positive path that does not require a shared entity, which is
    # the whole point of it. For any story about a major vendor the entity
    # intersection is empty by construction, because `_ENTITY_BLOCKLIST`
    # holds "microsoft", "google", "windows", "chrome" and friends. Krebs on
    # Security and The Hacker News covering the same Patch Tuesday share one
    # distinctive token ("microsoft", blocked as an entity), a title Jaccard
    # of 0.091 and no CVE — and both count 398 vulnerabilities. Without this
    # rule there is no path left for them and the reader sees the story
    # twice.
    #
    # Four things must line up. Each was added because dropping it produced
    # a false merge on the live store or on a hand-built pair:
    #
    #   * the same NUMBER counting the same KIND of thing. A bare number is
    #     not enough: "400 flaws" is not "400 organizations", and "615,000
    #     people" is not "615 GB". Pairing the unit is what lets the store's
    #     four separate "800"s — npm packages, kernel builds, network-layer
    #     attacks, poisoned packages — coexist without colliding.
    #   * a shared subject word carrying no digits, and never the unit noun
    #     itself. Otherwise the number vouches for itself:
    #     `_distinctive_tokens` keeps digit runs, so "100,000" donates the
    #     tokens "100" and "000", and two headlines that both say "500
    #     organizations" would offer "organization" as corroboration.
    #   * enough subject agreement for what is being counted. See
    #     `_MIN_SUBJECT_FOR_ROLLUP`.
    #   * neither headline may be a roundup.
    shared_quantities = a.quantities & b.quantities
    if shared_quantities and long_enough and not (
        _is_roundup_headline(a.title) or _is_roundup_headline(b.title)
    ):
        units = {unit for _, unit in shared_quantities}
        subject = {
            tok for tok in (a.distinctive & b.distinctive)
            if not any(ch.isdigit() for ch in tok)
            and _UNIT_SYNONYMS.get(tok, tok) not in units
        }
        needed = (
            _MIN_SUBJECT_FOR_ROLLUP
            if units & _ROLLUP_UNITS
            else _MIN_SUBJECT_FOR_QUANTITY
        )
        if len(subject) >= needed:
            return True

    return False


@dataclass
class StoryCluster:
    """One real-world story and every article we have about it."""

    key: str
    anchor: StoryFeatures
    members: list[StoryFeatures] = field(default_factory=list)

    @property
    def sources(self) -> list[str]:
        """Distinct source names in first-seen order."""
        seen: list[str] = []
        for m in self.members:
            if m.source not in seen:
                seen.append(m.source)
        return seen


def story_key_for(anchor: StoryFeatures) -> str:
    """Stable cluster id derived from the anchor article.

    Deriving it from the anchor's fingerprint (rather than from the token
    set) keeps the key stable across runs even as new members join and the
    shared vocabulary shifts. The `s:` prefix makes a story key visually
    distinguishable from a fingerprint in logs and stored JSON.
    """
    return "s:" + hashlib.sha256(anchor.fingerprint.encode("utf-8")).hexdigest()[:14]


def cluster_items(
    items: Sequence[NewsItem],
    *,
    window_days: int = _WINDOW_DAYS,
) -> list[StoryCluster]:
    """Group articles into stories using anchor-based greedy assignment.

    Ordering is deterministic — newest first, then fingerprint — so the same
    input always produces the same clusters and the same anchors, which is
    what makes `story_key` stable between pipeline runs.

    Each item is compared against existing cluster ANCHORS only, never
    against arbitrary members. That is what prevents transitive chaining:
    every membership decision is one direct pairwise comparison.
    """
    feats = [StoryFeatures.from_item(i) for i in items]
    feats.sort(key=lambda f: (f.published_at, f.fingerprint), reverse=True)

    clusters: list[StoryCluster] = []
    for f in feats:
        for cluster in clusters:
            if same_story(cluster.anchor, f, window_days=window_days):
                cluster.members.append(f)
                break
        else:
            clusters.append(
                StoryCluster(key=story_key_for(f), anchor=f, members=[f]),
            )
    return clusters


# --------------------------------------------------------------------------
# Canonical selection
# --------------------------------------------------------------------------

#: Headline quality tiers used to rank canonical candidates.
_HEADLINE_INDEX = 0     # bureaucratic index entry — worst canonical
_HEADLINE_TERSE = 1     # bare product name ("Siemens SIMATIC")
_HEADLINE_NORMAL = 2    # ordinary reporting headline


def headline_quality(title: str) -> int:
    """How well a headline stands on its own as the face of a story.

    Used for canonical selection. It does not decide whether two articles
    match, though RULE D shares its `_INDEX_HEADLINE_RES` list to recognize
    a roundup.
    """
    if any(rx.search(title or "") for rx in _INDEX_HEADLINE_RES):
        return _HEADLINE_INDEX
    if len(_distinctive_tokens(title)) < _MIN_DISTINCTIVE_FOR_TEXT:
        return _HEADLINE_TERSE
    return _HEADLINE_NORMAL


def choose_canonical(
    members: Sequence[NewsItem],
    *,
    prefer: Callable[[NewsItem], bool] | None = None,
) -> NewsItem:
    """Pick the article that represents a story to the reader.

    Ranking, highest priority first:
      1. `prefer(item)` is True. The API passes "already has an AI render in
         this locale" here — showing a story we can actually render beats
         showing the theoretically-best source as an empty card.
      2. A headline that tells the story. A KEV-catalog entry is the most
         authoritative item in its cluster and simultaneously the worst one
         to show a reader, so this outranks credibility deliberately.
      3. Higher source credibility. A CISA advisory outranks an aggregator.
      4. Most recent publication. A story develops — "flaw disclosed"
         becomes "flaw now exploited in the wild" three days later. The
         latest article carries the current state of the story, which beats
         giving the scoop credit and showing the reader stale news.
      5. Longer body. More source material means a better brief, and it's a
         decent proxy for original reporting over a two-paragraph rewrite.
      6. Fingerprint, purely so the result is deterministic.
    """
    if not members:
        raise ValueError("choose_canonical() needs at least one member")

    def sort_key(item: NewsItem) -> tuple[int, int, float, float, int, str]:
        return (
            1 if (prefer is not None and prefer(item)) else 0,
            headline_quality(item.title),
            round(float(item.source_credibility_score), 3),
            item.published_at.timestamp(),
            len(item.raw_content or ""),
            item.fingerprint,
        )

    return max(members, key=sort_key)


def assign_story_keys(
    items: Sequence[NewsItem],
    *,
    window_days: int = _WINDOW_DAYS,
) -> list[StoryCluster]:
    """Cluster `items` and write `story_key` / `duplicate_of` back onto them.

    The canonical member gets `duplicate_of = ""` (it is not a duplicate of
    anything); every other member points at the canonical's fingerprint.
    Both fields are also written on singleton clusters so that every item in
    the store carries a story key and downstream code never has to special-
    case "not yet clustered".

    Returns the clusters so callers can log or report on what merged.
    """
    by_fp = {i.fingerprint: i for i in items}
    clusters = cluster_items(items, window_days=window_days)
    for cluster in clusters:
        member_items = [by_fp[m.fingerprint] for m in cluster.members if m.fingerprint in by_fp]
        if not member_items:
            continue
        canonical = choose_canonical(member_items)
        for item in member_items:
            item.story_key = cluster.key
            item.duplicate_of = (
                "" if item.fingerprint == canonical.fingerprint else canonical.fingerprint
            )
    return clusters


def assign_incremental(
    new_items: Sequence[NewsItem],
    known_items: Sequence[NewsItem],
    *,
    window_days: int = _WINDOW_DAYS,
) -> list[NewsItem]:
    """Assign story keys to a fresh batch without disturbing stored items.

    This is the pipeline's entry point. Coverage of one story arrives across
    several ingest cycles — BleepingComputer at 09:00, The Hacker News at
    11:30 — so a fresh item has to be matched against what is already in the
    store, not just against its own batch.

    Re-running the full `assign_story_keys` over everything would work but
    would let a newly-arrived article re-anchor an existing cluster and
    change its `story_key`, breaking any reference already handed out. Here
    each existing story keeps its key, and a new item either joins one or
    starts its own.

    New items are matched against each known story's canonical article only,
    which preserves the no-transitive-chaining property.

    An item joining a story we already have is ALWAYS marked a duplicate,
    even when its headline or recency would win `choose_canonical`. The
    stored `duplicate_of` drives cost and broadcast decisions — "we have
    already rendered and published this story, don't do it again" — and
    first-seen-wins is the only rule that keeps those idempotent. Picking
    the nicest member to actually display is a separate, read-time decision
    made by `collapse_duplicates`, which is free to prefer the newer article.

    Returns the subset of `new_items` that were identified as duplicates of
    something (either stored or elsewhere in the same batch).
    """
    # Group what we already have by story, so each known story is
    # represented by exactly one article for matching purposes.
    groups: dict[str, list[NewsItem]] = {}
    for item in known_items:
        key = item.story_key or f"fp:{item.fingerprint}"
        groups.setdefault(key, []).append(item)

    known_anchors: list[tuple[str, StoryFeatures]] = []
    for key, members in groups.items():
        canonical = choose_canonical(members)
        known_anchors.append((key, StoryFeatures.from_item(canonical)))

    # Newest first so the batch's own anchors are chosen the same way
    # `cluster_items` would choose them.
    ordered = sorted(new_items, key=lambda i: (i.published_at, i.fingerprint), reverse=True)

    batch_anchors: list[tuple[str, StoryFeatures, NewsItem]] = []
    duplicates: list[NewsItem] = []

    for item in ordered:
        feats = StoryFeatures.from_item(item)

        # 1. Does it belong to a story we already know about? If so it is
        #    later coverage of something we have already handled.
        for key, anchor in known_anchors:
            if same_story(anchor, feats, window_days=window_days):
                item.story_key = key
                item.duplicate_of = choose_canonical(groups[key]).fingerprint
                groups[key].append(item)
                duplicates.append(item)
                break
        else:
            # 2. Does it belong to a story earlier in this same batch?
            for key, anchor, anchor_item in batch_anchors:
                if same_story(anchor, feats, window_days=window_days):
                    item.story_key = key
                    item.duplicate_of = anchor_item.fingerprint
                    duplicates.append(item)
                    break
            else:
                # 3. New story.
                item.story_key = story_key_for(feats)
                item.duplicate_of = ""
                batch_anchors.append((item.story_key, feats, item))

    return duplicates


def collapse_duplicates(
    items: Iterable[NewsItem],
    *,
    prefer: Callable[[NewsItem], bool] | None = None,
) -> tuple[list[NewsItem], dict[str, list[str]]]:
    """Read-time collapse: one item per story, plus who else reported it.

    Returns `(canonical_items, extra_sources_by_fingerprint)` where the map
    holds, for each surviving item, the names of the OTHER sources that
    covered the same story. Input order is preserved among survivors so
    callers keep whatever sort they applied.

    This is the defensive half of the design. `assign_story_keys` runs at
    ingest and is the cheap path; this function re-derives grouping from the
    stored `story_key` at read time so that items ingested before the
    feature existed — or ingested in separate cycles that never saw each
    other — still collapse correctly in the feed.

    Items without a `story_key` are treated as their own story, so a store
    that predates clustering degrades to today's behavior rather than
    collapsing everything into one bucket.
    """
    items = list(items)
    groups: dict[str, list[NewsItem]] = {}
    order: list[str] = []
    for item in items:
        key = getattr(item, "story_key", "") or f"fp:{item.fingerprint}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)

    survivors: list[NewsItem] = []
    extra_sources: dict[str, list[str]] = {}
    for key in order:
        members = groups[key]
        if len(members) == 1:
            # Nothing to choose between, so don't invoke `prefer` at all.
            # This matters more than it looks: `prefer` is backed by the AI
            # cache, which is a network round-trip against Postgres. Running
            # it over every item turned one feed request into hundreds of
            # queries. The overwhelming majority of stories are single-source,
            # so skipping them here removes almost all of that cost.
            survivors.append(members[0])
            continue
        canonical = choose_canonical(members, prefer=prefer)
        survivors.append(canonical)
        others: list[str] = []
        for m in members:
            if m.fingerprint == canonical.fingerprint:
                continue
            if m.source != canonical.source and m.source not in others:
                others.append(m.source)
        if others:
            extra_sources[canonical.fingerprint] = others

    # Restore the caller's ordering.
    rank = {i.fingerprint: n for n, i in enumerate(items)}
    survivors.sort(key=lambda i: rank.get(i.fingerprint, 0))
    return survivors, extra_sources


__all__ = [
    "StoryFeatures",
    "StoryCluster",
    "same_story",
    "cluster_items",
    "assign_story_keys",
    "collapse_duplicates",
    "choose_canonical",
    "story_key_for",
    "extract_cves",
    "extract_quantities",
]
