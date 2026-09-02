"""Command line for the local visitor analytics: ingest, report, status.

Three subcommands and one habit. `ingest` streams nginx log lines into the
persistent SQLite store, additively and idempotently — logrotate keeps fourteen
days, the user asked for all time, so the store is the only thing that can
answer the question. `report` renders a window of that store to the terminal, to
JSON or to a self-contained HTML file. `status` says what the store actually
holds, which is the first thing to check when a number looks wrong.

A bare `python -m server.analytics` is `report --since 30d`, because that is what
the user wants nine times out of ten. The insertion happens before argparse sees
the arguments, so `python -m server.analytics --json` still works.

Everything user-facing goes to stdout with the house `[analytics]` prefix; every
warning, degradation and diagnostic goes to stderr through `logging`. That split
is what makes `python -m server.analytics > report.txt` produce a clean file.

The one operational trap this tool exists inside: `/var/log/nginx/*` is mode
0640 `www-data:adm`, so a fresh checkout cannot read a single line until the
operator joins the `adm` group — and group membership only applies to new login
sessions, which is why people add themselves and then watch it fail anyway.
`_permission_message` says all of that at the moment it matters.

SCOPE: reads only cyberalertx's own dedicated log plus the shared legacy
archive, filtered to the cyberalertx vhost. The three other vhosts on this
box keep writing to /var/log/nginx/access.log untouched, and nothing here
writes to any log file, ever.

PRIVACY: nothing leaves the box. No network calls at runtime, no third-party
analytics, no dependency outside the stdlib. Raw IPs are never persisted or
printed — only salted hashes, with the salt rotated daily and retained 14 days.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import (
    DATA_DIR,
    DEFAULT_ARCHIVE_DIR,
    DEFAULT_DB_PATH,
    DEFAULT_LOG_DIR,
    DEFAULT_TZ,
    SALT_RETENTION_DAYS,
    SITE_HOSTS,
    __version__,
)
from .aggregate import build_coverage, build_report
from .bots import BEHAVIOURAL_RULE, Verdict
from .htmlreport import write_html
from .logread import LogRecord, ParseStats, discover_logs, iter_records
from .report import format_int, render
from .sessionize import (
    AUTOMATION_MIN_PAGEVIEWS,
    AutomationFindings,
    Event,
    Ledger,
    SaltProvider,
    demote_automation,
    iter_events,
    sessionize,
)
from .store import AnalyticsStore, DayCapabilities, SourceFile
from .useragent import Agent

logger = logging.getLogger("analytics")

TAG = "[analytics]"
SUBCOMMANDS = ("ingest", "report", "status")

# Global flags that consume a following value. `_insert_default_subcommand` has
# to skip those values, or it mistakes them for the subcommand: with
# `--db data.sqlite3 report`, an unaware scanner sees `data.sqlite3` first,
# concludes no subcommand was given and prepends one, producing
# `report --db data.sqlite3 report` — which argparse rejects. Kept beside the
# names it mirrors, and asserted against the real parser in
# `_check_value_flags` so the two cannot drift apart.
VALUE_TAKING_GLOBAL_FLAGS: frozenset[str] = frozenset({"--db", "--tz", "--color"})

_RELATIVE_RE = re.compile(r"^(\d+)\s*(min|h|d|w|m|y)$", re.IGNORECASE)
_RELATIVE_UNITS: dict[str, timedelta] = {
    "min": timedelta(minutes=1),
    "h": timedelta(hours=1),
    "d": timedelta(days=1),
    "w": timedelta(weeks=1),
    "m": timedelta(days=30),
    "y": timedelta(days=365),
}
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

_ITEMS_PATH = DATA_DIR / "items.json"

# Rows the store does not keep, and therefore cannot reconstruct. Surfaced as a
# report warning rather than silently reported as zero.
_STORE_LEDGER_CAVEAT = (
    "the store keeps parsed events, not raw lines — unparseable and blank lines "
    "are counted during ingest and read as 0 in this ledger. Use --from-logs for "
    "the full parse audit."
)


# --------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------


def _say(message: str, *, quiet: bool = False) -> None:
    """Print a `[analytics]` progress line to stdout, unless --quiet."""
    if not quiet:
        print(f"{TAG} {message}")


def _fail(message: str) -> None:
    """Print a `[analytics]` error line to stderr."""
    print(f"{TAG} {message}", file=sys.stderr)


def _emit(text: str) -> None:
    """Write the rendered report to stdout without ever dying on encoding.

    `report.render` already folds its output to ASCII when the terminal cannot
    take UTF-8, but a caller can override that, and article titles are
    Ukrainian. Falling back to the byte stream with `backslashreplace` keeps the
    run's end state correct rather than throwing away a full ingest at the last
    line.
    """
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "ascii"
        sys.stdout.flush()
        sys.stdout.buffer.write(text.encode(encoding, "backslashreplace"))


def _permission_message(path: object) -> str:
    """The actionable permission-denied text, verbatim from the contract."""
    return "\n".join((
        f"{TAG} permission denied reading {path}",
        f"{TAG} nginx logs are mode 0640 www-data:adm. Two ways to fix it:",
        f"{TAG}   1. sudo usermod -aG adm $USER      <- preferred, one time",
        f"{TAG}      then log out and back in, or for this shell only: newgrp adm",
        f'{TAG}   2. sudo -E "$(command -v python3)" -m server.analytics ingest',
        f"{TAG} Already added yourself to adm? Group membership only applies to NEW",
        f"{TAG} login sessions. Check with: id -nG",
    ))


# --------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------


def resolve_tz(name: str) -> tuple[tzinfo, str, bool]:
    """Return `(tzinfo, name, fell_back)` for an IANA zone name.

    A minimal container ships no tzdata and `ZoneInfo("Europe/Kyiv")` raises.
    That must not kill a run after every log line has been parsed, so the
    failure degrades to UTC, warns once, and is carried into the report header
    as `tz_fallback` so nobody reads a UTC heatmap as a Kyiv one.
    """
    try:
        return ZoneInfo(name), name, False
    except (ZoneInfoNotFoundError, ValueError, KeyError, OSError) as exc:
        logger.warning("timezone %s unavailable (%s) — falling back to UTC", name, exc)
        # The REQUESTED name comes back, not "UTC": the report has to be able to
        # say which zone it could not find, or the reader has no idea what the
        # numbers were supposed to be expressed in.
        return timezone.utc, name, True


def parse_when(value: str, *, now: datetime, tz: tzinfo,
               end: bool = False) -> datetime:
    """Parse one `--since` / `--until` value into an aware datetime.

    Accepts `7d`/`12h`/`45min`/`6w`/`3m`/`1y`, an ISO date (inclusive at both
    ends, so `--until 2026-08-31` really does include the 31st), an ISO
    datetime, `today`, `yesterday`, `now` and `all`. `end=True` selects the
    closing edge of a calendar day, which is the only difference between how the
    two flags read the same string. Raises ValueError on anything else; the
    caller turns that into exit 2 with the grammar spelled out.
    """
    raw = (value or "").strip()
    if not raw:
        raise ValueError("empty")
    lowered = raw.lower()

    if lowered == "now":
        return now
    if lowered == "all":
        return now if end else datetime(1970, 1, 1, tzinfo=tz)
    if lowered == "today":
        return _day_edge(now.astimezone(tz).date(), tz, end=end)
    if lowered == "yesterday":
        return _day_edge(now.astimezone(tz).date() - timedelta(days=1), tz, end=end)

    match = _RELATIVE_RE.match(lowered)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        return now - _RELATIVE_UNITS[unit] * amount

    if _ISO_DATE_RE.match(raw):
        return _day_edge(date.fromisoformat(raw), tz, end=end)

    try:
        parsed = datetime.fromisoformat(raw.replace(" ", "T", 1))
    except ValueError:
        raise ValueError(raw) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed


def _day_edge(day: date, tz: tzinfo, *, end: bool) -> datetime:
    """00:00:00 or 23:59:59.999999 local — both ends of a range are inclusive."""
    if end:
        return datetime(day.year, day.month, day.day, 23, 59, 59, 999999, tzinfo=tz)
    return datetime(day.year, day.month, day.day, tzinfo=tz)


def _window(args: argparse.Namespace, tz: tzinfo) -> tuple[datetime, datetime]:
    """Resolve --since/--until, or raise SystemExit(2) with the exact message."""
    now = datetime.now(tz)
    try:
        since = parse_when(args.since, now=now, tz=tz)
    except ValueError:
        _fail(f"cannot parse --since '{args.since}'. Use 7d, 2026-08-19, "
              "2026-08-19T10:00, today, yesterday or all.")
        raise SystemExit(EXIT_USAGE) from None
    try:
        until = parse_when(args.until, now=now, tz=tz, end=True)
    except ValueError:
        _fail(f"cannot parse --until '{args.until}'. Use 7d, 2026-08-19, "
              "2026-08-19T10:00, today, yesterday or now.")
        raise SystemExit(EXIT_USAGE) from None
    if since > until:
        _fail("--since is after --until. Nothing to report.")
        raise SystemExit(EXIT_USAGE)
    return since, until


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------


def _add_global_flags(parser: argparse.ArgumentParser) -> None:
    """Flags every subcommand accepts. Added per-subparser so that a bare
    invocation with only flags still resolves to `report`."""
    parser.add_argument(
        "--db", type=Path, default=DEFAULT_DB_PATH, metavar="PATH",
        help=f"The persistent SQLite store (default: {DEFAULT_DB_PATH}).")
    parser.add_argument(
        "--tz", default=DEFAULT_TZ, metavar="ZONE",
        help=("IANA timezone the report is expressed in. Every time-shaped "
              "conclusion — when to publish, where the peak is — is only "
              f"actionable in the audience's wall clock (default: {DEFAULT_TZ})."))
    parser.add_argument(
        "--no-color", action="store_true",
        help=("Force colour off. NO_COLOR, TERM=dumb and a non-tty stdout do "
              "the same thing automatically."))
    parser.add_argument(
        "--color", choices=("auto", "always", "never"), default="auto",
        help=("'always' keeps the escape codes when piping into `less -R`; "
              "--no-color wins over this (default: auto)."))
    parser.add_argument(
        "--ascii", action="store_true",
        help=("Force plain ASCII bars, sparklines and heatmap. Enabled "
              "automatically when stdout's encoding is not UTF-8, because a "
              "block glyph on a POSIX-locale terminal aborts the run."))
    parser.add_argument(
        "-v", "--verbose", action="count", default=0,
        help="-v for INFO, -vv for DEBUG. Diagnostics go to stderr.")
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress the [analytics] progress lines. Errors still print.")


def _add_source_flags(parser: argparse.ArgumentParser) -> None:
    """Where log lines come from. Shared by `ingest` and `report --from-logs`."""
    parser.add_argument(
        "--log", type=Path, action="append", metavar="PATH",
        help=("An explicit log file, plain or .gz. Repeatable. Highest priority "
              "source, and an exclusive one: naming a file suppresses the two "
              "directory scans below unless you also pass them explicitly. "
              "Without that, `--log one-file.gz` on this box would quietly "
              "also ingest every rotated log in /var/log/nginx."))
    # Both directories default to None rather than to their real defaults so
    # that `_sources_arg` can tell "user said nothing" from "user asked for
    # this directory". argparse cannot express that distinction any other way,
    # and the whole priority rule in section E depends on it.
    parser.add_argument(
        "--log-dir", type=Path, default=None, metavar="DIR",
        help=(f"Scanned for cyberalertx-access.jsonl* and access.log* "
              f"(default: {DEFAULT_LOG_DIR}, skipped when --log is given)."))
    parser.add_argument(
        "--archive-dir", type=Path, default=None, metavar="DIR",
        help=(f"Scanned for date-named rotated copies (default: "
              f"{DEFAULT_ARCHIVE_DIR}, skipped when --log is given). Files "
              "already read are recognised by content, so the archive copy "
              "and the /var/log original of the same day are ingested once."))


def build_parser() -> argparse.ArgumentParser:
    """Build the full argparse surface described in section E."""
    description = (__doc__ or "").split("\n\n")[0]
    parser = argparse.ArgumentParser(
        prog="python -m server.analytics",
        description=description,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m server.analytics                       last 30 days,"
            " terminal report\n"
            "  python -m server.analytics ingest                pull new log"
            " lines into the store\n"
            "  python -m server.analytics ingest --dry-run      show what would"
            " be inserted\n"
            "  python -m server.analytics report --since 7d --compare\n"
            "  python -m server.analytics report --since all --by month"
            " --all-time\n"
            "  python -m server.analytics report --since 7d --json >"
            " /tmp/audience.json\n"
            "  python -m server.analytics report --html"
            " data/analytics/report.html\n"
            "  python -m server.analytics report --since 7d --from-logs"
            "   cross-check the store\n"
            "  python -m server.analytics status                what the store"
            " holds\n"
        ),
    )
    parser.add_argument("--version", action="version",
                        version=f"cyberalertx analytics {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="{ingest,report,status}")

    # -- ingest ------------------------------------------------------------
    ingest = subparsers.add_parser(
        "ingest",
        help="Read log files into the persistent store.",
        description=("Read nginx log lines into the persistent store. Additive "
                     "and idempotent: a log file is never modified, moved or "
                     "deleted, and re-running over the same lines inserts "
                     "nothing the second time."),
    )
    _add_global_flags(ingest)
    _add_source_flags(ingest)
    ingest.add_argument(
        "--since", default="all", metavar="WHEN",
        help="Skip records older than this. 7d, 2026-08-19, today, all.")
    ingest.add_argument(
        "--until", default="now", metavar="WHEN",
        help="Skip records newer than this.")
    ingest.add_argument(
        "--reingest", action="store_true",
        help=("Re-read every file instead of trusting the already-ingested "
              "list. The per-line uniqueness index still prevents "
              "double-counting, so this is the slow path, not a destructive "
              "one."))
    ingest.add_argument(
        "--dry-run", action="store_true",
        help="Parse, classify and count, then write nothing and exit 0.")
    ingest.add_argument(
        "--batch-size", type=int, default=2000, metavar="N",
        help="Rows per transaction. Tune only for memory.")
    ingest.set_defaults(func=cmd_ingest)

    # -- report ------------------------------------------------------------
    report = subparsers.add_parser(
        "report",
        help="Render a window of the store as a report.",
        description=("Render an audience report for a window of the store. "
                     "Bot traffic is classified, subtracted and the subtraction "
                     "shown; dimensions the logs could not carry are reported "
                     "as suppressed with their reason, never as zero."),
    )
    _add_global_flags(report)
    report.add_argument(
        "--since", default="30d", metavar="WHEN",
        help="Start of the window, inclusive. 7d, 2026-08-19, today, all.")
    report.add_argument(
        "--until", default="now", metavar="WHEN",
        help="End of the window, inclusive. An ISO date includes that whole day.")
    report.add_argument(
        "--by", choices=("day", "week", "month", "year"), default="day",
        help="Bucket for the traffic-over-time section.")
    report.add_argument(
        "--all-time", action="store_true", dest="all_time",
        help=("Add the all-time summary, covering everything the store holds "
              "regardless of --since."))
    report.add_argument(
        "--compare", action="store_true",
        help=("Add period-over-period deltas against the preceding complete "
              "period. Partial periods are excluded — comparing a half-finished "
              "month against a whole one is how this section lies."))
    report.add_argument(
        "--top", type=int, default=10, metavar="N",
        help="Rows per table before the '+N more' line.")
    report.add_argument(
        "--host", action="append", metavar="HOST",
        help=("Vhost filter, repeatable or comma-separated. The literal value "
              "'all' includes the other vhosts on this box, and the report says "
              f"so loudly (default: {','.join(sorted(SITE_HOSTS))})."))
    report.add_argument(
        "--include-bots", action="store_true", dest="include_bots",
        help=("Include bot and agent traffic in the audience aggregates. These "
              "are then not audience numbers, and every label says so."))
    report.add_argument(
        "--hard-only", action="store_true", dest="hard_only",
        help=("Count only hard navigations, reproducing the naive "
              "document-only number for cross-checking."))
    report.add_argument(
        "--automation-threshold", type=int, default=AUTOMATION_MIN_PAGEVIEWS,
        dest="automation_threshold", metavar="N",
        help=("Pageview floor for the behavioural automation filter (default: "
              f"{AUTOMATION_MIN_PAGEVIEWS}). A user-agent is dropped from the "
              "audience only when it produced at least N human pageviews, "
              "fetched ZERO static assets across the whole window and was "
              "active on at least 5 days. Lower it and you start deleting "
              "returning readers, whose warm cache legitimately fetches no "
              "assets either; the report names every user-agent it removed and "
              "shows the evidence."))
    report.add_argument(
        "--no-automation-filter", action="store_true",
        dest="no_automation_filter",
        help=("Switch the behavioural automation filter off entirely. The "
              "audience numbers then count any scraper that wears a plausible "
              "browser user-agent and arrives through Cloudflare — on this "
              "site's own logs that was 44%% of the reported audience. The "
              "report says loudly that the filter did not run."))
    report.add_argument(
        "--rolling-salt", type=int, default=None, metavar="N",
        help=("Use one visitor salt across N days, enabling cross-day identity. "
              "Off by default and never enabled silently: the report prints a "
              "privacy note when it is on."))
    report.add_argument(
        "--json", action="store_true",
        help=("Emit the whole report as JSON on stdout instead of the terminal "
              "render. Keys are the dataclass field names."))
    report.add_argument(
        "--html", type=Path, default=None, metavar="PATH",
        help=("Also write a self-contained HTML file to PATH. It makes no "
              "network requests and opens offline. A relative path must stay "
              "inside the repository; an absolute one is taken as consent."))
    report.add_argument(
        "--from-logs", action="store_true", dest="from_logs",
        help=("Bypass the store and read the log files directly. Slower, and "
              "limited to what logrotate still holds — useful for verifying the "
              "store against the raw source."))
    _add_source_flags(report)
    report.set_defaults(func=cmd_report)

    # -- status ------------------------------------------------------------
    status = subparsers.add_parser(
        "status",
        help="Show what the store holds.",
        description=("Show the store's date coverage, row counts, per-day "
                     "dimension availability, last ingest time and size on "
                     "disk. Returns 0 even when the store is empty."),
    )
    _add_global_flags(status)
    status.set_defaults(func=cmd_status)

    return parser


def _insert_default_subcommand(argv: list[str]) -> list[str]:
    """Make a bare invocation mean `report --since 30d`.

    The first token that is neither a flag nor a flag's value decides: if it is
    not one of the three subcommand names, `report` is prepended. That keeps
    `python -m server.analytics --json` working, and — because the scan skips
    the values of the global flags listed in `VALUE_TAKING_GLOBAL_FLAGS` — also
    `--db data.sqlite3 report --since 7d`, which an unaware scan turns into a
    usage error by prepending a second `report`.

    `--db=path` needs no skip: the value rides in the same token.

    When a subcommand IS present but global flags precede it, the subcommand is
    hoisted to the front rather than left where it is. The global flags are
    defined on each subparser and not on the top-level parser — that is what
    lets a flags-only invocation resolve to `report` — so argparse reaches
    `--tz` before it has a subcommand to attach it to and rejects the run.
    Moving the subcommand to argv[0] turns `--tz UTC report --since 7d` into
    `report --tz UTC --since 7d`, which is the same command in the shape
    argparse can parse.
    """
    skip_next = False
    for index, token in enumerate(argv):
        if skip_next:
            skip_next = False
            continue
        if token in ("-h", "--help", "--version"):
            return argv
        if token.startswith("-"):
            if token in VALUE_TAKING_GLOBAL_FLAGS:
                skip_next = True
            continue
        if token not in SUBCOMMANDS:
            return ["report", *argv]
        if index == 0:
            return argv
        return [token, *argv[:index], *argv[index + 1:]]
    return ["report", *argv]


# --------------------------------------------------------------------------
# Shared plumbing
# --------------------------------------------------------------------------


def _colour_choice(args: argparse.Namespace) -> bool | None:
    """--no-color beats --color; 'auto' defers to the stream probes."""
    if args.no_color or args.color == "never":
        return False
    if args.color == "always":
        return True
    return None


def _host_filter(args: argparse.Namespace) -> tuple[str, ...]:
    """Normalise --host into a lowercase tuple; 'all' disables filtering."""
    raw = getattr(args, "host", None)
    if not raw:
        return tuple(sorted(SITE_HOSTS))
    hosts: list[str] = []
    for entry in raw:
        hosts.extend(part.strip().lower() for part in entry.split(",") if part.strip())
    return tuple(hosts) or tuple(sorted(SITE_HOSTS))


def _host_matches(record: LogRecord, hosts: frozenset[str]) -> bool:
    """Keep a record for this report.

    The extended format logs `$host` and the test is exact. The legacy format
    does not, so the vhost attribution from `logread` stands in: everything
    except a line positively attributed to one of the *other* three vhosts is
    kept, which deliberately keeps the unattributed direct-to-origin probes so
    the ledger can subtract them in the open.
    """
    if "all" in hosts:
        return True
    if record.host:
        return record.host.lower() in hosts
    return record.vhost != "other"


def _sources_arg(args: argparse.Namespace) -> dict[str, Any]:
    """`discover_logs` keyword arguments from the parsed flags.

    Implements the section E priority rule: --log wins, then --archive-dir,
    then --log-dir. The part that needs code rather than ordering is
    exclusivity. An explicit --log means "read this file", so the two default
    directories are dropped; naming a directory as well opts it back in. Both
    directories still work standalone, which is what the contract requires of
    them. `_resolved_sources` writes the outcome back onto the namespace so the
    progress and error messages name the directories actually scanned instead
    of the ones that were skipped.
    """
    explicit = list(args.log) if getattr(args, "log", None) else None
    log_dir = getattr(args, "log_dir", None)
    archive_dir = getattr(args, "archive_dir", None)
    if explicit is None:
        # Nothing named: fall back to both defaults, newest archive first.
        if archive_dir is None:
            archive_dir = DEFAULT_ARCHIVE_DIR
        if log_dir is None:
            log_dir = DEFAULT_LOG_DIR
    return {"log": explicit, "log_dir": log_dir, "archive_dir": archive_dir}


def _resolved_sources(args: argparse.Namespace) -> dict[str, Any]:
    """`_sources_arg` plus a note on the namespace of what was actually used."""
    sources = _sources_arg(args)
    args.log_dir = sources["log_dir"]
    args.archive_dir = sources["archive_dir"]
    return sources


def _describe_sources(args: argparse.Namespace) -> str:
    """Human-readable list of the places a failed discovery actually looked."""
    places: list[str] = []
    if getattr(args, "log", None):
        places.extend(str(p) for p in args.log)
    if args.archive_dir is not None:
        places.append(str(args.archive_dir))
    if args.log_dir is not None:
        places.append(str(args.log_dir))
    return ", ".join(places) if places else "nowhere"


class _CapabilityTracker:
    """Accumulate per-day `DayCapabilities` while events stream past.

    A dimension that did not exist on a given day must be *labelled* in the
    report, not plotted as a zero, and the only place that is cheaply knowable
    is here, one event at a time, while the rows are already in hand. One small
    dict per calendar date, so memory stays bounded no matter how large the log.
    """

    __slots__ = ("days",)

    def __init__(self) -> None:
        self.days: dict[str, dict[str, Any]] = {}

    def observe(self, event: Event) -> None:
        """Fold one event's available dimensions into its day's record."""
        record = event.record
        day = self.days.get(event.date)
        stamp = event.local_ts.isoformat()
        if day is None:
            day = {
                "formats": set(), "host": False, "client_ip": False,
                "country": False, "language": False, "hints": False,
                "rsc": False, "timing": False, "events": 0,
                "first": stamp, "last": stamp,
            }
            self.days[event.date] = day
        day["formats"].add(record.fmt)
        day["events"] += 1
        day["host"] = day["host"] or record.host is not None
        day["client_ip"] = day["client_ip"] or bool(record.ip_is_visitor)
        day["country"] = day["country"] or record.cf_country is not None
        day["language"] = day["language"] or bool(record.accept_language)
        day["hints"] = day["hints"] or bool(record.ch_available)
        day["rsc"] = day["rsc"] or record.prefetch is not None
        day["timing"] = day["timing"] or record.request_time is not None
        if stamp < day["first"]:
            day["first"] = stamp
        if stamp > day["last"]:
            day["last"] = stamp

    def capabilities(self) -> list[DayCapabilities]:
        """One `DayCapabilities` per observed date, oldest first."""
        out: list[DayCapabilities] = []
        for local_date in sorted(self.days):
            day = self.days[local_date]
            formats = day["formats"]
            log_format = ("mixed" if len(formats) > 1
                          else (next(iter(formats)) if formats else "legacy"))
            out.append(DayCapabilities(
                local_date=local_date,
                log_format=log_format,
                has_host=day["host"],
                has_client_ip=day["client_ip"],
                has_country=day["country"],
                has_accept_language=day["language"],
                has_client_hints=day["hints"],
                has_rsc_headers=day["rsc"],
                has_timing=day["timing"],
                events=day["events"],
                first_seen=day["first"],
                last_seen=day["last"],
            ))
        return out


def _tracked(events: Iterable[Event], tracker: _CapabilityTracker) -> Iterator[Event]:
    """Pass events through untouched while the tracker watches them."""
    for event in events:
        tracker.observe(event)
        yield event


class _RollingSaltProvider(SaltProvider):
    """A `SaltProvider` that reuses one salt across N days.

    The default is a fresh salt every day, which makes cross-day identity
    impossible by construction — a deliberate privacy trade, not an oversight.
    `--rolling-salt N` widens the window by flooring each moment onto an N-day
    grid before asking for its salt, so every day inside a window resolves to
    the same key. It is never enabled silently: the report carries a bold
    warning whenever it is on.
    """

    def __init__(self, days: int, **kwargs: Any) -> None:
        window = max(1, int(days))
        kwargs.setdefault("retention_days", max(SALT_RETENTION_DAYS, window))
        super().__init__(**kwargs)
        self._window = window

    def salt_for(self, moment: datetime) -> str:
        """Floor onto the N-day grid, then delegate."""
        anchor = moment - timedelta(days=moment.toordinal() % self._window)
        return super().salt_for(anchor)


def _load_titles() -> dict[str, str]:
    """Map article fingerprints to headlines, so the report shows titles.

    Best effort by design: a missing or unreadable `data/items.json` costs the
    content section its headlines and nothing else, and an analytics run must
    never fail because of the news store.
    """
    try:
        raw = json.loads(_ITEMS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.info("no article titles available (%s): %s", _ITEMS_PATH, exc)
        return {}
    items = raw.get("items", raw) if isinstance(raw, dict) else raw
    titles: dict[str, str] = {}
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            fingerprint = item.get("fingerprint")
            title = item.get("title")
            if isinstance(fingerprint, str) and isinstance(title, str):
                titles[fingerprint] = title
    return titles


def _load_publish_times(since: datetime, until: datetime) -> list[datetime]:
    """Publish timestamps in the window, for the heatmap overlay.

    Without these the "when they read" section shows the user their own cron
    schedule reflected back at them and calls it an audience.
    """
    try:
        raw = json.loads(_ITEMS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = raw.get("items", raw) if isinstance(raw, dict) else raw
    out: list[datetime] = []
    if not isinstance(items, list):
        return out
    for item in items:
        if not isinstance(item, dict):
            continue
        stamp = item.get("published_at")
        if not isinstance(stamp, str):
            continue
        try:
            moment = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        if since <= moment <= until:
            out.append(moment)
    return out


# --------------------------------------------------------------------------
# ingest
# --------------------------------------------------------------------------


def cmd_ingest(args: argparse.Namespace) -> int:
    """Stream log files into the store, additively and idempotently."""
    tz, tz_name, _ = resolve_tz(args.tz)
    since, until = _window(args, tz)
    quiet = args.quiet

    files = discover_logs(**_resolved_sources(args))
    if not files:
        _fail(f"no log files found. Looked in: {_describe_sources(args)}. "
              "Pass --log PATH to name one explicitly.")
        return EXIT_USAGE

    archive_root = (str(Path(args.archive_dir).resolve())
                    if args.archive_dir is not None else None)
    from_archive = sum(1 for info in files
                       if archive_root is not None
                       and str(Path(info.path).resolve()).startswith(archive_root))
    _say(f"scanning {len(files)} files: {from_archive} archive, "
         f"{len(files) - from_archive} live", quiet=quiet)

    salts = SaltProvider()
    stats = ParseStats()
    tracker = _CapabilityTracker()
    total_inserted = total_duplicates = total_lines = 0
    dates_touched: set[str] = set()

    with AnalyticsStore(args.db) as store:
        pending = [info for info in files
                   if store.needs_ingest(info, reingest=args.reingest)]
        skipped = len(files) - len(pending)
        _say(f"{len(files)} files found, {skipped} already ingested, "
             f"{len(pending)} to read", quiet=quiet)

        for info in pending:
            before = stats.total
            ledger = Ledger()
            records = _filtered_records(
                iter_records([info], stats=stats, since=since, until=until))
            events = _tracked(
                iter_events(records, tz=tz, salts=salts, ledger=ledger), tracker)
            inserted, duplicates = store.ingest_events(
                events, source=info, batch_size=args.batch_size,
                dry_run=args.dry_run)
            lines = stats.total - before
            total_lines += lines
            total_inserted += inserted
            total_duplicates += duplicates
            _say(f"{Path(info.path).name:<34} {format_int(lines):>8} lines -> "
                 f"{format_int(inserted):>7} events "
                 f"({format_int(ledger.direct_origin)} direct-to-origin)",
                 quiet=quiet)
            if not args.dry_run:
                store.record_source(SourceFile(
                    file_key=info.file_key,
                    last_path=str(info.path),
                    size=info.size,
                    mtime=info.mtime,
                    first_line=info.first_line,
                    lines_ingested=lines,
                    bytes_ingested=info.size,
                    ingested_at=datetime.now(timezone.utc).isoformat(),
                ))

        if stats.files_unreadable and not stats.files_read and not skipped:
            # Only a real failure when the run accomplished NOTHING: it read no
            # file AND had nothing already ingested to fall back on.
            #
            # The `not skipped` clause is load-bearing for the systemd timer.
            # discover_logs always scans /var/log/nginx as well as the archive,
            # so on a box where the live logs are unreadable (no adm group) but
            # the archive is current, every run finds 0 files to read and 15
            # already ingested. Without this clause that wholly successful
            # no-op exited 1, the timer reported FAILURE daily, and a genuine
            # ingest failure would be indistinguishable from the routine noise.
            _fail_unreadable(stats)
            return EXIT_ERROR

        capabilities = tracker.capabilities()
        dates_touched = {cap.local_date for cap in capabilities}
        if not args.dry_run:
            # Capability records are NOT written here. `store.ingest_events`
            # already accumulated and wrote them during the insert pass, and
            # writing the tracker's copy as well recorded every event twice —
            # `record_capabilities` sums on merge, so `status` reported exactly
            # double the events the store actually held. The tracker is still
            # needed for `dates_touched`, and it is the sole source on the
            # --from-logs path, which has no store to do it for us.
            rebuilt = store.rebuild_rollup(sorted(dates_touched))
        else:
            rebuilt = 0

        salts.prune()
        salts.save()

        _say(f"inserted {format_int(total_inserted)} events, skipped "
             f"{format_int(total_duplicates)} duplicates, "
             f"{format_int(stats.unparseable)} unparseable", quiet=quiet)
        if args.dry_run:
            _say("dry run — nothing was written", quiet=quiet)
        else:
            _say(f"rollup rebuilt for {len(dates_touched)} dates "
                 f"({format_int(rebuilt)} rows)", quiet=quiet)

        status = store.status()
        if status.first_date and status.last_date:
            _say(f"done. Store now holds {status.first_date} .. {status.last_date} "
                 f"({status.days_present} days, "
                 f"{format_int(status.total_events)} events).", quiet=quiet)
        else:
            _say("done. Store is empty.", quiet=quiet)

    _warn_unreadable(stats)
    logger.debug("ingest window %s .. %s in %s", since, until, tz_name)
    return EXIT_OK


def _filtered_records(records: Iterable[LogRecord]) -> Iterator[LogRecord]:
    """Ingest keeps every vhost's lines so the ledger can subtract them openly;
    the report applies the host filter later."""
    return iter(records)


def _warn_unreadable(stats: ParseStats) -> None:
    """A partly unreadable run continues and warns; only a total failure exits 1."""
    for path, reason in stats.files_unreadable:
        logger.warning("could not read %s: %s", path, reason)


def _fail_unreadable(stats: ParseStats) -> None:
    """Print the actionable message for a run that could read nothing at all."""
    path = stats.files_unreadable[0][0] if stats.files_unreadable else "the log files"
    reasons = " ".join(reason.lower() for _, reason in stats.files_unreadable)
    if "permission" in reasons or "denied" in reasons or "errno 13" in reasons:
        print(_permission_message(path), file=sys.stderr)
    else:
        _fail(f"no log file could be read. First failure: {path}")


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------


def cmd_report(args: argparse.Namespace) -> int:
    """Build and render a report for the requested window."""
    tz, tz_name, tz_fallback = resolve_tz(args.tz)
    since, until = _window(args, tz)
    hosts = frozenset(_host_filter(args))
    quiet = args.quiet or args.json

    if args.from_logs:
        built = _report_from_logs(args, tz=tz, tz_name=tz_name,
                                 tz_fallback=tz_fallback, since=since,
                                 until=until, hosts=hosts)
    else:
        built = _report_from_store(args, tz=tz, tz_name=tz_name,
                                   tz_fallback=tz_fallback, since=since,
                                   until=until, hosts=hosts)
    if isinstance(built, int):
        return built
    report = built

    if args.json:
        json.dump(_jsonable(report), sys.stdout, ensure_ascii=False, indent=2,
                  sort_keys=False)
        sys.stdout.write("\n")
    else:
        _emit(render(report, color=_colour_choice(args),
                     ascii_only=True if args.ascii else None))

    if args.html is not None:
        try:
            written = write_html(report, args.html)
        except (OSError, ValueError) as exc:
            _fail(f"cannot write HTML to {args.html}: {exc}")
            return EXIT_ERROR
        _say(f"wrote {written}", quiet=quiet)
    return EXIT_OK


def _automation_options(args: argparse.Namespace) -> dict[str, Any]:
    """The two CLI knobs on the behavioural filter, read once for both paths.

    Read through getattr with the module defaults so a caller that built its
    Namespace by hand — every existing test does — keeps the filter ON at the
    calibrated threshold rather than crashing or silently switching it off.
    """
    return {
        "enabled": not getattr(args, "no_automation_filter", False),
        "min_pageviews": int(getattr(args, "automation_threshold",
                                     AUTOMATION_MIN_PAGEVIEWS)),
    }


def _report_from_logs(args: argparse.Namespace, *, tz: tzinfo, tz_name: str,
                      tz_fallback: bool, since: datetime, until: datetime,
                      hosts: frozenset[str]) -> Any:
    """Build a report straight from the log files, bypassing the store."""
    files = discover_logs(**_resolved_sources(args))
    if not files:
        _fail(f"no log files found. Looked in: {_describe_sources(args)}. "
              "Pass --log PATH to name one explicitly.")
        return EXIT_USAGE

    stats = ParseStats()
    ledger = Ledger()
    tracker = _CapabilityTracker()
    salts = (_RollingSaltProvider(args.rolling_salt) if args.rolling_salt
             else SaltProvider())

    records = (r for r in iter_records(files, stats=stats, since=since, until=until)
               if _host_matches(r, hosts))
    events = list(_tracked(
        iter_events(records, tz=tz, salts=salts, hard_only=args.hard_only,
                    ledger=ledger), tracker))

    if stats.files_unreadable and not stats.files_read:
        _fail_unreadable(stats)
        return EXIT_ERROR
    _warn_unreadable(stats)

    # The cross-request pass, before ANYTHING downstream reads the events. The
    # ledger `iter_events` just filled is corrected in place, so the funnel
    # still sums to the line count; sessions, every audience counter and the
    # heatmap follow for free, because all of them read `Event.is_pageview`.
    events, automation = demote_automation(events, ledger=ledger,
                                           **_automation_options(args))

    sessions = sessionize(events)
    coverage = build_coverage(tracker.capabilities(),
                              since=since.date(), until=until.date())
    since = _clamp_since(since, coverage, tz)
    warnings = _extra_warnings(args, stats, from_store=False)
    return _assemble(args, events=events, sessions=sessions, ledger=ledger,
                     stats=stats, coverage=coverage, since=since, until=until,
                     tz_name=tz_name, tz_fallback=tz_fallback,
                     sources=[str(info.path) for info in files],
                     store=None, warnings=warnings, hosts=sorted(hosts),
                     automation=automation)


def _report_from_store(args: argparse.Namespace, *, tz: tzinfo, tz_name: str,
                       tz_fallback: bool, since: datetime, until: datetime,
                       hosts: frozenset[str]) -> Any:
    """Build a report from the persistent store — the normal path.

    The store holds enriched rows rather than `Event` objects, so the rows are
    rehydrated here, in the wiring layer, into exactly the shape the aggregator
    expects. Two columns the schema does not carry (`locale_assigned` and the
    agent subclass) come back at their defaults; both are additive migrations
    when they start to matter, and neither silently changes a count.
    """
    if not Path(args.db).exists():
        _fail(f"no analytics store at {args.db}. Run "
              "`python -m server.analytics ingest` first, or pass --from-logs "
              "to read the log files directly.")
        return EXIT_USAGE
    try:
        store = AnalyticsStore(args.db, read_only=True)
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            _fail("database is locked — another ingest may be running.")
        else:
            _fail(f"cannot open the store at {args.db}: {exc}")
        return EXIT_ERROR

    with store:
        capabilities = store.capabilities(since=since.date(), until=until.date())
        coverage = build_coverage(capabilities, since=since.date(),
                                  until=until.date())
        since = _clamp_since(since, coverage, tz)
        events: list[Event] = []
        broken = 0
        host_filtered = 0
        for row in store.iter_events(since=since.date(), until=until.date(),
                                     include_bots=True):
            if "all" not in hosts:
                host = _row_get(row, "host")
                if host and host.lower() not in hosts:
                    # Counted, not silently dropped. These lines are real and
                    # were read; they belong to one of the other vhosts sharing
                    # this box. Skipping them without a tally left the ledger
                    # claiming 'other vhosts 0' while its own line total had
                    # already shrunk by the number it was refusing to name.
                    host_filtered += 1
                    continue
            event = _event_from_row(row, tz=tz)
            if event is None:
                broken += 1
                continue
            events.append(event)

        if broken:
            logger.warning("%d stored rows could not be rehydrated and were "
                           "skipped", broken)
        if broken and not events:
            _fail("the store's rows do not match this version of the analytics "
                  "modules. Re-run `ingest --reingest`, or use --from-logs.")
            return EXIT_ERROR

        # Before the ledger is reconstructed, so `_ledger_from_events` sees the
        # rewritten verdicts and books them itself — no delta arithmetic needed
        # on this path, which is why no ledger is handed over.
        events, automation = demote_automation(events, **_automation_options(args))

        ledger = _ledger_from_events(events)
        ledger.other_vhost += host_filtered
        ledger.total_lines += host_filtered
        stats = ParseStats(total=ledger.total_lines)
        sessions = sessionize(events)
        warnings = _extra_warnings(args, stats, from_store=True)
        return _assemble(args, events=events, sessions=sessions, ledger=ledger,
                         stats=stats, coverage=coverage, since=since,
                         until=until, tz_name=tz_name, tz_fallback=tz_fallback,
                         sources=["<store>"], store=store, warnings=warnings,
                         hosts=sorted(hosts), automation=automation)


def _assemble(args: argparse.Namespace, *, events: Sequence[Event],
              sessions: Sequence[Any], ledger: Ledger, stats: ParseStats,
              coverage: Any, since: datetime, until: datetime, tz_name: str,
              tz_fallback: bool, sources: Sequence[str], store: Any,
              warnings: Sequence[str], hosts: Sequence[str],
              automation: AutomationFindings | None = None) -> Any:
    """Hand everything to `aggregate.build_report` and attach CLI-level notes."""
    report = build_report(
        events, list(sessions),
        ledger=ledger,
        parse_stats=stats,
        coverage=coverage,
        since=since,
        until=until,
        tz_name=tz_name,
        tz_fallback=tz_fallback,
        sources=list(sources),
        top_n=args.top,
        include_bots=args.include_bots,
        hard_only=args.hard_only,
        bucket=args.by,
        all_time=args.all_time,
        compare=args.compare,
        store=store,
        publish_times=_load_publish_times(since, until),
        titles=_load_titles(),
        automation=automation,
    )
    # The vhost filter is a CLI decision, so the CLI is what records it — the
    # header prints a loud line when it has been switched off.
    patch: dict[str, Any] = {"host_filter": tuple(hosts)}
    if warnings:
        patch["warnings"] = tuple(report.warnings) + tuple(warnings)
    return dataclasses.replace(report, **patch)


def _clamp_since(since: datetime, coverage: Any, tz: tzinfo) -> datetime:
    """Pull the window's start forward to the first day actually held.

    `--since all` resolves to the epoch, and a header reading "01 Jan 1970 -
    02 Sep 2026 (20 699 days)" is worse than useless: it invites the reader to
    treat fifteen days of data as twenty thousand. The coverage banner still
    states what is held; this only stops the *heading* from lying about it.
    """
    first = getattr(coverage, "first_date", None)
    if first is None:
        return since
    earliest = datetime(first.year, first.month, first.day, tzinfo=tz)
    return max(since, earliest)


def _extra_warnings(args: argparse.Namespace, stats: ParseStats, *,
                    from_store: bool) -> list[str]:
    """Warnings the CLI knows about that the aggregator cannot see."""
    warnings: list[str] = []
    if from_store:
        warnings.append(_STORE_LEDGER_CAVEAT)
    if args.rolling_salt:
        warnings.append(
            f"--rolling-salt {args.rolling_salt} is ON: one visitor salt spans "
            f"{args.rolling_salt} days, so visitor identity crosses days. This is "
            "a deliberate weakening of the daily-salt privacy default, and it "
            "only affects --from-logs runs; stored events keep the salt they "
            "were ingested with.")
    if args.include_bots:
        warnings.append(
            "--include-bots is ON: bot and agent traffic is inside every "
            "aggregate below. These are not audience numbers.")
    for path, reason in stats.files_unreadable:
        warnings.append(f"could not read {path} ({reason}) — it is missing from "
                        "every number below.")
    return warnings


# --------------------------------------------------------------------------
# Rehydration of stored rows
# --------------------------------------------------------------------------


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    """Read one column from a sqlite3.Row without dying on a schema change."""
    try:
        value = row[key]
    except (IndexError, KeyError, TypeError):
        return default
    return default if value is None else value


def _build(cls: Any, values: dict[str, Any]) -> Any:
    """Construct a dataclass from the subset of `values` it declares.

    Filtering on the declared field names means a field this module does not
    know about keeps its default instead of raising, which is what makes the
    additive-migration promise in `store.py` survive contact with the renderer.
    """
    names = {f.name for f in dataclasses.fields(cls)}
    return cls(**{k: v for k, v in values.items() if k in names})


def _event_from_row(row: Any, *, tz: tzinfo) -> Event | None:
    """Rebuild one `Event` from a stored row, or None if the row is unusable."""
    try:
        epoch = int(_row_get(row, "utc_epoch", 0) or 0)
        moment = datetime.fromtimestamp(epoch, tz=timezone.utc)
        local_ts = moment.astimezone(tz)
        offset = local_ts.utcoffset()
        log_format = str(_row_get(row, "log_format", "legacy") or "legacy")
        rule = str(_row_get(row, "rule", "default") or "default")
        klass = str(_row_get(row, "klass", "human") or "human")
        category = str(_row_get(row, "category", "human") or "human")
        nav = str(_row_get(row, "nav", "unknown") or "unknown")
        visitor = _row_get(row, "visitor")

        record = _build(LogRecord, {
            "fmt": log_format,
            "source_path": "<store>",
            "lineno": 0,
            "file_key": str(_row_get(row, "line_hash", "") or ""),
            "raw": "",
            "ts": moment,
            "tz_offset_seconds": int(offset.total_seconds()) if offset else 0,
            "client_ip": None,
            "peer_ip": None,
            "ip_is_visitor": visitor is not None,
            "host": _row_get(row, "host"),
            "method": _row_get(row, "method"),
            "path": str(_row_get(row, "path", "") or ""),
            "query": "",
            "raw_target": _row_get(row, "path"),
            "protocol": None,
            "status": _row_get(row, "status"),
            "body_bytes": _row_get(row, "body_bytes"),
            "total_bytes": _row_get(row, "total_bytes"),
            "request_time": _row_get(row, "request_time"),
            "upstream_time": _row_get(row, "upstream_time"),
            "scheme": None,
            "malformed_request": rule == "malformed",
            "cf_country": _row_get(row, "country"),
            "cf_ray": None,
            "cf_colo": None,
            "referer": None,
            "user_agent": None,
            "accept_language": _row_get(row, "language"),
            "rsc": nav in ("soft", "prefetch"),
            "prefetch": (nav == "prefetch") if log_format != "legacy" else None,
            "sec_fetch_mode": None,
            "sec_fetch_dest": None,
            "sec_purpose": None,
            "ch_ua": None,
            "ch_platform": None,
            "ch_platform_version": None,
            "ch_mobile": None,
            "ch_model": None,
            "ch_available": False,
            "vhost": "cyberalertx",
            "vhost_confidence": "certain",
        })

        agent = _build(Agent, {
            "browser_family": str(_row_get(row, "browser", "Other") or "Other"),
            "browser_version": _row_get(row, "browser_ver"),
            "browser_version_full": None,
            "os_family": str(_row_get(row, "os", "Unknown") or "Unknown"),
            "os_version": _row_get(row, "os_ver"),
            "os_version_reliable": bool(_row_get(row, "os_ver_ok", 0)),
            "device_type": str(_row_get(row, "device_type", "unknown") or "unknown"),
            "device_vendor": _row_get(row, "vendor"),
            "device_model": _row_get(row, "model"),
            "device_model_raw": _row_get(row, "model"),
            "model_source": _row_get(row, "model_source"),
            "in_app": _row_get(row, "in_app"),
            "is_webview": bool(_row_get(row, "in_app")),
            "ua_declares_bot": klass == "bot",
        })

        # subclass and subscribers are read back rather than left None: they are
        # what separates the site's own Telegram publishing from a person
        # pasting a link, and without them LINK SHARES (REACH) and FEED
        # SUBSCRIBERS render empty on the store path while --from-logs fills
        # them from the same lines. Rows ingested before schema v2 have NULL
        # here and simply do not contribute until a --reingest.
        subscribers = _row_get(row, "subscribers")
        verdict = _build(Verdict, {
            "klass": klass,
            "label": str(_row_get(row, "bot_label")
                         or ("Human" if klass == "human" else category)),
            "category": category,
            "rule": rule,
            "subclass": _row_get(row, "subclass"),
            "subscribers": int(subscribers) if subscribers is not None else None,
            "forged": rule == "forged-crawler" or category == "forged",
        })

        event: Event = _build(Event, {
            "record": record,
            "agent": agent,
            "verdict": verdict,
            "local_ts": local_ts,
            "date": str(_row_get(row, "local_date", local_ts.date().isoformat())),
            "hour": int(_row_get(row, "local_hour", local_ts.hour) or 0),
            "weekday": int(_row_get(row, "weekday", local_ts.weekday()) or 0),
            "locale": _row_get(row, "locale"),
            "locale_assigned": False,
            "page_kind": str(_row_get(row, "page_kind", "other") or "other"),
            "article_id": _row_get(row, "article_id"),
            "nav": nav,
            "is_pageview": bool(_row_get(row, "is_pageview", 0)),
            "referer_host": _row_get(row, "referer_host"),
            "channel": str(_row_get(row, "channel", "direct") or "direct"),
            "campaign": _row_get(row, "campaign"),
            "language": _row_get(row, "language"),
            "language_region": _row_get(row, "lang_region"),
            "country": _row_get(row, "country"),
            "visitor": visitor,
            "fmt": log_format,
            # The store never kept the raw user-agent, only its salted hash —
            # and that hash is stable for the life of the database, which is
            # exactly what lets the behavioural pass group one client across
            # days. Dropping it here collapsed every stored row into a single
            # identity and the pass could see nothing at all.
            "ua_key": _row_get(row, "ua_hash"),
        })
        return event
    except Exception as exc:  # pragma: no cover - schema drift is the whole point
        logger.debug("could not rehydrate a stored row: %s", exc)
        return None


def _ledger_from_events(events: Sequence[Event]) -> Ledger:
    """Reconstruct the composition audit from stored events.

    The store keeps parsed events, so the two rows that describe lines which
    never became events — blank and unparseable — stay at zero and the report
    carries a warning saying so. Everything else is recoverable from the
    verdict, the page kind and the navigation type, which is what makes the
    subtraction visible even on a store-backed report.
    """
    ledger = Ledger()
    for event in events:
        ledger.total_lines += 1
        verdict = event.verdict
        category = verdict.category
        if verdict.rule == "malformed" or category == "malformed":
            ledger.malformed += 1
        elif category == "other-vhost":
            ledger.other_vhost += 1
        elif category == "direct-origin":
            ledger.direct_origin += 1
        elif category == "forged" or verdict.forged:
            ledger.forged_crawlers += 1
        elif category == "health":
            ledger.health_probes += 1
        elif category == "scanner":
            ledger.scanners += 1
        elif verdict.rule == BEHAVIOURAL_RULE:
            # Before the `klass == "bot"` fallback below, or every demoted
            # request would silently land in "declared bots" and the one row
            # the reader most needs to see would never appear.
            ledger.suspected_automation += 1
        elif verdict.klass == "agent":
            subclass = verdict.subclass
            if subclass == "self":
                ledger.agents_self += 1
            elif subclass == "feed":
                ledger.agents_feed += 1
            else:
                ledger.agents_reach += 1
        elif verdict.klass == "bot":
            ledger.bots += 1
        elif event.is_pageview:
            ledger.human_pageviews += 1
            if event.nav == "soft":
                ledger.soft += 1
            else:
                ledger.hard += 1
        elif event.nav == "prefetch":
            ledger.prefetch += 1
        elif event.page_kind in ("asset", "metadata"):
            ledger.assets += 1
        elif event.page_kind == "api":
            ledger.api += 1
        elif event.page_kind == "feed":
            ledger.feeds += 1
        elif event.page_kind == "redirect":
            ledger.redirects += 1
        elif (event.record.status or 0) >= 400:
            ledger.non_2xx += 1
        else:
            ledger.other_paths += 1
    return ledger


# --------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------


def _jsonable(obj: Any) -> Any:
    """Convert the Report tree to JSON-safe values, keeping the field names.

    Stable keys are the dataclass field names, datetimes and dates become ISO
    strings, and a frozenset becomes a sorted list so two runs over the same
    data produce byte-identical output — which is what makes `--json` usable in
    a diff.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _jsonable(getattr(obj, f.name, None))
                for f in dataclasses.fields(obj)}
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, (frozenset, set)):
        values = [_jsonable(v) for v in obj]
        try:
            return sorted(values)
        except TypeError:  # pragma: no cover - heterogeneous set
            return values
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    return str(obj)


# --------------------------------------------------------------------------
# status
# --------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    """Say what the store holds. Returns 0 even when it holds nothing."""
    quiet = args.quiet
    if not Path(args.db).exists():
        _say(f"store: {args.db}  (does not exist yet)", quiet=quiet)
        _say("coverage: empty — run `python -m server.analytics ingest`",
             quiet=quiet)
        return EXIT_OK
    try:
        store = AnalyticsStore(args.db, read_only=True)
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            _fail("database is locked — another ingest may be running.")
            return EXIT_ERROR
        _fail(f"cannot open the store at {args.db}: {exc}")
        return EXIT_ERROR

    with store:
        status = store.status()
        size_mb = status.size_bytes / (1024 * 1024)
        _say(f"store: {status.path}  ({size_mb:.1f} MB, "
             f"schema v{status.schema_version})", quiet=quiet)
        if status.first_date and status.last_date:
            _say(f"coverage: {status.first_date} .. {status.last_date}  "
                 f"({status.days_present} days, "
                 f"{len(status.days_missing)} missing)", quiet=quiet)
        else:
            _say("coverage: empty — run `python -m server.analytics ingest`",
                 quiet=quiet)
        _say(f"events: {format_int(status.total_events)}   pageviews: "
             f"{format_int(status.total_pageviews)}   last ingest: "
             f"{status.last_ingest_at or 'never'}", quiet=quiet)
        # Said out loud, because the two numbers legitimately differ and a
        # reader who spots that without an explanation assumes one of them is
        # broken. The store is the record of what each REQUEST looked like;
        # `report` additionally applies a whole-window behavioural pass that no
        # single row could support, and shows the subtraction in its funnel.
        _say("  (per-request count — `report` subtracts suspected automation "
             "on top of this; see --automation-threshold)", quiet=quiet)
        _say(f"source files ingested: {format_int(status.source_files)}",
             quiet=quiet)

        if status.capabilities and not quiet:
            print()
            print("  date         format    events   country  visitor  lang  "
                  "hints  rsc  timing")
            for cap in status.capabilities:
                print("  {date:<12} {fmt:<8} {events:>8}   {country:<8} "
                      "{visitor:<8} {lang:<5} {hints:<6} {rsc:<4} {timing}".format(
                          date=cap.local_date,
                          fmt=cap.log_format,
                          events=format_int(cap.events),
                          country=_flag(cap.has_country),
                          visitor=_flag(cap.has_client_ip),
                          lang=_flag(cap.has_accept_language),
                          hints=_flag(cap.has_client_hints),
                          rsc=_flag(cap.has_rsc_headers),
                          timing=_flag(cap.has_timing)))
            print()

        absent = _absent_dimensions(status.capabilities)
        if absent:
            _say("dimensions absent for the whole range: " + ", ".join(absent)
                 + "  -- these arrive with the nginx change.", quiet=quiet)
        if status.days_missing:
            shown = ", ".join(status.days_missing[:8])
            more = (f" (+{len(status.days_missing) - 8} more)"
                    if len(status.days_missing) > 8 else "")
            _say(f"days with no data: {shown}{more}", quiet=quiet)
    return EXIT_OK


def _flag(value: bool) -> str:
    """'yes' / '-' — an absent dimension is a dash, never a zero."""
    return "yes" if value else "-"


def _absent_dimensions(capabilities: Sequence[DayCapabilities]) -> list[str]:
    """Dimensions no day in the store carries. The reason reports are labelled."""
    if not capabilities:
        return []
    checks: tuple[tuple[str, Callable[[DayCapabilities], bool]], ...] = (
        ("country", lambda c: c.has_country),
        ("visitor", lambda c: c.has_client_ip),
        ("language", lambda c: c.has_accept_language),
        ("client_hints", lambda c: c.has_client_hints),
        ("rsc", lambda c: c.has_rsc_headers),
        ("timing", lambda c: c.has_timing),
        ("host", lambda c: c.has_host),
    )
    return [name for name, probe in checks
            if not any(probe(cap) for cap in capabilities)]


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, dispatch, and translate failures into exit codes.

    Exit 0 covers "nothing matched": the end state is what the caller asked for.
    Exit 2 is bad input or nothing to do; exit 1 is a real failure — an
    unreadable log, a locked database, an unwritable HTML path.
    """
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(_insert_default_subcommand(raw))

    level = logging.WARNING
    if args.quiet:
        level = logging.ERROR
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s",
                        stream=sys.stderr)

    if not hasattr(args, "func"):  # pragma: no cover - argparse covers this
        parser.print_help()
        return EXIT_USAGE

    try:
        return int(args.func(args))
    except SystemExit as exc:
        return int(exc.code or 0)
    except PermissionError as exc:
        print(_permission_message(exc.filename or "the nginx log files"),
              file=sys.stderr)
        return EXIT_ERROR
    except sqlite3.OperationalError as exc:
        if "locked" in str(exc).lower():
            _fail("database is locked — another ingest may be running.")
        else:
            _fail(f"database error: {exc}")
        return EXIT_ERROR
    except sqlite3.DatabaseError as exc:
        _fail(f"the analytics database looks corrupt: {exc}")
        return EXIT_ERROR
    except BrokenPipeError:  # pragma: no cover - `| head`
        try:
            sys.stdout.close()
        except Exception:
            pass
        return EXIT_OK
    except KeyboardInterrupt:  # pragma: no cover - interactive
        _fail("interrupted.")
        return 130
    except OSError as exc:
        _fail(f"{exc}")
        return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
