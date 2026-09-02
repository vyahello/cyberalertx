"""Human / agent / bot classification — `server/analytics/bots.py`.

IN SCOPE: the seven classification rules and the order they must fire in.
Cloudflare provenance comes BEFORE any User-Agent test (D2), because the site
is fully proxied: a request whose socket peer is outside Cloudflare's published
ranges never traversed Cloudflare and is a direct-to-origin probe, whatever its
UA claims. A declared crawler arriving that way is forged (D3) and gets its own
bucket. /healthz is excluded by PATH (D5), never by UA, because the monitor
wears Chrome/151 and a real Referer.

DELIBERATELY NOT IN SCOPE: UA field extraction (test_analytics_useragent.py)
and pageview filtering (test_analytics_sessionize.py).

FIXTURES: lines are built with the shared builders. Cloudflare edge addresses
are real, because CF provenance is the thing under test and an edge address
identifies Cloudflare rather than a person; every other address is from a
documentation range.
"""
from __future__ import annotations

import ipaddress

import pytest

from server.analytics.bots import (
    BEHAVIOURAL_RULE,
    CLOUDFLARE_IPV4,
    CLOUDFLARE_IPV6,
    HEALTH_PATHS,
    SUSPECTED_AUTOMATION,
    Verdict,
    agent_subclass,
    classify,
    classify_user_agent,
    corroborates_monitoring,
    corroborates_scanner,
    corroborates_scraper,
    declares_crawler,
    is_cloudflare_ip,
    is_scanner_path,
    subscriber_count,
)
from tests.test_analytics_logread import (
    ANDROID_CHROME_UA,
    CF_EDGE_IP,
    DIRECT_ORIGIN_IP,
    extended_line,
    legacy_line,
    parse,
)
from tests.test_analytics_useragent import BROWSER_UAS

GOOGLEBOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
HEALTH_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)
ARTICLE_PATH = "/en/threat/e50e48c737157f8a"


def _verdict(**over: object) -> Verdict:
    """Classify one extended line. Defaults are a proxied human on an article."""
    over.setdefault("pip", CF_EDGE_IP)
    over.setdefault("u", ARTICLE_PATH)
    return classify(parse(extended_line(**over)))


# --------------------------------------------------------------------------
# rule order — the contract
# --------------------------------------------------------------------------

def test_a_forged_googlebot_is_caught_by_provenance_before_the_ua_table() -> None:
    """2 986 requests in one day claimed Googlebot from a single non-Google,
    non-Cloudflare address while fetching /wp-config.php and /.env. A UA-first
    classifier files every one of them under "search engine crawler"."""
    verdict = _verdict(pip=DIRECT_ORIGIN_IP, ua=GOOGLEBOT_UA, u="/.git/index", st="404")
    assert verdict.klass == "bot"
    assert verdict.category == "forged"
    assert verdict.rule == "forged-crawler"
    assert verdict.forged is True


def test_a_googlebot_arriving_through_cloudflare_is_a_real_crawler() -> None:
    verdict = _verdict(ua=GOOGLEBOT_UA)
    assert verdict.klass == "bot"
    assert verdict.category == "search"
    assert verdict.rule == "ua-signature"
    assert verdict.forged is False


def test_any_browser_from_outside_cloudflare_is_a_direct_to_origin_probe() -> None:
    """79.4% of one measured day. cyberalertx is the effective default server,
    so every IP-direct scan on the box lands here."""
    verdict = _verdict(pip=DIRECT_ORIGIN_IP, ua=ANDROID_CHROME_UA)
    assert verdict.klass == "bot"
    assert verdict.category == "direct-origin"
    assert verdict.rule == "cf-provenance"
    assert verdict.forged is False


def test_a_malformed_request_is_classified_before_provenance_is_consulted() -> None:
    record = parse(
        legacy_line(ip=DIRECT_ORIGIN_IP, request=r"\x16\x03\x01\x05\xA8",
                    status=400, bytes=166, ua="-")
    )
    verdict = classify(record)
    assert verdict.rule == "malformed"
    assert verdict.category == "malformed"
    assert verdict.klass == "bot"


def test_provenance_is_checked_before_the_health_path() -> None:
    """Rule 2 precedes rule 3: a /healthz that bypassed Cloudflare is not our
    monitor, it is somebody probing the origin directly."""
    verdict = _verdict(pip=DIRECT_ORIGIN_IP, u="/healthz", ua=HEALTH_UA)
    assert verdict.rule == "cf-provenance"


def test_the_health_monitor_is_excluded_by_path_never_by_ua() -> None:
    """D5: it wears Chrome/151 and Referer https://cyberalertx.com/en, and it
    fires ~60x/day. UA-based filtering counts it as a person."""
    verdict = _verdict(u="/healthz", ua=HEALTH_UA, ref="https://cyberalertx.com/en")
    assert verdict.klass == "bot"
    assert verdict.category == "health"
    assert verdict.rule == "health-path"
    assert "/healthz" in HEALTH_PATHS


@pytest.mark.parametrize(
    "path",
    [
        "/wp-config.php",       # the single most probed path on the internet
        "/.env",                # credential harvesting
        "/.git/index",          # source disclosure
        "/wp-admin/setup-config.php",
        "/phpmyadmin/index.php",
        "/vendor/phpunit/phpunit/phpunit.xml",
        "/.aws/credentials",
    ],
)
def test_scanner_paths_are_scanners_even_behind_a_browser_ua(path: str) -> None:
    verdict = _verdict(u=path, ua=ANDROID_CHROME_UA, st="404")
    assert verdict.klass == "bot"
    assert verdict.category == "scanner"
    assert verdict.rule == "scanner-path"
    assert is_scanner_path(path) is True


@pytest.mark.parametrize("path", ["/en", "/ua", ARTICLE_PATH, "/en/feed.xml", "/uk"])
def test_real_routes_are_not_scanner_paths(path: str) -> None:
    assert is_scanner_path(path) is False


@pytest.mark.parametrize("ua", ["", "-", "abcde", "  ", "x"])
def test_an_absent_or_stub_user_agent_is_generic_automation(ua: str) -> None:
    verdict = _verdict(ua=ua)
    assert verdict.klass == "bot"
    assert verdict.category == "generic"
    assert verdict.rule == "empty-ua"


def test_a_proxied_browser_reading_an_article_is_human() -> None:
    verdict = _verdict(ua=ANDROID_CHROME_UA)
    assert verdict.klass == "human"
    assert verdict.category == "human"
    assert verdict.rule == "default"
    assert verdict.forged is False


# --------------------------------------------------------------------------
# signature ordering traps
# --------------------------------------------------------------------------

def test_telegrambot_is_telegram_and_never_twitter() -> None:
    """Telegram's fetcher UA is literally "TelegramBot (like TwitterBot)".
    Matching twitterbot first attributes this site's entire primary
    distribution channel to Twitter — the same bug Cloudflare's own analytics
    ships. For a Telegram-first site it is the most damaging mis-ordering
    available."""
    verdict = _verdict(ua="TelegramBot (like TwitterBot)")
    assert verdict.label == "Telegram"
    assert "witter" not in verdict.label
    assert verdict.klass == "agent"
    assert verdict.subclass == "self"


@pytest.mark.parametrize(
    "specific, general",
    [
        # Apple's AI-training crawler is not Apple's search crawler.
        ("Mozilla/5.0 (compatible; Applebot-Extended/1.0; +http://www.apple.com/go/applebot)",
         "Mozilla/5.0 (compatible; Applebot/0.1; +http://www.apple.com/go/applebot)"),
        # GoogleOther is a product-team fetcher, not the search index.
        ("Mozilla/5.0 (compatible; GoogleOther/1.0; +http://www.google.com/bot.html)",
         GOOGLEBOT_UA),
        # The OCOB variant is an AI crawler; plain SemrushBot is SEO.
        ("Mozilla/5.0 (compatible; SemrushBot-OCOB/1.0; +http://www.semrush.com/bot.html)",
         "Mozilla/5.0 (compatible; SemrushBot/7~bl; +http://www.semrush.com/bot.html)"),
        # An externalfetcher is one person asking; an externalagent is a crawler.
        ("meta-externalfetcher/1.1", "meta-externalagent/1.1"),
        # And the same shape for Yandex.
        ("Mozilla/5.0 (compatible; YandexAdditional/3.0; +http://yandex.com/bots)",
         "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)"),
    ],
)
def test_the_specific_signature_is_not_swallowed_by_its_own_prefix(
    specific: str, general: str
) -> None:
    specific_hit = classify_user_agent(specific)
    general_hit = classify_user_agent(general)
    assert specific_hit is not None
    assert general_hit is not None
    assert specific_hit[0] != general_hit[0]      # different labels


def test_facebook_unfurler_and_facebook_ai_crawler_are_different_bots() -> None:
    """facebookexternalhit fires when a person shares a link; facebookbot is an
    AI training crawler. Merging them turns share events into crawl volume."""
    unfurler = _verdict(ua="facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)")
    crawler = _verdict(ua="facebookbot/1.0 (+https://developers.facebook.com/docs/sharing/webmasters/facebookbot)")
    assert unfurler.label != crawler.label
    assert unfurler.klass != crawler.klass
    assert unfurler.klass == "agent"
    assert crawler.klass == "bot"


def test_headless_chrome_is_tested_before_anything_concludes_chrome_means_human() -> None:
    verdict = _verdict(
        ua="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
           "HeadlessChrome/143.0.0.0 Safari/537.36"
    )
    assert verdict.klass == "bot"
    assert verdict.category == "headless"


@pytest.mark.parametrize(
    "ua, label_fragment",
    [
        ("Twitterbot/1.0", "witter"),
        ("Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)", "iscord"),
        ("LinkedInBot/1.0 (compatible; Mozilla/5.0; Jakarta Commons-HttpClient/3.1)", "inked"),
    ],
)
def test_link_unfurlers_are_reach_because_each_hit_is_a_person_sharing(
    ua: str, label_fragment: str
) -> None:
    verdict = _verdict(ua=ua)
    assert verdict.klass == "agent"
    assert verdict.subclass == "reach"
    assert label_fragment in verdict.label


def test_a_feed_reader_reports_its_subscriber_count() -> None:
    """The highest-value single regex in the tool: a real audience number that
    needs no identity at all."""
    ua = ("Feedly/1.0 (+http://www.feedly.com/fetcher.html; 47 subscribers; "
          "like FeedFetcher-Google)")
    verdict = _verdict(ua=ua, u="/en/feed.xml")
    assert verdict.klass == "agent"
    assert verdict.subclass == "feed"
    assert verdict.subscribers == 47
    assert subscriber_count(ua) == 47
    assert subscriber_count(ANDROID_CHROME_UA) is None


def test_baiduspider_render_fetches_assets_and_is_still_a_bot() -> None:
    """D4: "bots do not load assets" is false on this site — this exact crawler
    fetches /_next/static/chunks/*.js. Asset loading is not a humanity signal."""
    verdict = _verdict(
        u="/_next/static/chunks/244-f5cb5de441ba2ebb.js",
        ua="Mozilla/5.0 (compatible; Baiduspider-render/2.0; "
           "+http://www.baidu.com/search/spider.html)",
    )
    assert verdict.klass == "bot"


def test_the_generic_tail_never_eats_a_real_browser() -> None:
    """Parametrised over every browser UA in the useragent suite. A careless
    addition to the tail tokens (a bare "bot" matches "Cubot") would silently
    delete the audience, and this is the guard."""
    for ua in BROWSER_UAS:
        verdict = _verdict(ua=ua)
        assert verdict.klass == "human", ua


def test_agent_subclass_splits_self_reach_and_feed() -> None:
    assert agent_subclass("Telegram", "unfurler") == "self"
    assert agent_subclass("Twitter", "unfurler") == "reach"
    assert agent_subclass("Feedly", "feedreader") == "feed"
    assert agent_subclass("Googlebot", "search") is None


# --------------------------------------------------------------------------
# Cloudflare provenance
# --------------------------------------------------------------------------

def test_the_published_cloudflare_ranges_are_all_present() -> None:
    assert len(CLOUDFLARE_IPV4) == 15
    assert len(CLOUDFLARE_IPV6) == 7
    # The ranges the site's own traffic actually arrives on.
    for cidr in ("162.158.0.0/15", "172.64.0.0/13", "104.16.0.0/13", "141.101.64.0/18"):
        assert cidr in CLOUDFLARE_IPV4


def test_every_cidr_matches_at_its_first_and_last_address() -> None:
    """Off-by-one in a network boundary silently reclassifies real visitors as
    direct-to-origin probes and deletes them from the audience."""
    for cidr in CLOUDFLARE_IPV4 + CLOUDFLARE_IPV6:
        network = ipaddress.ip_network(cidr)
        assert is_cloudflare_ip(str(network[0])) is True, cidr
        assert is_cloudflare_ip(str(network[-1])) is True, cidr


@pytest.mark.parametrize(
    "value",
    [
        "203.0.113.1",       # documentation range, definitively not Cloudflare
        "198.51.100.6",
        "192.0.2.10",
        "2001:db8::1",       # the IPv6 documentation range
        None,                # a legacy line with no address at all
        "not-an-ip",         # never raises on garbage
        "",
        "162.158.0.0/15",    # a CIDR string is not an address
    ],
)
def test_non_cloudflare_input_is_rejected_without_raising(value: str | None) -> None:
    assert is_cloudflare_ip(value) is False


def test_declares_crawler_names_only_operators_that_publish_ip_ranges() -> None:
    assert declares_crawler(GOOGLEBOT_UA) is True
    assert declares_crawler("Mozilla/5.0 (compatible; bingbot/2.0; "
                            "+http://www.bing.com/bingbot.htm)") is True
    assert declares_crawler("TelegramBot (like TwitterBot)") is True
    assert declares_crawler(ANDROID_CHROME_UA) is False
    assert declares_crawler(None) is False


def test_classification_works_identically_on_legacy_lines() -> None:
    """C.6: logread sets peer_ip = client_ip on legacy records, so the
    strongest filter on the site runs on 14 days of existing history with no
    nginx change at all."""
    proxied = classify(parse(legacy_line(ip=CF_EDGE_IP, path=ARTICLE_PATH)))
    direct = classify(parse(legacy_line(ip=DIRECT_ORIGIN_IP, path=ARTICLE_PATH)))
    assert proxied.klass == "human"
    assert direct.klass == "bot"
    assert direct.rule == "cf-provenance"


# --------------------------------------------------------------------------
# the behavioural corroborators
# --------------------------------------------------------------------------
# `corroborates_scraper` is a judgement about ONE USER-AGENT ACROSS A WINDOW,
# not about a request, which is why it is not one of classify()'s seven rules
# and why it is tested here as a pure function. The end-to-end effect on an
# audience number is tested in test_analytics_aggregate.py.

#: The forged user-agent that actually did this on 15 days of production
#: traffic: iOS 13.2.3 shipped in 2019, it arrived through Cloudflare on 788
#: edge addresses, hit 380 paths, and never once fetched a /_next/ chunk.
SCRAPER_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 "
    "Mobile/15E148 Safari/604.1"
)


def _scraper(**over: object) -> bool:
    """The rule at its shipped thresholds, unless a test says otherwise."""
    kwargs: dict[str, object] = {
        "human_pageviews": 1442,
        "asset_requests": 0,
        "active_days": 15,
        "min_pageviews": 100,
        "min_active_days": 5,
    }
    kwargs.update(over)
    return corroborates_scraper(**kwargs)  # type: ignore[arg-type]


def test_volume_plus_categorically_zero_assets_convicts() -> None:
    """The measured case: 1 442 pageviews, 15 days, not one sub-resource."""
    assert _scraper() is True


def test_a_warm_cache_returning_reader_is_never_demoted() -> None:
    """THE expensive direction. On this origin 61-64% of ordinary readers fetch
    no asset at all — Cloudflare serves /_next/static from the edge and the
    browser cache serves it again — so "no assets" at low volume is the NORMAL
    condition of a returning reader. 42 pageviews was the largest innocent
    zero-asset user-agent measured over 15 days; it must survive untouched."""
    assert _scraper(human_pageviews=42) is False
    assert _scraper(human_pageviews=99) is False


def test_one_asset_fetch_exempts_an_agent_however_much_it_read() -> None:
    """Fetching an asset PROVES a browser, so the test is categorical rather
    than a ratio: a single fetch anywhere in the window ends the matter, even
    against a user-agent with ten times the threshold in pageviews."""
    assert _scraper(asset_requests=1) is False
    assert _scraper(human_pageviews=100_000, asset_requests=1) is False


def test_a_two_day_binge_is_reading_not_crawling() -> None:
    """A human can read a hundred pages in a weekend. Both real scraper pools
    ran 15 days out of 15."""
    assert _scraper(active_days=2) is False
    assert _scraper(active_days=5) is True


def test_a_threshold_below_one_is_refused_rather_than_obeyed() -> None:
    """A floor of zero would demote every reader whose browser cache spared the
    origin. The function refuses instead of doing what it was told."""
    assert _scraper(min_pageviews=0) is False
    assert _scraper(min_pageviews=-1) is False


def test_the_demotion_verdict_is_a_bot_that_never_claimed_to_be_a_crawler() -> None:
    """`forged` must stay False: forged-crawler is a security finding about
    somebody impersonating Google, and a scraper wearing an old iPhone UA is
    not that. Its rule must also differ from the four that `aggregate` routes
    into SECURITY NOISE, or the demoted traffic is dropped before the appendix
    that is supposed to name it."""
    assert SUSPECTED_AUTOMATION.klass == "bot"
    assert SUSPECTED_AUTOMATION.forged is False
    assert SUSPECTED_AUTOMATION.rule == BEHAVIOURAL_RULE
    assert SUSPECTED_AUTOMATION.rule not in (
        "cf-provenance", "forged-crawler", "scanner-path", "malformed",
    )


def test_the_two_unwired_corroborators_cannot_touch_anything_that_reads() -> None:
    """WHY THEY ARE NOT CALLED, pinned as a test rather than left as a comment.

    A pageview requires GET and a 200/304 (sessionize.is_pageview, conditions 1
    and 2). `corroborates_monitoring` is true only for {HEAD}; `corroborates_scanner`
    only when every status is a 301/308/404. Both are therefore false by
    construction for any client that read a single page, so neither can subtract
    a pageview — on this data or any other. If this test ever fails, wiring them
    into `demote_automation` becomes worth revisiting.
    """
    assert corroborates_monitoring(["HEAD"]) is True
    assert corroborates_monitoring(["HEAD", "GET"]) is False
    assert corroborates_scanner([404, 308], ["/wp-admin/", "/.env"]) is True
    assert corroborates_scanner([404, 200], ["/wp-admin/", ARTICLE_PATH]) is False
    assert corroborates_scanner([304], [ARTICLE_PATH]) is False
