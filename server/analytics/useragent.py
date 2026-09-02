"""User-Agent and Accept-Language parsing, honest about what it cannot know.

A User-Agent string is a fossil record of twenty years of browser politics,
and every naive parser built on it ships the same handful of wrong numbers.
This module exists to not ship them. The rules that matter, and why:

PRECEDENCE IS THE WHOLE GAME. Every modern browser lies about being every
older browser, so the order of tests decides the answer. Bots first, then
in-app webviews, then Chromium derivatives most-specific-first (Edg/ before
Chrome/, OPR/ before Chrome/, SamsungBrowser/ before Chrome/), then Gecko,
then Safari, then the legacy engines. First match wins and the scan stops.
Test Chrome/ before Safari/ and Edge disappears into Chrome; test Safari/
first and every Chromium browser on earth becomes Safari.

"K" IS NOT A PHONE. Chrome's UA reduction replaced the Android device model
with the literal letter K and the version with a frozen "Android 10".
Parsers that trust it publish reports naming a phantom #1 handset called K,
and a phantom Android 10 majority. Here K maps to None and the frozen
version is flagged unreliable — an unknown honestly labelled beats a
confident fiction.

VERSION/4.0 ON ANDROID IS A WEBVIEW MARKER, not a Safari version. Only read
Version/ as a browser version on Apple platforms.

IN_APP IS A SEPARATE FIELD FROM BROWSER_FAMILY. Telegram's in-app browser
renders with Chrome, so browser_family stays Chrome and in_app becomes
Telegram. That field answers "how much traffic comes from people tapping
links in my Telegram channels?" — probably the single most valuable question
this tool can answer, and more reliable than the Referer, because in-app taps
frequently send none at all.

THE WEBVIEW ESCAPE HATCHES ARE WHERE THE REAL DATA IS. UA reduction removed
the device model, but Telegram, Instagram and Facebook each append their own
block that puts it back — Telegram even carries the TRUE Android version,
overriding the frozen one. Given Telegram is this site's primary distribution
channel, that branch is the highest-value code in the module.

HONEST CEILINGS, to be surfaced by the report rather than hidden: iOS user
agents have never carried a device model, so "iPhone" is the ceiling unless
Facebook's block is present. Brave strips its own token and is unmeasurable;
it lands in the Chrome bucket. iPadOS Safari sends a Macintosh UA by default,
so iPads hide inside macOS with no server-side way to separate them. Chrome
on Android in "request desktop site" mode sends the Linux desktop UA, and
Sec-CH-UA-Mobile is the only fix — which exists on extended lines only.

SCOPE: pure string parsing over values already read from cyberalertx's own
logs. No I/O of any kind, no file access, no clock, no network. Nothing here
writes to any log file, ever.

PRIVACY: nothing leaves the box. A User-Agent is not an identifier here — it
is never hashed into a visitor id, never stored per request in raw form, and
never joined against anything. No network calls at runtime, no dependency
outside the stdlib.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger("analytics.useragent")


@dataclass(frozen=True, slots=True)
class Agent:
    """Everything a User-Agent string will honestly give up, and no more."""

    browser_family: str
    browser_version: str | None
    browser_version_full: str | None
    os_family: str
    os_version: str | None
    os_version_reliable: bool
    device_type: str
    device_vendor: str | None
    device_model: str | None
    device_model_raw: str | None
    model_source: str | None
    in_app: str | None
    is_webview: bool
    ua_declares_bot: bool


UNKNOWN_AGENT: Agent = Agent(
    browser_family="Other",
    browser_version=None,
    browser_version_full=None,
    os_family="Unknown",
    os_version=None,
    os_version_reliable=False,
    device_type="unknown",
    device_vendor=None,
    device_model=None,
    device_model_raw=None,
    model_source=None,
    in_app=None,
    is_webview=False,
    ua_declares_bot=False,
)


# --------------------------------------------------------------------------
# device model tables
# --------------------------------------------------------------------------
# PLACEHOLDER_MODELS is the anti-phantom-handset list. "K" is Chrome's UA
# reduction; "wv" is the WebView marker; the rest are shells that show up
# where a model should be. Every one of them maps to None.
PLACEHOLDER_MODELS: frozenset[str] = frozenset({
    "K", "WV", "MOBILE", "TABLET", "U", "GENERIC", "ANDROID",
})

# Ordered longest / most specific first: the scan stops at the first prefix
# that matches, so "ONEPLUS" must precede any shorter stem it contains.
VENDOR_PREFIXES: tuple[tuple[str, str], ...] = (
    ("ONEPLUS", "OnePlus"),
    ("SAMSUNG", "Samsung"),
    ("XIAOMI", "Xiaomi"),
    ("REDMI", "Xiaomi"),
    ("POCO", "Xiaomi"),
    ("HUAWEI", "Huawei"),
    ("HONOR", "Honor"),
    ("MOTOROLA", "Motorola"),
    ("INFINIX", "Infinix"),
    ("TECNO", "Tecno"),
    ("NOKIA", "Nokia"),
    ("ZENFONE", "ASUS"),
    ("ASUS", "ASUS"),
    ("PIXEL", "Google"),
    ("NEXUS", "Google"),
    ("IPHONE", "Apple"),
    ("IPAD", "Apple"),
    ("BLADE", "ZTE"),
    ("ZTE", "ZTE"),
    ("VIVO", "vivo"),
    ("REALME", "realme"),
    ("SONY", "Sony"),
    ("LENOVO", "Lenovo"),
    ("ITEL", "itel"),
    ("UMIDIGI", "UMIDIGI"),
    ("DOOGEE", "Doogee"),
    ("BLACKVIEW", "Blackview"),
    ("ULEFONE", "Ulefone"),
    ("CUBOT", "Cubot"),
    # Model-code stems. Samsung's SM-/GT- and realme's RMX are unambiguous;
    # the three-letter Huawei/Honor stems below are family codes shared across
    # a model's regional variants (ANE-LX1, ANE-LX2, ANE-LX3 are all one
    # phone), which is exactly the granularity a report should show.
    ("SM-", "Samsung"),
    ("GT-", "Samsung"),
    ("SGH-", "Samsung"),
    ("SCH-", "Samsung"),
    ("RMX", "realme"),
    ("MOTO", "Motorola"),
    ("XT16", "Motorola"),
    ("XT19", "Motorola"),
    ("XT20", "Motorola"),
    ("XT21", "Motorola"),
    ("XT22", "Motorola"),
    ("XT23", "Motorola"),
    ("XT24", "Motorola"),
    ("TA-", "Nokia"),
    ("LM-", "LG"),
    ("LG-", "LG"),
    ("CPH", "OPPO"),
    ("PBEM", "OPPO"),
    ("PCLM", "OPPO"),
    ("ANE-", "Huawei"),
    ("ELE-", "Huawei"),
    ("VOG-", "Huawei"),
    ("MAR-", "Huawei"),
    ("POT-", "Huawei"),
    ("CLT-", "Huawei"),
    ("LYA-", "Huawei"),
    ("JNY-", "Huawei"),
    ("DUB-", "Huawei"),
    ("AMN-", "Huawei"),
    ("MED-", "Huawei"),
    ("STK-", "Huawei"),
    ("JKM-", "Huawei"),
    ("SNE-", "Huawei"),
    ("EML-", "Huawei"),
    ("PRA-", "Huawei"),
    ("WAS-", "Huawei"),
    ("FIG-", "Huawei"),
    ("NAM-", "Huawei"),
    ("LLD-", "Honor"),
    ("COL-", "Honor"),
    ("HRY-", "Honor"),
    ("YAL-", "Honor"),
    ("JAT-", "Honor"),
    ("KSA-", "Honor"),
    ("DNN-", "Honor"),
)

# Model code stem -> marketing name. Looked up by LONGEST PREFIX on the
# uppercased code, so one entry covers every regional suffix (SM-A536B,
# SM-A536E, SM-A536U are all the Galaxy A53 5G).
#
# CURATED, NOT EXHAUSTIVE, AND THAT IS DELIBERATE. An unmapped code falls back
# to the raw code, which is ugly but true; a wrong mapping is a lie that reads
# as a fact. Entries were only added where the mapping is certain. Xiaomi's
# numeric codes (2201117TG and friends) are mostly absent for exactly this
# reason — MIUI often reports a readable name anyway. Refresh by adding rows;
# nothing else in the module needs to change.
ANDROID_MODEL_NAMES: dict[str, str] = {
    # --- Samsung Galaxy S -------------------------------------------------
    "SM-G900": "Galaxy S5",
    "SM-G920": "Galaxy S6",
    "SM-G925": "Galaxy S6 edge",
    "SM-G930": "Galaxy S7",
    "SM-G935": "Galaxy S7 edge",
    "SM-G950": "Galaxy S8",
    "SM-G955": "Galaxy S8+",
    "SM-G960": "Galaxy S9",
    "SM-G965": "Galaxy S9+",
    "SM-G970": "Galaxy S10e",
    "SM-G973": "Galaxy S10",
    "SM-G975": "Galaxy S10+",
    "SM-G977": "Galaxy S10 5G",
    "SM-G780": "Galaxy S20 FE",
    "SM-G781": "Galaxy S20 FE 5G",
    "SM-G980": "Galaxy S20",
    "SM-G981": "Galaxy S20 5G",
    "SM-G985": "Galaxy S20+",
    "SM-G986": "Galaxy S20+ 5G",
    "SM-G988": "Galaxy S20 Ultra 5G",
    "SM-G990": "Galaxy S21 FE 5G",
    "SM-G991": "Galaxy S21 5G",
    "SM-G996": "Galaxy S21+ 5G",
    "SM-G998": "Galaxy S21 Ultra 5G",
    "SM-S901": "Galaxy S22",
    "SM-S906": "Galaxy S22+",
    "SM-S908": "Galaxy S22 Ultra",
    "SM-S711": "Galaxy S23 FE",
    "SM-S911": "Galaxy S23",
    "SM-S916": "Galaxy S23+",
    "SM-S918": "Galaxy S23 Ultra",
    "SM-S921": "Galaxy S24",
    "SM-S926": "Galaxy S24+",
    "SM-S928": "Galaxy S24 Ultra",
    "SM-S931": "Galaxy S25",
    "SM-S936": "Galaxy S25+",
    "SM-S938": "Galaxy S25 Ultra",
    # --- Samsung Galaxy Note / Z -----------------------------------------
    "SM-N950": "Galaxy Note8",
    "SM-N960": "Galaxy Note9",
    "SM-N970": "Galaxy Note10",
    "SM-N975": "Galaxy Note10+",
    "SM-N980": "Galaxy Note20",
    "SM-N981": "Galaxy Note20 5G",
    "SM-N985": "Galaxy Note20 Ultra",
    "SM-N986": "Galaxy Note20 Ultra 5G",
    "SM-F900": "Galaxy Fold",
    "SM-F916": "Galaxy Z Fold2 5G",
    "SM-F926": "Galaxy Z Fold3 5G",
    "SM-F936": "Galaxy Z Fold4",
    "SM-F946": "Galaxy Z Fold5",
    "SM-F956": "Galaxy Z Fold6",
    "SM-F700": "Galaxy Z Flip",
    "SM-F707": "Galaxy Z Flip 5G",
    "SM-F711": "Galaxy Z Flip3 5G",
    "SM-F721": "Galaxy Z Flip4",
    "SM-F731": "Galaxy Z Flip5",
    "SM-F741": "Galaxy Z Flip6",
    # --- Samsung Galaxy A -------------------------------------------------
    "SM-A013": "Galaxy A01 Core",
    "SM-A015": "Galaxy A01",
    "SM-A022": "Galaxy A02",
    "SM-A025": "Galaxy A02s",
    "SM-A032": "Galaxy A03 Core",
    "SM-A035": "Galaxy A03",
    "SM-A037": "Galaxy A03s",
    "SM-A042": "Galaxy A04e",
    "SM-A045": "Galaxy A04",
    "SM-A047": "Galaxy A04s",
    "SM-A055": "Galaxy A05",
    "SM-A057": "Galaxy A05s",
    "SM-A065": "Galaxy A06",
    "SM-A105": "Galaxy A10",
    "SM-A107": "Galaxy A10s",
    "SM-A115": "Galaxy A11",
    "SM-A125": "Galaxy A12",
    "SM-A135": "Galaxy A13",
    "SM-A136": "Galaxy A13 5G",
    "SM-A145": "Galaxy A14",
    "SM-A146": "Galaxy A14 5G",
    "SM-A155": "Galaxy A15",
    "SM-A156": "Galaxy A15 5G",
    "SM-A165": "Galaxy A16",
    "SM-A205": "Galaxy A20",
    "SM-A207": "Galaxy A20s",
    "SM-A215": "Galaxy A21",
    "SM-A217": "Galaxy A21s",
    "SM-A225": "Galaxy A22",
    "SM-A226": "Galaxy A22 5G",
    "SM-A235": "Galaxy A23",
    "SM-A236": "Galaxy A23 5G",
    "SM-A245": "Galaxy A24",
    "SM-A255": "Galaxy A25 5G",
    "SM-A305": "Galaxy A30",
    "SM-A307": "Galaxy A30s",
    "SM-A315": "Galaxy A31",
    "SM-A325": "Galaxy A32",
    "SM-A326": "Galaxy A32 5G",
    "SM-A336": "Galaxy A33 5G",
    "SM-A346": "Galaxy A34 5G",
    "SM-A356": "Galaxy A35 5G",
    "SM-A366": "Galaxy A36 5G",
    "SM-A405": "Galaxy A40",
    "SM-A415": "Galaxy A41",
    "SM-A426": "Galaxy A42 5G",
    "SM-A505": "Galaxy A50",
    "SM-A507": "Galaxy A50s",
    "SM-A515": "Galaxy A51",
    "SM-A516": "Galaxy A51 5G",
    "SM-A525": "Galaxy A52",
    "SM-A526": "Galaxy A52 5G",
    "SM-A528": "Galaxy A52s 5G",
    "SM-A536": "Galaxy A53 5G",
    "SM-A546": "Galaxy A54 5G",
    "SM-A556": "Galaxy A55 5G",
    "SM-A566": "Galaxy A56 5G",
    "SM-A705": "Galaxy A70",
    "SM-A715": "Galaxy A71",
    "SM-A716": "Galaxy A71 5G",
    "SM-A725": "Galaxy A72",
    "SM-A736": "Galaxy A73 5G",
    "SM-A805": "Galaxy A80",
    # --- Samsung Galaxy M / J --------------------------------------------
    "SM-M115": "Galaxy M11",
    "SM-M127": "Galaxy M12",
    "SM-M135": "Galaxy M13",
    "SM-M146": "Galaxy M14 5G",
    "SM-M156": "Galaxy M15 5G",
    "SM-M215": "Galaxy M21",
    "SM-M225": "Galaxy M22",
    "SM-M236": "Galaxy M23 5G",
    "SM-M315": "Galaxy M31",
    "SM-M317": "Galaxy M31s",
    "SM-M325": "Galaxy M32",
    "SM-M336": "Galaxy M33 5G",
    "SM-M346": "Galaxy M34 5G",
    "SM-M515": "Galaxy M51",
    "SM-M526": "Galaxy M52 5G",
    "SM-M536": "Galaxy M53 5G",
    "SM-M546": "Galaxy M54 5G",
    "SM-J330": "Galaxy J3 (2017)",
    "SM-J400": "Galaxy J4",
    "SM-J415": "Galaxy J4+",
    "SM-J530": "Galaxy J5 (2017)",
    "SM-J600": "Galaxy J6",
    "SM-J610": "Galaxy J6+",
    "SM-J730": "Galaxy J7 (2017)",
    "SM-J810": "Galaxy J8",
    # --- Samsung tablets --------------------------------------------------
    "SM-T220": "Galaxy Tab A7 Lite",
    "SM-T500": "Galaxy Tab A7",
    "SM-T510": "Galaxy Tab A 10.1",
    "SM-T870": "Galaxy Tab S7",
    "SM-P610": "Galaxy Tab S6 Lite",
    "SM-X200": "Galaxy Tab A8",
    "SM-X205": "Galaxy Tab A8 LTE",
    "SM-X700": "Galaxy Tab S8",
    "SM-X710": "Galaxy Tab S9",
    "SM-X810": "Galaxy Tab S9+",
    # --- Xiaomi / Redmi / POCO (only the codes that are certain) ----------
    "M2003J15": "Redmi Note 9",
    "M2004J19": "Redmi 9",
    "M2006C3L": "Redmi 9A",
    "M2006C3M": "Redmi 9C",
    "M2007J20": "POCO X3 NFC",
    "M2101K6": "Redmi Note 10 Pro",
    "M2101K7A": "Redmi Note 10S",
    "M2102J20": "POCO X3 Pro",
    # --- OnePlus ----------------------------------------------------------
    "ONEPLUS A5010": "OnePlus 5T",
    "ONEPLUS A6013": "OnePlus 6T",
    "GM1913": "OnePlus 7 Pro",
    "HD1913": "OnePlus 7T Pro",
    "IN2013": "OnePlus 8",
    "IN2023": "OnePlus 8 Pro",
    "KB2005": "OnePlus 8T",
    "LE2113": "OnePlus 9",
    "LE2123": "OnePlus 9 Pro",
    # --- Huawei -----------------------------------------------------------
    "ANE-": "P20 lite",
    "EML-": "P20",
    "CLT-": "P20 Pro",
    "ELE-": "P30",
    "VOG-": "P30 Pro",
    "MAR-": "P30 lite",
    "JNY-": "P40 lite",
    "POT-": "P smart 2019",
    "FIG-": "P smart",
    "PRA-": "P8 lite 2017",
    "WAS-": "P10 lite",
    "LYA-": "Mate 20 Pro",
    "SNE-": "Mate 20 lite",
    "DUB-": "Y7 2019",
    "JKM-": "Y9 2019",
    "STK-": "Y9 Prime 2019",
    "AMN-": "Y5 2019",
    "MED-": "Y6p",
    # --- Honor ------------------------------------------------------------
    "LLD-": "Honor 9 lite",
    "COL-": "Honor 10",
    "HRY-": "Honor 10 lite",
    "YAL-": "Honor 20",
    "JAT-": "Honor 8A",
}

# Sorted longest-key-first once at import, so marketing_name() is a single
# scan with no per-call sorting.
_MODEL_STEMS: tuple[tuple[str, str], ...] = tuple(
    sorted(ANDROID_MODEL_NAMES.items(), key=lambda kv: -len(kv[0]))
)

# Apple hardware identifiers. Only reachable through Facebook's FBDV block —
# the plain iOS UA has never carried a model and never will.
APPLE_MODEL_NAMES: dict[str, str] = {
    "IPHONE8,1": "iPhone 6s", "IPHONE8,2": "iPhone 6s Plus", "IPHONE8,4": "iPhone SE",
    "IPHONE9,1": "iPhone 7", "IPHONE9,3": "iPhone 7", "IPHONE9,2": "iPhone 7 Plus",
    "IPHONE9,4": "iPhone 7 Plus",
    "IPHONE10,1": "iPhone 8", "IPHONE10,4": "iPhone 8",
    "IPHONE10,2": "iPhone 8 Plus", "IPHONE10,5": "iPhone 8 Plus",
    "IPHONE10,3": "iPhone X", "IPHONE10,6": "iPhone X",
    "IPHONE11,2": "iPhone XS", "IPHONE11,4": "iPhone XS Max",
    "IPHONE11,6": "iPhone XS Max", "IPHONE11,8": "iPhone XR",
    "IPHONE12,1": "iPhone 11", "IPHONE12,3": "iPhone 11 Pro",
    "IPHONE12,5": "iPhone 11 Pro Max", "IPHONE12,8": "iPhone SE (2nd gen)",
    "IPHONE13,1": "iPhone 12 mini", "IPHONE13,2": "iPhone 12",
    "IPHONE13,3": "iPhone 12 Pro", "IPHONE13,4": "iPhone 12 Pro Max",
    "IPHONE14,2": "iPhone 13 Pro", "IPHONE14,3": "iPhone 13 Pro Max",
    "IPHONE14,4": "iPhone 13 mini", "IPHONE14,5": "iPhone 13",
    "IPHONE14,6": "iPhone SE (3rd gen)", "IPHONE14,7": "iPhone 14",
    "IPHONE14,8": "iPhone 14 Plus",
    "IPHONE15,2": "iPhone 14 Pro", "IPHONE15,3": "iPhone 14 Pro Max",
    "IPHONE15,4": "iPhone 15", "IPHONE15,5": "iPhone 15 Plus",
    "IPHONE16,1": "iPhone 15 Pro", "IPHONE16,2": "iPhone 15 Pro Max",
    "IPHONE17,1": "iPhone 16 Pro", "IPHONE17,2": "iPhone 16 Pro Max",
    "IPHONE17,3": "iPhone 16", "IPHONE17,4": "iPhone 16 Plus",
    "IPHONE17,5": "iPhone 16e",
}

# A locale token in the platform block of an ancient UA ("uk-ua") sits exactly
# where a model sits, and is the classic way a parser invents a phone called
# "en-gb". Matched and rejected.
_LOCALE_TOKEN_RE: re.Pattern[str] = re.compile(r"^[a-z]{2,3}([-_][a-z0-9]{2,4})?$", re.I)
_BUILD_SPLIT_RE: re.Pattern[str] = re.compile(r"\s*build/", re.I)
_VERSION_ONLY_RE: re.Pattern[str] = re.compile(r"^[\d._]+$")
_MODEL_VENDOR_PREFIX_RE: re.Pattern[str] = re.compile(
    r"^(samsung|huawei|honor|xiaomi|redmi|oppo|vivo|lenovo|motorola|asus|zte|tcl|infinix|tecno)\s+",
    re.I,
)


# --------------------------------------------------------------------------
# browser / os / device tables
# --------------------------------------------------------------------------
# Coarse shape signal only — bots.py owns the authoritative catalogue and the
# Cloudflare-provenance rule that outranks it. This exists so that Agent can
# say "this string is not claiming to be a person" without importing bots.
_BOT_SHAPE_RE: re.Pattern[str] = re.compile(
    r"(?:bot/|bot;|bot\)|\bbot\b|spider|crawler|scraper|fetcher|headlesschrome|"
    r"lighthouse|phantomjs|puppeteer|playwright|selenium|\+http|http-client|"
    r"curl/|wget|python-requests|python-urllib|go-http-client|okhttp|libwww-perl|"
    r"apache-httpclient|java/|scrapy|httpx|aiohttp|guzzlehttp|postmanruntime|"
    r"facebookexternalhit|feedfetcher|feedly|inoreader|newsblur|slackbot|"
    r"whatsapp|discordbot|monitoring|uptimerobot|pingdom|zgrab|masscan|nuclei|"
    r"fasthttp)",
    re.I,
)
# Cubot and Robot are phones and words, not bots — the \bbot\b in the shape
# regex above uses word boundaries precisely so they do not match.
_BOT_PRODUCT_RE: re.Pattern[str] = re.compile(
    r"([A-Za-z][A-Za-z0-9._-]{2,}(?:bot|spider|crawler|fetcher|scraper))", re.I
)

# Browser precedence, most specific first. Every entry is (lowercase needle,
# family, version pattern). The needle test is a plain substring search
# because it runs on every line; the pattern only runs on a hit.
_BROWSER_RULES: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    # Edge, longest token first: EdgiOS and EdgA both contain neither "Edg/"
    # nor each other, but the ordering documents the intent.
    ("edgios/", "Edge", re.compile(r"EdgiOS/([\d.]+)", re.I)),
    ("edga/", "Edge", re.compile(r"EdgA/([\d.]+)", re.I)),
    ("edg/", "Edge", re.compile(r"Edg/([\d.]+)", re.I)),
    ("edge/", "Edge Legacy", re.compile(r"Edge/([\d.]+)", re.I)),
    # Opera. OPR/ is desktop and Android, OPiOS/ is iOS, OPT/ is Opera Touch.
    ("opios/", "Opera", re.compile(r"OPiOS/([\d.]+)", re.I)),
    ("opr/", "Opera", re.compile(r"OPR/([\d.]+)", re.I)),
    ("opt/", "Opera Touch", re.compile(r"OPT/([\d.]+)", re.I)),
    ("opera mini", "Opera Mini", re.compile(r"Opera Mini/([\d.]+)", re.I)),
    ("samsungbrowser/", "Samsung Internet", re.compile(r"SamsungBrowser/([\d.]+)", re.I)),
    ("yabrowser/", "Yandex Browser", re.compile(r"YaBrowser/([\d.]+)", re.I)),
    ("yasearchbrowser/", "Yandex Browser", re.compile(r"YaSearchBrowser/([\d.]+)", re.I)),
    ("vivaldi/", "Vivaldi", re.compile(r"Vivaldi/([\d.]+)", re.I)),
    # Brave only reaches here on the rare builds that keep the token; the
    # shipping default strips it and lands in Chrome. Unmeasurable, and the
    # report says so rather than pretending Brave has zero users.
    ("brave/", "Brave", re.compile(r"Brave/([\d.]+)", re.I)),
    ("whale/", "Whale", re.compile(r"Whale/([\d.]+)", re.I)),
    ("ucbrowser/", "UC Browser", re.compile(r"UCBrowser/([\d.]+)", re.I)),
    ("ucweb", "UC Browser", re.compile(r"UCWEB/?([\d.]+)?", re.I)),
    ("miuibrowser/", "MIUI Browser", re.compile(r"MiuiBrowser/([\d.]+)", re.I)),
    ("huaweibrowser/", "Huawei Browser", re.compile(r"HuaweiBrowser/([\d.]+)", re.I)),
    ("heytapbrowser/", "HeyTap Browser", re.compile(r"HeyTapBrowser/([\d.]+)", re.I)),
    ("qqbrowser/", "QQ Browser", re.compile(r"QQBrowser/([\d.]+)", re.I)),
    ("coc_coc_browser/", "Coc Coc", re.compile(r"coc_coc_browser/([\d.]+)", re.I)),
    ("duckduckgo/", "DuckDuckGo", re.compile(r"DuckDuckGo/([\d.]+)", re.I)),
    ("silk/", "Silk", re.compile(r"Silk/([\d.]+)", re.I)),
    ("crios/", "Chrome", re.compile(r"CriOS/([\d.]+)", re.I)),
    ("chrome/", "Chrome", re.compile(r"Chrome/([\d.]+)", re.I)),
    ("chromium/", "Chromium", re.compile(r"Chromium/([\d.]+)", re.I)),
    # Gecko.
    ("fxios/", "Firefox", re.compile(r"FxiOS/([\d.]+)", re.I)),
    ("focus/", "Firefox Focus", re.compile(r"Focus/([\d.]+)", re.I)),
    ("seamonkey/", "SeaMonkey", re.compile(r"SeaMonkey/([\d.]+)", re.I)),
    ("waterfox/", "Waterfox", re.compile(r"Waterfox/([\d.]+)", re.I)),
    ("palemoon/", "Pale Moon", re.compile(r"PaleMoon/([\d.]+)", re.I)),
    ("firefox/", "Firefox", re.compile(r"Firefox/([\d.]+)", re.I)),
)

_VERSION_RE: re.Pattern[str] = re.compile(r"Version/([\d.]+)", re.I)
_MSIE_RE: re.Pattern[str] = re.compile(r"MSIE ([\d.]+)", re.I)
_TRIDENT_RV_RE: re.Pattern[str] = re.compile(r"rv:([\d.]+)", re.I)

# OS detection patterns, applied in the precedence order below.
_WINDOWS_NT_RE: re.Pattern[str] = re.compile(r"Windows NT ([\d.]+)", re.I)
_WINDOWS_PHONE_RE: re.Pattern[str] = re.compile(r"Windows Phone(?: OS)? ([\d.]+)", re.I)
_ANDROID_RE: re.Pattern[str] = re.compile(r"Android[ /]([\d.]+)", re.I)
_IOS_RE: re.Pattern[str] = re.compile(r"(?:iPhone )?OS ([\d_]+) like Mac OS X", re.I)
_MACOS_RE: re.Pattern[str] = re.compile(r"Mac OS X ([\d_.]+)", re.I)
_CROS_RE: re.Pattern[str] = re.compile(r"CrOS \S+ ([\d.]+)", re.I)

# Windows NT version -> marketing name. 10.0 is FROZEN: Windows 11 also
# reports NT 10.0, so "10" alone is a lie and the split needs client hints.
_WINDOWS_NT_NAMES: dict[str, str] = {
    "10.0": "10/11",
    "6.3": "8.1",
    "6.2": "8",
    "6.1": "7",
    "6.0": "Vista",
    "5.2": "XP",
    "5.1": "XP",
}

_TV_TOKENS: tuple[str, ...] = (
    "smart-tv", "smarttv", "googletv", "android tv", "appletv", "apple tv",
    "crkey", "hbbtv", "netcast", "web0s", "webos.tv", "bravia", "; aft",
    "roku", "viera", "philipstv", "dtv", "tv safari",
)
_CONSOLE_TOKENS: tuple[str, ...] = ("playstation", "xbox", "nintendo")
_TABLET_TOKENS: tuple[str, ...] = ("ipad", "tablet", "playbook", "kindle", "silk/", "nexus 7", "nexus 10")
_MOBILE_TOKENS: tuple[str, ...] = (
    "mobile", "iphone", "ipod", "windows phone", "iemobile", "opera mini",
    "blackberry", "bb10", "webos", "palm",
)

# In-app browser shells. The order matters only in that Facebook's FBAN block
# and Instagram's block can both appear, and Instagram's is the more specific.
_IN_APP_TOKENS: tuple[tuple[str, str], ...] = (
    ("telegram-android", "Telegram"),
    ("telegram-ios", "Telegram"),
    ("telegramwebview", "Telegram"),
    ("instagram", "Instagram"),
    ("fbav/", "Facebook"),
    ("fban/", "Facebook"),
    ("fb_iab", "Facebook"),
    ("fbios", "Facebook"),
    ("musical_ly", "TikTok"),
    ("bytelocale", "TikTok"),
    ("bytedancewebview", "TikTok"),
    ("trill_", "TikTok"),
    ("twitterandroid", "Twitter"),
    ("twitter for iphone", "Twitter"),
    ("linkedinapp", "LinkedIn"),
    ("micromessenger", "WeChat"),
    ("viber", "Viber"),
    ("line/", "LINE"),
    ("snapchat", "Snapchat"),
    ("pinterest", "Pinterest"),
    ("vkandroidapp", "VK"),
)

_TELEGRAM_ANDROID_RE: re.Pattern[str] = re.compile(
    r"Telegram-Android/[\d.]+\s*\(\s*(?P<dev>[^;)]+?)\s*;\s*Android\s*(?P<os>[\d.]+)", re.I
)
_TELEGRAM_IOS_RE: re.Pattern[str] = re.compile(
    r"Telegram-iOS/[\d.]+\s*\(\s*(?P<dev>[^;)]+?)\s*;\s*iOS\s*(?P<os>[\d._]+)", re.I
)
_INSTAGRAM_ANDROID_RE: re.Pattern[str] = re.compile(
    r"Instagram\s+[\d.]+\s+Android\s*\(\s*\d+/(?P<os>[\d.]+);\s*\d+dpi;\s*"
    r"\d+x\d+;\s*(?P<vendor>[^;]+);\s*(?P<model>[^;]+);",
    re.I,
)
_FB_DEVICE_RE: re.Pattern[str] = re.compile(r"FBDV/([^;\]]+)", re.I)
_FB_OS_RE: re.Pattern[str] = re.compile(r"FBSV/([\d._]+)", re.I)


# --------------------------------------------------------------------------
# model helpers
# --------------------------------------------------------------------------
def clean_model(model: str) -> str | None:
    """Normalise a raw model token, or return None when it means nothing.

    Strips everything from 'Build/' onward, strips a leading vendor word
    ('SAMSUNG SM-S918B' -> 'SM-S918B'), and rejects the placeholders and
    locale-shaped tokens that a naive parser publishes as the site's most
    popular handset.
    """
    token = _BUILD_SPLIT_RE.split(model, maxsplit=1)[0].strip().strip(";,")
    token = _MODEL_VENDOR_PREFIX_RE.sub("", token).strip()
    if not token or len(token) > 64:
        return None
    if token.upper() in PLACEHOLDER_MODELS:
        return None
    if _LOCALE_TOKEN_RE.match(token) and "-" in token:
        # "uk-ua", "en-gb": a locale sitting where a model should be.
        return None
    if token.lower() in {"linux", "u", "wv", "unknown", "android"}:
        return None
    if ":" in token:
        # "rv:143.0" from a Firefox platform block sits exactly where a model
        # sits. No device code has ever contained a colon.
        return None
    if _VERSION_ONLY_RE.match(token):
        return None
    return token


def marketing_name(model_code: str) -> str | None:
    """Longest-prefix lookup in ANDROID_MODEL_NAMES, on the uppercased code.

    'SM-A536B' -> 'Galaxy A53 5G'. None when unmapped, and the caller then
    keeps the raw code: an ugly truth beats an invented product name.
    """
    if not model_code:
        return None
    upper = model_code.upper()
    for stem, name in _MODEL_STEMS:
        if upper.startswith(stem):
            return name
    return None


def vendor_for_model(model_code: str) -> str | None:
    """Ordered prefix scan of VENDOR_PREFIXES, longest/most specific first."""
    if not model_code:
        return None
    upper = model_code.upper()
    for prefix, vendor in VENDOR_PREFIXES:
        if upper.startswith(prefix):
            return vendor
    return None


def android_model(ua: str) -> str | None:
    """Extract the Android device model from the platform block.

    Preferred: the ';'-token containing 'Build/' — that token IS the model,
    and it is what makes the ancient 'Linux; U; Android 4.4.2; uk-ua;
    SM-G900F Build/KOT49H' shape work, since the locale token has no Build/.
    Fallback: the last token, skipping 'wv' / 'Mobile' / 'Tablet'.

    Returns None for anything that is not Android. The platform block of a
    Linux desktop is '(X11; Linux x86_64)', whose last token survives every
    token filter and would otherwise be reported as a handset called
    'Linux x86_64' — the same phantom-device failure as the 'K' placeholder,
    arriving from the other direction. The only positive evidence that a model
    is present at all is the Android token itself, so require it here rather
    than relying on every caller to check first.
    """
    start = ua.find("(")
    if start < 0:
        return None
    end = ua.find(")", start)
    block = ua[start + 1: end if end > start else len(ua)]
    tokens = [tok.strip() for tok in block.split(";") if tok.strip()]
    if not tokens:
        return None
    if not any(tok.lower() == "android" or tok.lower().startswith("android ")
               for tok in tokens):
        return None

    for token in tokens:
        if "build/" in token.lower():
            return clean_model(token)

    skip = {"wv", "mobile", "tablet", "linux", "u", "android"}
    for token in reversed(tokens):
        lowered = token.lower()
        if lowered in skip or lowered.startswith("android "):
            continue
        candidate = clean_model(token)
        if candidate:
            return candidate
        # A token that cleans to nothing (a locale, "rv:143.0", a placeholder)
        # is not the end of the search — the model may still be behind it.
    return None


def windows_version(platform_version: str | None) -> str | None:
    """Sec-CH-UA-Platform-Version -> 'Windows 11' | 'Windows 10' |
    'Windows (older)' | None.

    First component >= 13 is Windows 11. THIS THRESHOLD IS UNVERIFIED: it
    comes from Microsoft's published mapping of the platform-version hint, not
    from anything measured on this box, and the report must label the 10/11
    split as an estimate until someone checks it against a known machine.
    A first component of 0 means Windows 8.1 or older.
    """
    if not platform_version:
        return None
    head = platform_version.strip().strip('"').split(".", 1)[0]
    try:
        major = int(head)
    except ValueError:
        return None
    if major >= 13:
        return "Windows 11"
    if major >= 1:
        return "Windows 10"
    return "Windows (older)"


# --------------------------------------------------------------------------
# Accept-Language
# --------------------------------------------------------------------------
def parse_accept_language(value: str | None) -> list[tuple[str, float]]:
    """RFC 9110 preference list -> [(lowercased tag, q)] sorted by q descending.

    STABLE, so equal-q ties keep header order — which is the only thing that
    distinguishes 'uk,en' from 'en,uk' when a browser sends no q values at all.
    Entries with q=0 mean 'not acceptable' and are DROPPED rather than counted
    as a weak preference. '*' is skipped. Never raises: a malformed header
    costs its own broken entry, never the line.
    """
    if not value:
        return []
    entries: list[tuple[str, float]] = []
    for chunk in value.split(","):
        part = chunk.strip()
        if not part:
            continue
        tag, _, params = part.partition(";")
        tag = tag.strip().lower()
        if not tag or tag == "*":
            continue
        quality = 1.0
        for param in params.split(";"):
            key, _, raw = param.strip().partition("=")
            if key.strip().lower() == "q":
                try:
                    quality = float(raw.strip())
                except ValueError:
                    quality = 1.0
                break
        if quality <= 0.0:
            continue
        entries.append((tag, min(quality, 1.0)))
    return sorted(entries, key=lambda item: -item[1])


def primary_language(value: str | None) -> str | None:
    """Top tag's primary subtag, lowercased: 'uk-UA,uk;q=0.9,...' -> 'uk'."""
    entries = parse_accept_language(value)
    if not entries:
        return None
    return entries[0][0].split("-", 1)[0] or None


def primary_region(value: str | None) -> str | None:
    """Top tag's region subtag, uppercased: 'uk-UA,...' -> 'UA'. None if absent.

    A region is a two-letter alpha or three-digit subtag; the four-letter
    subtag in 'zh-Hans-CN' is a script and is skipped, so the answer is CN.
    """
    entries = parse_accept_language(value)
    if not entries:
        return None
    parts = entries[0][0].split("-")
    for part in parts[1:]:
        if len(part) == 2 and part.isalpha():
            return part.upper()
        if len(part) == 3 and part.isdigit():
            return part
    return None


# --------------------------------------------------------------------------
# the parse
# --------------------------------------------------------------------------
def _major(version: str | None) -> str | None:
    """'143.0.0.0' -> '143'. Majors are what a report can honestly aggregate."""
    if not version:
        return None
    head = version.split(".", 1)[0]
    return head or None


def _trim_version(version: str | None) -> str | None:
    """'14.0.0' -> '14', '17.5.1' -> '17.5.1'. Drops trailing zero groups only."""
    if not version:
        return None
    parts = version.replace("_", ".").split(".")
    while len(parts) > 1 and parts[-1] in {"0", ""}:
        parts.pop()
    return ".".join(parts) or None


def _browser(ua: str, low: str) -> tuple[str, str | None]:
    """Ordered precedence chain. First match wins, then stop."""
    for needle, family, pattern in _BROWSER_RULES:
        if needle in low:
            match = pattern.search(ua)
            return family, match.group(1) if match else None

    apple = any(token in low for token in ("iphone", "ipad", "ipod", "macintosh", "mac os x"))
    if apple and "safari/" in low:
        match = _VERSION_RE.search(ua)
        return "Safari", match.group(1) if match else None
    if "android" in low and ("version/" in low or "safari/" in low):
        # Version/4.0 here is the old Android stock browser or a bare WebView
        # shell — NEVER a Safari version.
        match = _VERSION_RE.search(ua)
        return "Android Browser", match.group(1) if match else None
    if "msie " in low:
        match = _MSIE_RE.search(ua)
        return "Internet Explorer", match.group(1) if match else None
    if "trident/" in low:
        match = _TRIDENT_RV_RE.search(ua)
        return "Internet Explorer", match.group(1) if match else None
    if "safari/" in low:
        match = _VERSION_RE.search(ua)
        return "Safari", match.group(1) if match else None
    if apple and "applewebkit" in low:
        # An in-app shell on iOS (Facebook, Telegram) drops the Safari token
        # but is still WebKit, because Apple allows nothing else.
        match = _VERSION_RE.search(ua)
        return "Safari", match.group(1) if match else None
    return "Other", None


def _operating_system(ua: str, low: str) -> tuple[str, str | None, bool]:
    """OS precedence: Windows Phone -> Windows -> Android -> iOS/iPadOS ->
    ChromeOS -> macOS -> Linux -> BSD.

    Android before Linux because every Android UA also says "Linux"; iOS and
    iPadOS before macOS because an iPad UA says "Mac OS X"; ChromeOS before
    Linux for the same reason. iPad is tested before iPhone only because the
    two tokens never co-occur, so the order between them is free.
    """
    if "windows phone" in low:
        match = _WINDOWS_PHONE_RE.search(ua)
        return "Windows Phone", match.group(1) if match else None, True
    if "windows nt" in low:
        match = _WINDOWS_NT_RE.search(ua)
        nt = match.group(1) if match else ""
        name = _WINDOWS_NT_NAMES.get(nt)
        # NT 10.0 is reported by Windows 10 AND Windows 11. "10" would be a
        # confident lie; "10/11" is the truth, and the flag says so.
        return "Windows", name, nt != "10.0" and name is not None
    if "windows" in low:
        return "Windows", None, False
    if "android" in low:
        match = _ANDROID_RE.search(ua)
        return "Android", match.group(1) if match else None, bool(match)
    if "ipad" in low:
        match = _IOS_RE.search(ua)
        return "iPadOS", _trim_version(match.group(1)) if match else None, bool(match)
    if "iphone" in low or "ipod" in low:
        match = _IOS_RE.search(ua)
        return "iOS", _trim_version(match.group(1)) if match else None, bool(match)
    if "cros " in low:
        match = _CROS_RE.search(ua)
        return "ChromeOS", match.group(1) if match else None, bool(match)
    if "mac os x" in low or "macintosh" in low:
        match = _MACOS_RE.search(ua)
        raw = match.group(1).replace("_", ".") if match else None
        if raw is None or raw.startswith("10.15.7") or raw == "10.15":
            # Safari froze at 10_15_7 in 2020 and Chrome reports it too. Any
            # Mac from the last five years reports this, so it means nothing.
            return "macOS", None, False
        return "macOS", raw, True
    if "linux" in low or "x11" in low:
        return "Linux", None, False
    if "freebsd" in low or "openbsd" in low or "netbsd" in low:
        return "BSD", None, False
    return "Unknown", None, False


def _device_type(low: str, os_family: str) -> str:
    """bot -> console -> tv -> tablet -> mobile -> desktop.

    TV comes before tablet because several Android TV boxes omit the "Mobile"
    token exactly the way a tablet does, and an Android UA without "Mobile" is
    a tablet by Chromium's own convention.
    """
    if any(token in low for token in _CONSOLE_TOKENS):
        return "console"
    if any(token in low for token in _TV_TOKENS):
        return "tv"
    if any(token in low for token in _TABLET_TOKENS):
        return "tablet"
    if os_family == "Android" and "mobile" not in low:
        return "tablet"
    if any(token in low for token in _MOBILE_TOKENS):
        return "mobile"
    if os_family in {"Windows", "macOS", "Linux", "ChromeOS", "BSD"}:
        return "desktop"
    if os_family == "Android":
        return "mobile"
    return "unknown"


def _in_app(low: str) -> str | None:
    """The app hosting the webview, or None for a real browser."""
    for token, name in _IN_APP_TOKENS:
        if token in low:
            return name
    return None


@lru_cache(maxsize=8192)
def parse_user_agent(
    ua: str | None,
    *,
    ch_platform: str | None = None,
    ch_platform_version: str | None = None,
    ch_mobile: bool | None = None,
    ch_model: str | None = None,
    ch_available: bool = False,
) -> Agent:
    """Full parse. Client hints, when present, OVERRIDE the UA-derived values
    and set model_source='client-hint'. Never raises; returns UNKNOWN_AGENT for
    None/empty input. Results are memoised with functools.lru_cache on the
    argument tuple (maxsize=8192) — a handful of UA strings cover most lines.
    """
    if ua is None:
        return UNKNOWN_AGENT
    text = ua.strip()
    if not text or text == "-":
        return UNKNOWN_AGENT
    low = text.lower()

    # 1. Bots first. A bot with a full Chrome UA (HeadlessChrome, or a
    #    crawler that copied one wholesale) must not be counted as a browser,
    #    and nothing below this point should even run.
    if _BOT_SHAPE_RE.search(low):
        product = _BOT_PRODUCT_RE.search(text)
        return Agent(
            browser_family=product.group(1) if product else "Bot",
            browser_version=None,
            browser_version_full=None,
            os_family="Unknown",
            os_version=None,
            os_version_reliable=False,
            device_type="bot",
            device_vendor=None,
            device_model=None,
            device_model_raw=None,
            model_source=None,
            in_app=None,
            is_webview=False,
            ua_declares_bot=True,
        )

    in_app = _in_app(low)
    is_webview = "; wv)" in low or "; wv;" in low or in_app is not None
    browser_family, version_full = _browser(text, low)
    os_family, os_version, os_reliable = _operating_system(text, low)

    model_raw = android_model(text) if os_family == "Android" else None
    model_source: str | None = "ua" if model_raw else None
    vendor = vendor_for_model(model_raw) if model_raw else None

    # Chromium's UA reduction freezes Android at 10 and blanks the model to
    # "K". A missing model beside version 10 is that reduction, not a phone
    # running Android 10.
    if os_family == "Android" and os_version == "10" and model_raw is None:
        os_reliable = False

    # 2. Webview escape hatches. These put back what UA reduction removed, and
    #    Telegram even carries the true Android version.
    if in_app == "Telegram":
        match = _TELEGRAM_ANDROID_RE.search(text)
        if match:
            device = match.group("dev").strip()
            head, _, tail = device.partition(" ")
            candidate = clean_model(tail or device)
            if candidate:
                model_raw = candidate
                model_source = "telegram"
                vendor = head.title() if tail else vendor_for_model(candidate)
            os_family, os_version, os_reliable = "Android", match.group("os"), True
        else:
            match = _TELEGRAM_IOS_RE.search(text)
            if match:
                model_raw = match.group("dev").strip() or model_raw
                model_source = "telegram"
                vendor = "Apple"
                os_family = "iPadOS" if "ipad" in (model_raw or "").lower() else "iOS"
                os_version = _trim_version(match.group("os"))
                os_reliable = True
    elif in_app == "Instagram":
        match = _INSTAGRAM_ANDROID_RE.search(text)
        if match:
            candidate = clean_model(match.group("model"))
            if candidate:
                model_raw = candidate
                model_source = "instagram"
                vendor = match.group("vendor").strip().title() or vendor
            os_family, os_version, os_reliable = "Android", match.group("os"), True
            # The block also carries dpi and WIDTHxHEIGHT. That resolution is
            # real but is an Instagram-only curiosity, and must NEVER be
            # reported as a site-wide screen-size statistic.
    elif in_app == "Facebook":
        match = _FB_DEVICE_RE.search(text)
        if match:
            candidate = match.group(1).strip()
            if candidate and candidate.upper() not in PLACEHOLDER_MODELS:
                model_raw = candidate
                model_source = "facebook"
                vendor = "Apple" if candidate.lower().startswith(("iphone", "ipad", "ipod")) else vendor_for_model(candidate)
        os_match = _FB_OS_RE.search(text)
        if os_match:
            os_version = _trim_version(os_match.group(1))
            os_reliable = True

    # Firefox on Android never adopted UA reduction, so its Android version is
    # real. So are iOS versions, and anything a webview block supplied.
    if os_family == "Android" and browser_family.startswith("Firefox"):
        os_reliable = os_version is not None

    device_type = _device_type(low, os_family)

    # 3. Client hints last: they are measured, not sniffed, and they override.
    if ch_platform:
        platform = ch_platform.strip().strip('"')
        mapped = {
            "windows": "Windows", "android": "Android", "macos": "macOS",
            "ios": "iOS", "ipados": "iPadOS", "linux": "Linux",
            "chrome os": "ChromeOS", "chromium os": "ChromeOS",
        }.get(platform.lower())
        if mapped:
            os_family = mapped
            if mapped == "Windows":
                name = windows_version(ch_platform_version)
                if name == "Windows 11":
                    os_version, os_reliable = "11", True
                elif name == "Windows 10":
                    os_version, os_reliable = "10", True
                elif name == "Windows (older)":
                    os_reliable = False
            elif ch_platform_version:
                os_version = _trim_version(ch_platform_version.strip().strip('"'))
                os_reliable = os_version is not None
    if ch_model:
        candidate = clean_model(ch_model.strip().strip('"'))
        if candidate:
            model_raw = candidate
            model_source = "client-hint"
            vendor = vendor_for_model(candidate) or vendor
    if ch_mobile is not None:
        if ch_mobile:
            device_type = "mobile"
        elif device_type == "mobile":
            # Chrome on Android in "request desktop site" mode sends the Linux
            # desktop UA; Sec-CH-UA-Mobile is the only thing that catches it.
            device_type = "tablet" if os_family == "Android" else "desktop"
        elif os_family == "Android" and device_type != "tablet":
            device_type = "tablet"

    model_name = marketing_name(model_raw) if model_raw else None
    if model_name is None and model_raw and model_source == "facebook":
        model_name = APPLE_MODEL_NAMES.get(model_raw.upper())

    return Agent(
        browser_family=browser_family,
        browser_version=_major(version_full),
        browser_version_full=version_full,
        os_family=os_family,
        os_version=os_version,
        os_version_reliable=os_reliable,
        device_type=device_type,
        device_vendor=vendor,
        device_model=model_name or model_raw,
        device_model_raw=model_raw,
        model_source=model_source,
        in_app=in_app,
        is_webview=is_webview,
        ua_declares_bot=False,
    )
