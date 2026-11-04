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

  VETO 3 — a labelled digest is never a text match
      A weekly digest ("DOU News #274", "Weekly Recap", "ThreatsDay")
      copies the headlines of the stories it lists, so it can look like any
      one of them. It stands for several stories, and folding it into one
      of them hides either the digest or the story. Applies to RULE C, D
      and E; the CVE rules above still let a KEV catalog entry join the
      reporting on its CVE.

  RULE D — the same counted quantity about the same subject. See the
      comment block in `same_story`.

  RULE E — a rare shared name within 48 hours
      Two outlets covering one incident often share almost no wording.
      BleepingComputer's "Chainalysis discloses data breach from 'offensive
      agentic techniques'" and The Hacker News's "Chainalysis Confirms
      Intrusion Into Internal Tools and Exposure of Customer Identity Data"
      share one word — but it is a name, and nothing else in the corpus
      mentions it. That rarity is the evidence. Requires, all of:

        * published within `_RARE_NAME_WINDOW` of each other;
        * a shared NAME (`_headline_names`, much stricter than `_entities`:
          a quoted name, a name-shaped token such as "PHP2Shell" or "ASA",
          a capital that is not just sentence-initial or title-case, or a
          Latin word inside a Cyrillic headline). A name is the whole run
          of adjacent proper nouns, so "Claude Code" does not match the
          "Claude" of "Fake ChatGPT and Claude Apps", and "Cisco SD-WAN"
          does not match the "Cisco" of "Cisco firewall";
        * that name is rare in the corpus window: in at most
          `_RARE_NAME_MAX_DF` headlines, or — for a heavily covered event —
          in at most `_BURST_NAME_MAX_DF` headlines that all fall inside one
          `_RARE_NAME_WINDOW` burst, with a second shared headline word to
          corroborate it. Five outlets naming «Повітряна тривога» within 19
          hours is one event; "Cisco" in five headlines is several;
        * compatible categories (`_CATEGORY_FAMILIES`), with a second shared
          headline word when either side is uncategorized ("other");
        * neither headline is a digest or announces a follow-up ("two more
          zero-days", "another", "again", «знову», «ще дві»);
        * for vulnerability coverage: two shared names or one multi-word
          name (vendor AND product), neither headline naming a product the
          other lacks, and neither joining two named products with "and".
          A vendor ships many flaws: "Cisco SD-WAN" and "Cisco ASA" are two
          stories even on the same day, and "Flaws in Collabora Online and
          Arista VeloCloud" is two advisories in one headline.

      Document frequency is a property of the batch, so `same_story` takes
      it as an argument (`name_stats`) rather than computing it; without it
      RULE E is off and the function behaves exactly as before.

Ukrainian headlines
-------------------
Ukrainian is inflected: «Повітряна тривога» and «Повітряної тривоги» are
one name, as are "застосунок" and "застосунку". `_norm_token` strips common
inflectional endings from Cyrillic tokens (keeping a stem of at least four
letters, see `_stem_cyrillic`) and the tokenizer keeps "з'явилося" whole
whatever apostrophe the outlet typed (' ’ ʼ). Latin tokens are untouched:
every Latin feature is byte-for-byte what it was. The stemmer is light —
verb forms and consonant alternations ("тривозі") still differ. `_entities` also stopped treating
every Cyrillic word of five letters as an entity: Ukrainian capitalizes only
proper names, so a capital that is not sentence-initial, a quoted name, an
acronym or a Latin word inside the headline is what marks one.

Known limits
------------
Precision is carried by CVE identifiers whenever both articles name one.
Where neither does, RULE C is a bet: two headlines that share this much
distinctive vocabulary within five days are the same story. That bet was
checked against 377 real stored articles (the 200-item live store plus a
177-item earlier snapshot) and produced no false merges, but it is a
heuristic and not a proof. Two outlets writing near-identical CVE-less
headlines about different vendors in the same week would merge incorrectly.

RULE E is the document-frequency weighting that paragraph used to call for,
applied to names only. Its residual risk is one victim with two unrelated
incidents inside 48 hours, neither naming a CVE, and both headlines naming
nothing but the victim. In incremental mode a name's frequency is whatever
the store holds at that moment, so the second story about any vendor sees
a low count; the run-based names, the vulnerability-family product checks
and the CVE veto, not rarity, are what hold those apart. Replaying the
2026-11 snapshot through `assign_incremental` in fetch order, the one
merge incremental mode makes that batch mode does not is BleepingComputer's
Binance hack report with ain.ua's explainer on North Korea pegged to it.

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
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Iterable, Literal, Mapping, Sequence

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

#: RULE E — a shared rare name only counts between articles this close.
#: Coverage of one incident lands within a day or two; a vendor's next
#: advisory lands within a week, so the general `_WINDOW_DAYS` is too wide.
_RARE_NAME_WINDOW = timedelta(hours=48)
#: RULE E — a name in more headlines than this is a topic, not a story.
_RARE_NAME_MAX_DF = 3
#: RULE E — the ceiling for a name whose every mention sits in one burst.
_BURST_NAME_MAX_DF = 8
#: RULE E — shared distinctive headline words required when the name alone
#: is not trusted: a burst-rare name, or an uncategorized item. A two-word
#: name such as «Повітряна тривога» supplies both on its own.
_MIN_SHARED_FOR_CORROBORATION = 2
#: RULE E — a quoted span longer than this is a quotation, not a name.
_MAX_QUOTED_NAME_TOKENS = 4
#: Ukrainian stems shorter than this are too ambiguous to compare.
_MIN_CYRILLIC_STEM = 4

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[^\W_]+(?:[-.][^\W_]+)*", flags=re.UNICODE)
_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
_LATIN_RE = re.compile(r"[A-Za-z]")
# The Ukrainian apostrophe is part of the word ("з'явилося", "п’яти"), but
# `_TOKEN_RE` splits on it, and outlets type it three ways. Between two
# Cyrillic letters it is dropped, so every spelling yields one token. Latin
# text is untouched: "Anthropic's" keeps its English tokenization.
_CYRILLIC_APOSTROPHE_RE = re.compile(
    r"(?<=[Ѐ-ӿ])['’ʼ‘`](?=[Ѐ-ӿ])"
)

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
    # Ukrainian headline vocabulary for the same categories. Stemming makes
    # these compare across inflections, which is exactly why they must be
    # listed: "хакерської атаки" and "кібератаки" are in a large share of
    # all Ukrainian headlines and identify no story. "уразливість" is the
    # older spelling dev.ua still uses.
    "уразливість", "уразливості", "кібератака", "кібератаки",
    "атакували", "атакувати", "атакував", "хакерська", "хакерської",
    "хакерський", "хакерські", "злам", "зламали", "зламав", "зламала",
    "зламаний", "кіберзлочинці", "шахрай", "шахраї", "шахраїв",
    "вірус", "вірусне", "шкідливе", "шкідливий", "шкідливого", "фішинг",
    "фішингові", "кіберзагроза", "кіберзагрози", "інцидент",
    "кіберінцидент", "уразливий", "вразливий", "компанія", "компанії",
    "сервіс", "сервісу",
})

# Tokens that look like entities but are too common to anchor a merge on.
_ENTITY_BLOCKLIST: frozenset[str] = frozenset({
    "the", "new", "cisa", "cert", "nvd", "mitre", "google", "microsoft",
    "apple", "linux", "windows", "android", "ios", "chrome", "firefox",
    "safari", "edge", "aws", "azure", "cloud", "web", "app", "apps",
    "software", "hardware", "internet", "online", "ai", "llm",
})


# Ukrainian inflectional endings, longest first so the first match is the
# longest. Nouns, adjectives and participles only: those are what names are
# made of. The abstract-noun family -ість/-ості/-остей alternates its vowel,
# so it is stripped whole ("вразливість", "вразливості" -> "вразлив").
_UK_ENDINGS: tuple[str, ...] = tuple(sorted({
    "остями", "остям", "остях", "остей", "ості", "ість", "істю",
    "ією", "ими", "іми", "ами", "ями", "ого", "ому", "ові", "еві", "єві",
    "ія", "ії", "ію", "ій", "ий", "их", "іх", "им", "ім", "ої", "ою",
    "ею", "єю", "ую", "юю", "ах", "ях", "ам", "ям", "ів", "їв", "ом",
    "ем", "єм", "ей",
    "а", "я", "и", "і", "ї", "у", "ю", "о", "е", "є", "ь", "й",
}, key=len, reverse=True))
_UK_REFLEXIVE: tuple[str, ...] = ("ся", "сь")


def _stem_cyrillic(word: str) -> str:
    """A light, deterministic Ukrainian stem for matching, not for display.

    Strips the reflexive suffix, then the longest inflectional ending that
    still leaves `_MIN_CYRILLIC_STEM` letters, then folds the fleeting vowel
    of "-ок"/"-ець" ("застосунок"/"застосунку" -> "застосунк", "кінець"/
    "кінця" -> "кінц"). Shorter words are returned unchanged: a three-letter
    stem collides with too much. It is not a morphological analyser — verb
    forms and consonant alternations ("тривога"/"тривозі") still differ —
    but it makes the common case of one name in two grammatical cases
    compare equal, which is all matching needs.
    """
    w = word
    for suffix in _UK_REFLEXIVE:
        if w.endswith(suffix) and len(w) - len(suffix) >= _MIN_CYRILLIC_STEM + 1:
            w = w[: -len(suffix)]
            break
    for ending in _UK_ENDINGS:
        if w.endswith(ending) and len(w) - len(ending) >= _MIN_CYRILLIC_STEM:
            w = w[: -len(ending)]
            break
    if len(w) >= _MIN_CYRILLIC_STEM + 1 and w.endswith("ок"):
        w = w[:-2] + "к"
    elif len(w) >= _MIN_CYRILLIC_STEM + 1 and w.endswith("ец"):
        w = w[:-2] + "ц"
    return w


def _prepare(text: str) -> str:
    """Normalize a headline before tokenizing: join Cyrillic apostrophes."""
    return _CYRILLIC_APOSTROPHE_RE.sub("", text or "")


def _norm_token(tok: str) -> str:
    """Lowercase, strip a trailing English plural, stem Ukrainian.

    Crude on purpose: "escapes"/"escape" and "flaws"/"flaw" must compare
    equal or a headline pair like "VM escapes" vs "VM escape" scores far
    lower than it should. We only strip a trailing "s" when the word is
    longer than four letters and doesn't end in "ss"/"us"/"is"/"os", which
    avoids mangling "access", "virus", "analysis", "macos"; "sas", "ios"
    and "cms" are under the length floor. ("https" does fold to "http".)

    A token containing Cyrillic goes through `_stem_cyrillic` instead (the
    last hyphen segment only, so "ші-моделі" -> "ші-модел"). Latin tokens
    take exactly the path they always did.
    """
    t = tok.lower()
    if _CYRILLIC_RE.search(t):
        head, sep, last = t.rpartition("-")
        return head + sep + _stem_cyrillic(last)
    if len(t) > 4 and t.endswith("s") and not t.endswith(("ss", "us", "is", "os")):
        return t[:-1]
    return t


# `_norm_token` folds a trailing plural, so the comparison sets hold
# "patche" and "vulnerabilitie" rather than "patches" and "vulnerabilities".
# Listing only the surface forms above therefore leaked both straight back in
# as distinctive tokens AND as named entities — 4 headlines each in the live
# store. Fold the vocabulary the same way it will be looked up.
#
# The same holds for Ukrainian stems: "вразливості" is looked up as
# "вразлив", so the folded set has to contain "вразлив".
_GENERIC_SECURITY_TERMS = frozenset(
    _GENERIC_SECURITY_TERMS | {_norm_token(_t) for _t in _GENERIC_SECURITY_TERMS}
)
_STOPWORDS = frozenset(_STOPWORDS | {_norm_token(_t) for _t in _STOPWORDS})


# Names that are real proper nouns but anchor nothing: places, nationalities,
# agencies that comment on every story, and calendar words. RULE E trusts a
# rare shared name, and "Russian", «Києві», "FBI" or "Tuesday" can be rare in
# a 200-item window while naming no particular story. Same rationale as
# `_ENTITY_BLOCKLIST`, which RULE E also applies. Stored folded.
_NAME_BLOCKLIST: frozenset[str] = frozenset(_norm_token(_t) for _t in {
    # Places and nationalities
    "ukraine", "ukrainian", "russia", "russian", "china", "chinese",
    "iran", "iranian", "korea", "korean", "north", "south", "east", "west",
    "america", "american", "europe", "european", "asia", "asian", "africa",
    "african", "japan", "japanese", "israel", "israeli", "india", "indian",
    "germany", "german", "france", "french", "britain", "british",
    "england", "australia", "australian", "canada", "canadian", "poland",
    "polish", "taiwan", "taiwanese", "vietnam", "vietnamese", "pakistan",
    "syria", "syrian", "iraq", "iraqi", "turkey", "turkish", "belarus",
    "belarusian", "kyiv", "moscow", "beijing", "washington", "usa",
    "global", "world", "worldwide", "international", "national", "federal",
    "україна", "україни", "україні", "україну", "українці", "українців",
    "київ", "києва", "києві", "львів", "львова", "харків", "харкова",
    "одеса", "одеси", "дніпро", "росія", "росії", "росію", "росією",
    "рф", "сша", "америка", "америки", "європа", "європи", "європі",
    "європу", "китай", "китаю", "кндр", "іран", "ірану", "ізраїль",
    "польща", "польщі", "франція", "франції", "німеччина", "німеччини",
    "британія", "британії", "японія", "японії", "білорусь", "білорусі",
    "москва", "москви", "пекін", "світ", "світі", "світу", "єс",
    # Agencies and bodies that appear across unrelated stories
    "fbi", "nsa", "ncsc", "europol", "interpol", "doj", "ftc", "nato",
    "cert-ua", "enisa", "bsi", "anssi", "jpcert", "acsc", "cccs",
    "сбу", "мвс", "зсу", "нбу", "мінцифри", "мінцифра", "мінцифрою",
    "держспецзвязку", "держспецзвязок", "кіберполіція", "кіберполіції",
    "уряд", "уряду", "верховна", "рада", "ради", "нато", "оон",
    # Technology acronyms. Spelled like names, mean a kind of thing: two
    # ransomware gangs hitting "NAS devices" the same day are two stories.
    "api", "sql", "ssh", "vpn", "tls", "ssl", "dns", "nas", "sms", "ddos",
    "uefi", "tcp", "udp", "http", "https", "pdf", "usb", "gpu", "cpu",
    "iot", "ics", "scada", "plc", "hmi", "rdp", "smb", "ldap", "saml",
    "sso", "mfa", "2fa", "otp", "url", "apt", "c2", "ioc", "soc", "siem",
    "edr", "xdr", "ceo", "cto", "ciso", "pc", "pcs", "urgent", "ші", "пз", "іт",
    # Calendar words
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "sunday", "q1", "q2", "q3", "q4",
})


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
# `_quantity_unit` looks words up after `_norm_token`, which stems the
# Ukrainian entries ("вразливостей" -> "вразлив"). Fold both tables.
_UNIT_SYNONYMS = {**_UNIT_SYNONYMS, **{_norm_token(k): v for k, v in _UNIT_SYNONYMS.items()}}
_UNIT_SKIP = frozenset(_UNIT_SKIP | {_norm_token(_t) for _t in _UNIT_SKIP})

#: Units whose count identifies a release rather than describing an event.
_ROLLUP_UNITS: frozenset[str] = frozenset({"vuln"})


def extract_cves(text: str) -> frozenset[str]:
    """Uppercased CVE ids found in `text`. Empty set when there are none."""
    return frozenset(m.group(0).upper() for m in _CVE_RE.finditer(text or ""))


def _title_tokens(title: str) -> set[str]:
    """All content tokens from a title (stopwords removed, plurals folded)."""
    return {
        _norm_token(t)
        for t in _TOKEN_RE.findall(_prepare(title))
        if len(t) > 2 and t.lower() not in _STOPWORDS
    }


def _distinctive_tokens(title: str) -> set[str]:
    """Title tokens with generic security vocabulary removed.

    What's left is the part of a headline that actually identifies the
    story: product names, vendor names, malware families, actor names,
    version numbers.
    """
    return {t for t in _title_tokens(title) if t not in _GENERIC_SECURITY_TERMS}


# --------------------------------------------------------------------------
# Headline anatomy: where each word sits. Shared by `_entities` (Cyrillic
# branch) and `_headline_names`, which both need to know whether a capital
# letter means "proper noun" or merely "first word of the sentence".
# --------------------------------------------------------------------------

# A quoted span. Ukrainian outlets use «…», "…" and „…“ interchangeably for
# one name — itc.ua wrote "Повітряна тривога" where dou.ua wrote «Повітряна
# тривога». Single quotes only count when they cannot be an apostrophe or a
# possessive: not glued to a word on the outside.
_QUOTE_RE = re.compile(
    r"«([^«»]{1,80})»"
    r"|“([^“”]{1,80})”"
    r"|„([^„“”]{1,80})[“”]"
    r'|(?<!\w)"([^"]{1,80})"(?!\w)'
    r"|(?<![\w'‘’])['‘]([^'‘’]{1,80})['’](?!\w)"
)
#: A capital after one of these starts a sentence and proves nothing.
_SENTENCE_BOUNDARY = ".!?…:|"
#: Skipped when looking back for a boundary: whitespace, openers, dashes.
_BOUNDARY_SKIP = " \t\n\r«\"“„'‘([{—–-"


@dataclass(frozen=True)
class _Word:
    raw: str
    norm: str
    initial: bool       # first word of the headline or of a sentence in it
    quote: int          # index of the enclosing quoted span, or -1
    cyrillic: bool
    joined: bool = False  # only whitespace separates it from the previous word


def _is_initial(text: str, start: int) -> bool:
    i = start - 1
    while i >= 0 and text[i] in _BOUNDARY_SKIP:
        i -= 1
    return i < 0 or text[i] in _SENTENCE_BOUNDARY


def _scan(title: str) -> tuple[str, list[_Word], list[tuple[int, int]]]:
    """Tokenize a headline, recording position facts for each word."""
    text = _prepare(title)
    spans = [
        (m.start(g), m.end(g))
        for m in _QUOTE_RE.finditer(text)
        for g in range(1, (m.lastindex or 0) + 1)
        if m.group(g) is not None
    ]
    words: list[_Word] = []
    prev_end = -1
    for m in _TOKEN_RE.finditer(text):
        raw = m.group(0)
        quote = next((n for n, (s, e) in enumerate(spans) if s <= m.start() < e), -1)
        words.append(_Word(
            raw=raw,
            norm=_norm_token(raw),
            initial=_is_initial(text, m.start()),
            quote=quote,
            cyrillic=bool(_CYRILLIC_RE.search(raw)),
            joined=prev_end >= 0 and text[prev_end:m.start()].isspace(),
        ))
        prev_end = m.end()
    return text, words, spans


def _is_cyrillic_headline(text: str) -> bool:
    return len(_CYRILLIC_RE.findall(text)) > len(_LATIN_RE.findall(text))


def _is_acronym(raw: str) -> bool:
    letters = [ch for ch in raw if ch.isalpha()]
    return len(letters) >= 2 and all(ch.isupper() for ch in letters)


def _is_name_shaped(raw: str) -> bool:
    """Spelled like a name whatever its position: "PHP2Shell", "VeloCloud",
    "iPhone", "LiteLLM", "C3RB3R", "ASA", "МНС".

    Camel case means an upper-case letter directly after a lower-case one,
    so "China-Linked" (a capital after a hyphen) is not name-shaped.
    """
    if _is_acronym(raw):
        return True
    has_digit = any(ch.isdigit() for ch in raw)
    has_alpha = any(ch.isalpha() for ch in raw)
    if has_digit and has_alpha:
        return True
    return any(a.islower() and b.isupper() for a, b in zip(raw, raw[1:]))


def _is_title_case(words: Sequence[_Word]) -> bool:
    """Is every word capitalized, so that a capital means nothing?

    The Hacker News and CISA title-case their headlines; BleepingComputer
    and every Ukrainian outlet use sentence case. Measured over non-initial
    content words of four letters or more, outside quotes.
    """
    probe = [
        w for w in words
        if not w.initial and w.quote < 0 and len(w.raw) >= 4
        and w.raw.isalpha() and w.raw.lower() not in _STOPWORDS
    ]
    if not probe:
        return False
    capitalized = sum(1 for w in probe if w.raw[0].isupper())
    return capitalized / len(probe) >= 0.6


def _entities(title: str) -> set[str]:
    """Tokens that plausibly name a specific product, vendor or malware family.

    Heuristic, and deliberately so: anything that survived the generic-term
    filter and either starts with a capital letter in the original headline
    or contains a digit/hyphen (version strings, "wp2shell", "CVE-like"
    product codes), or is five letters or longer.

    Cyrillic words are judged differently. The five-letter clause made every
    Ukrainian content word an "entity" — eleven of twelve words of a typical
    dev.ua headline — so for Cyrillic the gate RULE C relies on meant
    nothing. Ukrainian capitalizes only proper names, which is a far better
    signal than English offers: a Cyrillic word is an entity when it is
    capitalized somewhere other than the start of a sentence, is an
    acronym ("МНС", "ДТЕК"), or sits inside a short quoted name («Повітряна
    тривога»). Latin words inside a Cyrillic headline keep the Latin test.
    """
    _, words, _ = _scan(title)
    found: set[str] = set()
    for w in words:
        raw, norm = w.raw, w.norm
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
        if w.cyrillic:
            looks_like_entity = (
                _is_acronym(raw)
                or (raw[0].isupper() and not w.initial)
                or (w.quote >= 0 and _quoted_name_tokens(words, w.quote) is not None)
            )
        else:
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


def _quoted_name_tokens(words: Sequence[_Word], quote: int) -> list[str] | None:
    """Content stems of quoted span `quote`, or None if it is not a name.

    A name is short. «Повітряна тривога» and 'Silent Train' are names;
    «Фундамент для незалежної мережі зв'язку України» is a quotation, and
    so is anything past `_MAX_QUOTED_NAME_TOKENS` words.
    """
    inside = [w for w in words if w.quote == quote]
    if not inside or len(inside) > _MAX_QUOTED_NAME_TOKENS:
        return None
    content = [
        w.norm for w in inside
        if w.raw.lower() not in _STOPWORDS and not w.raw.isdigit()
    ]
    if not content or all(t in _GENERIC_SECURITY_TERMS for t in content):
        return None
    return content


def _body_proper_nouns(body: str) -> frozenset[str]:
    """Words the article body capitalizes somewhere other than a sentence start.

    The test for a headline's first word, which is capitalized whatever it
    is. BleepingComputer's "Chainalysis discloses data breach..." starts
    with the name; its body says "analytics firm Chainalysis disclosed",
    which settles it. The Hacker News title-cases every word, so the same
    test is what tells its "Chainalysis" from its "Intrusion" — the body
    says "a cybersecurity incident", lower case.
    """
    text = _prepare(body)
    found: set[str] = set()
    for m in _TOKEN_RE.finditer(text):
        raw = m.group(0)
        if len(raw) <= 2 or not raw[0].isupper():
            continue
        if _is_initial(text, m.start()):
            continue
        found.add(_norm_token(raw))
    return frozenset(found)


_CONJUNCTIONS: frozenset[str] = frozenset({"and", "plus", "та", "і", "й"})


def _headline_names(title: str, body: str = "") -> tuple[frozenset[str], bool]:
    """Strict proper names in a headline, and whether it joins two of them.

    The names are RULE E's match keys, and much narrower than `_entities`,
    because RULE E trusts a single shared name where RULE C asks for a whole
    shared headline. A word is a proper noun when the headline itself marks
    it as one:

      * name-shaped spelling: "PHP2Shell", "VeloCloud", "ASA", "МНС";
      * a capital that is not explained by position. In a sentence-case
        headline that is any non-initial capital. A Latin word inside a
        Cyrillic headline counts when capitalized — "Binance", "Ajax",
        "Stfalcon". A first word, or any word of a title-cased headline,
        needs `_body_proper_nouns` to confirm it.

    A key is a maximal RUN of adjacent proper nouns, not a single word, so
    a product only matches the same product. "Claude Code" and the
    "Claude" of "Fake ChatGPT and Claude Apps" are different keys; so are
    "Cisco SD-WAN" and the "Cisco" of "Cisco firewall". Inside a run a
    capitalized generic or blocklisted word is still part of the name
    ("Claude Code", "Microsoft Authenticator"), but a run needs at least one
    word that qualifies on its own, and geographic/calendar words
    (`_NAME_BLOCKLIST`) end a run and are dropped. A short quoted span is
    one key on its own ("повітрян тривог"), so «Ядерна тривога» does not
    match «Повітряна тривога» on "тривог". Every key is normalized with
    `_norm_token`, so Ukrainian inflections compare equal.

    The second value is True when a conjunction has a name before it and a
    different name after it — "Flaws in Collabora Online and Arista
    VeloCloud" is two advisories in one headline. See RULE E.
    """
    text, words, spans = _scan(title)
    cyrillic_headline = _is_cyrillic_headline(text)
    title_case = not cyrillic_headline and _is_title_case(words)
    body_nouns: frozenset[str] | None = None

    def capital_counts(w: _Word) -> bool:
        nonlocal body_nouns
        if not w.raw[:1].isupper():
            return False
        if cyrillic_headline and not w.cyrillic:
            return True
        if not w.initial and not title_case:
            return True
        if body_nouns is None:
            body_nouns = _body_proper_nouns(body)
        return w.norm in body_nouns

    def blocked(w: _Word) -> bool:
        return w.norm in _NAME_BLOCKLIST or any(
            part in _NAME_BLOCKLIST for part in w.norm.split("-")
        )

    def strong(w: _Word) -> bool:
        """Qualifies as a name on its own."""
        raw, norm = w.raw, w.norm
        if len(raw) <= 2 or raw.isdigit() or blocked(w):
            return False
        if raw.lower() in _STOPWORDS or norm in _STOPWORDS:
            return False
        if norm in _GENERIC_SECURITY_TERMS or norm in _ENTITY_BLOCKLIST:
            return False
        return _is_name_shaped(raw) or capital_counts(w)

    def part(w: _Word) -> bool:
        """May extend a run that contains a strong word."""
        if len(w.raw) <= 2 and not w.raw.isdigit():
            return False
        if blocked(w) or w.raw.lower() in _STOPWORDS:
            return False
        return w.raw.isdigit() or _is_name_shaped(w.raw) or capital_counts(w)

    # (key, first word index, last word index)
    found: list[tuple[str, int, int]] = []
    for n in range(len(spans)):
        tokens = _quoted_name_tokens(words, n)
        if tokens is None:
            continue
        key = " ".join(tokens)
        idx = [i for i, w in enumerate(words) if w.quote == n]
        if key not in _NAME_BLOCKLIST and key not in _ENTITY_BLOCKLIST:
            found.append((key, idx[0], idx[-1]))

    run: list[int] = []

    def close_run() -> None:
        while run and words[run[-1]].raw.isdigit():
            run.pop()
        while run and words[run[0]].raw.isdigit():
            run.pop(0)
        if run and any(strong(words[i]) for i in run):
            found.append((" ".join(words[i].norm for i in run), run[0], run[-1]))
        run.clear()

    for i, w in enumerate(words):
        if w.quote >= 0 or not part(w):
            close_run()
            continue
        if run and not w.joined:
            close_run()
        run.append(i)
    close_run()

    names = frozenset(k for k, _, _ in found)
    joins = False
    for i, w in enumerate(words):
        if w.quote >= 0 or w.raw.lower() not in _CONJUNCTIONS:
            continue
        before = {k for k, _, last in found if last < i}
        after = {k for k, first, _ in found if first > i}
        if before and (after - before):
            joins = True
            break
    return names, joins


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
    re.compile(r"\bweek in (?:review|ransomware|security)\b", re.IGNORECASE),
    re.compile(r"\bпідсумки\s+тижня\b|\bголовне\s+за\s+тиждень\b|\bновини\s+тижня\b",
               re.IGNORECASE),
    # Several topics joined by pipes: "Витік довіри до інтернету | Російський
    # супутник-камікадзе | Кінець BioWare — DOU News #273". Recognized by
    # shape so a renamed issue line does not let a digest back in.
    re.compile(r"\S\s+\|\s+\S.*\s\|\s+\S"),
)

# A headline announcing a further development: "Ivanti patches two more
# Connect Secure zero-days", "PHP Warns of Another Unpatched RCE", "campaign
# returns", «Супермаркети ... знову опинилися під ударом». It says in words
# that it is not the earlier story, so RULE E — whose only evidence is a
# shared name — must not fold it into the earlier one. ("third" is guarded
# against "third-party".)
_FOLLOW_UP_RE = re.compile(
    r"\b(?:\d+|one|two|three|four|five|six|several|dozens?)\s+more\b(?!\s+than\b)"
    r"|\banother\b|\bsecond\b(?!-)|\bthird\b(?!-)|\bagain\b|\breturns?\b"
    r"|\bresurfaces?\b|\bnew wave\b"
    r"|\bзнову\b|\bвдруге\b|\bповторн|\bнова\s+хвиля\b"
    r"|\bще\s+(?:\d+|од|дв|три|чотир|пять|кільк)",
    re.IGNORECASE,
)

# RULE E — which categories can describe the same story. The classifier's
# labels are noisy at the edges (a satellite launch filed as "exploit"), so
# the families are coarse: a vulnerability write-up and an exploitation
# report are one family, a breach and the malware behind it another. An
# uncategorized item ("other") is compatible with anything but has to bring
# a second shared headline word (`_MIN_SHARED_FOR_CORROBORATION`).
_CATEGORY_FAMILIES: dict[str, str] = {
    "vulnerability": "vuln", "exploit": "vuln", "zero-day": "vuln",
    "breach": "incident", "ransomware": "incident", "malware": "incident",
    "botnet": "incident", "spyware": "incident", "data leak": "incident",
    "phishing": "fraud", "scam": "fraud", "social engineering": "fraud",
}


def _is_labelled_digest(title: str) -> bool:
    """A headline that says outright it indexes several stories (VETO 3)."""
    return any(rx.search(title or "") for rx in _INDEX_HEADLINE_RES)


def _is_follow_up_headline(title: str) -> bool:
    return _FOLLOW_UP_RE.search(_prepare(title)) is not None


def _category_family(category: str) -> str | None:
    """The coarse family of a category, or None when it is uncategorized."""
    return _CATEGORY_FAMILIES.get((category or "").strip().lower())


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
    #: Strict proper names from the headline (`_headline_names`), the keys
    #: RULE E matches on. Defaulted for the same reason as `quantities`.
    names: frozenset[str] = frozenset()
    #: The classifier's category, for RULE E's compatibility check.
    category: str = ""
    #: The headline joins two named subjects ("X and Y"); see
    #: `_headline_names`.
    joins_subjects: bool = False
    #: Source-independence evidence (see `independent_sources`): the article
    #: URL normalised, URLs the body cites, and the outlets the body
    #: explicitly attributes the report to ("according to BleepingComputer").
    url: str = ""
    cited_urls: frozenset[str] = frozenset()
    attributed_outlets: frozenset[str] = frozenset()

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
        names, joins_subjects = _headline_names(item.title, item.raw_content or "")
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
            names=names,
            category=item.category or "",
            joins_subjects=joins_subjects,
            url=normalize_url(item.url),
            cited_urls=frozenset(
                normalize_url(u) for u in _URL_RE.findall(item.raw_content or "")
            ),
            attributed_outlets=attributed_outlets(item.raw_content or ""),
        )


@dataclass(frozen=True)
class NameStats:
    """How often, and over what stretch, a name appears in the corpus.

    `df` is document frequency: how many headlines in the batch carry the
    name, as a name or as an ordinary headline word (counting both is the
    conservative choice — a word that is a name in one headline and a plain
    word in four others is common). `first_seen`/`last_seen` bound those
    headlines in time, which is what lets RULE E tell five outlets covering
    one incident in an afternoon from one vendor in the news all week.
    """

    df: int
    first_seen: datetime
    last_seen: datetime

    @property
    def span(self) -> timedelta:
        return self.last_seen - self.first_seen


def name_statistics(features: Iterable[StoryFeatures]) -> dict[str, NameStats]:
    """Corpus statistics for RULE E, over every headline in `features`.

    Pass the result to `same_story(..., name_stats=...)`. `cluster_items`
    and `assign_incremental` compute it themselves over the batch they see.
    """
    counts: dict[str, int] = {}
    first: dict[str, datetime] = {}
    last: dict[str, datetime] = {}
    for f in features:
        when = f.published_at
        if not isinstance(when, datetime):
            continue
        for key in f.names | f.distinctive:
            counts[key] = counts.get(key, 0) + 1
            if key not in first or when < first[key]:
                first[key] = when
            if key not in last or when > last[key]:
                last[key] = when
    return {k: NameStats(df=n, first_seen=first[k], last_seen=last[k]) for k, n in counts.items()}


def _within_window(a: StoryFeatures, b: StoryFeatures, *, days: int) -> bool:
    return _within(a, b, timedelta(days=days))


def _within(a: StoryFeatures, b: StoryFeatures, limit: timedelta) -> bool:
    try:
        delta = abs(a.published_at - b.published_at)  # type: ignore[operator]
    except TypeError:  # pragma: no cover - defensive against naive/aware mix
        return False
    return bool(delta <= limit)


def _rare_name_match(
    a: StoryFeatures,
    b: StoryFeatures,
    name_stats: Mapping[str, NameStats],
) -> bool:
    """RULE E. See the module docstring; every clause below is a guard.

    Assumes the caller already applied the time window, VETO 1, VETO 2 and
    VETO 3. Symmetric in `a` and `b`.
    """
    if not _within(a, b, _RARE_NAME_WINDOW):
        return False
    if _is_roundup_headline(a.title) or _is_roundup_headline(b.title):
        return False
    if _is_follow_up_headline(a.title) or _is_follow_up_headline(b.title):
        return False

    fam_a, fam_b = _category_family(a.category), _category_family(b.category)
    if fam_a is not None and fam_b is not None and fam_a != fam_b:
        return False

    shared = a.names & b.names
    if not shared:
        return False

    corroborated = (
        len(a.distinctive & b.distinctive) >= _MIN_SHARED_FOR_CORROBORATION
    )

    def rare(name: str) -> bool:
        stats = name_stats.get(name)
        if stats is None:
            return False
        if stats.df <= _RARE_NAME_MAX_DF:
            return True
        # A heavily covered event: every mention inside one burst. Needs a
        # second shared headline word, because a vendor having a bad day
        # looks exactly like this too.
        return (
            stats.df <= _BURST_NAME_MAX_DF
            and stats.span <= _RARE_NAME_WINDOW
            and corroborated
        )

    rare_shared = {n for n in shared if rare(n)}
    if not rare_shared:
        return False

    # An uncategorized item could be anything that mentions the name — a
    # funding round, a product launch — so it has to agree on more than it.
    if (fam_a is None or fam_b is None) and not corroborated:
        return False

    # Vulnerability coverage: the name has to be the product, not just the
    # vendor. One shared name is at best the vendor, and a headline naming
    # a product the other does not is a different flaw.
    if "vuln" in (fam_a, fam_b):
        if len(shared) < 2 and not any(" " in n for n in shared):
            return False
        if (a.names - b.names) and (b.names - a.names):
            return False
        # A headline covering two advisories at once must not be matched
        # on one of them.
        if a.joins_subjects or b.joins_subjects:
            return False

    return True


# --------------------------------------------------------------------------
# Match decisions and confidence
# --------------------------------------------------------------------------

Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class MatchDecision:
    """Why one article joined (or was kept apart from) a story's anchor.

    `fingerprint` is the article being placed, `anchor` the representative
    it was compared with. `rule` names the deciding rule; `confidence` says
    how much its evidence is worth:

      high   — the evidence identifies one event: the same article text,
               identical CVE sets with headline agreement, a strong
               distinctive-headline match, a manual merge;
      medium — strong but indirect: identical CVEs with no shared wording,
               partial CVE overlap with support, the weak RULE C band, a
               shared counted quantity, a rare shared name;
      low    — related but NOT the same story: one CVE exploited against two
               different named victims, one name in two different victims'
               incidents, a follow-up announcing a new development. Low
               never merges; it is kept on the cluster as a link.
    """

    fingerprint: str
    anchor: str
    rule: str
    confidence: Confidence
    reason: str

    @property
    def merges(self) -> bool:
        return self.confidence != "low"

    def to_dict(self) -> dict[str, str]:
        return {
            "fingerprint": self.fingerprint, "anchor": self.anchor,
            "rule": self.rule, "confidence": self.confidence, "reason": self.reason,
        }


# A headline reporting a named victim's incident, as opposed to a flaw or a
# campaign: "Acme Corp hit by ransomware", "Hackers breach Globex",
# «Хакери зламали застосунок …». Deliberately narrow — "exploited in
# attacks" and "malware built to steal" describe a threat, not a victim.
_INCIDENT_HEADLINE_RE = re.compile(
    r"\b(?:breach(?:ed|es)?|hacked|hit\s+by|hits|suffers?|suffered|"
    r"disrupt(?:s|ed|ion)?|outage|victims?|attack(?:ed)?\s+on|"
    r"data\s+(?:breach|leak|theft))\b"
    r"|\bзлам|\bатакува|\bпостражда|\bзазна",
    re.IGNORECASE,
)

# A headline announcing a development of an earlier story: arrests,
# sentencing, exploitation that started later, a decryptor, a root cause.
# Together with `_FOLLOW_UP_RE` ("another", "two more", "again").
_DEVELOPMENT_RE = re.compile(
    r"\bnow\s+(?:\w+\s+){0,2}(?:exploited|under\s+attack|abused|weaponi[sz]ed)\b"
    r"|\bupdate[d]?:|\bnew\s+details\b|\bexpands?\b|\bwidens?\b"
    r"|\barrest(?:ed|s)?\b|\bcharged\b|\bindicted\b|\bsentenced\b|\bgets\s+\d+\s+(?:months|years)\b"
    r"|\bdecryptor\b|\broot\s+cause\b|\bpost-?mortem\b|\bfined\b"
    r"|\bзаарешт|\bзатрима|\bзасуди|\bвирок|\bнові\s+деталі",
    re.IGNORECASE,
)

#: A follow-up is only told apart from same-cycle coverage after this gap.
#: Outlets covering one event publish within hours; a development (the
#: patched flaw now exploited, the arrest) lands days later.
_FOLLOW_UP_MIN_GAP = timedelta(hours=36)


def _name_words(f: StoryFeatures) -> set[str]:
    return {w for n in f.names for w in n.split()}


def _names_disjoint(a: StoryFeatures, b: StoryFeatures) -> bool:
    """Both headlines name a subject and neither's names appear in the other."""
    wa, wb = _name_words(a), _name_words(b)
    return bool(wa) and bool(wb) and not (wa & (b.distinctive | wb)) and not (wb & (a.distinctive | wa))


def _is_incident_headline(title: str) -> bool:
    return _INCIDENT_HEADLINE_RE.search(_prepare(title or "")) is not None


def _different_victims(a: StoryFeatures, b: StoryFeatures) -> bool:
    """Both headlines report a victim's incident and each names a subject
    the other lacks: two incidents that share a CVE, a family or an actor."""
    return (
        _is_incident_headline(a.title) and _is_incident_headline(b.title)
        and bool(a.names - b.names) and bool(b.names - a.names)
    )


_THREAT_NOUN_RE = re.compile(
    r"^\s*(?:ransomware|gang|group|crew|hackers?|apt|malware|botnet|operators?|"
    r"affiliates?|stealer|loader|backdoor|trojan|угруповання|хакери)\b",
    re.IGNORECASE,
)


def _names_a_threat(names: Iterable[str], titles: Iterable[str]) -> bool:
    """Does a shared name stand for the attacker (a family, a gang, an
    actor) rather than the victim? True when some headline follows it with
    a threat noun: "Akira ransomware", "Qilin gang", "APT28 hackers"."""
    texts = [_prepare(t or "").lower() for t in titles]
    for name in names:
        n = name.lower()
        for text in texts:
            start = text.find(n)
            while start >= 0:
                if _THREAT_NOUN_RE.match(text[start + len(n):]):
                    return True
                start = text.find(n, start + 1)
    return False


def _cve_guard(
    a: StoryFeatures,
    b: StoryFeatures,
    decide: Callable[[str, Confidence, str], MatchDecision],
    cve_list: str,
) -> MatchDecision | None:
    if _different_victims(a, b):
        extra_a = ", ".join(sorted(a.names - b.names)[:2])
        extra_b = ", ".join(sorted(b.names - a.names)[:2])
        return decide(
            "same_cve_different_incident", "low",
            f"same CVE ({cve_list}) in two incidents with different named "
            f"subjects ({extra_a} / {extra_b}); kept as separate, linked stories",
        )
    return None


def _is_development_headline(title: str) -> bool:
    text = _prepare(title or "")
    return _DEVELOPMENT_RE.search(text) is not None or _FOLLOW_UP_RE.search(text) is not None


def _follow_up(a: StoryFeatures, b: StoryFeatures) -> bool:
    """The later article announces a development the earlier one lacked,
    and they are far enough apart for that to be a new turn of the story."""
    try:
        gap = b.published_at - a.published_at  # type: ignore[operator]
    except TypeError:  # pragma: no cover - defensive
        return False
    if not isinstance(gap, timedelta) or abs(gap) < _FOLLOW_UP_MIN_GAP:
        return False
    earlier, later = (a, b) if gap > timedelta(0) else (b, a)
    return _is_development_headline(later.title) and not _is_development_headline(earlier.title)


def _follow_up_or(a: StoryFeatures, b: StoryFeatures, decision: MatchDecision) -> MatchDecision:
    """Downgrade a positive match to a low-confidence link for a follow-up."""
    if _follow_up(a, b):
        return MatchDecision(
            decision.fingerprint, decision.anchor, "follow_up", "low",
            f"follow-up with a new development ({decision.reason}); "
            "kept as a separate, linked story",
        )
    return decision


def same_story(
    a: StoryFeatures,
    b: StoryFeatures,
    *,
    window_days: int = _WINDOW_DAYS,
    name_stats: Mapping[str, NameStats] | None = None,
) -> bool:
    """Pairwise "are these the same underlying story?" decision.

    Pure and symmetric: `same_story(a, b) == same_story(b, a)`. See the
    module docstring for the rule table and the reasoning behind each
    threshold.

    `name_stats` is the corpus document frequency RULE E needs (see
    `name_statistics`). Rarity is a property of the batch, not of the pair,
    so the caller supplies it; when it is None, RULE E is off and the
    decision is exactly what it was before RULE E existed.

    True exactly when `match_story` returns a decision that merges, i.e.
    one of high or medium confidence. A low-confidence relation (same CVE
    in another victim's incident, a follow-up development) is NOT a merge.
    """
    decision = match_story(a, b, window_days=window_days, name_stats=name_stats)
    return decision is not None and decision.merges


def match_story(
    a: StoryFeatures,
    b: StoryFeatures,
    *,
    window_days: int = _WINDOW_DAYS,
    name_stats: Mapping[str, NameStats] | None = None,
) -> MatchDecision | None:
    """The full pairwise decision: which rule fired, how confident, and why.

    None when no rule relates the two articles (or a veto separates them).
    A decision with `confidence == "low"` relates them without merging —
    see `MatchDecision`. `fingerprint` is `b`, `anchor` is `a`; every other
    field is symmetric in `a` and `b`.
    """
    def decide(rule: str, confidence: Confidence, reason: str) -> MatchDecision:
        return MatchDecision(b.fingerprint, a.fingerprint, rule, confidence, reason)

    if a.fingerprint == b.fingerprint:
        return decide("same_fingerprint", "high", "same article URL")
    if not _within_window(a, b, days=window_days):
        return None

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
        return decide("rule0_identical_body", "high",
                      "identical article body (duplicate URL or syndicated copy)")

    both_have_cves = bool(a.cves) and bool(b.cves)
    shared_cves = a.cves & b.cves

    # VETO 1 — both name CVEs and none coincide. Different advisories.
    if both_have_cves and not shared_cves:
        return None

    shared_entities = a.entities & b.entities
    title_j = _jaccard(a.distinctive, b.distinctive)
    cve_list = ", ".join(sorted(shared_cves)[:3])

    # RULE A — identical CVE sets.
    #
    # Guarded twice since the audit (see `_cve_guard`): one CVE exploited
    # against two different named victims is two incidents, and a later
    # article announcing a new development is a follow-up. Both come back
    # as a low-confidence link instead of a merge.
    if both_have_cves and a.cves == b.cves:
        guard = _cve_guard(a, b, decide, cve_list)
        if guard is not None:
            return guard
        agreement = shared_entities or (a.names & b.names) or (a.distinctive & b.distinctive)
        return _follow_up_or(a, b, decide(
            "rule_a_identical_cves",
            "high" if agreement else "medium",
            f"identical CVE set ({cve_list})"
            + ("" if agreement else "; headlines share no wording"),
        ))

    # RULE B — partial CVE overlap, but only with textual support so that a
    # multi-CVE roundup can't bridge unrelated stories.
    if both_have_cves and _jaccard(a.cves, b.cves) >= _CVE_JACCARD_MIN:
        if shared_entities and title_j >= _TITLE_JACCARD_SUPPORT:
            guard = _cve_guard(a, b, decide, cve_list)
            if guard is not None:
                return guard
            return _follow_up_or(a, b, decide(
                "rule_b_cve_overlap", "medium",
                f"overlapping CVEs ({cve_list}) with a shared entity and title "
                f"overlap {title_j:.2f}",
            ))

    # VETO 2 — same source republishing one headline, with no CVE agreement
    # to vouch for the match. Product-named advisory entries, not one story.
    if a.source == b.source and a.title.strip().lower() == b.title.strip().lower():
        return None

    # VETO 3 — a labelled digest stands for several stories. Every rule
    # below matches on headline text, and a digest's headline is made of
    # other stories' headlines. The CVE rules above already had their say.
    if _is_labelled_digest(a.title) or _is_labelled_digest(b.title):
        return None

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
    # Audit addition: both headlines name their subject and the names are
    # disjoint ("Critical flaw in Zyxel firewalls lets attackers run code" /
    # "... in SonicWall firewalls ..."). The shared words are the template,
    # the names say these are two vendors — RULE C must not fire.
    # "Disjoint" is judged word by word against the other headline's whole
    # vocabulary, so "VeloCloud Orchestrator" still meets "VeloCloud", and a
    # sentence-initial "Cisco" (not a name) still meets the name "Cisco".
    names_disjoint = _names_disjoint(a, b)
    if shared_entities and long_enough and not names_disjoint:
        shared_tokens = len(a.distinctive & b.distinctive)
        words = ", ".join(sorted(a.distinctive & b.distinctive)[:5])
        if title_j >= _TITLE_JACCARD_STRONG and shared_tokens >= _MIN_SHARED_STRONG:
            return _follow_up_or(a, b, decide(
                "rule_c_title_strong", "high",
                f"distinctive headline match {title_j:.2f} ({words})",
            ))
        if title_j >= _TITLE_JACCARD_WEAK and shared_tokens >= _MIN_SHARED_WEAK:
            return _follow_up_or(a, b, decide(
                "rule_c_title_weak", "medium",
                f"distinctive headline match {title_j:.2f} ({words})",
            ))

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
            qty = ", ".join(f"{v} {u}" for v, u in sorted(shared_quantities)[:2])
            return _follow_up_or(a, b, decide(
                "rule_d_quantity", "medium",
                f"same counted quantity ({qty}) about {', '.join(sorted(subject)[:3])}",
            ))

    # RULE E — a rare shared name within 48 hours. Off unless the caller
    # supplied corpus statistics; see `_rare_name_match`.
    if name_stats is not None and _rare_name_match(a, b, name_stats):
        names = ", ".join(sorted(a.names & b.names)[:3])
        if _different_victims(a, b) and _names_a_threat(a.names & b.names, (a.title, b.title)):
            return decide(
                "same_threat_different_victim", "low",
                f"shared name ({names}) but each headline names a different "
                "victim or subject; kept as separate, linked stories",
            )
        return _follow_up_or(a, b, decide(
            "rule_e_rare_name", "medium", f"rare shared name within 48h ({names})",
        ))

    return None


@dataclass
class StoryCluster:
    """One real-world story and every article we have about it."""

    key: str
    anchor: StoryFeatures
    members: list[StoryFeatures] = field(default_factory=list)
    #: One decision per member that joined after the anchor (high/medium,
    #: or a manual `override_merge`). The anchor itself has none.
    decisions: list[MatchDecision] = field(default_factory=list)
    #: Low-confidence relations to OTHER stories (follow-ups, the same CVE
    #: or family in another victim's incident). Never merges; a link.
    links: list[MatchDecision] = field(default_factory=list)
    #: True when a manual `split` override closed this story to joins.
    closed: bool = False

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
    overrides: "StoryOverrides | None" = None,
) -> list[StoryCluster]:
    """Group articles into stories using anchor-based greedy assignment.

    Ordering is deterministic — newest first, then fingerprint — so the same
    input always produces the same clusters and the same anchors, which is
    what makes `story_key` stable between pipeline runs.

    Each item is compared against existing cluster ANCHORS only, never
    against arbitrary members. That is what prevents transitive chaining:
    every membership decision is one direct pairwise comparison.

    RULE E's corpus statistics are computed over `items` — the whole batch
    is the "current corpus window".

    `overrides` (see `StoryOverrides`) are applied after matching: a manual
    merge joins its partner's story whatever the rules say; a split item
    starts a story of its own that no rule can join. Items themselves are
    never modified here.
    """
    feats = [StoryFeatures.from_item(i) for i in items]
    feats.sort(key=lambda f: (f.published_at, f.fingerprint), reverse=True)
    stats = name_statistics(feats)
    ov = overrides or StoryOverrides()

    clusters: list[StoryCluster] = []
    placed: dict[str, StoryCluster] = {}
    for f in feats:
        target: StoryCluster | None = None
        decision: MatchDecision | None = None
        links: list[MatchDecision] = []
        partner = next((placed[p] for p in ov.partners(f.fingerprint) if p in placed), None)
        if partner is not None:
            target = partner
            decision = MatchDecision(
                f.fingerprint, partner.anchor.fingerprint, "override_merge", "high",
                ov.reason_for(f.fingerprint)
                or next((ov.reason_for(p) for p in ov.partners(f.fingerprint)
                         if ov.reason_for(p)), "manual merge override"),
            )
        elif f.fingerprint not in ov.split:
            for cluster in clusters:
                if cluster.closed:
                    continue
                d = match_story(cluster.anchor, f, window_days=window_days, name_stats=stats)
                if d is None:
                    continue
                if d.merges:
                    target, decision = cluster, d
                    break
                links.append(d)
        if target is None:
            target = StoryCluster(
                key=story_key_for(f), anchor=f, members=[f],
                closed=f.fingerprint in ov.split,
            )
            clusters.append(target)
        else:
            target.members.append(f)
            if decision is not None:
                target.decisions.append(decision)
        target.links.extend(links)
        placed[f.fingerprint] = target
    return clusters


# --------------------------------------------------------------------------
# Source independence
# --------------------------------------------------------------------------

_URL_RE = re.compile(r"https?://[^\s<>\"'()\]]+", re.IGNORECASE)
_TRACKING_PARAM_RE = re.compile(r"^(?:utm_|fbclid|gclid|mc_|ref$|source$)", re.IGNORECASE)


def normalize_url(url: str) -> str:
    """Scheme-less, www-less, tracking-free, trailing-slash-free URL, so two
    copies of one original link compare equal."""
    text = (url or "").strip().rstrip(".,;")
    if not text:
        return ""
    text = re.sub(r"^https?://", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^www\.", "", text, flags=re.IGNORECASE)
    text = text.split("#", 1)[0]
    if "?" in text:
        base, query = text.split("?", 1)
        kept = [q for q in query.split("&") if q and not _TRACKING_PARAM_RE.match(q.split("=", 1)[0])]
        text = base + ("?" + "&".join(sorted(kept)) if kept else "")
    return text.rstrip("/").lower()


#: Outlets whose reporting other outlets relay, with the spellings they are
#: cited under. Keys are the canonical names `independent_sources` returns.
KNOWN_OUTLETS: dict[str, tuple[str, ...]] = {
    "BleepingComputer": ("bleepingcomputer", "bleeping computer"),
    "The Hacker News": ("the hacker news", "thehackernews"),
    "SecurityWeek": ("securityweek", "security week"),
    "The Record": ("the record", "therecord", "recorded future news"),
    "Krebs on Security": ("krebsonsecurity", "krebs on security", "brian krebs"),
    "The Register": ("the register",),
    "Dark Reading": ("dark reading", "darkreading"),
    "Reuters": ("reuters",),
    "Bloomberg": ("bloomberg",),
    "TechCrunch": ("techcrunch",),
    "Wired": ("wired",),
    "Ars Technica": ("ars technica",),
    "Cybernews": ("cybernews",),
    "The Verge": ("the verge",),
    "Securelist (Kaspersky)": ("securelist",),
    "dev.ua": ("dev.ua",),
    "ain.ua": ("ain.ua",),
    "itc.ua": ("itc.ua",),
    "dou.ua": ("dou.ua", "dou"),
    "Укрінформ": ("укрінформ", "ukrinform"),
}

_ATTRIBUTION_LEADS = (
    r"according\s+to(?:\s+(?:a|an|the))?(?:\s+(?:report|story|article)\s+(?:by|from|in))?",
    r"(?:as\s+)?(?:first\s+|originally\s+)?reported\s+by",
    r"(?:as\s+)?(?:first\s+|originally\s+)?reported\s+(?:in|on)",
    r"via", r"per", r"citing", r"told",
    r"повідомляє", r"повідомило", r"повідомили", r"за\s+даними", r"за\s+інформацією",
    r"пише", r"з\s+посиланням\s+на", r"як\s+повідомляє", r"передає",
)
_ATTRIBUTION_RE = re.compile(
    r"(?:" + "|".join(_ATTRIBUTION_LEADS) + r")\s+[«\"“]?(?P<rest>[^\n]{0,40})",
    re.IGNORECASE,
)


def attributed_outlets(text: str) -> frozenset[str]:
    """Known outlets the text explicitly credits with the report."""
    found: set[str] = set()
    for m in _ATTRIBUTION_RE.finditer(text or ""):
        rest = m.group("rest").lower()
        for canonical, aliases in KNOWN_OUTLETS.items():
            if any(rest.startswith(alias) for alias in aliases):
                found.add(canonical)
    return frozenset(found)


def _source_key(name: str) -> str:
    low = (name or "").strip().lower()
    for canonical, aliases in KNOWN_OUTLETS.items():
        if low == canonical.lower() or any(low.startswith(a) for a in aliases):
            return canonical
    return name


def independent_sources(cluster: StoryCluster) -> list[str]:
    """See `source_origins`; the distinct origins, oldest first."""
    out: list[str] = []
    for origin in source_origins(cluster.members).values():
        if origin not in out:
            out.append(origin)
    return out


def source_origins(members: Sequence[StoryFeatures]) -> dict[str, str]:
    """The cluster's independent ORIGINS, in first-seen order.

    Repeated reporting collapses into the origin it repeats:
      * identical article bodies (RULE 0's digest) are one report;
      * an article whose body credits another outlet ("according to
        BleepingComputer", «повідомляє dev.ua») counts as that outlet;
      * an article citing another member's URL, or two members with the
        same normalised URL, are one report;
      * one outlet reporting a story twice is one origin.
    Corroboration should count `len(independent_sources(cluster))`, never
    `len(cluster.sources)`.

    Returns `{fingerprint: origin}`, oldest member first.
    """
    members = list(members)
    parent = list(range(len(members)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    by_url = {m.url: n for n, m in enumerate(members) if m.url}
    for i, m in enumerate(members):
        for j in range(i + 1, len(members)):
            o = members[j]
            if m.body_digest and m.body_digest == o.body_digest:
                union(i, j)
            elif m.url and m.url == o.url:
                union(i, j)
        for cited in m.cited_urls:
            hit = by_url.get(cited)
            if hit is not None and hit != i:
                union(i, hit)

    # Order members oldest-first: the earliest copy is the origin's face.
    def when(n: int) -> float:
        p = members[n].published_at
        return p.timestamp() if isinstance(p, datetime) else 0.0

    oldest_first = sorted(range(len(members)), key=lambda k: (when(k), k))
    origin_of_group: dict[int, str] = {}
    credited_of_group: dict[int, str] = {}
    for n in oldest_first:
        root, m = find(n), members[n]
        origin_of_group.setdefault(root, _source_key(m.source))
        credited = sorted(o for o in m.attributed_outlets if o != _source_key(m.source))
        if credited:
            # An explicit attribution beats "whoever we saw first".
            credited_of_group.setdefault(root, credited[0])
    origin_of_group.update(credited_of_group)

    return {members[n].fingerprint: origin_of_group[find(n)] for n in oldest_first}


# --------------------------------------------------------------------------
# Manual corrections
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class StoryOverrides:
    """Editor corrections to clustering, applied after matching.

      split — fingerprints that must stand as stories of their own;
      merge — pairs (a, b) that must be one story: b joins a's story.

    A manual merge outranks a split (split X + merge X,Y puts X with Y and
    nothing else). Overrides never touch the stored articles or their source
    metadata; they only change which story an article is grouped into.
    File format and CLI: `docs/intel/STORIES_AND_EVIDENCE.md`.
    """

    split: frozenset[str] = frozenset()
    merge: tuple[tuple[str, str], ...] = ()
    reasons: Mapping[str, str] = field(default_factory=dict)

    def partners(self, fingerprint: str) -> list[str]:
        """Every fingerprint manually merged with this one (transitively)."""
        group = {fingerprint}
        changed = True
        while changed:
            changed = False
            for a, b in self.merge:
                if (a in group) != (b in group):
                    group |= {a, b}
                    changed = True
        group.discard(fingerprint)
        return sorted(group)

    def reason_for(self, fingerprint: str) -> str:
        return str(self.reasons.get(fingerprint, ""))

    def __bool__(self) -> bool:
        return bool(self.split or self.merge)


def load_story_overrides(path: "str | os.PathLike[str]") -> StoryOverrides:
    """Read `data/stories/overrides.json`; a missing or broken file is empty."""
    import json
    from pathlib import Path

    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return StoryOverrides()
    if not isinstance(raw, dict):
        return StoryOverrides()
    split: set[str] = set()
    merge: list[tuple[str, str]] = []
    reasons: dict[str, str] = {}
    for entry in raw.get("split") or []:
        if isinstance(entry, dict) and entry.get("fingerprint"):
            fp = str(entry["fingerprint"])
            split.add(fp)
            reasons[fp] = str(entry.get("reason") or "manual split override")
    for entry in raw.get("merge") or []:
        fps = entry.get("fingerprints") if isinstance(entry, dict) else None
        if isinstance(fps, list) and len(fps) == 2 and all(fps):
            a, b = str(fps[0]), str(fps[1])
            merge.append((a, b))
            reason = str(entry.get("reason") or "manual merge override")
            reasons.setdefault(a, reason)
            reasons.setdefault(b, reason)
    return StoryOverrides(split=frozenset(split), merge=tuple(merge), reasons=reasons)


def apply_story_overrides(
    items: Sequence[NewsItem], overrides: StoryOverrides,
) -> list[MatchDecision]:
    """Correct STORED grouping in memory (read time) — nothing is written.

    Split X: X gets a story key of its own and `duplicate_of = ""`; if X was
    its story's canonical, the remaining members get a new canonical. Merge
    (a, b): b moves into a's story and points at its canonical; b's old story
    gets a new canonical if b was it. Returns one decision per change.
    """
    if not overrides:
        return []
    by_fp = {i.fingerprint: i for i in items}

    def members(key: str) -> list[NewsItem]:
        return [i for i in items if (i.story_key or f"fp:{i.fingerprint}") == key]

    def recanonicalize(key: str) -> None:
        group = members(key)
        if not group:
            return
        current = [i for i in group if not i.duplicate_of]
        canon = current[0] if len(current) == 1 else choose_canonical(group)
        for i in group:
            i.duplicate_of = "" if i is canon else canon.fingerprint

    changes: list[MatchDecision] = []
    for fp in sorted(overrides.split):
        item = by_fp.get(fp)
        if item is None:
            continue
        old_key = item.story_key or f"fp:{fp}"
        if len(members(old_key)) <= 1:
            continue
        item.story_key = "s:" + hashlib.sha256(f"split:{fp}".encode("utf-8")).hexdigest()[:14]
        item.duplicate_of = ""
        recanonicalize(old_key)
        changes.append(MatchDecision(fp, fp, "override_split", "high",
                                     overrides.reason_for(fp) or "manual split override"))
    for a_fp, b_fp in overrides.merge:
        a, b = by_fp.get(a_fp), by_fp.get(b_fp)
        if a is None or b is None:
            continue
        a_key = a.story_key or f"fp:{a_fp}"
        b_key = b.story_key or f"fp:{b_fp}"
        if a_key == b_key:
            continue
        b.story_key = a_key if a.story_key else story_key_for(StoryFeatures.from_item(a))
        if not a.story_key:
            a.story_key = b.story_key
        b.duplicate_of = "x"  # force re-pointing below
        recanonicalize(b.story_key)
        recanonicalize(b_key)
        changes.append(MatchDecision(b_fp, a_fp, "override_merge", "high",
                                     overrides.reason_for(b_fp) or "manual merge override"))
    return changes


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
    overrides: StoryOverrides | None = None,
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
    clusters = cluster_items(items, window_days=window_days, overrides=overrides)
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
    overrides: StoryOverrides | None = None,
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

    RULE E's corpus statistics cover the store plus the arriving batch:
    rarity is judged against everything the reader could be shown.

    `overrides`: a new item under a manual split starts its own story; one
    manually merged with a stored or earlier batch item joins that item's
    story. A stored item under a split is not used as a story's anchor.
    """
    ov = overrides or StoryOverrides()
    # Group what we already have by story, so each known story is
    # represented by exactly one article for matching purposes.
    groups: dict[str, list[NewsItem]] = {}
    key_of: dict[str, str] = {}
    for item in known_items:
        key = item.story_key or f"fp:{item.fingerprint}"
        key_of[item.fingerprint] = key
        if item.fingerprint in ov.split:
            continue
        groups.setdefault(key, []).append(item)

    known_feats = {i.fingerprint: StoryFeatures.from_item(i) for i in known_items}
    new_feats = {i.fingerprint: StoryFeatures.from_item(i) for i in new_items}
    stats = name_statistics({**known_feats, **new_feats}.values())

    known_anchors: list[tuple[str, StoryFeatures]] = []
    for key, members in groups.items():
        canonical = choose_canonical(members)
        known_anchors.append((key, known_feats[canonical.fingerprint]))

    # Newest first so the batch's own anchors are chosen the same way
    # `cluster_items` would choose them.
    ordered = sorted(new_items, key=lambda i: (i.published_at, i.fingerprint), reverse=True)

    batch_anchors: list[tuple[str, StoryFeatures, NewsItem]] = []
    duplicates: list[NewsItem] = []

    for item in ordered:
        feats = new_feats[item.fingerprint]

        # 0. Manual corrections outrank every rule.
        partner_key = next(
            (key_of[p] for p in ov.partners(item.fingerprint) if p in key_of), None,
        )
        if partner_key is not None:
            partner_group = groups.setdefault(partner_key, [])
            partner_canon = choose_canonical(partner_group) if partner_group else None
            item.story_key = partner_key
            item.duplicate_of = partner_canon.fingerprint if partner_canon is not None else ""
            partner_group.append(item)
            key_of[item.fingerprint] = partner_key
            if partner_canon is not None:
                duplicates.append(item)
            continue
        if item.fingerprint in ov.split:
            item.story_key = story_key_for(feats)
            item.duplicate_of = ""
            key_of[item.fingerprint] = item.story_key
            continue

        # 1. Does it belong to a story we already know about? If so it is
        #    later coverage of something we have already handled.
        for key, anchor in known_anchors:
            if same_story(anchor, feats, window_days=window_days, name_stats=stats):
                item.story_key = key
                item.duplicate_of = choose_canonical(groups[key]).fingerprint
                groups[key].append(item)
                key_of[item.fingerprint] = key
                duplicates.append(item)
                break
        else:
            # 2. Does it belong to a story earlier in this same batch?
            for key, anchor, anchor_item in batch_anchors:
                if same_story(anchor, feats, window_days=window_days, name_stats=stats):
                    item.story_key = key
                    item.duplicate_of = anchor_item.fingerprint
                    key_of[item.fingerprint] = key
                    groups.setdefault(key, []).append(item)
                    duplicates.append(item)
                    break
            else:
                # 3. New story.
                item.story_key = story_key_for(feats)
                item.duplicate_of = ""
                key_of[item.fingerprint] = item.story_key
                groups.setdefault(item.story_key, []).append(item)
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
    "KNOWN_OUTLETS",
    "MatchDecision",
    "StoryOverrides",
    "apply_story_overrides",
    "attributed_outlets",
    "independent_sources",
    "load_story_overrides",
    "match_story",
    "normalize_url",
    "source_origins",
    "NameStats",
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
    "name_statistics",
]
