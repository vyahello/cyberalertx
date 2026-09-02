"""Local visitor analytics for cyberalertx — shared constants, nothing else.

This package answers "who actually reads the site?" from the nginx access
logs that are already on disk, and from nothing else. No JavaScript beacon
ships to readers, no third party is told what they read, no request leaves
the box. The logs were always there; the only missing piece was something
willing to read them without inventing the numbers it cannot measure.

This module is deliberately thin and deliberately dependency-free. It holds
the paths and identity constants that four separate modules would otherwise
each invent a slightly different version of — one agent writing
`data/analytics.db`, another `data/analytics.sqlite3`, and a fortnight of
history landing in a file nobody reads again. It imports nothing from its
siblings, so `import server.analytics` never drags the parser, the store or
the renderer into a process that only wanted a path.

SALT ROTATION AT 04:00, NOT MIDNIGHT: the daily salt forces a session split
at rotation time, so the cut belongs in the traffic trough where near-zero
sessions get severed. Splitting at midnight instead is a daily-batch
artefact that manufactures a 00:00 session spike and a crop of fake bounces,
and then someone spends an afternoon explaining the spike.

SCOPE: reads only cyberalertx's own dedicated log plus the shared legacy
archive, filtered to the cyberalertx vhost. The three other vhosts on this
box keep writing to /var/log/nginx/access.log untouched, and nothing here
writes to any log file, ever.

PRIVACY: nothing leaves the box. No network calls at runtime, no third-party
analytics, no dependency outside the stdlib. Raw IPs are never persisted or
printed — only salted hashes, with the salt rotated daily and retained 14
days, so the salt cannot outlive the logs it could re-key.
"""
from __future__ import annotations

import os
import pathlib

import re
from pathlib import Path

__version__: str = "1.0.0"

# --- paths ----------------------------------------------------------------
# parents[2] because this file is <repo>/server/analytics/__init__.py.
REPO_ROOT: Path = Path(__file__).resolve().parents[2]
DATA_DIR: Path = REPO_ROOT / "data"
ANALYTICS_DIR: Path = DATA_DIR / "analytics"

# Everything the tool writes lives under the already-gitignored data/, which
# backup.sh tars daily and keeps 14 archives of.
DEFAULT_DB_PATH: Path = DATA_DIR / "analytics.sqlite3"
DEFAULT_SALT_PATH: Path = ANALYTICS_DIR / "salts.json"
DEFAULT_HTML_PATH: Path = ANALYTICS_DIR / "report.html"

# Read sources. The archive directory holds date-named .gz copies produced by
# the archive-daily.sh stopgap; /var/log/nginx holds the live log and the
# 14 rotations logrotate keeps. Both must work standalone.
DEFAULT_ARCHIVE_DIR: Path = DATA_DIR / "nginx-archive"
DEFAULT_LOG_DIR: Path = Path("/var/log/nginx")

# .jsonl, NOT .log: /etc/logrotate.d/nginx globs /var/log/nginx/*.log and is
# shared with three other vhosts. Two logrotate configs naming one file is a
# "duplicate log entry" error, logrotate skips the entry, and our 365-day
# retention silently never applies. A glob does not cross an extension.
DEFAULT_LOG_NAME: str = "cyberalertx-access.jsonl"
LEGACY_LOG_NAME: str = "access.log"

# --- identity -------------------------------------------------------------
SITE_HOSTS: frozenset[str] = frozenset({"cyberalertx.com", "www.cyberalertx.com"})

# Sibling vhosts sharing this nginx instance. They appear in the legacy shared
# access.log and in Referer headers, and every audience number must exclude
# them.
#
# Deliberately NOT hardcoded. This repository is public, and a literal list
# here would publish which unrelated sites are co-hosted on the same box --
# infrastructure topology that is nobody else's business. Set it in .env
# (gitignored) instead:
#
#     CYBERALERTX_OTHER_VHOSTS=one.example.org,two.example.org
#
# Empty is a safe default: with no siblings configured, host-based exclusion
# simply never fires. That is only a real loss on LEGACY lines, which carry no
# host field and must be attributed by Referer and path. Extended-format lines
# always carry $host, so they are attributed exactly regardless of this list.
# Read from the environment first, then from data/other-vhosts.txt (one host per
# line, "#" comments allowed). The file matters because the systemd unit
# deliberately carries no EnvironmentFile -- handing log analytics the app's
# secrets would be a poor trade for one hostname list -- so an env-only lookup
# would be silently empty under the timer while working by hand. data/ is
# gitignored, so neither route puts the list in the repository.
_VHOSTS_FILE = pathlib.Path(__file__).resolve().parents[2] / "data" / "other-vhosts.txt"


def _configured_hosts() -> frozenset[str]:
    raw = os.environ.get("CYBERALERTX_OTHER_VHOSTS", "")
    hosts = {h.strip().lower() for h in raw.split(",") if h.strip()}
    if not hosts:
        try:
            for line in _VHOSTS_FILE.read_text(encoding="utf-8").splitlines():
                line = line.split("#", 1)[0].strip().lower()
                if line:
                    hosts.add(line)
        except OSError:
            pass          # absent or unreadable is the normal public-checkout case
    return frozenset(hosts)


OTHER_VHOSTS: frozenset[str] = _configured_hosts()

# First DNS label of each sibling ("shop.example.org" -> "shop"), used to spot a
# sibling's own routes inside a legacy line that has neither host nor Referer.
# Derived, so configuring a hostname is all anyone ever has to do.
OTHER_VHOST_TOKENS: frozenset[str] = frozenset(
    host.split(".", 1)[0] for host in OTHER_VHOSTS if "." in host
)

# The reporting timezone default. Every time-shaped conclusion ("the audience
# reads at 09:00") is only actionable in the audience's own wall clock, and
# the audience is in Kyiv. The instant always comes from the offset the log
# line itself carries; this is only how that instant is displayed.
DEFAULT_TZ: str = "Europe/Kyiv"

LOCALES: tuple[str, ...] = ("en", "ua")
# /uk is the pre-rename locale. next.config.ts 308-redirects it to /ua, so real
# humans on old links still generate /uk hits and it must never be read as a
# scanner probe.
LEGACY_LOCALES: tuple[str, ...] = ("uk",)

# Article URLs are /<locale>/threat/<fingerprint>, and the fingerprint is a
# 16-character hex digest. Anything else under /threat/ is a probe.
FINGERPRINT_RE: re.Pattern[str] = re.compile(r"^[0-9a-f]{16}$")

# --- sessionisation and salt policy ---------------------------------------
SESSION_GAP_MINUTES: int = 30
SALT_ROTATION_HOUR: int = 4
SALT_RETENTION_DAYS: int = 14
