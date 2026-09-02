"""User-Agent and Accept-Language parsing — `server/analytics/useragent.py`.

IN SCOPE: the browser precedence chain, Android model extraction (including
the "K" placeholder that ships a phantom #1 handset in naive tools), OS
precedence and frozen-version honesty, device typing, the three in-app WebView
escape hatches, client-hint override, and RFC 9110 language preference lists.

DELIBERATELY NOT IN SCOPE: whether a UA belongs to a bot. `parse_user_agent`
sets only the coarse `ua_declares_bot` shape signal; `bots.py` is authoritative
and is tested in test_analytics_bots.py.

FIXTURES: UA strings are transcribed by hand, anonymised where they carried an
address. Nothing is read from disk.
"""
from __future__ import annotations

import pytest

from server.analytics.useragent import (
    PLACEHOLDER_MODELS,
    UNKNOWN_AGENT,
    android_model,
    clean_model,
    marketing_name,
    parse_accept_language,
    parse_user_agent,
    primary_language,
    primary_region,
    vendor_for_model,
    windows_version,
)

# --------------------------------------------------------------------------
# the thirteen UA strings, each one breaking a naive parser
# --------------------------------------------------------------------------

EDGE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0"
)
OPERA_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 OPR/129.0.0.0"
)
SAMSUNG_UA = (
    "Mozilla/5.0 (Linux; Android 13; SAMSUNG SM-S918B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) SamsungBrowser/23.0 Chrome/115.0.0.0 Mobile Safari/537.36"
)
ANDROID_K_MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Mobile Safari/537.36"
)
ANDROID_K_TABLET_UA = (
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)
ANCIENT_ANDROID_UA = (
    "Mozilla/5.0 (Linux; U; Android 4.4.2; uk-ua; SM-G900F Build/KOT49H) "
    "AppleWebKit/534.30 (KHTML, like Gecko) Version/4.0 Mobile Safari/534.30"
)
MAC_SAFARI_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.6 Safari/605.1.15"
)
TELEGRAM_ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/143.0.0.0 Mobile Safari/537.36 Telegram-Android/11.9.0 "
    "(Samsung SM-A155M; Android 14; SDK 34; AVERAGE)"
)
CHROME_IOS_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) CriOS/143.0.0.0 Mobile/15E148 Safari/604.1"
)
LINUX_DESKTOP_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)
FIREFOX_ANDROID_UA = (
    "Mozilla/5.0 (Android 14; Mobile; rv:143.0) Gecko/143.0 Firefox/143.0"
)
FACEBOOK_IOS_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/21F90 "
    "[FBAN/FBIOS;FBDV/iPhone14,3;FBMD/iPhone;FBSN/iOS;FBSV/17.5.1;FBSS/3;"
    "FBID/phone;FBLC/en_US;FBOP/5]"
)
ANDROID_WEBVIEW_UA = (
    "Mozilla/5.0 (Linux; Android 14; SM-A155M Build/UP1A.231005.007; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/143.0.0.0 "
    "Mobile Safari/537.36"
)
IPHONE_SAFARI_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 "
    "Safari/604.1"
)

#: Every real-browser UA in this file. test_analytics_bots.py imports this and
#: asserts each one classifies as human, so a careless addition to the generic
#: bot tail tokens cannot silently eat the audience.
BROWSER_UAS: tuple[str, ...] = (
    EDGE_UA,
    OPERA_UA,
    SAMSUNG_UA,
    ANDROID_K_MOBILE_UA,
    ANDROID_K_TABLET_UA,
    ANCIENT_ANDROID_UA,
    MAC_SAFARI_UA,
    TELEGRAM_ANDROID_UA,
    CHROME_IOS_UA,
    LINUX_DESKTOP_UA,
    FIREFOX_ANDROID_UA,
    FACEBOOK_IOS_UA,
    ANDROID_WEBVIEW_UA,
)


# --------------------------------------------------------------------------
# browser precedence — first match wins, most specific first
# --------------------------------------------------------------------------

def test_edge_is_edge_not_chrome_and_not_safari() -> None:
    """Edge's UA contains both Chrome/ and Safari/. Edg/ must be tested first."""
    agent = parse_user_agent(EDGE_UA)
    assert agent.browser_family == "Edge"
    assert agent.browser_version == "143"
    assert agent.os_family == "Windows"
    assert agent.device_type == "desktop"


def test_opera_is_opera_not_chrome() -> None:
    agent = parse_user_agent(OPERA_UA)
    assert agent.browser_family == "Opera"
    assert agent.browser_version == "129"


def test_samsung_internet_wins_over_chrome_and_the_vendor_prefix_is_stripped() -> None:
    agent = parse_user_agent(SAMSUNG_UA)
    assert agent.browser_family == "Samsung Internet"
    assert agent.device_vendor == "Samsung"
    assert agent.device_model_raw == "SM-S918B"      # "SAMSUNG " prefix removed
    assert agent.device_model == "Galaxy S23 Ultra"  # mapped, not a bare code
    assert agent.device_type == "mobile"


def test_the_letter_k_is_a_placeholder_and_never_a_device_called_k() -> None:
    """Chromium's UA reduction replaced the model with a literal "K". Tools
    that take it at face value publish a phantom #1 handset called K."""
    agent = parse_user_agent(ANDROID_K_MOBILE_UA)
    assert agent.device_model is None
    assert agent.device_model_raw is None
    assert agent.os_family == "Android"
    assert agent.os_version_reliable is False   # "Android 10" is frozen too
    assert agent.device_type == "mobile"
    assert "K" in PLACEHOLDER_MODELS


def test_android_without_the_mobile_token_is_a_tablet() -> None:
    """Chromium's own convention: no `Mobile` token means a large screen."""
    agent = parse_user_agent(ANDROID_K_TABLET_UA)
    assert agent.device_type == "tablet"


def test_the_ancient_android_model_is_the_build_token_not_the_locale() -> None:
    """`Linux; U; Android 4.4.2; uk-ua; SM-G900F Build/KOT49H` — taking the
    last-but-one token gives the locale, and a phantom device named uk-ua."""
    agent = parse_user_agent(ANCIENT_ANDROID_UA)
    assert agent.device_model_raw == "SM-G900F"
    assert (agent.device_model or "").lower() != "uk-ua"
    assert agent.os_family == "Android"
    assert agent.os_version == "4.4.2"
    assert agent.os_version_reliable is True    # a genuine version, not frozen


def test_macos_safari_reports_no_os_version_because_apple_froze_it() -> None:
    agent = parse_user_agent(MAC_SAFARI_UA)
    assert agent.browser_family == "Safari"
    assert agent.browser_version == "18"
    assert agent.os_family == "macOS"
    assert agent.os_version is None            # 10_15_7 is frozen, not real
    assert agent.os_version_reliable is False
    assert agent.device_type == "desktop"


def test_telegram_webview_recovers_vendor_model_and_the_true_android_version() -> None:
    """The highest-value branch in the module: Telegram is this site's primary
    distribution channel, and its block carries what UA reduction removed."""
    agent = parse_user_agent(TELEGRAM_ANDROID_UA)
    assert agent.in_app == "Telegram"
    assert agent.browser_family == "Chrome"     # in_app is NOT the browser
    assert agent.device_vendor == "Samsung"
    assert agent.device_model_raw == "SM-A155M"
    assert agent.device_model == "Galaxy A15"
    assert agent.os_version == "14"             # overrides the frozen "Android 10"
    assert agent.os_version_reliable is True
    assert agent.model_source == "telegram"
    assert agent.is_webview is True


def test_chrome_on_ios_is_chrome() -> None:
    agent = parse_user_agent(CHROME_IOS_UA)
    assert agent.browser_family == "Chrome"
    assert agent.os_family == "iOS"
    assert agent.os_version == "18.6"
    assert agent.device_type == "mobile"


def test_x11_linux_is_a_desktop() -> None:
    # It may also be an Android phone in "request desktop site" mode; only
    # Sec-CH-UA-Mobile can tell, and that exists on extended lines only.
    agent = parse_user_agent(LINUX_DESKTOP_UA)
    assert agent.os_family == "Linux"
    assert agent.device_type == "desktop"
    assert agent.device_model is None


def test_firefox_on_android_reports_a_real_os_version() -> None:
    """Gecko never froze the Android version, so this one is trustworthy."""
    agent = parse_user_agent(FIREFOX_ANDROID_UA)
    assert agent.browser_family == "Firefox"
    assert agent.os_family == "Android"
    assert agent.os_version == "14"
    assert agent.os_version_reliable is True
    assert agent.device_model is None
    assert agent.device_type == "mobile"


def test_facebook_ios_block_is_the_only_route_to_an_iphone_model() -> None:
    agent = parse_user_agent(FACEBOOK_IOS_UA)
    assert agent.in_app == "Facebook"
    assert agent.model_source == "facebook"
    assert agent.os_family == "iOS"
    assert agent.os_version == "17.5.1"         # FBSV, not the frozen UA value
    assert agent.device_model_raw == "iPhone14,3"
    assert agent.is_webview is True


@pytest.mark.parametrize(
    "ua",
    [
        # An unfurler wearing a complete browser UA except for its own token.
        "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        # Headless Chrome differs from Chrome by one word.
        ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
         "HeadlessChrome/143.0.0.0 Safari/537.36"),
    ],
)
def test_a_declared_bot_short_circuits_the_precedence_chain(ua: str) -> None:
    assert parse_user_agent(ua).ua_declares_bot is True


def test_a_real_browser_never_declares_itself_a_bot() -> None:
    for ua in BROWSER_UAS:
        assert parse_user_agent(ua).ua_declares_bot is False


# --------------------------------------------------------------------------
# the traps that are not on the numbered list
# --------------------------------------------------------------------------

def test_version_4_0_on_android_is_a_webview_marker_not_a_safari_version() -> None:
    """`Version/` is only a Safari version on Apple platforms."""
    agent = parse_user_agent(ANDROID_WEBVIEW_UA)
    assert agent.browser_family == "Chrome"
    assert agent.browser_version == "143"
    assert agent.is_webview is True
    assert agent.device_model_raw == "SM-A155M"


def test_windows_nt_10_is_reported_as_10_slash_11_never_as_10() -> None:
    """Microsoft froze the token at 10.0 for Windows 11. Claiming "10" would
    silently misreport every Windows 11 reader."""
    agent = parse_user_agent(EDGE_UA)
    assert agent.os_version == "10/11"
    assert agent.os_version_reliable is False


@pytest.mark.parametrize(
    "platform_version, expected",
    [
        ("15.0.0", "Windows 11"),   # >= 13 is Windows 11 — THRESHOLD UNVERIFIED
        ("13.0.0", "Windows 11"),   # the documented boundary itself
        ("10.0.0", "Windows 10"),
        ("0.3.0", "Windows (older)"),   # 7/8.x report a 0.x platform version
        (None, None),
        ("", None),
        ("garbage", None),          # never raises on a header a client wrote
    ],
)
def test_windows_version_splits_10_from_11_via_the_platform_hint(
    platform_version: str | None, expected: str | None
) -> None:
    assert windows_version(platform_version) == expected


def test_client_hints_override_the_ua_and_say_so() -> None:
    agent = parse_user_agent(
        ANDROID_K_MOBILE_UA,
        ch_platform="Android",
        ch_platform_version="15",
        ch_mobile=True,
        ch_model="SM-S928B",
        ch_available=True,
    )
    assert agent.model_source == "client-hint"
    assert agent.device_model_raw == "SM-S928B"
    assert agent.os_version == "15"
    assert agent.os_version_reliable is True
    assert agent.device_type == "mobile"


def test_a_hint_sending_browser_with_an_empty_model_is_desktop_not_unknown() -> None:
    """escape=json turns a missing header into "", so absent and empty look
    alike in the log. ch_available recovers the distinction: hints present with
    an empty model is desktop Chromium, which genuinely has no model."""
    agent = parse_user_agent(
        EDGE_UA,
        ch_platform="Windows",
        ch_platform_version="15.0.0",
        ch_mobile=False,
        ch_model="",
        ch_available=True,
    )
    assert agent.device_type == "desktop"
    assert agent.device_model is None


def test_missing_and_empty_user_agents_return_the_singleton() -> None:
    assert parse_user_agent(None) is UNKNOWN_AGENT
    assert parse_user_agent("") is UNKNOWN_AGENT
    assert UNKNOWN_AGENT.browser_family == "Other"
    assert UNKNOWN_AGENT.device_type == "unknown"


def test_parsing_is_memoised_because_a_handful_of_strings_cover_most_lines() -> None:
    assert parse_user_agent(EDGE_UA) is parse_user_agent(EDGE_UA)


@pytest.mark.parametrize(
    "ua",
    [
        "",
        "-",
        "\\x16\\x03\\x01",                     # TLS bytes in the UA field
        "Mozilla/5.0 (" * 400,                # pathological repetition
        "Mozilla/5.0 (Linux; Android",        # truncated mid-block
        "(((((;;;;;)))))",
    ],
)
def test_the_ua_parser_never_raises_on_any_input(ua: str) -> None:
    agent = parse_user_agent(ua)
    assert agent.browser_family is not None


# --------------------------------------------------------------------------
# model helpers
# --------------------------------------------------------------------------

def test_android_model_prefers_the_build_token() -> None:
    assert (android_model(ANCIENT_ANDROID_UA) or "").startswith("SM-G900F")
    assert (android_model(ANDROID_WEBVIEW_UA) or "").startswith("SM-A155M")
    assert android_model(LINUX_DESKTOP_UA) is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("SAMSUNG SM-S918B", "SM-S918B"),     # vendor prefix stripped
        ("SM-A155M Build/UP1A.231005.007", "SM-A155M"),  # Build/ onward dropped
        ("K", None),                          # the reduction placeholder
        ("wv", None),                         # the webview token, not a model
        ("Mobile", None),
        ("uk-ua", None),                      # locale-shaped, from ancient UAs
        ("", None),
    ],
)
def test_clean_model_rejects_everything_meaningless(
    raw: str, expected: str | None
) -> None:
    assert clean_model(raw) == expected


def test_marketing_name_maps_a_code_and_admits_when_it_cannot() -> None:
    assert marketing_name("SM-A155M") == "Galaxy A15"
    assert marketing_name("sm-s918b") == "Galaxy S23 Ultra"   # case-insensitive
    assert marketing_name("ZZ-NOTATHING") is None


def test_vendor_for_model_scans_prefixes_longest_first() -> None:
    assert vendor_for_model("SM-A155M") == "Samsung"
    assert vendor_for_model("ZZ-NOTATHING") is None


# --------------------------------------------------------------------------
# Accept-Language
# --------------------------------------------------------------------------

def test_accept_language_keeps_the_order_the_header_declares() -> None:
    header = "uk-UA,uk;q=0.9,ru;q=0.8,en-US;q=0.7,en;q=0.6"
    assert parse_accept_language(header) == [
        ("uk-ua", 1.0),
        ("uk", 0.9),
        ("ru", 0.8),
        ("en-us", 0.7),
        ("en", 0.6),
    ]
    assert primary_language(header) == "uk"
    assert primary_region(header) == "UA"


def test_a_missing_q_defaults_to_one_and_therefore_sorts_first() -> None:
    parsed = parse_accept_language("en;q=0.5,uk")
    assert parsed[0] == ("uk", 1.0)
    assert parsed[1] == ("en", 0.5)


def test_q_zero_means_not_acceptable_and_is_dropped_not_counted() -> None:
    parsed = parse_accept_language("uk;q=0.9,ru;q=0")
    assert parsed == [("uk", 0.9)]


def test_the_wildcard_is_skipped() -> None:
    parsed = parse_accept_language("uk,*;q=0.5")
    assert [tag for tag, _ in parsed] == ["uk"]


def test_equal_q_ties_keep_header_order() -> None:
    """A stable sort, so the header's own preference survives."""
    parsed = parse_accept_language("de;q=0.8,uk;q=0.8,en;q=0.8")
    assert [tag for tag, _ in parsed] == ["de", "uk", "en"]


def test_a_safari_style_bare_tag_parses() -> None:
    assert parse_accept_language("uk-ua") == [("uk-ua", 1.0)]
    assert primary_language("uk-ua") == "uk"
    assert primary_region("uk-ua") == "UA"


@pytest.mark.parametrize("value", [None, "", "-", ";;;", "q=", "en;q=notanumber"])
def test_accept_language_never_raises_on_a_header_a_client_wrote(
    value: str | None,
) -> None:
    parsed = parse_accept_language(value)
    assert isinstance(parsed, list)


def test_primary_language_and_region_are_none_without_a_header() -> None:
    assert primary_language(None) is None
    assert primary_region(None) is None
    assert primary_region("uk") is None      # no region subtag present
