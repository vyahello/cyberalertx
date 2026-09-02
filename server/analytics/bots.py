"""Human / agent / bot classification, in the order the evidence deserves.

The naive version of this module is a list of user-agent substrings. On this
site the naive version is wrong by a factor of twenty, because two measured
facts break it:

CLOUDFLARE PROVENANCE OUTRANKS THE USER-AGENT STRING. cyberalertx is fully
Cloudflare-proxied, so a request whose socket peer sits outside Cloudflare's
published ranges never traversed Cloudflare and never came from a reader. It
is a direct-to-origin probe, definitionally not audience, whatever its UA
claims. That was 3 927 of 4 947 lines in one measured day — 79.4%. It is the
strongest filter available here, it works on the legacy logs with no nginx
change at all, and it therefore runs BEFORE any UA test.

USER-AGENT STRINGS ARE ACTIVELY FORGED HERE. In one day, 2 986 requests
claimed Googlebot from a single address that belongs to neither Google nor
Cloudflare, while fetching /wp-config.php and /.env. Another wore a Galaxy
S20 UA from an AWS address. A declared crawler arriving from outside
Cloudflare on a Cloudflare-proxied site is forged, gets its own bucket, and
is reported separately — because "Googlebot crawled us 3 000 times today" is
a very different sentence from "someone spent the day pretending to be
Google".

THE HEALTH MONITOR WEARS A BROWSER. GET /healthz arrives ~60x/day with a
full Chrome UA and a real Referer of https://cyberalertx.com/en. It is
excluded BY PATH. Any UA-based attempt counts it as a person.

REJECTED HEURISTICS, DOCUMENTED SO NOBODY RE-ADDS THEM:

  * "Bots do not load assets" is FALSE on this site. Baiduspider-render
    demonstrably fetches /_next/static/chunks/*.js, while Cloudflare's edge
    and the browser cache mean a returning human's assets never reach the
    origin at all. The inverse is sound and IS used elsewhere: a request
    carrying ?_rsc= is a strong POSITIVE human signal, because App Router
    client-side navigation only fires from a real JS-executing browser.

    THE ASYMMETRY, and it is the whole of the behavioural rule below.
    FETCHING an asset PROVES a browser and must never whitelist anything;
    NOT fetching one is evidence only AT VOLUME. Measured over 15 days here:
    111 of the 182 user-agents that produced a human pageview fetched no
    asset at all, and site-wide the origin logs 0.79 assets per pageview
    when a cold Next.js page load is ten to twenty chunks. Cloudflare serves
    /_next/static from the edge (immutable, cached a year) and the browser
    cache serves it again, so a returning reader's page requests arrive
    alone. Zero assets is the NORMAL condition of a real reader, not an
    anomaly, and it separates automation from audience only above a hard
    pageview floor — `corroborates_scraper`, at the bottom of this module.
  * "Empty Referer plus a deep-path entry implies a bot" must NEVER be used.
    Telegram's in-app browser sends no Referer, and Telegram is this site's
    primary distribution channel. That rule would delete precisely the main
    audience and leave a report full of crawlers.

FRAMING RULE FOR THE REPORT: never write "X% of traffic is bots". Write "X%
of requests reaching the origin". Cloudflare's managed rules drop the worst
traffic long before it reaches this log; what is in the file is the residue,
and only Cloudflare's own dashboard sees the pre-filter picture.

SCOPE: pure classification over records already parsed from cyberalertx's own
logs. No I/O, no network lookups, no reverse DNS, no live fetch of anyone's
published IP ranges. Nothing here writes to any log file, ever.

PRIVACY: nothing leaves the box. Addresses are tested against a compiled
in-memory list and are never resolved, never logged, and never persisted by
this module. No dependency outside the stdlib.
"""
from __future__ import annotations

import ipaddress
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from ipaddress import IPv4Network, IPv6Network
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - import-cycle avoidance, types only
    from .logread import LogRecord
    from .useragent import Agent

logger = logging.getLogger("analytics.bots")


@dataclass(frozen=True, slots=True)
class Verdict:
    """Why one request was or was not counted as a person.

    `rule` is the audit trail. A silently-discarded bucket is one nobody
    notices has grown to swallow real traffic, so every drop can name the rule
    that dropped it and the security section prints the totals.
    """

    klass: str
    label: str
    category: str
    rule: str
    subclass: str | None
    subscribers: int | None
    forged: bool


# --------------------------------------------------------------------------
# Cloudflare ranges
# --------------------------------------------------------------------------
# Fetched 2026-09-02 from https://www.cloudflare.com/ips-v4 and /ips-v6,
# cross-checked against https://api.cloudflare.com/client/v4/ips.
#
# THESE GO STALE. Re-check occasionally with:
#   curl -s https://api.cloudflare.com/client/v4/ips | grep -o '"etag":"[^"]*"'
# and compare against CF_RANGES_ETAG below. A stale list FAILS CLOSED: a
# visitor arriving through a new, untrusted Cloudflare range is classified as
# direct-to-origin and dropped from the audience. That is degraded analytics,
# never a security hole and never an outage. The free self-check runs on every
# ingest — a line carrying a CF-Ray from a peer outside this list increments
# ParseStats.stale_cf_ranges, and the report prints a warning when it is
# non-zero. Do NOT auto-fetch and rewrite this list from cron.
CLOUDFLARE_IPV4: tuple[str, ...] = (
    "173.245.48.0/20",
    "103.21.244.0/22",
    "103.22.200.0/22",
    "103.31.4.0/22",
    "141.101.64.0/18",
    "108.162.192.0/18",
    "190.93.240.0/20",
    "188.114.96.0/20",
    "197.234.240.0/22",
    "198.41.128.0/17",
    "162.158.0.0/15",
    "104.16.0.0/13",
    "104.24.0.0/14",
    "172.64.0.0/13",
    "131.0.72.0/22",
)
CLOUDFLARE_IPV6: tuple[str, ...] = (
    "2400:cb00::/32",
    "2606:4700::/32",
    "2803:f800::/32",
    "2405:b500::/32",
    "2405:8100::/32",
    "2a06:98c0::/29",
    "2c0f:f248::/32",
)
CLOUDFLARE_NETWORKS: tuple[IPv4Network | IPv6Network, ...] = tuple(
    [ipaddress.ip_network(cidr) for cidr in CLOUDFLARE_IPV4]
    + [ipaddress.ip_network(cidr) for cidr in CLOUDFLARE_IPV6]
)
CF_RANGES_FETCHED: str = "2026-09-02"
CF_RANGES_ETAG: str = "38f79d050aa027e3be3865e495dcc9bc"


@lru_cache(maxsize=65536)
def is_cloudflare_ip(ip: str | None) -> bool:
    """Membership test against CLOUDFLARE_NETWORKS, using ipaddress from the
    stdlib. Handles IPv4 and IPv6. Returns False for None and for anything that
    does not parse as an address. Memoised (lru_cache, maxsize=65536).
    """
    if not ip:
        return False
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    version = address.version
    for network in CLOUDFLARE_NETWORKS:
        if network.version == version and address in network:
            return True
    return False


# --------------------------------------------------------------------------
# signature catalogue
# --------------------------------------------------------------------------
# (lowercase token, label, category, klass). ORDER IS THE CONTRACT: the loop
# returns the first entry whose token appears in the lowercased UA, so every
# specific token must precede any token it contains or resembles.
SIGNATURES: tuple[tuple[str, str, str, str], ...] = (
    # -- ORDERING TRAP 1: telegrambot BEFORE twitterbot -------------------
    # Telegram's fetcher announces itself as "TelegramBot (like TwitterBot)".
    # Match twitterbot first and 100% of this site's primary distribution
    # channel is attributed to Twitter. Cloudflare's own bot analytics ships
    # this exact bug. For a Telegram-first site it is the single most damaging
    # mis-ordering available, so this entry stays at the top of the list.
    ("telegrambot", "Telegram", "unfurler", "agent"),

    # -- ORDERING TRAP 2: specific variants before their prefixes ---------
    ("applebot-extended", "Applebot-Extended", "ai", "bot"),
    ("applebot", "Applebot", "search", "bot"),
    ("googleother-image", "GoogleOther-Image", "tooling", "bot"),
    ("googleother-video", "GoogleOther-Video", "tooling", "bot"),
    ("googleother", "GoogleOther", "tooling", "bot"),
    ("google-extended", "Google-Extended", "ai", "bot"),
    ("google-inspectiontool", "Google InspectionTool", "tooling", "bot"),
    ("google-read-aloud", "Google Read-Aloud", "tooling", "agent"),
    ("google-safety", "Google Safety", "tooling", "bot"),
    ("googlebot-image", "Googlebot Image", "search", "bot"),
    ("googlebot-news", "Googlebot News", "search", "bot"),
    ("googlebot-video", "Googlebot Video", "search", "bot"),
    ("googlebot", "Googlebot", "search", "bot"),
    ("google favicon", "Google Favicon", "tooling", "bot"),
    ("yandexadditionalbot", "YandexAdditional", "seo", "bot"),
    ("yandexadditional", "YandexAdditional", "seo", "bot"),
    ("yandeximages", "YandexImages", "search", "bot"),
    ("yandexmobilebot", "YandexMobileBot", "search", "bot"),
    ("yandexbot", "YandexBot", "search", "bot"),
    ("semrushbot-ocob", "SemrushBot-OCOB", "ai", "bot"),
    ("semrushbot-swa", "SemrushBot-SWA", "seo", "bot"),
    ("semrushbot-ba", "SemrushBot-BA", "seo", "bot"),
    ("semrushbot", "SemrushBot", "seo", "bot"),
    # An unfurler and an AI training crawler from the same company. Different
    # buckets, different meaning, never merged.
    ("meta-externalfetcher", "Meta-ExternalFetcher", "unfurler", "agent"),
    ("meta-externalagent", "Meta-ExternalAgent", "ai", "bot"),
    ("facebookexternalhit", "facebookexternalhit", "unfurler", "agent"),
    ("facebookcatalog", "FacebookCatalog", "tooling", "bot"),
    ("facebookbot", "FacebookBot", "ai", "bot"),
    ("baiduspider-render", "Baiduspider-render", "search", "bot"),
    ("baiduspider", "Baiduspider", "search", "bot"),
    # -- ORDERING TRAP 3: headless Chrome before "contains Chrome" --------
    # Nothing below may conclude "this string contains Chrome, therefore a
    # person" — these two contain a complete, current Chrome UA.
    ("headlesschrome", "HeadlessChrome", "headless", "bot"),
    ("chrome-lighthouse", "Lighthouse", "headless", "bot"),
    ("google page speed", "PageSpeed", "headless", "bot"),

    # -- AI: user-triggered fetchers are AGENTS, crawlers are BOTS --------
    # An agent hit means one specific person asked for this page right now.
    # That is reach, not audience, and it belongs in neither bucket alone.
    ("chatgpt-user", "ChatGPT-User", "ai", "agent"),
    ("oai-searchbot", "OAI-SearchBot", "ai", "bot"),
    ("gptbot", "GPTBot", "ai", "bot"),
    ("claude-user", "Claude-User", "ai", "agent"),
    ("claude-searchbot", "Claude-SearchBot", "ai", "bot"),
    ("claude-web", "Claude-Web", "ai", "bot"),
    ("claudebot", "ClaudeBot", "ai", "bot"),
    ("anthropic-ai", "Anthropic-AI", "ai", "bot"),
    ("perplexity-user", "Perplexity-User", "ai", "agent"),
    ("perplexitybot", "PerplexityBot", "ai", "bot"),
    ("amzn-user", "Amzn-User", "ai", "agent"),
    ("mistralai-user", "MistralAI-User", "ai", "agent"),
    ("kimi-user", "Kimi-User", "ai", "agent"),
    ("manus-user", "Manus-User", "ai", "agent"),
    ("notebooklm", "NotebookLM", "ai", "agent"),
    ("gemini-deep-research", "Gemini-Deep-Research", "ai", "agent"),
    # "operator/" with the slash, never a bare "operator": the bare word turns
    # up in mobile-carrier and enterprise proxy UAs.
    ("operator/", "Operator", "ai", "agent"),
    ("amazonbot", "Amazonbot", "ai", "bot"),
    ("bytespider", "Bytespider", "ai", "bot"),
    ("ccbot", "CCBot", "ai", "bot"),
    ("cohere-ai", "cohere-ai", "ai", "bot"),
    ("diffbot", "Diffbot", "ai", "bot"),
    ("omgili", "Omgili", "ai", "bot"),
    ("img2dataset", "img2dataset", "ai", "bot"),
    ("timpibot", "Timpibot", "ai", "bot"),
    ("youbot", "YouBot", "ai", "bot"),
    ("ai2bot", "AI2Bot", "ai", "bot"),
    ("duckassistbot", "DuckAssistBot", "ai", "bot"),

    # -- search ------------------------------------------------------------
    ("bingpreview", "BingPreview", "search", "bot"),
    ("adidxbot", "AdIdxBot", "seo", "bot"),
    ("bingbot", "bingbot", "search", "bot"),
    ("msnbot", "msnbot", "search", "bot"),
    ("duckduckbot", "DuckDuckBot", "search", "bot"),
    ("duckduckgo-favicons", "DuckDuckGo Favicons", "tooling", "bot"),
    ("petalbot", "PetalBot", "search", "bot"),
    ("aspiegel", "PetalBot", "search", "bot"),
    ("seznambot", "SeznamBot", "search", "bot"),
    ("sogou", "Sogou", "search", "bot"),
    ("exabot", "Exabot", "search", "bot"),
    ("naver", "Naver", "search", "bot"),
    ("yeti/", "Naver Yeti", "search", "bot"),
    ("coccocbot", "CocCocBot", "search", "bot"),
    ("mojeekbot", "MojeekBot", "search", "bot"),
    ("qwantify", "Qwantify", "search", "bot"),
    ("marginalia", "Marginalia", "search", "bot"),
    ("ia_archiver", "Internet Archive", "seo", "bot"),
    ("archive.org_bot", "Internet Archive", "seo", "bot"),

    # -- seo / marketing crawlers -----------------------------------------
    ("ahrefsbot", "AhrefsBot", "seo", "bot"),
    ("ahrefssiteaudit", "AhrefsSiteAudit", "seo", "bot"),
    ("mj12bot", "MJ12bot", "seo", "bot"),
    ("dotbot", "DotBot", "seo", "bot"),
    ("rogerbot", "rogerbot", "seo", "bot"),
    ("blexbot", "BLEXBot", "seo", "bot"),
    ("serpstatbot", "serpstatbot", "seo", "bot"),
    ("dataforseobot", "DataForSeoBot", "seo", "bot"),
    ("screaming frog", "Screaming Frog", "seo", "bot"),
    ("sitebulb", "Sitebulb", "seo", "bot"),
    ("linkdexbot", "linkdexbot", "seo", "bot"),
    ("megaindex", "MegaIndex", "seo", "bot"),
    ("barkrowler", "Barkrowler", "seo", "bot"),
    ("babbar", "Babbar", "seo", "bot"),
    ("zoominfobot", "ZoominfoBot", "seo", "bot"),
    ("sistrix", "SISTRIX", "seo", "bot"),
    ("netcraftsurveyagent", "Netcraft", "seo", "bot"),
    ("seokicks", "SEOkicks", "seo", "bot"),

    # -- unfurlers: every hit is a person pasting a link somewhere --------
    # This is the amplification metric, and it is invisible in a binary
    # human/bot split. Note twitterbot sits BELOW telegrambot, above.
    ("twitterbot", "Twitterbot", "unfurler", "agent"),
    ("discordbot", "Discordbot", "unfurler", "agent"),
    ("slackbot", "Slackbot", "unfurler", "agent"),
    ("slack-imgproxy", "Slack", "unfurler", "agent"),
    ("whatsapp", "WhatsApp", "unfurler", "agent"),
    ("linkedinbot", "LinkedInBot", "unfurler", "agent"),
    ("skypeuripreview", "Skype", "unfurler", "agent"),
    ("viber", "Viber", "unfurler", "agent"),
    ("signal-desktop", "Signal", "unfurler", "agent"),
    ("cardyb", "Bluesky", "unfurler", "agent"),
    ("bluesky", "Bluesky", "unfurler", "agent"),
    ("mastodon/", "Mastodon", "unfurler", "agent"),
    ("pleroma", "Pleroma", "unfurler", "agent"),
    ("misskey/", "Misskey", "unfurler", "agent"),
    ("akkoma", "Akkoma", "unfurler", "agent"),
    ("friendica", "Friendica", "unfurler", "agent"),
    ("redditbot", "Redditbot", "unfurler", "agent"),
    ("pinterest", "Pinterest", "unfurler", "agent"),
    ("tumblr", "Tumblr", "unfurler", "agent"),
    ("vkshare", "VK", "unfurler", "agent"),
    ("embedly", "Embedly", "unfurler", "agent"),
    ("iframely", "Iframely", "unfurler", "agent"),
    ("quora link preview", "Quora", "unfurler", "agent"),
    ("flipboard", "Flipboard", "unfurler", "agent"),
    ("nuzzel", "Nuzzel", "unfurler", "agent"),
    ("outbrain", "Outbrain", "unfurler", "agent"),

    # -- feed readers: report SUBSCRIBERS, never visits -------------------
    # ORDERING TRAP 4: feedly BEFORE feedfetcher-google. Feedly's UA ends
    # "; like FeedFetcher-Google)", so the wrong order silently relabels the
    # site's largest feed reader as a Google service and throws away the
    # subscriber count embedded in the same string.
    ("feedly", "Feedly", "feedreader", "agent"),
    ("feedbin", "Feedbin", "feedreader", "agent"),
    ("inoreader", "Inoreader", "feedreader", "agent"),
    ("newsblur", "NewsBlur", "feedreader", "agent"),
    ("feedburner", "FeedBurner", "feedreader", "agent"),
    ("feedfetcher-google", "FeedFetcher-Google", "feedreader", "agent"),
    ("theoldreader", "The Old Reader", "feedreader", "agent"),
    ("netvibes", "Netvibes", "feedreader", "agent"),
    ("bazqux", "BazQux", "feedreader", "agent"),
    ("miniflux", "Miniflux", "feedreader", "agent"),
    ("freshrss", "FreshRSS", "feedreader", "agent"),
    ("tiny tiny rss", "Tiny Tiny RSS", "feedreader", "agent"),
    ("ttrss", "Tiny Tiny RSS", "feedreader", "agent"),
    ("rssowl", "RSSOwl", "feedreader", "agent"),
    ("netnewswire", "NetNewsWire", "feedreader", "agent"),
    ("newsboat", "Newsboat", "feedreader", "agent"),
    ("akregator", "Akregator", "feedreader", "agent"),
    ("liferea", "Liferea", "feedreader", "agent"),
    ("reeder", "Reeder", "feedreader", "agent"),
    ("nextcloud-news", "Nextcloud News", "feedreader", "agent"),

    # -- monitoring --------------------------------------------------------
    ("uptimerobot", "UptimeRobot", "monitoring", "bot"),
    ("pingdom", "Pingdom", "monitoring", "bot"),
    ("statuscake", "StatusCake", "monitoring", "bot"),
    ("site24x7", "Site24x7", "monitoring", "bot"),
    ("newrelicpinger", "New Relic", "monitoring", "bot"),
    ("datadog", "Datadog", "monitoring", "bot"),
    ("prometheus", "Prometheus", "monitoring", "bot"),
    ("blackbox_exporter", "Blackbox Exporter", "monitoring", "bot"),
    ("zabbix", "Zabbix", "monitoring", "bot"),
    ("nagios", "Nagios", "monitoring", "bot"),
    ("check_http", "Monitoring Plugins", "monitoring", "bot"),
    ("betteruptime", "Better Uptime", "monitoring", "bot"),
    ("hetrixtool", "HetrixTools", "monitoring", "bot"),
    ("updown.io", "updown.io", "monitoring", "bot"),
    ("freshping", "Freshping", "monitoring", "bot"),
    ("gtmetrix", "GTmetrix", "monitoring", "bot"),
    ("webpagetest", "WebPageTest", "monitoring", "bot"),

    # -- scanners and attack tooling --------------------------------------
    ("nuclei", "Nuclei", "scanner", "bot"),
    ("sqlmap", "sqlmap", "scanner", "bot"),
    ("nikto", "Nikto", "scanner", "bot"),
    ("acunetix", "Acunetix", "scanner", "bot"),
    ("netsparker", "Netsparker", "scanner", "bot"),
    ("wpscan", "WPScan", "scanner", "bot"),
    ("masscan", "masscan", "scanner", "bot"),
    ("zgrab", "zgrab", "scanner", "bot"),
    ("zmap", "ZMap", "scanner", "bot"),
    ("nmap", "Nmap", "scanner", "bot"),
    ("dirbuster", "DirBuster", "scanner", "bot"),
    ("gobuster", "gobuster", "scanner", "bot"),
    ("feroxbuster", "feroxbuster", "scanner", "bot"),
    ("wfuzz", "wfuzz", "scanner", "bot"),
    ("l9explore", "l9explore", "scanner", "bot"),
    ("l9tcpid", "l9tcpid", "scanner", "bot"),
    ("expanse", "Expanse", "scanner", "bot"),
    ("censys", "Censys", "scanner", "bot"),
    ("internet-measurement", "Internet Measurement", "scanner", "bot"),
    ("shodan", "Shodan", "scanner", "bot"),
    ("leakix", "LeakIX", "scanner", "bot"),
    ("paloaltonetworks", "Palo Alto", "scanner", "bot"),
    ("cyberresilience", "CyberResilience", "scanner", "bot"),
    ("researchscan", "ResearchScan", "scanner", "bot"),
    ("odin", "ODIN", "scanner", "bot"),

    # -- headless / automation --------------------------------------------
    ("phantomjs", "PhantomJS", "headless", "bot"),
    ("puppeteer", "Puppeteer", "headless", "bot"),
    ("playwright", "Playwright", "headless", "bot"),
    ("selenium", "Selenium", "headless", "bot"),
    ("cypress", "Cypress", "headless", "bot"),
    ("electron/", "Electron", "headless", "bot"),

    # -- libraries and command-line tooling -------------------------------
    ("curl/", "curl", "tooling", "bot"),
    ("wget", "Wget", "tooling", "bot"),
    ("python-requests", "python-requests", "tooling", "bot"),
    ("python-urllib", "python-urllib", "tooling", "bot"),
    ("urllib3", "urllib3", "tooling", "bot"),
    ("aiohttp", "aiohttp", "tooling", "bot"),
    ("httpx", "httpx", "tooling", "bot"),
    ("go-http-client", "Go HTTP client", "tooling", "bot"),
    ("fasthttp", "fasthttp", "tooling", "bot"),
    ("okhttp", "OkHttp", "tooling", "bot"),
    ("apache-httpclient", "Apache HttpClient", "tooling", "bot"),
    ("java/", "Java", "tooling", "bot"),
    ("libwww-perl", "libwww-perl", "tooling", "bot"),
    ("lwp::", "libwww-perl", "tooling", "bot"),
    ("guzzlehttp", "Guzzle", "tooling", "bot"),
    ("axios", "axios", "tooling", "bot"),
    ("node-fetch", "node-fetch", "tooling", "bot"),
    ("postmanruntime", "Postman", "tooling", "bot"),
    ("insomnia", "Insomnia", "tooling", "bot"),
    ("restsharp", "RestSharp", "tooling", "bot"),
    ("scrapy", "Scrapy", "tooling", "bot"),
    ("httpie", "HTTPie", "tooling", "bot"),
    ("winhttp", "WinHTTP", "tooling", "bot"),
    ("powershell", "PowerShell", "tooling", "bot"),
    ("wordpress/", "WordPress", "tooling", "bot"),
    ("jetpack", "Jetpack", "tooling", "bot"),
    ("w3c_validator", "W3C Validator", "tooling", "bot"),

    # -- infrastructure ----------------------------------------------------
    ("cloudflare-traffic-manager", "Cloudflare", "infra", "bot"),
    ("cloudflare-healthchecks", "Cloudflare", "infra", "bot"),
    ("cloudflare-ssldetector", "Cloudflare", "infra", "bot"),
    ("amazon cloudfront", "CloudFront", "infra", "bot"),
    ("prerender", "Prerender", "infra", "bot"),
    ("varnish", "Varnish", "infra", "bot"),

    # -- GENERIC TAIL: must stay last -------------------------------------
    # These are last-resort shape tests, and they only fire when the token is
    # not preceded by a letter (see _generic_hit). There is deliberately NO
    # bare "bot" token: it matches the phone "Cubot", the word "Robot", and a
    # long tail of real handsets, and a careless addition here would quietly
    # eat the audience.
    ("bot/", "Unknown bot", "generic", "bot"),
    ("bot;", "Unknown bot", "generic", "bot"),
    ("bot)", "Unknown bot", "generic", "bot"),
    (" bot ", "Unknown bot", "generic", "bot"),
    ("spider", "Unknown spider", "generic", "bot"),
    ("crawler", "Unknown crawler", "generic", "bot"),
    ("scraper", "Unknown scraper", "generic", "bot"),
    ("fetcher", "Unknown fetcher", "generic", "bot"),
    ("http-client", "Unknown HTTP client", "generic", "bot"),
    ("+http", "Unknown bot", "generic", "bot"),
)

# Fast pre-filter. About 99% of human lines fail this single pass and never
# touch the ordered loop. It is NOT used for ordering: a regex alternation
# returns the match that starts EARLIEST in the string, which is not the same
# as "the first entry in SIGNATURES wins" — and getting that wrong is exactly
# the telegrambot/twitterbot bug.
_SIGNATURE_PREFILTER: re.Pattern[str] = re.compile(
    "|".join(re.escape(token) for token, _, _, _ in SIGNATURES)
)

# Crawlers whose operators publish IP ranges. Used ONLY by rule 2: one of
# these arriving from outside Cloudflare on a Cloudflare-proxied site is
# forged, and saying so by name is the point of the bucket.
DECLARED_CRAWLERS: tuple[tuple[str, str], ...] = (
    ("googlebot", "Googlebot"),
    ("google-extended", "Google-Extended"),
    ("googleother", "GoogleOther"),
    ("bingbot", "bingbot"),
    ("msnbot", "msnbot"),
    ("yandexbot", "YandexBot"),
    ("yandeximages", "YandexImages"),
    ("baiduspider", "Baiduspider"),
    ("applebot", "Applebot"),
    ("duckduckbot", "DuckDuckBot"),
    ("petalbot", "PetalBot"),
    ("facebookexternalhit", "facebookexternalhit"),
    ("facebookbot", "FacebookBot"),
    ("meta-external", "Meta"),
    ("telegrambot", "TelegramBot"),
    ("twitterbot", "Twitterbot"),
    ("discordbot", "Discordbot"),
    ("slackbot", "Slackbot"),
    ("linkedinbot", "LinkedInBot"),
    ("pinterestbot", "Pinterestbot"),
    ("ahrefsbot", "AhrefsBot"),
    ("semrushbot", "SemrushBot"),
    ("gptbot", "GPTBot"),
    ("chatgpt-user", "ChatGPT-User"),
    ("oai-searchbot", "OAI-SearchBot"),
    ("claudebot", "ClaudeBot"),
    ("claude-searchbot", "Claude-SearchBot"),
    ("claude-user", "Claude-User"),
    ("anthropic-ai", "Anthropic-AI"),
    ("perplexitybot", "PerplexityBot"),
    ("amazonbot", "Amazonbot"),
    ("bytespider", "Bytespider"),
    ("uptimerobot", "UptimeRobot"),
    ("sogou", "Sogou"),
    ("seznambot", "SeznamBot"),
)

# Excluded BY PATH, never by UA: the monitor wears Chrome/151.0.0.0 and sends
# a real Referer of https://cyberalertx.com/en, roughly 60 times a day.
HEALTH_PATHS: frozenset[str] = frozenset({"/healthz"})

# Paths nobody on this site has ever legitimately requested. `/.well-known/`
# is carved out because ACME renewal lives there.
SCANNER_PATH_RE: re.Pattern[str] = re.compile(
    r"^/\.(?!well-known/)"
    r"|/\.(?:git|env|aws|ssh|svn|hg|vscode|idea|docker|npmrc)(?:/|$|\.)"
    r"|/wp-|/wordpress|/xmlrpc\.php|/wlwmanifest"
    r"|/phpmyadmin|/phpunit|/phpinfo|/pma/|/adminer|/administrator/"
    r"|/cgi-bin/|/vendor/|/laravel|/telescope/|/actuator|/solr/|/druid"
    r"|/manager/html|/jenkins|/hudson|/struts|/boaform|/geoserver"
    r"|/owa/|/autodiscover|/ecp/|/mifs/|/remote/fgt_lang|/\+cscoe\+/"
    r"|/config\.(?:json|php|ya?ml)|/credentials|/id_rsa|/dump\.sql"
    r"|/backup|/shell|/eval-stdin|/setup\.php|/install\.php"
    r"|/debug/default/view|/hnap1|/tmui/|/api/jsonws|/server-status"
    r"|/graphql-?playground|/\.\./|/etc/passwd",
    re.I,
)
# Extensions this site does not serve at all. Next.js renders routes, not
# files; anything asking for one of these is asking for someone else's server.
SCANNER_EXT_RE: re.Pattern[str] = re.compile(
    r"\.(?:php\d?|phtml|asp|aspx|jsp|cgi|pl|sh|bak|old|save|swp|sql"
    r"|zip|tar|tgz|rar|7z|env|ini|conf|cfg|log|ya?ml|pem|key)$",
    re.I,
)

# Feedly, Feedbin, Inoreader, NewsBlur and FeedBurner all embed their reader
# count in the UA. Take the max seen per reader per day and the result is a
# genuine subscriber number — a real audience metric that no amount of
# request counting can produce, since one reader polls ~96 times a day.
SUBSCRIBER_RE: re.Pattern[str] = re.compile(r"(\d+)\s+subscribers?", re.I)

# Agents that fire because a person did something. TelegramBot is the
# exception and gets its own subclass; see agent_subclass.
_REACH_CATEGORIES: frozenset[str] = frozenset({"unfurler"})
_AI_AGENT_LABELS: frozenset[str] = frozenset({
    "ChatGPT-User", "Claude-User", "Perplexity-User", "Amzn-User",
    "MistralAI-User", "Kimi-User", "Manus-User", "NotebookLM",
    "Gemini-Deep-Research", "Operator", "Google Read-Aloud",
})

# next.config.ts 308-redirects the pre-rename /uk locale, so real humans on
# old links generate redirect-only sessions. They are not scanners.
LOCALE_REDIRECT_RE: re.Pattern[str] = re.compile(r"^/uk(/|$)")
_SCANNER_STATUSES: frozenset[int] = frozenset({301, 308, 404})


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _generic_hit(low: str, token: str) -> bool:
    """Match a generic tail token only where a letter does not precede it.

    "Cubot;" contains "bot;" and is a phone. "Robot" contains "bot" and is a
    word. Requiring a non-letter before the token is what keeps the last-resort
    shape tests from eating real handsets.
    """
    start = low.find(token)
    while start != -1:
        if start == 0 or not low[start - 1].isalpha():
            return True
        start = low.find(token, start + 1)
    return False


def classify_user_agent(ua: str | None) -> tuple[str, str, str, str] | None:
    """(label, category, klass, subclass|'') for the first matching SIGNATURES
    entry, or None. Uses a compiled alternation as a fast pre-filter — about
    99% of human lines exit on one pass — then the explicit ordered loop for
    correctness. Do NOT rely on the regex alternation for ordering: it picks
    the match starting EARLIEST in the string, which is not the same as 'first
    entry in SIGNATURES wins'.
    """
    if not ua:
        return None
    low = ua.lower()
    if not _SIGNATURE_PREFILTER.search(low):
        return None
    for token, label, category, klass in SIGNATURES:
        hit = _generic_hit(low, token) if category == "generic" else token in low
        if hit:
            return (label, category, klass, agent_subclass(label, category) or "")
    return None


def declares_crawler(ua: str | None) -> bool:
    """True when the UA names a well-known crawler whose operator publishes IP
    ranges (Googlebot, Bingbot, YandexBot, Baiduspider, Applebot, DuckDuckBot,
    PetalBot, facebookexternalhit, TelegramBot, ...). Used only by rule 2.
    """
    return _crawler_label(ua) is not None


def _crawler_label(ua: str | None) -> str | None:
    """The declared crawler's name, for the forged-crawler label."""
    if not ua:
        return None
    low = ua.lower()
    for token, label in DECLARED_CRAWLERS:
        if token in low:
            return label
    return None


def is_scanner_path(path: str) -> bool:
    """SCANNER_PATH_RE or SCANNER_EXT_RE against the lowercased, query-stripped
    path."""
    if not path:
        return False
    target = path.split("?", 1)[0].lower()
    return bool(SCANNER_PATH_RE.search(target) or SCANNER_EXT_RE.search(target))


def subscriber_count(ua: str) -> int | None:
    """Feedly/Feedbin/Inoreader/NewsBlur/FeedBurner embed 'N subscribers' in
    the UA. Sum the max-seen count per reader per day and you have a genuine
    RSS subscriber number — a real audience metric, not a guess. Highest-value
    single regex in the tool.
    """
    if not ua:
        return None
    match = SUBSCRIBER_RE.search(ua)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:  # pragma: no cover - the group is \d+
        return None


def agent_subclass(label: str, category: str) -> str | None:
    """'self' for TelegramBot; 'reach' for the other unfurlers; 'feed' for feed
    readers; None otherwise.

    The three answer different questions and must never be summed:

      self  TelegramBot counts the site's OWN publishing. Telegram fetches a
            link preview once, when the link is first posted, then serves the
            cached preview to every viewer and every forward. Volume is
            therefore articles published x 2 (EN and UA channels) — a near
            perfect proxy for the cron job and a near useless proxy for reach.
            Useful as an ops signal: if it diverges from the publish count,
            the pipeline broke.
      reach Each hit is one person pasting a link somewhere. For a site whose
            growth depends on forwarding, this is the amplification metric.
      feed  N stable subscribers behind ~96 polls a day. Report subscribers
            and polling frequency, never visits, or Feedly tops the visitor
            table forever.
    """
    if label == "Telegram":
        return "self"
    if category in _REACH_CATEGORIES:
        return "reach"
    if category == "feedreader":
        return "feed"
    if label in _AI_AGENT_LABELS:
        # A person asked an assistant for this page just now. Same meaning as
        # a paste: reach, not audience.
        return "reach"
    return None


# --------------------------------------------------------------------------
# the classification
# --------------------------------------------------------------------------
def classify(record: LogRecord, *, agent: Agent | None = None) -> Verdict:
    """Apply the seven rules, in order. Never raises.

        1. malformed request                 -> bot / malformed
        2. peer outside Cloudflare           -> bot / forged | direct-origin
        3. /healthz                          -> bot / health
        4. scanner path                      -> bot / scanner
        5. UA signature                      -> that entry's klass
        6. empty / stub UA                   -> bot / generic
        7. otherwise                         -> human

    Rule 2 before rule 5 is the whole point: the site is fully Cloudflare
    proxied, so provenance is evidence and the UA string is a claim. Rule 3
    before rule 5 is the health monitor, which claims to be Chrome and is not
    a reader.
    """
    ua = record.user_agent

    if record.malformed_request:
        return Verdict("bot", "Malformed request", "malformed", "malformed", None, None, False)

    peer = record.peer_ip
    if peer is not None and not is_cloudflare_ip(peer):
        label = _crawler_label(ua)
        if label is not None:
            return Verdict("bot", f"Forged {label}", "forged", "forged-crawler", None, None, True)
        return Verdict("bot", "Direct-to-origin", "direct-origin", "cf-provenance", None, None, False)

    path = record.path.split("?", 1)[0]
    normalised = path.rstrip("/").lower() or "/"
    if normalised in HEALTH_PATHS:
        return Verdict("bot", "Health check", "health", "health-path", None, None, False)

    if is_scanner_path(path):
        return Verdict("bot", "Scanner", "scanner", "scanner-path", None, None, False)

    signature = classify_user_agent(ua)
    if signature is not None:
        label, category, klass, subclass = signature
        subscribers = subscriber_count(ua or "") if subclass == "feed" else None
        return Verdict(klass, label, category, "ua-signature", subclass or None, subscribers, False)

    if ua is None or len(ua.strip()) < 12:
        # No real browser has ever sent a UA this short. "-", "", "Mozilla"
        # and a five-character stub are all the same thing.
        return Verdict("bot", "No user agent", "generic", "empty-ua", None, None, False)

    if agent is not None and agent.ua_declares_bot:
        # Corroboration only: the Agent parser saw bot shape that the
        # signature catalogue does not name yet. bots.py stays authoritative.
        return Verdict("bot", "Unknown bot", "generic", "ua-signature", None, None, False)

    return Verdict("human", "Human", "human", "default", None, None, False)


# --------------------------------------------------------------------------
# behavioural heuristics — corroboration only, never a sole basis
# --------------------------------------------------------------------------
# These three read a GROUP of requests, not one request, so none of them can
# live inside `classify` above: `classify` is pure, per-record and its verdict
# is written into the store, where a batch-order-dependent answer could never
# be reproduced by `ingest --reingest`. They are called — when they are called
# at all — from `sessionize.demote_automation`, a whole-window pass in the
# report wiring, over an identity that groups every request sharing one
# user-agent. See the note above each for whether it is live.
#
# WHY TWO OF THE THREE ARE NOT CALLED, measured rather than assumed. A pageview
# requires `method == "GET"` and `status in (200, 304)` (sessionize.is_pageview,
# conditions 1 and 2). `corroborates_monitoring` is true only for an identity
# whose methods are exactly {HEAD}; `corroborates_scanner` only for one whose
# statuses are all in {301, 308, 404}. Both are therefore FALSE BY CONSTRUCTION
# for any identity that produced a single human pageview, so neither can move
# one pageview out of the audience, on this data or any other. Confirmed
# against 15 days of production traffic (75 269 lines): monitoring fires for 10
# identities / 76 requests / 0 human pageviews; scanner fires for 3 570
# identities / 10 619 requests / 0 human pageviews.
#
# They are left uncalled rather than wired up because the only thing wiring
# them could change is a LABEL, and it would change it wrongly: 3 383 of those
# 3 570 scanner-corroborated identities sent a single request, so at
# user-agent scope the rule would demote a reader who followed one broken link
# — precisely the sole-basis use each docstring forbids. They stay here, tested
# and ready, for the day a session type carries `methods` and `statuses` and
# they can corroborate something instead of deciding alone.
def corroborates_monitoring(methods: Sequence[str]) -> bool:
    """True when a session issued nothing but HEAD requests.

    A browser never does this. Corroborating evidence for an unlabelled
    monitor, to be combined with a signature or a path — never used alone to
    demote a session, because a single HEAD from a link checker inside an
    otherwise human session must not delete the reader.

    NOT CALLED. See the block comment above: an identity whose methods are
    exactly {HEAD} has zero pageviews by construction, so this can never
    subtract one. Deliberate, not an oversight.
    """
    seen = {method.upper() for method in methods if method}
    return bool(seen) and seen == {"HEAD"}


def corroborates_scanner(statuses: Sequence[int], paths: Sequence[str]) -> bool:
    """True when a session never reached a real route.

    NOT CALLED. See the block comment above: every status being a 301/308/404
    means no status was a 200 or a 304, so the identity has zero pageviews by
    construction. Deliberate, not an oversight.

    Every status in {301, 308, 404} and no path that the site actually serves.
    308 matters as much as 404: /wp-admin/ returns 308, not 404, because
    Next.js trailing-slash normalisation redirects before anything decides the
    route does not exist, and scanners rarely follow. A 404-only rule misses
    most scanner traffic.

    /uk and /uk/* are whitelisted: next.config.ts permanently redirects the
    old locale, so real humans following old links generate 308s too.
    """
    if not statuses:
        return False
    if not set(statuses).issubset(_SCANNER_STATUSES):
        return False
    for path in paths:
        if LOCALE_REDIRECT_RE.match(path or ""):
            return False
    return True


# The rule name the behavioural pass stamps on a demoted request. Deliberately
# NOT one of the four rules `aggregate.build_report` routes into SECURITY NOISE
# ("cf-provenance", "forged-crawler", "scanner-path", "malformed"): a scraper
# wearing a plausible browser UA is automated traffic, not an attack, and it
# belongs in the automated appendix where the reader can see what was
# subtracted, on what evidence, and disagree with it.
BEHAVIOURAL_RULE: str = "behavioural"
SUSPECTED_AUTOMATION_CATEGORY: str = "suspected-automation"

#: The verdict written over every request of a demoted identity. `forged` stays
#: False — nothing here claimed to be a crawler — so this can never inflate the
#: forged-crawler count, which is a security finding and means something else.
SUSPECTED_AUTOMATION: Verdict = Verdict(
    klass="bot",
    label="Suspected automation",
    category=SUSPECTED_AUTOMATION_CATEGORY,
    rule=BEHAVIOURAL_RULE,
    subclass=None,
    subscribers=None,
    forged=False,
)


def corroborates_scraper(
    *,
    human_pageviews: int,
    asset_requests: int,
    active_days: int,
    min_pageviews: int,
    min_active_days: int,
) -> bool:
    """True when one user-agent identity read pages at volume and NEVER once
    fetched a sub-resource, across the whole observed window.

    This is the live one, and the only member of the trio that can subtract a
    pageview. It is a judgement about a user-agent over a window, never about a
    request, which is why it is not one of `classify`'s seven rules.

    The three conditions are a conjunction and each one is load-bearing:

      asset_requests == 0   CATEGORICAL, not a ratio. A ratio does not separate
                            anything here: 61-64% of ordinary reader
                            user-agents on this origin also sit at exactly 0.00,
                            because Cloudflare serves /_next/static from the
                            edge and the browser cache serves it again. One
                            single asset fetch anywhere in the window PROVES a
                            browser and ends the matter.
      human_pageviews >=    The floor that turns "no assets" from the norm into
      min_pageviews         a finding. Measured over 15 days: the largest
                            innocent zero-asset user-agent held 42 pageviews,
                            the smaller of the two confirmed scraper pools 415
                            — a 9.9x gap with nothing inside it. The default
                            floor of 100 sits near the log-midpoint of the
                            interval that stays safe at every window length
                            from ten days up, 2.4x above the innocent maximum
                            and 2.6x below the weakest detection.
      active_days >=        A human binge is one to three days. Both pools ran
      min_active_days       15 days out of 15. This is what stops a single
                            heavy reading session from being read as a crawl.

    FAILS OPEN. Everything it cannot prove stays audience: a low-volume
    user-agent that fetches no asset is a returning reader with a warm cache
    and is never demoted, and one asset fetch exempts an identity entirely.
    The inverse is never applied — fetching assets does NOT whitelist a
    declared crawler, because Baiduspider-render demonstrably fetches
    /_next/static/chunks/*.js and the signature catalogue outranks this.

    FAILURE MODE, stated so it can be designed around rather than discovered:
    a scraper that fetches one asset per window defeats this test completely.
    """
    if min_pageviews < 1:
        # A floor of zero would demote every warm-cache reader on the site.
        # Refuse rather than obey.
        return False
    return (
        asset_requests == 0
        and human_pageviews >= min_pageviews
        and active_days >= min_active_days
    )
