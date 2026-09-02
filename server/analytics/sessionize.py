"""Turn parsed log records into pageviews, visitors and sessions.

This is the module where "log lines" become "people reading articles", and it
is therefore the module where the report is most easily made to lie. Three
decisions carry that weight and each one is spelled out below, in code and in
comment, with the direction of the error it can still produce:

* a **pageview allowlist**, because the site has exactly two page shapes and a
  denylist can never enumerate the junk;
* **prefetch exclusion**, because the language switcher fires a mirror prefetch
  for every real pageview and counting it drives the EN/UA split to 50/50 by
  construction;
* **cookieless identity**, a salted daily hash of the coarse network address
  plus the UA, which is deliberately unavailable on legacy-format lines because
  those record Cloudflare edge IPs and an edge IP identifies Cloudflare rather
  than a person.

Everything here streams. `iter_events` is a generator over records, and the only
structure that grows with the input is the per-visitor pageview grouping inside
`sessionize`, which holds pageviews (a few hundred a day) and never assets.

SCOPE: reads only cyberalertx's own dedicated log plus the shared legacy
archive, filtered to the cyberalertx vhost. The three other vhosts on this
box keep writing to /var/log/nginx/access.log untouched, and nothing here
writes to any log file, ever.

PRIVACY: nothing leaves the box. No network calls at runtime, no third-party
analytics, no dependency outside the stdlib. Raw IPs are never persisted or
printed — only salted hashes, with the salt rotated daily and retained 14 days.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import secrets
import tempfile
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field, fields as dataclass_fields, replace
from datetime import date, datetime, timedelta, tzinfo
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import parse_qsl

from . import (
    DEFAULT_SALT_PATH,
    SALT_RETENTION_DAYS,
    SALT_ROTATION_HOUR,
    SESSION_GAP_MINUTES,
    SITE_HOSTS,
)
from .bots import (
    BEHAVIOURAL_RULE,
    SUSPECTED_AUTOMATION,
    Verdict,
    classify,
    corroborates_scraper,
    is_scanner_path,
)
from .logread import LEGACY, LogRecord, referer_host
from .useragent import Agent, UNKNOWN_AGENT, parse_user_agent, primary_language, primary_region

logger = logging.getLogger("analytics.sessionize")


# ---------------------------------------------------------------------------
# Page classification — an ALLOWLIST, not a denylist
# ---------------------------------------------------------------------------
# The site renders exactly two page shapes: a locale home and a locale article.
# Anything else is infrastructure, a redirect, or a probe. A denylist would have
# to enumerate every junk path ever invented, and every new scanner path would
# silently be counted as a pageview — which is precisely how a log analyser ends
# up reporting thousands of daily "visitors" on a site with a few hundred.
#
# The 16-hex constraint mirrors FINGERPRINT_RE in
# frontend/app/[locale]/threat/[id]/page.tsx:35. An id of any other shape cannot
# address a real article, so /en/threat/wp-admin is a 404 probe, not content.
#
# FAILURE MODE: a genuinely new page shape (say /en/about) counts as "other"
# until someone adds it here. That is the intended direction of the error —
# under-counting a new route is recoverable, silently counting scanner noise as
# audience is not.
_HOME_RE = re.compile(r"^/(en|ua)/?$")
_ARTICLE_RE = re.compile(r"^/(en|ua)/threat/([0-9a-f]{16})/?$")
_FEED_RE = re.compile(r"^/(en|ua)/feed\.xml$")

# Locale prefix of any path, including the retired /uk which next.config.ts
# 301-redirects to /ua. Old bookmarks and inbound links still hit it, and that
# volume is a genuine measurement of surviving external links.
_LOCALE_RE = re.compile(r"^/(en|ua|uk)(?:/|$)")

# The denylist survives — NOT as a pageview filter (the allowlist does that job)
# but as a classifier for the discarded traffic, so the ledger can explain every
# dropped line instead of silently swallowing it.
_ASSET_RE = re.compile(
    r"^/(?:_next/static/|_next/image|_next/data/|_next/webpack-hmr|brand/)"
    r"|^/favicon\.ico$"
    r"|^/apple-touch-icon"
    r"|\.map$"
)
_METADATA_RE = re.compile(
    r"^/(?:robots\.txt|sitemap[^/]*\.xml|manifest\.webmanifest|sw\.js|"
    r"browserconfig\.xml|\.well-known/)"
)
_API_RE = re.compile(r"^/(?:api/|socket\.io)")
_APP_OTHER_RE = re.compile(r"^/(?:posts|admin|feedback)(?:/|$)")

# /_next/data/* is the Pages Router data route. This is an App Router site, so it
# can never legitimately appear; /_next/webpack-hmr is dev-server only. Both are
# kept as defensive no-ops, and a non-zero count of either is a FINDING (a stale
# build or a dev server exposed to the internet), not routine traffic.
PAGE_KINDS: tuple[str, ...] = (
    "home",
    "article",
    "feed",
    "asset",
    "api",
    "redirect",
    "probe",
    "metadata",
    "other",
)

NAV_KINDS: tuple[str, ...] = ("hard", "soft", "prefetch", "unknown", "none")

CHANNELS: tuple[str, ...] = (
    "campaign",
    "telegram",
    "search",
    "social",
    "rss",
    "referral",
    "internal",
    "direct",
)

# Acquisition host tables. Exact host or dotted-suffix match, so "evil-t.me" does
# not read as Telegram, while "web.telegram.org" does.
TELEGRAM_HOSTS: frozenset[str] = frozenset(
    {"t.me", "telegram.me", "telegram.org", "web.telegram.org", "desktop.telegram.org"}
)
SOCIAL_HOSTS: frozenset[str] = frozenset(
    {
        "x.com",
        "twitter.com",
        "t.co",
        "linkedin.com",
        "lnkd.in",
        "facebook.com",
        "m.facebook.com",
        "reddit.com",
        "news.ycombinator.com",
        "mastodon.social",
        "bsky.app",
    }
)
RSS_HOSTS: frozenset[str] = frozenset(
    {"feedly.com", "inoreader.com", "newsblur.com", "theoldreader.com", "feedbin.com"}
)
# Search engines are matched as a dotted token anywhere in the host, because the
# regional domains are unbounded: google.com.ua, www.google.de, cse.google.com …
# FAILURE MODE: a host like "google.com.phish.example" reads as search. It is a
# referrer string, not a security boundary, and the mislabel costs one row.
SEARCH_TOKENS: tuple[str, ...] = (
    "google.",
    "bing.",
    "duckduckgo.",
    "yandex.",
    "search.brave.",
    "ecosia.",
    "startpage.",
    "search.marginalia.",
    "mojeek.",
    "qwant.",
)

_UTM_KEYS: frozenset[str] = frozenset({"utm_source", "utm_medium", "utm_campaign"})

# How long after a "/" -> "/en" redirect a pageview is still considered to be the
# redirect's landing. Two seconds is generous for a 307 followed by a fetch on
# the same connection and tight enough that two different people behind one
# Cloudflare edge IP rarely collide.
_ASSIGNED_LOCALE_WINDOW_SECONDS = 10.0
_ASSIGNED_LOCALE_MAX_TRACKED = 4096

# Pageviews per session kept in the path/article tuples. A session that read 200
# pages is already an outlier; the cap bounds memory on a scraper that slipped
# through the classifier without distorting any count (pageviews is a counter,
# not len(paths)).
_SESSION_PATH_CAP = 200


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Event:
    """One enriched, classified request — the unit everything downstream counts."""

    record: LogRecord
    agent: Agent
    verdict: Verdict
    local_ts: datetime          # converted into the reporting tz, once, here
    date: str                   # "YYYY-MM-DD" in the reporting tz
    hour: int                   # 0-23 local
    weekday: int                # 0=Mon .. 6=Sun
    locale: str | None          # "en" | "ua" | "uk" | None
    locale_assigned: bool       # True when arrived via the / -> /en middleware redirect
    page_kind: str
    article_id: str | None      # 16-hex fingerprint when page_kind == "article"
    nav: str                    # "hard" | "soft" | "prefetch" | "unknown" | "none"
    is_pageview: bool
    referer_host: str | None
    channel: str
    campaign: str | None        # utm_campaign when channel == "campaign"
    language: str | None        # primary Accept-Language subtag
    language_region: str | None
    country: str | None         # cf_country, "XX"/"T1" preserved
    visitor: str | None         # salted hash; None when identity is unavailable
    fmt: str                    # EXTENDED | LEGACY, hoisted for convenience
    # Run-local grouping key for the user-agent, used by `demote_automation`
    # and by nothing else. Defaulted because `__main__._build` constructs this
    # class from a filtered dict of stored columns, and a defaultless new field
    # would make every rehydrated row raise. Never printed, never persisted.
    ua_key: str | None = None


@dataclass(frozen=True, slots=True)
class Session:
    """A run of pageviews by one visitor with no gap longer than the timeout."""

    visitor: str
    started: datetime           # local tz
    ended: datetime
    pageviews: int
    entry_path: str
    entry_locale: str | None
    entry_kind: str
    channel: str
    campaign: str | None
    country: str | None
    language: str | None
    agent: Agent
    locales: frozenset[str]
    paths: tuple[str, ...]      # in order, capped at 200 to bound memory
    articles: tuple[str, ...]
    is_bounce: bool             # exactly one pageview
    duration_seconds: float     # last - first pageview; 0.0 for a bounce
    saw_rsc: bool
    fmt: str


@dataclass
class Ledger:
    """The composition audit: how N raw lines became M human pageviews.

    Printed FIRST in every report, because it licenses everything below it. The
    buckets are mutually exclusive by construction — `iter_events` assigns each
    record to exactly one — so `steps()` sums to `total_lines` and a reader can
    check the arithmetic by eye. `hard` and `soft` are a breakdown OF
    `human_pageviews`, not another deduction, and are printed as an annotation.
    """

    total_lines: int = 0
    blank: int = 0
    unparseable: int = 0
    malformed: int = 0
    other_vhost: int = 0
    out_of_range: int = 0
    direct_origin: int = 0
    forged_crawlers: int = 0
    health_probes: int = 0
    scanners: int = 0
    bots: int = 0
    agents_self: int = 0
    agents_reach: int = 0
    agents_feed: int = 0
    assets: int = 0
    api: int = 0
    feeds: int = 0
    redirects: int = 0
    prefetch: int = 0
    non_2xx: int = 0
    other_paths: int = 0
    # Subtracted by the whole-window behavioural pass, AFTER every per-request
    # rule above has had its say. It is a deduction like the rest and is taken
    # OUT of human_pageviews (plus that identity's other human-classified
    # requests), never added beside it, so the rows still sum to total_lines.
    suspected_automation: int = 0
    human_pageviews: int = 0
    hard: int = 0
    soft: int = 0

    def steps(self) -> list[tuple[str, int, float | None]]:
        """Ordered (label, count, share-of-total) rows for the renderer.

        The final row is 'human pageviews'. Rows sum to `total_lines`; the
        renderer prints the total separately as the opening line. Share is None
        when there is nothing to take a share of, never 0.0 — a percentage of an
        empty denominator is not zero, it is undefined.
        """
        total = self.total_lines
        rows: list[tuple[str, int, float | None]] = []
        ordered: tuple[tuple[str, int], ...] = (
            ("blank lines", self.blank),
            ("unparseable lines", self.unparseable),
            ("malformed requests", self.malformed),
            ("other vhosts", self.other_vhost),
            ("outside the reporting window", self.out_of_range),
            ("direct-to-origin (never traversed Cloudflare)", self.direct_origin),
            ("forged crawlers (claimed a crawler, wasn't)", self.forged_crawlers),
            ("scanners & probes", self.scanners),
            ("health checks", self.health_probes),
            ("declared bots", self.bots),
            ("agents: own publishing (Telegram fetch)", self.agents_self),
            ("agents: link unfurlers (reach)", self.agents_reach),
            ("agents: feed readers", self.agents_feed),
            ("static assets", self.assets),
            ("site metadata & API", self.api),
            ("feeds", self.feeds),
            ("redirects", self.redirects),
            ("RSC prefetch (locale switcher)", self.prefetch),
            ("non-2xx page requests", self.non_2xx),
            ("other paths", self.other_paths),
            ("suspected automation (behavioural)", self.suspected_automation),
            ("human pageviews", self.human_pageviews),
        )
        for label, count in ordered:
            rows.append((label, count, (count / total) if total else None))
        return rows

    def accounted(self) -> int:
        """Sum of every bucket — must equal `total_lines`; used by the tests."""
        return sum(count for _label, count, _share in self.steps())


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------
def classify_page(path: str) -> tuple[str, str | None, str | None]:
    """Return (page_kind, locale, article_id) for a request path.

    Allowlist first, so a page can only be a page if it matches one of the two
    real shapes. Everything after that exists to label the discarded traffic.
    """
    if not path:
        # A malformed request field leaves path empty; it is a probe, never a page.
        return "probe", None, None

    article = _ARTICLE_RE.match(path)
    if article is not None:
        return "article", article.group(1), article.group(2)

    home = _HOME_RE.match(path)
    if home is not None:
        return "home", home.group(1), None

    feed = _FEED_RE.match(path)
    if feed is not None:
        # Feed polling is 50-100 requests/day per subscriber. Counted in its own
        # section as SUBSCRIBERS, never as visits — otherwise Feedly is the
        # site's top "reader" and the real audience disappears under it.
        return "feed", feed.group(1), None

    locale_match = _LOCALE_RE.match(path)
    locale = locale_match.group(1) if locale_match is not None else None

    if path == "/" or locale == "uk":
        # "/" is a 307 to /en (middleware.ts) and /uk/* is a 301 to /ua
        # (next.config.ts). Both are counted, neither is a pageview: the landing
        # produces its own 200 line, and counting the redirect too double-counts
        # every arrival on the bare domain.
        return "redirect", locale, None
    if _ASSET_RE.search(path):
        return "asset", locale, None
    if _METADATA_RE.match(path):
        return "metadata", locale, None
    if _API_RE.match(path):
        return "api", locale, None
    if path == "/healthz" or is_scanner_path(path):
        return "probe", locale, None
    if _APP_OTHER_RE.match(path):
        return "other", locale, None
    return "other", locale, None


def classify_nav(record: LogRecord) -> str:
    """Return the navigation kind: hard | soft | prefetch | unknown | none.

    App Router traffic comes in three shapes and naive counting fails in both
    directions. Drop every RSC request and a session that lands on /en, toggles
    to /ua and reads two articles counts as ONE pageview. Keep every RSC request
    and the LanguageSwitcher's viewport prefetch manufactures a mirror pageview
    for every real one, inverting the locale conclusion — which is the single
    most valuable number in this report.

    FAILURE MODE (unfixable, footnoted, never corrected): back/forward and
    re-visits inside the Router Cache emit no request at all, and a click on a
    link whose prefetch already landed may emit nothing either. Locale switching
    is therefore systematically UNDER-measured. No correction multiplier is
    applied anywhere — that would be inventing data.
    """
    if record.method != "GET":
        return "none"
    if record.fmt == LEGACY:
        # The combined format carries no Next-Router-Prefetch / Sec-Purpose
        # header, so a prefetch is indistinguishable from a real soft navigation.
        # Legacy pageviews are hard navigations only (see is_pageview) and the
        # nav kind is honestly "unknown" rather than a guess.
        return "unknown"
    if record.prefetch or (record.sec_purpose or "").strip().lower() == "prefetch":
        return "prefetch"
    if record.rsc:
        return "soft"
    dest = (record.sec_fetch_dest or "").strip().lower()
    if dest and dest not in ("document", "empty", "iframe"):
        # script/style/image/font: a subresource, not a navigation.
        return "none"
    return "hard"


def is_pageview(record: LogRecord, *, page_kind: str, nav: str) -> bool:
    """Mechanical page-ness: conditions 1-4 of the five-part pageview test.

    1. GET only — HEAD and OPTIONS are monitors and probes, never readers.
    2. status in (200, 304) — every 3xx has a successor line that IS counted,
       and 4xx/5xx never rendered anything.
    3. page_kind in ("home", "article").
    4. nav != "prefetch".

    Condition 5 — `verdict.klass == "human"` — is applied by `enrich`, which is
    where the verdict is in scope. Callers wanting the bot-inclusive count use
    `counts_as_pageview`.
    """
    if record.method != "GET":
        return False
    if record.status not in (200, 304):
        return False
    if page_kind not in ("home", "article"):
        return False
    if nav == "prefetch":
        return False
    if record.fmt == LEGACY and record.rsc:
        # C.7: a legacy line with ?_rsc= could be a real soft navigation or the
        # locale switcher's prefetch, and nothing in the line distinguishes them.
        # Counting them would reintroduce the EN/UA symmetry trap, so legacy
        # pageviews are hard navigations only — a documented LOWER BOUND.
        return False
    return True


def counts_as_pageview(event: Event, *, include_bots: bool = False) -> bool:
    """Whether an event counts as a pageview for the current report mode.

    `Event.is_pageview` is always the human-only answer, so the audience numbers
    cannot be inflated by a flag. `--include-bots` re-runs the mechanical test
    and adds the non-human page requests on top, for the diagnostic view only.
    """
    if event.is_pageview:
        return True
    if not include_bots:
        return False
    return is_pageview(event.record, page_kind=event.page_kind, nav=event.nav)


def classify_channel(referer: str | None, query: str) -> tuple[str, str | None]:
    """Return (channel, campaign) for an entry request, in strict priority order.

    The order matters more than any individual rule: a UTM-tagged Telegram link
    must read as `campaign`, not `telegram`, or the instrumentation can never be
    evaluated against the un-tagged baseline.

    `internal` is a real bucket and is excluded from acquisition entirely. A
    naive script counts a same-site referer as "referral" and then proudly
    reports that the site's top referrer is the site.
    """
    if query:
        try:
            params = dict(parse_qsl(query, keep_blank_values=False))
        except (ValueError, UnicodeDecodeError):  # pragma: no cover - defensive
            params = {}
        if _UTM_KEYS & params.keys():
            return "campaign", params.get("utm_campaign") or params.get("utm_source")

    host = referer_host(referer)
    if not host:
        # True direct traffic, in-app browsers that strip the header, privacy
        # extensions, and this site's own strict-origin-when-cross-origin policy
        # all land here. It is ALWAYS rendered "direct / unattributed" so nobody
        # reads it as "people typed the URL".
        return "direct", None

    if host in SITE_HOSTS:
        return "internal", None
    if _host_matches(host, TELEGRAM_HOSTS):
        return "telegram", None
    if any(token in host for token in SEARCH_TOKENS):
        return "search", None
    if _host_matches(host, SOCIAL_HOSTS):
        return "social", None
    if _host_matches(host, RSS_HOSTS):
        return "rss", None
    return "referral", None


def _host_matches(host: str, table: frozenset[str]) -> bool:
    """Exact host or dotted-suffix match against a host table."""
    if host in table:
        return True
    return any(host.endswith("." + known) for known in table)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------
def ip_key(ip: str | None) -> str:
    """Coarsen an address for hashing: IPv4 keeps the full /32, IPv6 the /64.

    RFC 4941 privacy extensions rotate the low 64 bits of an IPv6 address, often
    daily and sometimes hourly, so hashing the full /128 splits one person into
    several. The /64 is the subscriber network and is stable.

    FAILURE MODES, with direction:
      * carrier-grade NAT (Kyivstar, Vodafone UA, lifecell) puts hundreds of
        subscribers behind one IPv4 — an UNDERCOUNT, and on this mobile-heavy
        Ukrainian audience it is the dominant error. True uniques are HIGHER
        than reported.
      * shared office / university / VPN egress — undercount, unfixable.
      * a /64 shared by a household — undercount, small.
    """
    if not ip:
        return ""
    try:
        parsed = ip_address(ip.strip())
    except ValueError:
        return ""
    if parsed.version == 6:
        packed = parsed.packed[:8]
        return packed.hex()
    return parsed.compressed


def visitor_id(record: LogRecord, *, salt: str) -> str | None:
    """Salted daily visitor hash, or None when identity is not measurable.

    None on every legacy-format record. `$remote_addr` in the shared combined
    log is the CLOUDFLARE EDGE IP: one measured day put 121 human pageviews
    behind 99 distinct edge addresses, so "unique visitors" computed from it
    would be a count of Cloudflare's fleet. Suppressed, never estimated.

    Accept-Language joins the hash because it is free and separates two people
    behind one NAT who read in different languages. A person switching browser
    language mid-session splits into two visitors; rare enough to accept.
    """
    if not record.ip_is_visitor:
        return None
    key = ip_key(record.client_ip)
    if not key:
        return None
    digest = hashlib.blake2b(
        b"\x00".join(
            (
                salt.encode("utf-8"),
                key.encode("utf-8"),
                (record.user_agent or "").encode("utf-8", "replace"),
                (record.accept_language or "").encode("utf-8", "replace"),
            )
        ),
        digest_size=8,
    )
    return digest.hexdigest()


def _identity_key(record: LogRecord, salt: str) -> str:
    """A transient, in-memory correlation key that works on BOTH formats.

    Used only to pair a `/` -> `/en` redirect with the pageview that follows it.
    On legacy lines the address is a Cloudflare edge IP, so this key is coarse
    and can pair two different people who share an edge and a UA within ten
    seconds — an over-attribution of `locale_assigned`, bounded by the window
    and by consuming each redirect exactly once. Never persisted, never printed.
    """
    digest = hashlib.blake2b(
        b"\x00".join(
            (
                salt.encode("utf-8"),
                ip_key(record.peer_ip or record.client_ip).encode("utf-8"),
                (record.user_agent or "").encode("utf-8", "replace"),
            )
        ),
        digest_size=8,
    )
    return digest.hexdigest()


class SaltProvider:
    """Per-day visitor-id salts, persisted so a re-run yields identical numbers.

    The salt file is a re-identification key: with it and a log, any address can
    be re-hashed and looked up. It is therefore written 0600, kept in gitignored
    `data/`, and pruned at `retention_days` so it cannot outlive the logs it
    could re-key.

    The analytics day starts at `rotation_hour` local (04:00), not midnight.
    Rotating the salt forces a session split at the boundary, so the cut belongs
    in the traffic trough. Do NOT "fix" this by splitting sessions at midnight —
    midnight splitting is a daily-batch artefact that manufactures a 00:00
    session spike and a matching crop of fake bounces.
    """

    def __init__(
        self,
        path: Path = DEFAULT_SALT_PATH,
        *,
        retention_days: int = SALT_RETENTION_DAYS,
        rotation_hour: int = SALT_ROTATION_HOUR,
        window_days: int = 1,
    ) -> None:
        self._path = Path(path)
        self._retention_days = int(retention_days)
        self._rotation_hour = int(rotation_hour)
        # window_days > 1 is the `--rolling-salt N` escape hatch. It buys
        # cross-day identity at the cost of a longer-lived re-identification key,
        # and it is NEVER enabled silently: the CLI prints that it is on and the
        # report labels the affected numbers.
        self._window_days = max(1, int(window_days))
        self._salts: dict[str, str] = {}
        self._dirty = False
        self._load()

    # -- persistence -------------------------------------------------------
    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            # A corrupt salt file must not stop a report. Starting empty mints
            # fresh salts, which renumbers visitors for the affected days; that
            # is a visible discontinuity, not a wrong number.
            logger.warning("Unreadable salt file %s (%s) — starting empty.", self._path, exc)
            return
        salts = payload.get("salts") if isinstance(payload, dict) else None
        if isinstance(salts, dict):
            self._salts = {str(k): str(v) for k, v in salts.items() if isinstance(v, str)}

    def save(self) -> None:
        """Atomic write (tempfile in the same dir + os.replace), mode 0600."""
        if not self._dirty:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "salts": dict(sorted(self._salts.items()))}
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(self._path.parent),
            prefix=self._path.name + ".",
            suffix=".tmp",
            delete=False,
        )
        try:
            with handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.chmod(handle.name, 0o600)
            os.replace(handle.name, self._path)
        except OSError:
            with contextlib.suppress(OSError):
                os.unlink(handle.name)
            raise
        else:
            self._dirty = False
        # The mode is re-applied after replace: an existing file keeps its own
        # permissions through os.replace on some filesystems.
        try:
            os.chmod(self._path, 0o600)
        except OSError:  # pragma: no cover - defensive
            logger.warning("Could not chmod 0600 %s", self._path)

    # -- salts -------------------------------------------------------------
    def day_key(self, moment: datetime) -> str:
        """The analytics-day key for an instant: the day that STARTED at 04:00."""
        shifted = moment - timedelta(hours=self._rotation_hour)
        day = shifted.date()
        if self._window_days > 1:
            ordinal = day.toordinal()
            day = day.fromordinal(ordinal - (ordinal % self._window_days))
        return day.isoformat()

    def salt_for(self, moment: datetime) -> str:
        """The salt for the analytics day containing `moment`, minting if needed."""
        key = self.day_key(moment)
        salt = self._salts.get(key)
        if salt is None:
            salt = secrets.token_hex(16)
            self._salts[key] = salt
            self._dirty = True
            # Persist immediately: a report that crashes after minting must not
            # renumber every visitor on the next run.
            self.save()
        return salt

    def prune(self) -> int:
        """Drop salts older than retention_days. Returns the number removed."""
        if not self._salts:
            return 0
        newest = max(self._salts)
        cutoff = date.fromisoformat(newest) - timedelta(days=self._retention_days)
        stale = [key for key in self._salts if date.fromisoformat(key) < cutoff]
        for key in stale:
            del self._salts[key]
        if stale:
            self._dirty = True
            self.save()
        return len(stale)


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------
def enrich(
    record: LogRecord,
    *,
    tz: tzinfo,
    salt: str,
    hard_only: bool = False,
    agent: Agent | None = None,
    verdict: Verdict | None = None,
) -> Event:
    """Convert one LogRecord into an Event. Never raises.

    The timestamp is converted into the reporting timezone exactly ONCE, here,
    and everything downstream buckets on the converted value. A report built in
    UTC for a UTC+3 audience shifts the daily peak three hours and every
    recommendation derived from it is wrong.
    """
    local_ts = record.ts.astimezone(tz)
    if agent is None:
        agent = parse_user_agent(
            record.user_agent,
            ch_platform=record.ch_platform,
            ch_platform_version=record.ch_platform_version,
            ch_mobile=record.ch_mobile,
            ch_model=record.ch_model,
            ch_available=record.ch_available,
        )
    if verdict is None:
        verdict = classify(record, agent=agent)

    page_kind, locale, article_id = classify_page(record.path)
    nav = classify_nav(record)
    pageview = is_pageview(record, page_kind=page_kind, nav=nav) and verdict.klass == "human"
    if pageview and hard_only and nav == "soft":
        # --hard-only reproduces the naive document-only number for
        # cross-checking. A sharp divergence between the two counts is itself
        # informative: it measures how much reading happens after the first
        # paint, which no document-only analyser can see.
        pageview = False

    channel, campaign = classify_channel(record.referer, record.query)

    return Event(
        record=record,
        agent=agent if agent is not None else UNKNOWN_AGENT,
        verdict=verdict,
        local_ts=local_ts,
        date=local_ts.date().isoformat(),
        hour=local_ts.hour,
        weekday=local_ts.weekday(),
        locale=locale,
        locale_assigned=False,
        page_kind=page_kind,
        article_id=article_id,
        nav=nav,
        is_pageview=pageview,
        referer_host=referer_host(record.referer),
        channel=channel,
        campaign=campaign,
        language=primary_language(record.accept_language),
        language_region=primary_region(record.accept_language),
        country=record.cf_country,
        visitor=visitor_id(record, salt=salt),
        fmt=record.fmt,
        ua_key=ua_identity(record.user_agent),
    )


def iter_events(
    records: Iterable[LogRecord],
    *,
    tz: tzinfo,
    salts: SaltProvider,
    hard_only: bool = False,
    ledger: Ledger | None = None,
) -> Iterator[Event]:
    """Stream records -> events, filling the ledger as it goes. Bounded memory.

    Every record lands in exactly one ledger bucket, in the order below, so the
    ledger's rows sum to the line count and the reader can verify the arithmetic
    without trusting the tool. `total_lines`, `blank` and `unparseable` come
    from ParseStats and are set by the caller — those lines never became records.

    The only state held across records is a small bounded map used to detect the
    "/" -> "/en" redirect landing, capped at 4096 entries.
    """
    pending_redirects: dict[str, datetime] = {}

    for record in records:
        salt = salts.salt_for(record.ts.astimezone(tz))
        event = enrich(record, tz=tz, salt=salt, hard_only=hard_only)

        if ledger is not None:
            _account(ledger, event)

        # -- locale assignment ------------------------------------------------
        # middleware.ts sends "/" to "/en" with a 307. Those EN arrivals were
        # ASSIGNED a locale, not chosen, and counting them as "chose EN" inflates
        # the English share of the language matrix. The pairing is best-effort
        # and its count is printed as a footnote so the reader can discount it.
        if event.page_kind == "redirect" and record.path == "/" and record.status in (301, 302, 307, 308):
            if len(pending_redirects) >= _ASSIGNED_LOCALE_MAX_TRACKED:
                pending_redirects.clear()  # cheap bound; loses a few pairings
            pending_redirects[_identity_key(record, salt)] = event.local_ts
        elif event.is_pageview and event.page_kind == "home":
            key = _identity_key(record, salt)
            seen = pending_redirects.pop(key, None)
            if seen is not None:
                delta = (event.local_ts - seen).total_seconds()
                if 0.0 <= delta <= _ASSIGNED_LOCALE_WINDOW_SECONDS:
                    event = replace(event, locale_assigned=True)

        yield event


def _account(ledger: Ledger, event: Event) -> None:
    """Put an event in exactly one ledger bucket. Order is the contract."""
    record = event.record
    verdict = event.verdict

    if record.malformed_request:
        ledger.malformed += 1
        return
    if record.vhost == "other":
        ledger.other_vhost += 1
        return

    if verdict.klass != "human":
        if verdict.forged:
            ledger.forged_crawlers += 1
        elif verdict.rule == "cf-provenance":
            ledger.direct_origin += 1
        elif verdict.rule == BEHAVIOURAL_RULE:
            # Only reachable when a demoted event is fed back through
            # `iter_events`; the normal path retires it via
            # `_retire_from_ledger` after the fact. Present so the two cannot
            # disagree about which bucket this verdict belongs in.
            ledger.suspected_automation += 1
        elif verdict.category == "health":
            ledger.health_probes += 1
        elif verdict.category == "scanner":
            ledger.scanners += 1
        elif verdict.klass == "agent":
            if verdict.subclass == "self":
                ledger.agents_self += 1
            elif verdict.subclass == "reach":
                ledger.agents_reach += 1
            elif verdict.subclass == "feed":
                ledger.agents_feed += 1
            else:
                ledger.bots += 1
        else:
            ledger.bots += 1
        return

    if event.is_pageview:
        ledger.human_pageviews += 1
        if event.nav == "soft":
            ledger.soft += 1
        else:
            # Legacy pageviews are "unknown" nav but are hard navigations by
            # construction (C.7), so they count as hard.
            ledger.hard += 1
        return

    if event.page_kind == "asset":
        ledger.assets += 1
    elif event.page_kind in ("api", "metadata"):
        ledger.api += 1
    elif event.page_kind == "feed":
        ledger.feeds += 1
    elif event.page_kind == "redirect" or (record.status is not None and 300 <= record.status < 400):
        ledger.redirects += 1
    elif event.nav == "prefetch":
        ledger.prefetch += 1
    elif event.page_kind in ("home", "article"):
        # A real page shape that did not render: 404, 500, or a HEAD probe from
        # something the classifier let through as human.
        ledger.non_2xx += 1
    else:
        ledger.other_paths += 1


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------
def _session_pageview(event: Event, include_bots: bool) -> bool:
    return bool(event.visitor) and counts_as_pageview(event, include_bots=include_bots)


def sessionize(
    events: Iterable[Event],
    *,
    gap_minutes: int = SESSION_GAP_MINUTES,
    include_bots: bool = False,
) -> list[Session]:
    """Group pageview events per visitor, splitting on a gap > gap_minutes.

    Computed over PAGEVIEWS ONLY. Sessionizing over asset requests inflates
    every duration and erases bounces, because a page's twenty asset fetches
    trail its pageview by a few seconds and make every single-page visit look
    engaged.

    Does NOT split at midnight (see SaltProvider for why the day boundary is
    04:00), and events with `visitor is None` — every legacy line — produce no
    sessions at all rather than a fabricated one.

    MEMORY: only pageviews with a visitor are held, grouped by visitor. On this
    site that is a few hundred rows a day; asset and bot traffic, which is the
    bulk of the file, never enters the structure.
    """
    by_visitor: dict[str, list[Event]] = {}
    for event in events:
        if not _session_pageview(event, include_bots):
            continue
        assert event.visitor is not None  # narrowed by _session_pageview
        by_visitor.setdefault(event.visitor, []).append(event)

    gap = timedelta(minutes=gap_minutes)
    sessions: list[Session] = []
    for visitor, visitor_events in by_visitor.items():
        visitor_events.sort(key=lambda ev: ev.local_ts)
        run: list[Event] = []
        for event in visitor_events:
            if run and (event.local_ts - run[-1].local_ts) > gap:
                sessions.append(_build_session(visitor, run))
                run = []
            run.append(event)
        if run:
            sessions.append(_build_session(visitor, run))

    sessions.sort(key=lambda session: (session.started, session.visitor))
    return sessions


def _build_session(visitor: str, run: Sequence[Event]) -> Session:
    entry = run[0]
    last = run[-1]
    paths = tuple(ev.record.path for ev in run[:_SESSION_PATH_CAP])
    articles = tuple(ev.article_id for ev in run[:_SESSION_PATH_CAP] if ev.article_id)
    locales = frozenset(ev.locale for ev in run if ev.locale)
    formats = {ev.fmt for ev in run}

    # Duration is last pageview - first pageview, and it is SYSTEMATICALLY an
    # underestimate: the time spent on the final page is invisible because
    # nothing marks its end. On a news site the final page is usually the
    # article the person came for, so the dwell time lost is precisely the one
    # that matters. A bounced session therefore has duration 0.0 BY
    # CONSTRUCTION — averaging bounces in produces a number that measures the
    # bounce rate, not reading, which is why the report excludes them and calls
    # the result "measured span (engaged visits)", never "time on site".
    duration = (last.local_ts - entry.local_ts).total_seconds() if len(run) > 1 else 0.0

    return Session(
        visitor=visitor,
        started=entry.local_ts,
        ended=last.local_ts,
        pageviews=len(run),
        entry_path=entry.record.path,
        entry_locale=entry.locale,
        entry_kind=entry.page_kind,
        channel=entry.channel,
        campaign=entry.campaign,
        country=entry.country,
        language=entry.language,
        agent=entry.agent,
        locales=locales,
        paths=paths,
        articles=articles,
        # Bounce = exactly one pageview. It is an UPPER BOUND here and must be
        # labelled as one every time it is printed: App Router back/forward and
        # cached soft navigations emit no request, so genuine engagement can be
        # indistinguishable from a single-page visit.
        is_bounce=len(run) == 1,
        duration_seconds=duration,
        saw_rsc=any(ev.nav == "soft" for ev in run),
        fmt=next(iter(formats)) if len(formats) == 1 else "mixed",
    )


def same_day_returns(sessions: Sequence[Session]) -> int:
    """Visitors with two or more sessions on the same local day.

    This is the ONLY returning-visitor figure this tool may print. Cross-day
    identity is not computable by construction — the salt rotates daily — so
    "X% returning visitors", 7/30-day retention and new-vs-returning are never
    produced, not even as estimates.
    """
    per_day: dict[tuple[str, str], int] = {}
    for session in sessions:
        key = (session.started.date().isoformat(), session.visitor)
        per_day[key] = per_day.get(key, 0) + 1
    return sum(1 for count in per_day.values() if count >= 2)


# ---------------------------------------------------------------------------
# The behavioural automation pass
# ---------------------------------------------------------------------------
# `bots.classify` sees ONE request: a user-agent signature, a scanner path, a
# Cloudflare peer. That is the correct scope for a verdict that gets written
# into the store, and it is structurally blind to the thing that actually
# distinguishes a scraper from a reader on this site — what one client did
# across two thousand requests and fifteen days.
#
# The measured hole it leaves: a single forged iPhone user-agent ("iPhone OS
# 13_2_3", an OS from 2019) arrived through Cloudflare on 788 different edge
# addresses, hit 380 distinct paths, fetched both the /en and /ua copy of the
# same article, ran on a ~592-second cycle with no diurnal curve at all, and
# NEVER ONCE requested a /_next/ chunk. Every request of it looked like a
# person. Together with a second identity polling "/" -> "/en" around the clock
# it accounted for 1 857 of 4 181 reported pageviews — 44.4% of the audience.
#
# WHY THE PASS LIVES HERE AND RUNS WHERE IT RUNS. This module owns the question
# "is this a pageview", so it owns the answer that changes one. The pass itself
# is called from the report wiring, over the materialised event list, AFTER
# `iter_events` and BEFORE `sessionize()` / the ledger / `build_report` — which
# means `Event.is_pageview` is rewritten once and every downstream counter,
# session, table and heat cell follows with no logic change anywhere. It is
# deliberately NOT run at ingest: the store is the record of what one request
# looked like, this is the record of what the whole window showed, and baking a
# batch-order-dependent judgement into permanent rows would make
# `ingest --reingest` unreproducible.
#
# THE DIRECTION OF ERROR THAT MATTERS. Demoting a reader is expensive and
# demoting a bot is cheap, so every threshold below is set to fail towards
# keeping readers. See `bots.corroborates_scraper` for the evidence behind each.

#: Hard floor. A user-agent below this many pageviews is NEVER demoted, whatever
#: else it does. Measured over 15 days of production traffic: the largest
#: innocent zero-asset user-agent held 42 pageviews and the smaller of the two
#: confirmed scraper pools held 415. Any floor in [43, 415] demotes exactly the
#: two pools and zero readers; 100 is near the log-midpoint of the interval that
#: stays safe at every window length from ten days upward. A floor of 20 would
#: have destroyed 931 genuine pageviews across 32 real reader populations.
AUTOMATION_MIN_PAGEVIEWS: int = 100

#: A heavy reading day is one to three days. Both confirmed pools ran 15 of 15.
AUTOMATION_MIN_ACTIVE_DAYS: int = 5

#: Below this many days of observed traffic the pass SUPPRESSES ITSELF and
#: changes nothing. This is not caution, it is a measured inversion: sliding
#: windows over the same 15 days put the largest innocent zero-asset user-agent
#: at 84 pageviews and the smallest scraper detection at 48 over three days, so
#: a short-window rule deletes readers and keeps bots. "Categorically zero
#: assets" only becomes meaningful once the window is long enough that a real
#: browser population would have been caught fetching something.
AUTOMATION_MIN_WINDOW_DAYS: int = 10

#: How much of a raw user-agent string reaches the appendix. The forged-crawler
#: table already prints UA strings at 120; this matches it.
_AGENT_LABEL_MAX = 120


def ua_identity(ua: str | None) -> str | None:
    """A run-local grouping key for one user-agent string, or None.

    The behavioural pass groups requests by user-agent across the whole window
    and has to do it on both report paths. `--from-logs` holds the raw string;
    the store deliberately never persisted one and offers its own salted
    `ua_hash` instead. The two keys do not agree and do not need to — a key only
    has to be stable within one run. Nothing writes this value anywhere: it is
    not persisted, not printed and not part of the JSON.

    None for an absent or empty user-agent, and None is never demoted: an
    identity the report cannot name is one it must not judge. That costs
    nothing here — on 15 days of real traffic the 4 822 lines with no
    user-agent produced zero human pageviews, because rule 6 of `classify`
    has already called them bots.
    """
    if ua is None:
        return None
    text = ua.strip()
    if not text:
        return None
    return hashlib.blake2b(text.encode("utf-8", "replace"), digest_size=8).hexdigest()


@dataclass(frozen=True, slots=True)
class AgentProfile:
    """What one user-agent identity did across the whole window.

    The evidence a reader needs to disagree with the verdict, which is the
    point: a filter nobody can audit is a filter nobody notices has grown to
    swallow real traffic.
    """

    key: str
    label: str                    # raw UA on --from-logs; parsed shape + key on the store path
    requests: int                 # every line sharing this UA, whatever it was classified
    human_requests: int           # of those, the ones `classify` called human
    human_pageviews: int          # of those, the ones that counted as audience
    asset_requests: int           # THE exculpatory signal; one is enough to exempt
    distinct_paths: int
    distinct_sources: int | None  # None when the log carried no usable peer address
    active_days: int
    active_hours: int
    demoted: bool


@dataclass(frozen=True, slots=True)
class AutomationFindings:
    """The outcome of one behavioural pass — including a pass that did nothing.

    `ran` False with a `reason` is a first-class result, not an error. The pass
    suppresses itself on a short window rather than applying a rule the data
    cannot support, and the report says so out loud, because a silently skipped
    filter and a filter that found nothing look identical from the outside.
    """

    ran: bool
    reason: str | None
    min_pageviews: int
    min_active_days: int
    min_window_days: int
    window_days: int              # distinct local dates actually observed
    identities: int               # user-agent identities that produced a pageview
    demoted_agents: tuple[AgentProfile, ...]
    demoted_events: int           # human-classified requests moved out
    demoted_pageviews: int        # of those, the ones that were audience
    pageviews_before: int         # human pageviews before the pass
    demoted_by_date: dict[str, int]   # pageviews removed per local date

    @property
    def pageviews_after(self) -> int:
        return self.pageviews_before - self.demoted_pageviews

    @property
    def demoted_share(self) -> float | None:
        """Share of the pre-pass audience this removed, or None if there was none."""
        if self.pageviews_before <= 0:
            return None
        return self.demoted_pageviews / self.pageviews_before


@dataclass
class _Tally:
    """Mutable accumulator behind one AgentProfile. Never leaves this module."""

    label: str = ""
    requests: int = 0
    human_requests: int = 0
    human_pageviews: int = 0
    asset_requests: int = 0
    paths: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)
    days: set[str] = field(default_factory=set)
    hours: set[int] = field(default_factory=set)
    saw_source: bool = False


def _agent_label(event: Event, key: str) -> str:
    """Name one identity for the appendix, on whichever path built the event.

    `--from-logs` has the raw user-agent and prints it truncated, exactly as the
    forged-crawler table already does. The store never persisted the string, so
    the parsed dimensions it DID keep are reassembled instead and the grouping
    key's prefix is appended, so two identities of the same shape stay
    distinguishable and can be matched against the store by hand.
    """
    raw = (event.record.user_agent or "").strip()
    if raw:
        return raw[:_AGENT_LABEL_MAX]
    agent = event.agent
    parts: list[str] = []
    for value in (
        " ".join(part for part in (agent.browser_family, agent.browser_version) if part),
        " ".join(part for part in (agent.os_family, agent.os_version) if part),
        agent.device_type,
    ):
        if value and value not in ("Other", "Unknown", "unknown"):
            parts.append(value)
    shape = " · ".join(parts) if parts else "unnamed agent"
    return f"{shape} #{key[:8]}"


def profile_agents(events: Iterable[Event]) -> dict[str, AgentProfile]:
    """Group every event by user-agent identity and describe what each one did.

    Counts requests of EVERY class, not just the human ones. That is deliberate
    in both directions: the forged-iPhone pool sent 997 of its 2 667 requests
    straight to the origin and those are already correctly bucketed as
    direct-to-origin, but they are still the same client and they still count
    as evidence — and, more importantly, an asset fetched by any arm of an
    identity exempts the whole identity. Erring towards exemption is the
    intended direction.

    Events with no user-agent are skipped entirely; see `ua_identity`.
    """
    tallies: dict[str, _Tally] = {}
    for event in events:
        key = event.ua_key
        if not key:
            continue
        tally = tallies.get(key)
        if tally is None:
            tally = tallies[key] = _Tally(label=_agent_label(event, key))
        tally.requests += 1
        if event.verdict.klass == "human":
            tally.human_requests += 1
        if event.is_pageview:
            tally.human_pageviews += 1
        if event.page_kind == "asset":
            tally.asset_requests += 1
        tally.paths.add(event.record.path)
        tally.days.add(event.date)
        tally.hours.add(event.hour)
        source = event.record.peer_ip or event.record.client_ip
        if source:
            tally.saw_source = True
            tally.sources.add(source)

    return {
        key: AgentProfile(
            key=key,
            label=tally.label,
            requests=tally.requests,
            human_requests=tally.human_requests,
            human_pageviews=tally.human_pageviews,
            asset_requests=tally.asset_requests,
            distinct_paths=len(tally.paths),
            # None, not 0. A store-backed report holds no addresses at all — the
            # store persists none by design — and printing 0 there would read as
            # "one client", which is the opposite of what the data says.
            distinct_sources=len(tally.sources) if tally.saw_source else None,
            active_days=len(tally.days),
            active_hours=len(tally.hours),
            demoted=False,
        )
        for key, tally in tallies.items()
    }


def demote_automation(
    events: Sequence[Event],
    *,
    enabled: bool = True,
    min_pageviews: int = AUTOMATION_MIN_PAGEVIEWS,
    min_active_days: int = AUTOMATION_MIN_ACTIVE_DAYS,
    min_window_days: int = AUTOMATION_MIN_WINDOW_DAYS,
    ledger: Ledger | None = None,
) -> tuple[list[Event], AutomationFindings]:
    """Rewrite the events of every user-agent the whole window convicts.

    Returns a NEW list — the input is untouched — in the original order, with
    each demoted identity's human-classified events carrying
    `is_pageview=False` and `bots.SUSPECTED_AUTOMATION`. Requests of a demoted
    identity that some earlier rule already called non-human (the forged
    iPhone's direct-to-origin arm, for instance) are left exactly where they
    are: that verdict is a stronger, per-request finding and the security
    section is built from it.

    Pass the `ledger` that `iter_events` filled and it is corrected in place,
    exactly, by replaying `_account` for each retired event and subtracting what
    it had contributed. On the store path the ledger is built afterwards from
    the rewritten events instead, so no ledger is passed there.

    THE FAILURE MODES, both directions, because this is the one function in the
    tool that deletes readers:

      * The verdict is per USER-AGENT and per WINDOW, not per person. A demoted
        user-agent takes with it any genuine reader who happens to send that
        exact string. Two mass-market strings would be a real cost; the two
        this actually convicts are a 2019 iOS build and a headless-shaped
        Chrome, and their pageview-per-path ratios (3.8 and 26) are nothing a
        person produces.
      * The inverse is NEVER applied. A low-volume user-agent with no asset
        fetches is a returning reader with a warm cache, and stays audience.
      * One asset fetch anywhere in the window exempts an identity completely,
        so a scraper that requests a single stylesheet per window defeats this.
        That is the cost of refusing to guess, and it is in the footnotes.
      * Below `min_window_days` the pass refuses to run at all rather than run
        weakly — the separation does not merely get noisier at short windows,
        it inverts.
    """
    pageviews_before = sum(1 for event in events if event.is_pageview)
    window_days = len({event.date for event in events})

    def _nothing(reason: str) -> tuple[list[Event], AutomationFindings]:
        return list(events), AutomationFindings(
            ran=False,
            reason=reason,
            min_pageviews=min_pageviews,
            min_active_days=min_active_days,
            min_window_days=min_window_days,
            window_days=window_days,
            identities=0,
            demoted_agents=(),
            demoted_events=0,
            demoted_pageviews=0,
            pageviews_before=pageviews_before,
            demoted_by_date={},
        )

    if not enabled:
        return _nothing("switched off with --no-automation-filter")
    if min_pageviews < 1:
        # Zero would demote every warm-cache reader on the site. Refuse loudly
        # rather than obey; the report prints this reason verbatim.
        return _nothing(
            f"--automation-threshold {min_pageviews} is not a floor at all — a "
            "threshold below 1 would demote every reader whose browser cache "
            "spared the origin, so the pass refused to run"
        )
    if window_days < min_window_days:
        return _nothing(
            f"insufficient history: {window_days} day(s) of traffic in this window, "
            f"the rule needs {min_window_days}. Below that the separation does not "
            "weaken, it INVERTS — measured over three-day windows the largest "
            "innocent zero-asset agent held 84 pageviews and the smallest real "
            "scraper 48 — so the pass is suppressed rather than applied. The "
            "audience number below is therefore the per-request one and includes "
            "whatever automation wears a browser user-agent"
        )

    profiles = profile_agents(events)
    convicted: dict[str, AgentProfile] = {}
    for key, profile in profiles.items():
        if corroborates_scraper(
            human_pageviews=profile.human_pageviews,
            asset_requests=profile.asset_requests,
            active_days=profile.active_days,
            min_pageviews=min_pageviews,
            min_active_days=min_active_days,
        ):
            convicted[key] = replace(profile, demoted=True)

    rewritten: list[Event] = []
    demoted_events = 0
    demoted_pageviews = 0
    demoted_by_date: dict[str, int] = {}
    for event in events:
        if event.ua_key in convicted and event.verdict.klass == "human":
            if ledger is not None:
                _retire_from_ledger(ledger, event)
            demoted_events += 1
            if event.is_pageview:
                demoted_pageviews += 1
                demoted_by_date[event.date] = demoted_by_date.get(event.date, 0) + 1
            rewritten.append(replace(event, is_pageview=False,
                                     verdict=SUSPECTED_AUTOMATION))
        else:
            rewritten.append(event)

    findings = AutomationFindings(
        ran=True,
        reason=None,
        min_pageviews=min_pageviews,
        min_active_days=min_active_days,
        min_window_days=min_window_days,
        window_days=window_days,
        identities=sum(1 for p in profiles.values() if p.human_pageviews > 0),
        demoted_agents=tuple(sorted(
            convicted.values(),
            key=lambda p: (-p.human_pageviews, p.label),
        )),
        demoted_events=demoted_events,
        demoted_pageviews=demoted_pageviews,
        pageviews_before=pageviews_before,
        demoted_by_date=demoted_by_date,
    )
    return rewritten, findings


def _retire_from_ledger(ledger: Ledger, event: Event) -> None:
    """Move one event from whatever bucket it was in into suspected automation.

    Replays `_account` on a scratch ledger and subtracts the result, rather than
    reimplementing the dispatch. The bucket order in `_account` is the contract;
    a second copy of it here is exactly how the two would silently drift, and a
    ledger that no longer sums to the line count is worse than no ledger.
    """
    scratch = Ledger()
    _account(scratch, event)
    for field_ in dataclass_fields(Ledger):
        delta = getattr(scratch, field_.name)
        if delta:
            setattr(ledger, field_.name, getattr(ledger, field_.name) - delta)
    ledger.suspected_automation += 1
