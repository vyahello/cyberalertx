"""nginx access-log reading: discovery, decompression, parsing, attribution.

Everything downstream codes against `LogRecord` and never against a log line,
because there are two log formats on this box and there will be a third the
day nginx changes again. The two that exist today:

  LEGACY    the stock `combined` format, one file shared by four vhosts, no
            host field, and no real_ip config anywhere — so column one is the
            Cloudflare EDGE address, not the reader. 14 days of it, kept only
            because logrotate says so.
  EXTENDED  the dedicated `cax_json` format: one JSON object per line, every
            value quoted as a string, host and true client IP included.

DETECTION IS PER LINE, NEVER PER FILE. The rotated file covering the nginx
reload contains both formats, and special-casing that one day is exactly how
a parser starts lying quietly. A leading `{` means extended, otherwise the
combined regex gets a turn, otherwise the line is counted as unparseable with
a reason and dropped.

THE PARSER NEVER RAISES. About 240 lines a day carry raw TLS handshake bytes
in the request field, rendered as nginx hex escapes with no method, path or
protocol; others carry an empty request field; the last line of a live file is
routinely half-written. Those are normal, counted outcomes — a crash here
would throw away the whole run's work over four bytes of someone else's
malformed ClientHello. Two distinct failures are counted separately:
`unparseable` (matched no format at all, returns None) and `malformed_request`
(the line parsed, the request field did not — the timestamp, status and
address are still perfectly usable, and bots.py classifies it as malformed).

THE ASYMMETRY WORTH UNDERSTANDING: legacy records set `peer_ip = client_ip`
and `ip_is_visitor = False`. The Cloudflare-provenance test — the strongest
bot filter on this site, 79.4% of one day's lines — is therefore written once
against `peer_ip` and works identically on both formats, on history that
already exists, with no nginx change at all. Visitor identity is the opposite
story: 121 pageviews arrived via 99 edge IPs, so on legacy data unique
visitors are suppressed, never estimated.

MEMORY IS BOUNDED BY DESIGN. discover -> iter_lines -> parse -> iter_records
is a generator chain from end to end. Nothing here ever holds a whole file, a
whole day, or a list of records; a year of history must cost the same
resident memory as an hour of it.

SCOPE: reads only cyberalertx's own dedicated log plus the shared legacy
archive, filtered to the cyberalertx vhost. The three other vhosts on this
box keep writing to /var/log/nginx/access.log untouched, and nothing here
writes to any log file, ever. Files are opened read-only, and never appended
to, truncated, removed or rotated.

PRIVACY: nothing leaves the box. No network calls at runtime, no third-party
analytics, no dependency outside the stdlib. Raw IPs live in a LogRecord in
memory for as long as it takes to classify and hash them, and are never
persisted or printed by anything downstream.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import re
import zlib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import OTHER_VHOST_TOKENS, OTHER_VHOSTS, SITE_HOSTS

logger = logging.getLogger("analytics.logread")

EXTENDED: str = "extended"
LEGACY: str = "legacy"

# The "v" field of the cax_json format. A bump means the field set changed and
# an old parser must refuse the line loudly rather than mis-read it.
FORMAT_VERSION: str = "1"

# Explicit month table instead of strptime("%b"): %b is locale-dependent in C
# while nginx always emits English abbreviations, so under a non-C locale
# strptime either breaks or — worse — silently misparses. It is also 5-10x
# faster, and this runs once per line over a year of history.
_MONTHS: dict[str, int] = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

# The combined-format regex. `(?:[^"\\]|\\.)*` for the quoted fields is what
# makes the hostile lines parse: nginx's default escaping renders an interior
# `"` as \x22 and a `\` as \x5C, so a bare `"` byte in the file can only ever
# be a field delimiter and a lone trailing backslash before a closing quote
# cannot occur. Raw TLS bytes, Cyrillic referers and user agents full of
# pipes, commas and semicolons all survive as exactly one field each.
_LEGACY_RE: re.Pattern[str] = re.compile(
    r'^(?P<ip>\S+) (?P<ident>\S+) (?P<user>\S+) '
    r'\[(?P<time>[^\]]+)\] '
    r'"(?P<request>(?:[^"\\]|\\.)*)" '
    r'(?P<status>\d{3}|-) (?P<bytes>\d+|-) '
    r'"(?P<referer>(?:[^"\\]|\\.)*)" '
    r'"(?P<ua>(?:[^"\\]|\\.)*)"\s*$'
)

# nginx escape=default renders every byte outside the printable ASCII range,
# plus `"` and `\`, as \xNN. Applied to LEGACY fields only: escape=json values
# arrive already decoded by json.loads.
_NGINX_ESCAPE_RE: re.Pattern[bytes] = re.compile(rb"\\x([0-9A-Fa-f]{2})")

# Discovery helpers.
_ROTATION_RE: re.Pattern[str] = re.compile(r"\.(\d+)(?:\.gz)?$")
_DATE_IN_NAME_RE: re.Pattern[str] = re.compile(r"(\d{4}-\d{2}-\d{2})")

# What counts as a log file in each source directory.
#
# The archive glob deliberately does NOT include bare "*.log": the archive
# directory also holds hand-kept samples such as real-fixture.log, and
# ingesting a curated sample would double-count fourteen real requests.
_ARCHIVE_GLOBS: tuple[str, ...] = ("*.gz", "*.jsonl")
_LOG_DIR_GLOBS: tuple[str, ...] = (
    "cyberalertx-access.jsonl",
    "cyberalertx-access.jsonl.*",
    "access.log",
    "access.log.*",
)

# Legacy vhost attribution (C.4). Ordered, first match wins.
_LOCALE_PATH_RE: re.Pattern[str] = re.compile(r"^/(en|ua|uk)(/|$)")
_SITE_PATH_RE: re.Pattern[str] = re.compile(r"^/(posts|healthz|admin|feedback)(/|$)|^/brand/")
_SITE_META_PATHS: frozenset[str] = frozenset({
    "/sitemap.xml", "/robots.txt", "/manifest.webmanifest", "/favicon.ico",
})
_OTHER_PATH_RE: re.Pattern[str] = re.compile(r"^/socket\.io|^/api/")
_NEXT_PATH_RE: re.Pattern[str] = re.compile(r"^/_next/")

_HEAD_BYTES: int = 65536


# --------------------------------------------------------------------------
# dataclasses
# --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class RawLine:
    """One physical log line plus enough provenance to dedupe it on re-ingest."""

    text: str
    source: str
    lineno: int
    file_key: str


@dataclass(frozen=True, slots=True)
class LogFileInfo:
    """Identity of one log file, for discovery ordering and idempotent ingest.

    `file_key` is content-derived, not name-derived, on purpose: the archive
    stopgap copies access.log.1.gz to access-2026-09-01.log.gz, and the two
    must be recognised as the same stream and read once. Hashing the first 64
    KiB DECOMPRESSED also makes a .gz and its uncompressed twin identical, and
    keeps the key stable for the live file as it grows through the day.
    """

    path: Path
    size: int
    mtime: float
    compressed: bool
    file_key: str
    first_line: str


@dataclass
class ParseStats:
    """Mutable running tally. Passed into iter_records and read afterwards.

    This is the raw material for the report's DATA QUALITY ledger, which comes
    first in the output because it is what licenses every number below it.
    """

    total: int = 0
    extended: int = 0
    legacy: int = 0
    unparseable: int = 0
    malformed_request: int = 0
    blank: int = 0
    reasons: dict[str, int] = field(default_factory=dict)
    files_read: list[str] = field(default_factory=list)
    files_unreadable: list[tuple[str, str]] = field(default_factory=list)
    # Lines carrying a CF-Ray header from a peer outside our compiled
    # Cloudflare list. Non-zero means the published ranges have moved and
    # CLOUDFLARE_IPV4/IPV6 in bots.py need a refresh: the classifier is
    # currently discarding real readers as direct-to-origin probes.
    stale_cf_ranges: int = 0


@dataclass(frozen=True, slots=True)
class LogRecord:
    """One parsed request. Format-neutral: every consumer codes against this."""

    # -- provenance
    fmt: str
    source_path: str
    lineno: int
    file_key: str
    raw: str
    # -- time
    ts: datetime
    tz_offset_seconds: int
    # -- network
    client_ip: str | None
    peer_ip: str | None
    ip_is_visitor: bool
    # -- request
    host: str | None
    method: str | None
    path: str
    query: str
    raw_target: str | None
    protocol: str | None
    status: int | None
    body_bytes: int | None
    total_bytes: int | None
    request_time: float | None
    upstream_time: float | None
    scheme: str | None
    malformed_request: bool
    # -- cloudflare
    cf_country: str | None
    cf_ray: str | None
    cf_colo: str | None
    # -- headers
    referer: str | None
    user_agent: str | None
    accept_language: str | None
    # -- next.js / fetch metadata
    rsc: bool
    prefetch: bool | None
    sec_fetch_mode: str | None
    sec_fetch_dest: str | None
    sec_purpose: str | None
    # -- client hints
    ch_ua: str | None
    ch_platform: str | None
    ch_platform_version: str | None
    ch_mobile: bool | None
    ch_model: str | None
    ch_available: bool
    # -- attribution
    vhost: str
    vhost_confidence: str


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------
def _is_gz(path: Path) -> bool:
    """True when the file should be read through gzip."""
    return path.suffix == ".gz"


def log_file_info(path: Path) -> LogFileInfo:
    """Stat + read the head decompressed to compute a growth-stable file_key.

    The key identifies a STREAM, not a snapshot of it, and it is derived from
    the FIRST COMPLETE LINE rather than from a fixed-size prefix. That is the
    whole subtlety here. Hashing the first 64 KiB looks equivalent and is not:
    a log smaller than 64 KiB changes its hash every time nginx appends to it,
    so today's live `cyberalertx-access.jsonl` gets a brand-new identity on
    every ingest until it happens to exceed 64 KiB. Each of those identities
    looks unseen, every line in the file is hashed against it, and the whole
    day re-inserts — silently, since the per-line UNIQUE index cannot reject
    lines whose hash includes a file key that has changed underneath them.

    The first line of an append-only log never changes, and it carries a
    timestamp, an address and a request, so it separates one day's rotation
    from another's while surviving `archive-daily.sh` copying the file under a
    new name.

    Never raises on a short or empty file. May raise OSError when the file
    cannot be read at all — discover_logs catches that and keeps going, so
    one unreadable rotation never costs the whole run.
    """
    stat = path.stat()
    compressed = _is_gz(path)
    head = b""
    try:
        if compressed:
            with gzip.open(path, "rb") as gz:
                head = gz.read(_HEAD_BYTES)
        else:
            with open(path, "rb") as fh:
                head = fh.read(_HEAD_BYTES)
    except (EOFError, gzip.BadGzipFile, zlib.error) as exc:
        # A truncated or garbled .gz still has a usable prefix most of the
        # time; when it does not, an empty head is fine — the key stays stable
        # and iter_lines records the real failure with its message. Note that
        # PermissionError and the other OSErrors deliberately propagate:
        # discover_logs turns those into a placeholder entry so the report can
        # say which file it could not read, rather than quietly omitting it.
        logger.debug("could not read head of %s: %s", path, exc)
    # Only the first COMPLETE line — up to and including its newline — feeds the
    # key, so appending to the file cannot change it. A head with no newline at
    # all is a single unterminated line, which is still being written; it falls
    # back to the whole head, and settles as soon as the line is finished.
    newline = head.find(b"\n")
    anchor = head[:newline + 1] if newline >= 0 else head
    if anchor:
        file_key = hashlib.sha256(anchor).hexdigest()[:32]
    else:
        # Every empty file would otherwise share one key and be deduped down to
        # a single entry, which reads as a bug the first time someone looks.
        file_key = "empty-" + hashlib.sha256(str(path).encode()).hexdigest()[:26]
    first_line = head.split(b"\n", 1)[0].decode("utf-8", "replace").rstrip("\r")
    return LogFileInfo(
        path=path,
        size=stat.st_size,
        mtime=stat.st_mtime,
        compressed=compressed,
        file_key=file_key,
        first_line=first_line,
    )


def _unreadable_info(path: Path, exc: OSError) -> LogFileInfo:
    """A placeholder for a file we could not fingerprint.

    It is still returned to the caller so that iter_lines gets its turn,
    fails the same way, and records the error in ParseStats.files_unreadable
    where the report can print it. Silently dropping the file here would hide
    a permissions problem behind a plausible-looking but incomplete report.
    """
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return LogFileInfo(
        path=path,
        size=size,
        mtime=0.0,
        compressed=_is_gz(path),
        # Unique per path, so several unreadable files do not collapse into one.
        file_key="unreadable-" + hashlib.sha256(str(path).encode()).hexdigest()[:20],
        first_line="",
    )


def _recency_key(info: LogFileInfo) -> tuple[str, int, str]:
    """Sort key ordering log files OLDEST FIRST.

    Two naming schemes have to interleave correctly in one list:

      * date-named archives   access-2026-08-19.log.gz
      * logrotate rotations   access.log, access.log.1, access.log.2.gz ...

    The date in the name wins when there is one; otherwise the file's mtime
    date stands in, which is exactly right for rotations since logrotate
    stamps them when it rotates. Within one day, a HIGHER rotation number is
    OLDER, so the index is negated: .2 sorts before .1 sorts before the live
    file (index -1 -> +1, sorting last).
    """
    name = info.path.name
    match = _DATE_IN_NAME_RE.search(name)
    if match:
        date_part = match.group(1)
    else:
        date_part = datetime.fromtimestamp(info.mtime).date().isoformat() if info.mtime else "0000-00-00"
    rot = _ROTATION_RE.search(name)
    index = int(rot.group(1)) if rot else -1
    return (date_part, -index, name)


def _dir_candidates(directory: Path, globs: Sequence[str]) -> list[Path]:
    """Every readable regular file in `directory` matching one of `globs`."""
    found: dict[str, Path] = {}
    try:
        for pattern in globs:
            for path in directory.glob(pattern):
                if path.is_file() and not path.name.startswith("."):
                    found[str(path)] = path
    except OSError as exc:
        logger.warning("cannot list %s: %s", directory, exc)
    return list(found.values())


def discover_logs(
    *,
    log: Sequence[Path] | None = None,
    log_dir: Path | None = None,
    archive_dir: Path | None = None,
) -> list[LogFileInfo]:
    """Resolve the set of log files to read, newest-content-last.

    Priority when several sources are given: explicit --log paths, then
    archive_dir (data/nginx-archive/*.gz, date-named), then log_dir
    (/var/log/nginx/{cyberalertx-access.jsonl*,access.log*}). Files whose
    file_key is already present are dropped, so an archive copy and the
    /var/log original of the same day are read once. Unreadable files are
    recorded, never raised.
    """
    candidates: list[Path] = []
    if log:
        candidates.extend(Path(p) for p in log)
    if archive_dir is not None:
        candidates.extend(_dir_candidates(Path(archive_dir), _ARCHIVE_GLOBS))
    if log_dir is not None:
        candidates.extend(_dir_candidates(Path(log_dir), _LOG_DIR_GLOBS))

    seen_keys: set[str] = set()
    infos: list[LogFileInfo] = []
    # Unreadable sources are summarised in ONE line after the loop rather than
    # warned about individually. A box whose live logs are root-only produces 15
    # of these every single run, and a daily timer that prints 15 warnings on a
    # healthy day trains the reader to ignore the one day it matters.
    unreadable: list[str] = []
    for path in candidates:
        try:
            info = log_file_info(path)
        except OSError as exc:
            logger.debug("cannot fingerprint %s: %s", path, exc)
            unreadable.append(str(path))
            info = _unreadable_info(path, exc)
        if info.file_key in seen_keys:
            logger.debug("skipping %s: same content as an earlier source", path)
            continue
        seen_keys.add(info.file_key)
        infos.append(info)

    if unreadable:
        # Name the first few so the message is actionable, then count the rest.
        shown = ", ".join(unreadable[:3])
        more = f" (+{len(unreadable) - 3} more)" if len(unreadable) > 3 else ""
        logger.warning("cannot read %d of %d candidate log files: %s%s",
                       len(unreadable), len(candidates), shown, more)

    infos.sort(key=_recency_key)
    return infos


# --------------------------------------------------------------------------
# streaming
# --------------------------------------------------------------------------
def open_log(path: Path) -> Iterator[str]:
    """Yield decoded lines from a plain or .gz file, read-only, streaming.

    Mode 'rt', encoding utf-8, errors='replace' — a log full of someone's raw
    TLS bytes is not valid UTF-8 and never will be. Bounded memory: the file
    object is iterated, never read. PermissionError / OSError propagate to the
    caller, which is iter_lines, which records them.
    """
    opener = gzip.open if _is_gz(path) else open
    with opener(path, mode="rt", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            yield line.rstrip("\n").rstrip("\r")


def iter_lines(
    files: Sequence[LogFileInfo],
    *,
    stats: ParseStats | None = None,
) -> Iterator[RawLine]:
    """Stream RawLine across every file, recording unreadable files into stats
    instead of aborting the run.

    A gzip stream that ends mid-member (the archive copy taken while logrotate
    was still writing) yields everything up to the break and then records the
    error: half a day of real traffic beats no day at all.
    """
    for info in files:
        source = str(info.path)
        lineno = 0
        try:
            for line in open_log(info.path):
                lineno += 1
                yield RawLine(text=line, source=source, lineno=lineno, file_key=info.file_key)
        except (OSError, EOFError) as exc:
            if stats is not None:
                stats.files_unreadable.append((source, f"{type(exc).__name__}: {exc}"))
            logger.warning("stopped reading %s after %d lines: %s", source, lineno, exc)
            if lineno == 0:
                continue
        if stats is not None and source not in stats.files_read:
            stats.files_read.append(source)


# --------------------------------------------------------------------------
# field-level helpers
# --------------------------------------------------------------------------
def parse_nginx_time(value: str) -> tuple[datetime, int]:
    """Parse '02/Sep/2026:00:05:56 +0300' or '2026-09-02T00:05:56+03:00'.

    Returns (aware datetime, offset seconds). Raises ValueError on garbage —
    callers catch it and count the line as unparseable.

    Uses an explicit month dict, NOT strptime with %b: %b is locale-dependent
    in C while nginx always emits English abbreviations, so under a non-C
    locale strptime breaks or silently misparses. It is also 5-10x faster,
    and this is the hot loop.

    THE OFFSET IS READ, NEVER ASSUMED. These logs stamp +0300 (Europe/Kyiv);
    a parser that defaults to UTC shifts every one of them three hours and
    then reports the audience reading at 06:00.
    """
    text = value.strip()
    if not text:
        raise ValueError("empty timestamp")
    if len(text) >= 20 and text[2] == "/" and text[6] == "/":
        try:
            day = int(text[0:2])
            month = _MONTHS[text[3:6]]
            year = int(text[7:11])
            hour = int(text[12:14])
            minute = int(text[15:17])
            second = int(text[18:20])
            offset = _parse_offset(text[20:])
            stamp = datetime(
                year, month, day, hour, minute, second,
                tzinfo=timezone(timedelta(seconds=offset)),
            )
        except (KeyError, ValueError, OverflowError) as exc:
            raise ValueError(f"bad combined timestamp {value!r}") from exc
        return stamp, offset

    try:
        stamp = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"bad iso timestamp {value!r}") from exc
    utcoffset = stamp.utcoffset()
    if utcoffset is None:
        raise ValueError(f"timestamp carries no offset: {value!r}")
    return stamp, int(utcoffset.total_seconds())


def _parse_offset(text: str) -> int:
    """'+0300' or '+03:00' -> 10800. Raises ValueError when absent or broken."""
    raw = text.strip()
    if not raw or raw[0] not in "+-":
        raise ValueError(f"missing utc offset in {text!r}")
    sign = -1 if raw[0] == "-" else 1
    digits = raw[1:].replace(":", "")
    if len(digits) < 4 or not digits[:4].isdigit():
        raise ValueError(f"bad utc offset {text!r}")
    hours = int(digits[0:2])
    minutes = int(digits[2:4])
    return sign * (hours * 3600 + minutes * 60)


def unescape_nginx(value: str) -> str:
    r"""Undo escape=default's \xNN sequences and re-decode as UTF-8.

    Recovers Cyrillic in Referer and User-Agent, which nginx writes one escaped
    byte at a time (\xD0\xBF...). Applied to LEGACY fields only — escape=json
    values arrive already decoded through json.loads. Never raises: undecodable
    byte sequences become U+FFFD, which is honest and harmless.
    """
    if "\\x" not in value:
        return value
    payload = _NGINX_ESCAPE_RE.sub(
        lambda m: bytes([int(m.group(1), 16)]),
        value.encode("utf-8", "surrogateescape"),
    )
    return payload.decode("utf-8", "replace")


def split_request(request: str) -> tuple[str | None, str | None, str | None]:
    """'GET /en HTTP/1.1' -> ('GET', '/en', 'HTTP/1.1').

    Anything not exactly three space-separated parts -> (None, None, None).
    That is not a parse failure: it is a malformed request field, which on this
    box means raw TLS handshake bytes or an empty request from a scanner that
    spoke the wrong protocol at port 443. A real target can never contain a
    space, because nginx escapes it to \\x20.
    """
    parts = request.split(" ")
    if len(parts) != 3 or not parts[0] or not parts[1]:
        return (None, None, None)
    return (parts[0], parts[1], parts[2])


def split_target(target: str) -> tuple[str, str]:
    """'/en/threat/ab?x=1' -> ('/en/threat/ab', 'x=1').

    Percent-decodes the path with errors='replace'; leaves the query raw,
    because the query is matched against literal markers like `_rsc` and
    decoding it would only invite double-decoding bugs. Never raises.
    """
    if not target:
        return ("", "")
    path, _, query = target.partition("?")
    try:
        decoded = unquote(path, encoding="utf-8", errors="replace")
    except (UnicodeDecodeError, ValueError):  # pragma: no cover - unquote is total
        decoded = path
    return (decoded, query)


def referer_host(referer: str | None) -> str | None:
    """Lowercased hostname of a referer URL, or None. Never raises on garbage."""
    if not referer or referer == "-":
        return None
    try:
        host = urlsplit(referer).hostname
    except ValueError:
        return None
    return host.lower() if host else None


def attribute_vhost(
    *,
    host: str | None,
    path: str,
    referer: str | None,
) -> tuple[str, str]:
    """Return (vhost, confidence) per C.4. host is None for legacy lines.

    Extended lines log $host, so attribution is exact and always `certain`.
    Legacy lines do not, so this is a heuristic and says so — rules 4 and 5 are
    `likely` rather than `certain` because the other three vhosts COULD serve
    those paths, and measured traffic says they do not.

    Because cyberalertx is the effective default server for 0.0.0.0:443, every
    IP-direct probe and every unmatched-Host request also lands in the shared
    legacy log and falls through to `unattributed`. That is correct:
    `unattributed` is overwhelmingly hostile traffic, it is counted in the
    security section, and it is excluded from every audience number.
    """
    if host is not None:
        name = host.split(":", 1)[0].strip().lower()
        return ("cyberalertx", "certain") if name in SITE_HOSTS else ("other", "certain")

    ref_host = referer_host(referer)
    if ref_host is not None:
        if ref_host in SITE_HOSTS:
            return ("cyberalertx", "certain")
        if ref_host in OTHER_VHOSTS:
            return ("other", "certain")
    if _LOCALE_PATH_RE.match(path):
        return ("cyberalertx", "certain")
    if _SITE_PATH_RE.match(path):
        return ("cyberalertx", "likely")
    if path in _SITE_META_PATHS:
        return ("cyberalertx", "likely")
    if any(tok in path for tok in OTHER_VHOST_TOKENS) or _OTHER_PATH_RE.match(path):
        return ("other", "likely")
    if _NEXT_PATH_RE.match(path):
        return ("ambiguous", "ambiguous")
    return ("unattributed", "ambiguous")


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------
def detect_format(line: str) -> str | None:
    """EXTENDED, LEGACY, or None. Per C.2. Never raises."""
    text = line.lstrip()
    if not text:
        return None
    if text[0] == "{":
        return EXTENDED
    if _LEGACY_RE.match(text):
        return LEGACY
    return None


def _fail(stats: ParseStats | None, reason: str) -> LogRecord | None:
    """Count one unparseable line under `reason` and return None.

    Typed as returning a record so the parse functions can `return _fail(...)`
    on one line, which keeps every failure path visibly next to the condition
    that caused it.
    """
    if stats is not None:
        stats.unparseable += 1
        stats.reasons[reason] = stats.reasons.get(reason, 0) + 1
    return None


def _text(value: object) -> str | None:
    """Log field -> str or None. nginx writes '-' for absent in the combined
    format and '' for absent under escape=json; both mean the same thing."""
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    text = text.strip()
    if not text or text == "-":
        return None
    return text


def _as_int(value: object) -> int | None:
    text = _text(value)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _as_float(value: object) -> float | None:
    """Float, taking the FIRST value of a comma list.

    $upstream_response_time is a list when a request touched several upstreams
    ('0.021, 0.104'); the first hop is the one this site ever cares about.
    """
    text = _text(value)
    if text is None:
        return None
    head = text.split(",", 1)[0].strip()
    try:
        return float(head)
    except ValueError:
        return None


def _as_bool_hint(value: object) -> bool | None:
    """Sec-CH-UA-Mobile is the structured-header boolean '?1' / '?0'."""
    text = _text(value)
    if text is None:
        return None
    return text in {"?1", "1", "true", "True"}


def _colo_from_ray(ray: str | None) -> str | None:
    """'9a1b2c3d4e5f6789-IEV' -> 'IEV'. The edge that served the request."""
    if not ray or "-" not in ray:
        return None
    suffix = ray.rsplit("-", 1)[1].strip()
    return suffix.upper() if suffix.isalpha() and len(suffix) == 3 else None


def _has_rsc_query(query: str) -> bool:
    """True when the query carries Next.js's `_rsc` cache-buster."""
    return "_rsc" in query


def parse_line(raw: RawLine, *, stats: ParseStats | None = None) -> LogRecord | None:
    """Parse one line into a LogRecord, or None if it matches no format.

    NEVER raises, for any input, including truncated and binary lines. The
    blanket except is deliberate and load-bearing: an unforeseen byte sequence
    must cost one counted line, not the entire ingest.
    """
    if stats is not None:
        stats.total += 1
    text = raw.text.lstrip()
    if not text:
        if stats is not None:
            stats.blank += 1
        return None
    try:
        if text[0] == "{":
            return parse_extended(raw, stats=stats)
        if _LEGACY_RE.match(text):
            return parse_legacy(raw, stats=stats)
    except Exception as exc:  # noqa: BLE001 - see docstring
        logger.debug("unexpected parse failure at %s:%d: %r", raw.source, raw.lineno, exc)
        return _fail(stats, "parser-error")
    return _fail(stats, "no-format-match")


def parse_extended(raw: RawLine, *, stats: ParseStats | None = None) -> LogRecord | None:
    """json.loads + coercion. Unknown 'v' -> None with reason 'unknown-version'."""
    try:
        payload = json.loads(raw.text)
    except ValueError:
        return _fail(stats, "bad-json")
    if not isinstance(payload, dict):
        return _fail(stats, "bad-json")
    if _text(payload.get("v")) != FORMAT_VERSION:
        return _fail(stats, "unknown-version")

    try:
        stamp, offset = parse_nginx_time(str(payload.get("t", "")))
    except ValueError:
        return _fail(stats, "bad-time")

    host = _text(payload.get("h"))
    client_ip = _text(payload.get("ip"))
    # $realip_remote_addr is the socket peer. When real_ip did not substitute
    # anything the two are the same address, and falling back keeps the
    # Cloudflare-provenance test working instead of silently skipping it.
    peer_ip = _text(payload.get("pip")) or client_ip

    method = _text(payload.get("m"))
    raw_target = _text(payload.get("u"))
    path, query = split_target(raw_target or "")
    malformed = method is None or raw_target is None

    referer = _text(payload.get("ref"))
    vhost, confidence = attribute_vhost(host=host, path=path, referer=referer)

    ray = _text(payload.get("ray"))
    sec_purpose = _text(payload.get("sp"))
    prefetch_header = _text(payload.get("pf"))
    ch_ua = _text(payload.get("chua"))

    if stats is not None:
        stats.extended += 1
        if malformed:
            stats.malformed_request += 1

    return LogRecord(
        fmt=EXTENDED,
        source_path=raw.source,
        lineno=raw.lineno,
        file_key=raw.file_key,
        raw=raw.text,
        ts=stamp,
        tz_offset_seconds=offset,
        client_ip=client_ip,
        peer_ip=peer_ip,
        # Extended lines carry the true visitor address, restored by real_ip
        # from CF-Connecting-IP. This is the flag every visitor-identity number
        # keys off; legacy lines set it False and those numbers are suppressed.
        ip_is_visitor=True,
        host=host,
        method=method if not malformed else None,
        path="" if malformed else path,
        query="" if malformed else query,
        raw_target=raw_target if not malformed else None,
        protocol=_text(payload.get("pr")) if not malformed else None,
        status=_as_int(payload.get("st")),
        body_bytes=_as_int(payload.get("bs")),
        total_bytes=_as_int(payload.get("bt")),
        request_time=_as_float(payload.get("rt")),
        upstream_time=_as_float(payload.get("ut")),
        scheme=_text(payload.get("sch")),
        malformed_request=malformed,
        cf_country=_text(payload.get("cc")),
        cf_ray=ray,
        cf_colo=_colo_from_ray(ray),
        referer=referer,
        user_agent=_text(payload.get("ua")),
        accept_language=_text(payload.get("al")),
        rsc=bool(_text(payload.get("rsc"))) or _has_rsc_query(query),
        # Next-Router-Prefetch is the whole reason this format exists: without
        # it every EN pageview's mirror /ua prefetch counts as a UA read and
        # the locale split converges on 50/50 by construction.
        prefetch=bool(prefetch_header) or (sec_purpose is not None and "prefetch" in sec_purpose.lower()),
        sec_fetch_mode=_text(payload.get("sfm")),
        sec_fetch_dest=_text(payload.get("sfd")),
        sec_purpose=sec_purpose,
        ch_ua=ch_ua,
        ch_platform=_text(payload.get("chp")),
        ch_platform_version=_text(payload.get("chpv")),
        ch_mobile=_as_bool_hint(payload.get("chm")),
        ch_model=_text(payload.get("chmd")),
        # A non-empty Sec-CH-UA means a hint-sending browser, so an empty model
        # beside it is a genuinely empty model (desktop Chromium) rather than
        # "no hints". escape=json collapses both to "", and this is how the
        # distinction is recovered in Python.
        ch_available=ch_ua is not None,
        vhost=vhost,
        vhost_confidence=confidence,
    )


def parse_legacy(raw: RawLine, *, stats: ParseStats | None = None) -> LogRecord | None:
    """_LEGACY_RE + request-field split + vhost heuristic (C.4)."""
    match = _LEGACY_RE.match(raw.text.lstrip())
    if match is None:
        return _fail(stats, "no-format-match")

    try:
        stamp, offset = parse_nginx_time(match.group("time"))
    except ValueError:
        return _fail(stats, "bad-time")

    # Unescape BEFORE splitting: the raw TLS handshake lines are escaped byte
    # by byte, and unescaping them first is what turns them into a request
    # field with no three-part shape, i.e. into a counted malformed request
    # rather than a surprise.
    request = unescape_nginx(match.group("request"))
    method, target, protocol = split_request(request)
    malformed = method is None
    path, query = split_target(target or "")

    referer = _text(unescape_nginx(match.group("referer")))
    user_agent = _text(unescape_nginx(match.group("ua")))
    ip = _text(match.group("ip"))
    vhost, confidence = attribute_vhost(host=None, path=path, referer=referer)

    if stats is not None:
        stats.legacy += 1
        if malformed:
            stats.malformed_request += 1

    return LogRecord(
        fmt=LEGACY,
        source_path=raw.source,
        lineno=raw.lineno,
        file_key=raw.file_key,
        raw=raw.text,
        ts=stamp,
        tz_offset_seconds=offset,
        # There is no real_ip config anywhere in the legacy setup, so this is
        # the Cloudflare EDGE address. It is useless for identity (121
        # pageviews arrived via 99 of them) and perfect for provenance.
        client_ip=ip,
        peer_ip=ip,
        ip_is_visitor=False,
        host=None,
        method=method,
        path=path,
        query=query,
        raw_target=target,
        protocol=protocol,
        status=_as_int(match.group("status")),
        body_bytes=_as_int(match.group("bytes")),
        total_bytes=None,
        request_time=None,
        upstream_time=None,
        scheme=None,
        malformed_request=malformed,
        cf_country=None,
        cf_ray=None,
        cf_colo=None,
        referer=referer,
        user_agent=user_agent,
        accept_language=None,
        rsc=_has_rsc_query(query),
        # Unknowable, and that is the point: with no Next-Router-Prefetch
        # header a prefetch is indistinguishable from a real soft navigation,
        # so sessionize drops legacy `_rsc` lines from pageviews entirely and
        # the report labels legacy periods "hard navigations only".
        prefetch=None,
        sec_fetch_mode=None,
        sec_fetch_dest=None,
        sec_purpose=None,
        ch_ua=None,
        ch_platform=None,
        ch_platform_version=None,
        ch_mobile=None,
        ch_model=None,
        ch_available=False,
        vhost=vhost,
        vhost_confidence=confidence,
    )


def iter_records(
    files: Sequence[LogFileInfo],
    *,
    stats: ParseStats | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Iterator[LogRecord]:
    """The one entry point every consumer uses. Streams, bounded memory.

    since/until are tz-aware and compared against LogRecord.ts, which carries
    the offset the line itself was stamped with.
    """
    # Deferred import: bots.py names LogRecord only under TYPE_CHECKING, so
    # there is no import cycle at module load, and the parse layer stays
    # importable on its own. The Cloudflare self-check belongs here because
    # this is the only place that sees every record and the stats object.
    from .bots import is_cloudflare_ip

    for raw in iter_lines(files, stats=stats):
        record = parse_line(raw, stats=stats)
        if record is None:
            continue
        if since is not None and record.ts < since:
            continue
        if until is not None and record.ts > until:
            continue
        if (
            stats is not None
            and record.cf_ray is not None
            and record.peer_ip is not None
            and not is_cloudflare_ip(record.peer_ip)
        ):
            # A CF-Ray proves the request came through Cloudflare; a peer
            # outside our list says our list is stale. Free self-check.
            stats.stale_cf_ranges += 1
        yield record
