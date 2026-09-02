"""Log discovery and line parsing — `server/analytics/logread.py`.

IN SCOPE: the two shared fixture builders used by the whole analytics suite,
format auto-detection, extended and legacy round-trips, the hostile-input
cases that must never raise (raw TLS bytes, empty request fields, truncated
lines, bad JSON), timestamp parsing with the offset the line actually carries,
nginx escape decoding, vhost attribution and file discovery.

DELIBERATELY NOT IN SCOPE: classification (`bots.py`), pageview filtering
(`sessionize.py`) and anything that needs a database. Those have their own
files and import the two builders from here.

FIXTURES: every line is built inline. Nothing reads /var/log, data/ or the
network, and every timestamp is derived from `datetime.now(timezone.utc)` so a
hardcoded date can never age out of a relative window (commit 84b4f7d fixed
exactly that bug elsewhere in this repo). Every address is from a
documentation range (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) except
where Cloudflare provenance is the thing under test, in which case a real
Cloudflare edge range is used — those identify Cloudflare, not a person.
"""
from __future__ import annotations

import gzip
import json
import locale
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.analytics import logread
from server.analytics.logread import (
    EXTENDED,
    LEGACY,
    LogRecord,
    ParseStats,
    RawLine,
    attribute_vhost,
    detect_format,
    discover_logs,
    iter_lines,
    iter_records,
    log_file_info,
    parse_line,
    parse_nginx_time,
    referer_host,
    split_request,
    split_target,
    unescape_nginx,
)

# --------------------------------------------------------------------------
# shared fixture builders — imported by the other test_analytics_* modules
# --------------------------------------------------------------------------

#: Every production line stamps Europe/Kyiv. Nothing in this suite assumes UTC.
KYIV = timezone(timedelta(hours=3))

_MONTH_ABBR = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)

#: A plausible Ukrainian reader on a mid-range Samsung, the modal device here.
ANDROID_CHROME_UA = (
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Mobile Safari/537.36"
)

#: A real Cloudflare edge address (162.158.0.0/15). Identifies Cloudflare, not
#: a person, so it is safe to commit and it is what a proxied request shows.
CF_EDGE_IP = "172.71.23.29"

#: Outside every published Cloudflare range: a direct-to-origin probe.
DIRECT_ORIGIN_IP = "203.0.113.7"


def now_local() -> datetime:
    """Now, in the +0300 offset every production line carries.

    Every fixture timestamp hangs off this rather than a literal date.
    """
    return datetime.now(timezone.utc).astimezone(KYIV).replace(microsecond=0)


def nginx_stamp(moment: datetime) -> str:
    """Render `$time_local`: 02/Sep/2026:00:05:56 +0300.

    Built from an explicit month table rather than strftime('%b') so the
    builder itself cannot break under a non-C locale — the same reason
    logread.parse_nginx_time refuses %b.
    """
    offset = moment.utcoffset() or timedelta(0)
    total = int(offset.total_seconds())
    sign = "+" if total >= 0 else "-"
    hours, minutes = divmod(abs(total) // 60, 60)
    return (
        f"{moment.day:02d}/{_MONTH_ABBR[moment.month - 1]}/{moment.year}:"
        f"{moment.hour:02d}:{moment.minute:02d}:{moment.second:02d} "
        f"{sign}{hours:02d}{minutes:02d}"
    )


def iso_stamp(moment: datetime) -> str:
    """Render `$time_iso8601`: 2026-09-02T00:05:56+03:00."""
    return moment.replace(microsecond=0).isoformat()


def extended_line(**over: object) -> str:
    """One line of the cax_json format.

    Defaults describe a plausible Ukrainian mobile reader arriving from
    Telegram; pass any key from the log_format (v, t, h, ip, pip, m, u, pr, st,
    bs, bt, rt, ut, sch, cc, ray, ref, ua, al, rsc, pf, sfm, sfd, sp, chua,
    chp, chpv, chm, chmd) to override it, or `ts` as a datetime. Values go
    through json.dumps exactly as nginx's escape=json would, so tests exercise
    the real decoding path, and every value is quoted — including the numerics,
    which is what stops "ut":- from crashing the parser on every non-upstream
    response.
    """
    moment = over.pop("ts", None)
    if not isinstance(moment, datetime):
        moment = now_local()
    fields: dict[str, str] = {
        "v": "1",
        "t": iso_stamp(moment),
        "h": "cyberalertx.com",
        "ip": "192.0.2.10",
        "pip": CF_EDGE_IP,
        "m": "GET",
        "u": "/ua/threat/e50e48c737157f8a",
        "pr": "HTTP/2.0",
        "st": "200",
        "bs": "20645",
        "bt": "21230",
        "rt": "0.031",
        "ut": "0.028",
        "sch": "https",
        "cc": "UA",
        "ray": "9c4f1c2b3d4e5f60-IEV",
        "ref": "https://t.me/",
        "ua": ANDROID_CHROME_UA,
        "al": "uk-UA,uk;q=0.9,ru;q=0.8,en-US;q=0.7,en;q=0.6",
        "rsc": "",
        "pf": "",
        "sfm": "navigate",
        "sfd": "document",
        "sp": "",
        "chua": '"Chromium";v="143", "Google Chrome";v="143", "Not?A_Brand";v="24"',
        "chp": "Android",
        "chpv": "14",
        "chm": "?1",
        "chmd": "SM-A155M",
    }
    for key, value in over.items():
        fields[key] = "" if value is None else str(value)
    body = ",".join(
        f"{_json_str(k)}:{_json_str(v)}" for k, v in fields.items()
    )
    return "{" + body + "}"


def legacy_line(**over: object) -> str:
    """One line of the default combined format.

    Defaults describe the same reader as `extended_line`, minus every field the
    legacy format lacks, so a test can assert the two produce the same
    LogRecord where the formats overlap. Keys: ip, ident, user, ts, request (or
    method/path/protocol), status, bytes, referer, ua. Values are inserted
    verbatim, so a caller wanting nginx's escape=default \\xNN sequences writes
    them literally.
    """
    moment = over.pop("ts", None)
    if not isinstance(moment, datetime):
        moment = now_local()
    method = str(over.pop("method", "GET"))
    path = str(over.pop("path", "/ua/threat/e50e48c737157f8a"))
    protocol = str(over.pop("protocol", "HTTP/2.0"))
    request = over.pop("request", f"{method} {path} {protocol}")
    ip = str(over.pop("ip", CF_EDGE_IP))
    ident = str(over.pop("ident", "-"))
    user = str(over.pop("user", "-"))
    status = str(over.pop("status", "200"))
    size = str(over.pop("bytes", "20645"))
    referer = str(over.pop("referer", "-"))
    ua = str(over.pop("ua", ANDROID_CHROME_UA))
    if over:
        raise TypeError(f"legacy_line got unexpected keys: {sorted(over)}")
    return (
        f'{ip} {ident} {user} [{nginx_stamp(moment)}] "{request}" '
        f'{status} {size} "{referer}" "{ua}"'
    )


def _json_str(value: str) -> str:
    """Quote one value the way nginx's escape=json does: raw UTF-8 kept."""
    return json.dumps(value, ensure_ascii=False)


def raw_line(text: str, *, lineno: int = 1) -> RawLine:
    """Wrap a line with the provenance `parse_line` expects."""
    return RawLine(text=text, source="/tmp/fixture.log", lineno=lineno, file_key="k0")


def parse(text: str, *, stats: ParseStats | None = None) -> LogRecord:
    """Parse one line and assert it produced a record."""
    record = parse_line(raw_line(text), stats=stats)
    assert record is not None
    return record


def write_log(path: Path, lines: list[str]) -> Path:
    """Write log lines to a file under tmp_path, gzipped when the name ends .gz."""
    body = "".join(line + "\n" for line in lines)
    if path.name.endswith(".gz"):
        path.write_bytes(gzip.compress(body.encode("utf-8")))
    else:
        path.write_text(body, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# round-trips
# --------------------------------------------------------------------------

def test_extended_line_round_trips_every_field(tmp_path: Path) -> None:
    moment = now_local() - timedelta(minutes=5)
    record = parse(extended_line(ts=moment))

    assert record.fmt == EXTENDED
    assert record.ts == moment
    assert record.tz_offset_seconds == 3 * 3600
    assert record.host == "cyberalertx.com"
    assert record.client_ip == "192.0.2.10"
    assert record.peer_ip == CF_EDGE_IP
    assert record.ip_is_visitor is True
    assert record.method == "GET"
    assert record.path == "/ua/threat/e50e48c737157f8a"
    assert record.query == ""
    assert record.protocol == "HTTP/2.0"
    assert record.status == 200
    assert record.body_bytes == 20645
    assert record.total_bytes == 21230
    assert record.request_time == pytest.approx(0.031)
    assert record.upstream_time == pytest.approx(0.028)
    assert record.scheme == "https"
    assert record.malformed_request is False
    assert record.cf_country == "UA"
    assert record.cf_colo == "IEV"
    assert record.referer == "https://t.me/"
    assert record.user_agent == ANDROID_CHROME_UA
    assert record.accept_language.startswith("uk-UA")
    assert record.rsc is False
    assert record.prefetch is False
    assert record.sec_fetch_mode == "navigate"
    assert record.sec_fetch_dest == "document"
    assert record.sec_purpose is None
    assert record.ch_platform == "Android"
    assert record.ch_platform_version == "14"
    assert record.ch_mobile is True
    assert record.ch_model == "SM-A155M"
    assert record.ch_available is True
    assert record.vhost == "cyberalertx"
    assert record.vhost_confidence == "certain"


def test_legacy_line_round_trips(tmp_path: Path) -> None:
    moment = now_local() - timedelta(minutes=5)
    record = parse(legacy_line(ts=moment, status=200, bytes=6598))

    assert record.fmt == LEGACY
    assert record.ts == moment
    assert record.tz_offset_seconds == 3 * 3600
    assert record.host is None
    assert record.method == "GET"
    assert record.path == "/ua/threat/e50e48c737157f8a"
    assert record.status == 200
    assert record.body_bytes == 6598
    assert record.user_agent == ANDROID_CHROME_UA
    assert record.malformed_request is False
    # Fields the combined format simply does not carry.
    assert record.cf_country is None
    assert record.accept_language is None
    assert record.total_bytes is None
    assert record.request_time is None
    assert record.ch_available is False


def test_the_two_formats_agree_where_they_overlap() -> None:
    """The whole point of the format-neutral LogRecord: consumers code once."""
    moment = now_local() - timedelta(hours=2)
    ext = parse(extended_line(ts=moment, u="/en", bs="6598"))
    leg = parse(legacy_line(ts=moment, path="/en", bytes=6598))

    assert ext.ts == leg.ts
    assert ext.path == leg.path
    assert ext.method == leg.method
    assert ext.status == leg.status
    assert ext.body_bytes == leg.body_bytes
    assert ext.user_agent == leg.user_agent
    assert ext.vhost == leg.vhost == "cyberalertx"


# --------------------------------------------------------------------------
# format detection
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "line, expected",
    [
        (extended_line(), EXTENDED),          # a '{' first byte is the whole rule
        (legacy_line(), LEGACY),              # the combined regex
        ("   " + legacy_line(), LEGACY),      # leading whitespace is stripped first
        ("this is not a log line at all", None),
        ("", None),                           # blank: skipped, never counted
        ("{not json but starts with a brace", EXTENDED),  # detection is by shape,
                                                          # the JSON error comes later
    ],
)
def test_detect_format_classifies_by_shape(line: str, expected: str | None) -> None:
    assert detect_format(line) == expected


def test_both_formats_in_one_file_are_parsed(tmp_path: Path) -> None:
    """A rotated file spans the reload boundary on the day the change lands.

    Detection is per line, never per file, so this must need no special case.
    """
    path = write_log(
        tmp_path / "access.log",
        [legacy_line(path="/en"), extended_line(u="/ua"), legacy_line(path="/ua")],
    )
    stats = ParseStats()
    records = list(iter_records([log_file_info(path)], stats=stats))

    assert [r.fmt for r in records] == [LEGACY, EXTENDED, LEGACY]
    assert stats.legacy == 2
    assert stats.extended == 1
    assert stats.unparseable == 0


# --------------------------------------------------------------------------
# hostile input — the parser never raises
# --------------------------------------------------------------------------

def test_raw_tls_handshake_bytes_are_a_malformed_request_not_a_crash() -> None:
    """~240 lines/day: a TLS ClientHello sent to the plaintext port, rendered
    by nginx as \\xNN escapes with no method, path or protocol."""
    tls = (
        r"\x16\x03\x01\x05\xA8\x01\x00\x05\xA4\x03\x03,?Bh\xA9\xB4\x87A\xC2V?0k"
        r"\xD9\xDE\xCE\xF4T\xD8k\xC13\xC5\x12\xE4\xCF\x9C\xD0\xAC\xF0`$ \xEC"
    )
    stats = ParseStats()
    moment = now_local() - timedelta(minutes=1)
    record = parse(
        legacy_line(ts=moment, ip="198.51.100.6", request=tls, status=400,
                    bytes=166, ua="-"),
        stats=stats,
    )

    assert record.malformed_request is True
    assert record.method is None
    assert record.protocol is None
    assert record.path == ""
    # The usable fields survive — this line is still evidence about a day.
    assert record.status == 400
    assert record.ts == moment
    assert record.client_ip == "198.51.100.6"
    assert stats.malformed_request == 1
    assert stats.unparseable == 0


def test_empty_request_field_is_a_malformed_request() -> None:
    stats = ParseStats()
    record = parse(
        legacy_line(ip="198.51.100.9", request="", status=400, bytes=0, ua="-"),
        stats=stats,
    )

    assert record.malformed_request is True
    assert record.method is None
    assert record.path == ""
    assert record.status == 400
    assert stats.malformed_request == 1


@pytest.mark.parametrize(
    "line",
    [
        legacy_line()[: len(legacy_line()) // 2],   # torn mid-write
        '{"v":"1","t":"2026-09-02T00:00:0',          # torn JSON
        "\x00\x01\x02\xff binary noise",             # not text at all
        "- - - - -",
        '{"v":"1"',
    ],
)
def test_truncated_and_garbage_lines_are_counted_never_raised(line: str) -> None:
    stats = ParseStats()
    assert parse_line(raw_line(line), stats=stats) is None
    assert stats.unparseable == 1
    assert sum(stats.reasons.values()) == 1


def test_invalid_json_is_unparseable_with_reason_bad_json() -> None:
    stats = ParseStats()
    assert parse_line(raw_line('{"v":"1", "t": nope}'), stats=stats) is None
    assert stats.reasons.get("bad-json") == 1


def test_unknown_version_is_unparseable_with_its_own_reason() -> None:
    stats = ParseStats()
    assert parse_line(raw_line(extended_line(v="2")), stats=stats) is None
    assert stats.reasons.get("unknown-version") == 1


def test_no_format_match_has_its_own_reason() -> None:
    stats = ParseStats()
    assert parse_line(raw_line("nothing like a log line"), stats=stats) is None
    assert stats.reasons.get("no-format-match") == 1


# --------------------------------------------------------------------------
# timestamps
# --------------------------------------------------------------------------

def test_parse_nginx_time_reads_the_offset_carried_in_the_line() -> None:
    """D1: the log timezone is whatever the line says. Never assume UTC."""
    moment = now_local()
    parsed, offset = parse_nginx_time(nginx_stamp(moment))
    assert parsed == moment
    assert offset == 3 * 3600

    utc_moment = moment.astimezone(timezone.utc)
    parsed_utc, offset_utc = parse_nginx_time(nginx_stamp(utc_moment))
    assert parsed_utc == utc_moment
    assert offset_utc == 0
    # Same instant, two renderings — the offset is read, never assumed.
    assert parsed == parsed_utc


def test_parse_nginx_time_accepts_the_iso8601_shape_too() -> None:
    moment = now_local()
    parsed, offset = parse_nginx_time(iso_stamp(moment))
    assert parsed == moment
    assert offset == 3 * 3600


def test_parse_nginx_time_does_not_depend_on_the_c_locale() -> None:
    """%b is locale-dependent in C; nginx always emits English abbreviations."""
    moment = now_local()
    stamp = nginx_stamp(moment)
    previous = locale.setlocale(locale.LC_TIME)
    for candidate in ("uk_UA.UTF-8", "de_DE.UTF-8", "fr_FR.UTF-8"):
        try:
            locale.setlocale(locale.LC_TIME, candidate)
        except locale.Error:
            continue
        try:
            parsed, offset = parse_nginx_time(stamp)
            assert parsed == moment
            assert offset == 3 * 3600
            return
        finally:
            locale.setlocale(locale.LC_TIME, previous)
    pytest.skip("no non-C LC_TIME locale is installed on this box")


def test_parse_nginx_time_raises_valueerror_on_garbage() -> None:
    """Callers catch this and count the line; it never escapes parse_line."""
    with pytest.raises(ValueError):
        parse_nginx_time("32/Xxx/2026:99:99:99 +9999")


# --------------------------------------------------------------------------
# escaping and field splitting
# --------------------------------------------------------------------------

def test_unescape_nginx_recovers_cyrillic_and_leaves_ascii_alone() -> None:
    escaped = r"\xD0\xBA\xD1\x96\xD0\xB1\xD0\xB5\xD1\x80"   # "кібер" as UTF-8
    assert unescape_nginx(escaped) == "кібер"
    assert unescape_nginx("https://cyberalertx.com/en") == "https://cyberalertx.com/en"
    assert unescape_nginx("") == ""


def test_a_user_agent_full_of_punctuation_parses_as_one_field() -> None:
    """nginx escapes an interior quote to \\x22, so a bare " can only ever be a
    delimiter. The quoted-field regex must survive everything else."""
    hostile = (
        "Mozilla/5.0 (Linux; Android 14; SM-A155M Build/UP1A) "
        "[FBAN/FBAV;a=1,b=2;c=[3];d=4] \\x22quoted\\x22 |pipe| +http://x.test/"
    )
    record = parse(legacy_line(ua=hostile, referer="https://t.me/"))
    assert record.user_agent is not None
    assert "|pipe|" in record.user_agent
    assert record.referer == "https://t.me/"
    assert record.status == 200        # the fields after the UA still line up


@pytest.mark.parametrize(
    "request_field, expected",
    [
        ("GET /en HTTP/1.1", ("GET", "/en", "HTTP/1.1")),
        ("POST /api/x HTTP/2.0", ("POST", "/api/x", "HTTP/2.0")),
        ("", (None, None, None)),                       # empty request field
        ("GET /en", (None, None, None)),                # two parts, not three
        ("GET /en HTTP/1.1 extra", (None, None, None)),  # four parts
        ("\\x16\\x03\\x01", (None, None, None)),          # TLS bytes
    ],
)
def test_split_request_is_exactly_three_parts_or_nothing(
    request_field: str, expected: tuple[str | None, str | None, str | None]
) -> None:
    assert split_request(request_field) == expected


@pytest.mark.parametrize(
    "target, expected",
    [
        ("/en/threat/ab?x=1", ("/en/threat/ab", "x=1")),
        ("/en", ("/en", "")),
        ("/ua?", ("/ua", "")),
        ("/ua/threat/x?_rsc=1a2b", ("/ua/threat/x", "_rsc=1a2b")),
        # Percent-decoding the path is what makes the Next.js chunk paths
        # readable: /_next/static/chunks/app/%5Blocale%5D/... -> [locale]
        ("/_next/static/chunks/app/%5Blocale%5D/page.js?v=1",
         ("/_next/static/chunks/app/[locale]/page.js", "v=1")),
        ("/%FF%FEbroken", ("/��broken", "")),   # errors='replace'
    ],
)
def test_split_target_separates_and_percent_decodes_the_path(
    target: str, expected: tuple[str, str]
) -> None:
    assert split_target(target) == expected


@pytest.mark.parametrize(
    "referer, expected",
    [
        ("https://t.me/cyberalertx", "t.me"),
        ("https://CyberAlertX.com/en", "cyberalertx.com"),
        ("-", None),
        ("", None),
        (None, None),
        ("not a url", None),
    ],
)
def test_referer_host_never_raises_on_garbage(
    referer: str | None, expected: str | None
) -> None:
    assert referer_host(referer) == expected


# --------------------------------------------------------------------------
# vhost attribution (C.4)
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "host, path, referer, expected",
    [
        # 1: a site referer is proof, whatever the path is.
        (None, "/anything", "https://cyberalertx.com/en", ("cyberalertx", "certain")),
        # 3: only this site has locale-prefixed paths.
        (None, "/en/threat/e50e48c737157f8a", "-", ("cyberalertx", "certain")),
        (None, "/uk", "-", ("cyberalertx", "certain")),   # the 301'd old locale
        # 4: site-only routes, but another vhost *could* serve them.
        (None, "/healthz", "-", ("cyberalertx", "likely")),
        (None, "/brand/logo.svg", "-", ("cyberalertx", "likely")),
        # 5: site metadata paths, same reasoning.
        (None, "/sitemap.xml", "-", ("cyberalertx", "likely")),
        # 6: the neighbours' shapes.
        (None, "/api/status", "-", ("other", "likely")),
        (None, "/socket.io/?EIO=4", "-", ("other", "likely")),
        # 7: more than one Next.js app could sit behind this nginx.
        (None, "/_next/static/chunks/main.js", "-", ("ambiguous", "ambiguous")),
        # 8: bare / and scanner probes — overwhelmingly hostile, never audience.
        (None, "/", "-", ("unattributed", "ambiguous")),
        (None, "/wp-config.php", "-", ("unattributed", "ambiguous")),
        # Extended lines carry $host, so attribution is exact.
        ("cyberalertx.com", "/", "-", ("cyberalertx", "certain")),
        ("www.cyberalertx.com", "/wp-config.php", "-", ("cyberalertx", "certain")),
        ("neighbour.example.org", "/en", "-", ("other", "certain")),
    ],
)
def test_vhost_attribution_rules_fire_in_order(
    host: str | None, path: str, referer: str, expected: tuple[str, str]
) -> None:
    assert attribute_vhost(host=host, path=path, referer=referer) == expected


def test_a_configured_sibling_referer_is_conclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sibling vhost's Referer attributes the line to that sibling.

    OTHER_VHOSTS is read from CYBERALERTX_OTHER_VHOSTS at import time and is
    empty by default, precisely so the public repository does not disclose
    which unrelated sites share this box. The rule is therefore only
    exercisable with the list patched in.
    """
    monkeypatch.setattr(
        logread, "OTHER_VHOSTS", frozenset({"neighbour.example.org"}))
    monkeypatch.setattr(
        logread, "OTHER_VHOST_TOKENS", frozenset({"neighbour"}))

    assert logread.attribute_vhost(
        host=None, path="/socket.io/", referer="https://neighbour.example.org/",
    ) == ("other", "certain")


def test_an_unconfigured_sibling_referer_is_not_guessed_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no siblings configured the rule stays silent rather than guessing.

    Patched empty on purpose. A developer checkout may have
    data/other-vhosts.txt present, and without this the test would pass merely
    because the example host is not the configured one -- proving nothing about
    the empty case it claims to cover.

    The path still decides, so this lands on the /socket.io shape rule rather
    than being wrongly claimed for cyberalertx.
    """
    monkeypatch.setattr(logread, "OTHER_VHOSTS", frozenset())
    monkeypatch.setattr(logread, "OTHER_VHOST_TOKENS", frozenset())

    assert logread.attribute_vhost(
        host=None, path="/socket.io/", referer="https://neighbour.example.org/",
    ) == ("other", "likely")


def test_extended_host_beats_the_path_heuristic() -> None:
    """A locale path served by another vhost is still the other vhost."""
    record = parse(extended_line(h="neighbour.example.org", u="/en"))
    assert record.vhost == "other"
    assert record.vhost_confidence == "certain"


# --------------------------------------------------------------------------
# identity of the address fields (C.6)
# --------------------------------------------------------------------------

def test_legacy_collapses_client_and_peer_ip_and_disowns_identity() -> None:
    """Legacy $remote_addr is the Cloudflare EDGE IP. Setting peer_ip to the
    same value lets the provenance rule be written once, against peer_ip, and
    work on both formats — while ip_is_visitor=False blocks visitor counting."""
    record = parse(legacy_line(ip=CF_EDGE_IP))
    assert record.client_ip == CF_EDGE_IP
    assert record.peer_ip == CF_EDGE_IP
    assert record.ip_is_visitor is False


def test_extended_keeps_visitor_and_edge_addresses_distinct() -> None:
    record = parse(extended_line(ip="192.0.2.44", pip=CF_EDGE_IP))
    assert record.client_ip == "192.0.2.44"
    assert record.peer_ip == CF_EDGE_IP
    assert record.ip_is_visitor is True


# --------------------------------------------------------------------------
# files: streaming, keys, discovery, unreadable members
# --------------------------------------------------------------------------

def test_gzip_and_plain_twins_share_a_file_key(tmp_path: Path) -> None:
    """file_key is content-derived, so archive-daily.sh's copy of a rotation is
    recognised as the same stream it came from."""
    lines = [legacy_line(path=f"/en/threat/{i:016x}") for i in range(5)]
    plain = write_log(tmp_path / "access.log.1", lines)
    packed = write_log(tmp_path / "access-2026-08-30.log.gz", lines)

    plain_info = log_file_info(plain)
    packed_info = log_file_info(packed)

    assert plain_info.compressed is False
    assert packed_info.compressed is True
    assert plain_info.file_key == packed_info.file_key
    assert plain_info.first_line == packed_info.first_line


def test_both_plain_and_gzipped_files_stream(tmp_path: Path) -> None:
    lines = [legacy_line(path="/en"), legacy_line(path="/ua")]
    plain = write_log(tmp_path / "access.log", lines)
    packed = write_log(tmp_path / "access-2026-08-30.log.gz", lines)

    stats = ParseStats()
    records = list(
        iter_records([log_file_info(plain), log_file_info(packed)], stats=stats)
    )
    assert len(records) == 4
    assert {r.path for r in records} == {"/en", "/ua"}
    assert len(stats.files_read) == 2


def test_discover_logs_dedupes_an_archive_copy_against_the_original(
    tmp_path: Path,
) -> None:
    lines = [legacy_line(path="/en/threat/aaaaaaaaaaaaaaaa")]
    log_dir = tmp_path / "nginx"
    archive_dir = tmp_path / "archive"
    log_dir.mkdir()
    archive_dir.mkdir()
    write_log(log_dir / "access.log", lines)
    write_log(archive_dir / "access-2026-09-01.log.gz", lines)

    found = discover_logs(log_dir=log_dir, archive_dir=archive_dir)
    keys = [info.file_key for info in found]
    assert len(keys) == len(set(keys))
    assert len(found) == 1


def test_discover_logs_returns_distinct_files_from_both_sources(
    tmp_path: Path,
) -> None:
    """Both directory sources must work, together and standalone."""
    log_dir = tmp_path / "nginx"
    archive_dir = tmp_path / "archive"
    log_dir.mkdir()
    archive_dir.mkdir()
    write_log(log_dir / "access.log", [legacy_line(path="/en")])
    write_log(archive_dir / "access-2026-09-01.log.gz", [legacy_line(path="/ua")])

    both = discover_logs(log_dir=log_dir, archive_dir=archive_dir)
    assert len(both) == 2
    assert len(discover_logs(log_dir=log_dir)) == 1
    assert len(discover_logs(archive_dir=archive_dir)) == 1


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read a mode 000 file")
def test_an_unreadable_file_is_recorded_and_the_run_continues(
    tmp_path: Path,
) -> None:
    good = write_log(tmp_path / "access.log", [legacy_line(path="/en")])
    bad = write_log(tmp_path / "access.log.1", [legacy_line(path="/ua")])
    infos = [log_file_info(good), log_file_info(bad)]
    bad.chmod(0o000)
    try:
        stats = ParseStats()
        lines = list(iter_lines(infos, stats=stats))
    finally:
        bad.chmod(0o644)

    assert len(lines) == 1
    assert [path for path, _ in stats.files_unreadable] == [str(bad)]
    assert str(good) in stats.files_read


def test_iter_records_streams_and_never_materialises_the_file(
    tmp_path: Path,
) -> None:
    """Bounded memory is a hard constraint: a year of logs must not be a list."""
    lines = [
        legacy_line(path=f"/en/threat/{i:016x}", ts=now_local() - timedelta(seconds=i))
        for i in range(50_000)
    ]
    path = write_log(tmp_path / "access.log", lines)

    stats = ParseStats()
    records = iter_records([log_file_info(path)], stats=stats)
    assert iter(records) is records            # a live iterator, not a sequence
    assert not isinstance(records, (list, tuple))

    seen = 0
    for _ in records:
        seen += 1
    assert seen == 50_000
    assert stats.total == 50_000
    assert stats.legacy == 50_000


def test_iter_records_filters_on_the_since_and_until_window(
    tmp_path: Path,
) -> None:
    now = now_local()
    path = write_log(
        tmp_path / "access.log",
        [
            legacy_line(ts=now - timedelta(days=9), path="/en"),
            legacy_line(ts=now - timedelta(days=1), path="/ua"),
            legacy_line(ts=now - timedelta(minutes=1), path="/en"),
        ],
    )
    records = list(
        iter_records([log_file_info(path)], since=now - timedelta(days=7), until=now)
    )
    assert len(records) == 2
    assert all(r.ts >= now - timedelta(days=7) for r in records)


def test_blank_lines_are_skipped_and_not_counted_as_failures(
    tmp_path: Path,
) -> None:
    path = write_log(tmp_path / "access.log", [legacy_line(), "", "   ", legacy_line()])
    stats = ParseStats()
    records = list(iter_records([log_file_info(path)], stats=stats))

    assert len(records) == 2
    assert stats.unparseable == 0
