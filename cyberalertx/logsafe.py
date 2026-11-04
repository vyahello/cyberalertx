"""Keep credentials out of log records written by third-party HTTP logging.

httpx logs every request at INFO as `HTTP Request: GET <full URL> …`. Two of
our integrations put a credential in the URL because their APIs require it:
the Telegram Bot API (`/bot<token>/method`) and Threads GET calls
(`?access_token=…`, as documented by Meta). This filter rewrites those parts
of any record on the `httpx`/`httpcore` loggers before a handler sees it.
Installing it is idempotent.
"""
from __future__ import annotations

import logging
import re

_PATTERNS = (
    (re.compile(r"/bot\d+:[A-Za-z0-9_-]+"), "/bot[redacted]"),
    (re.compile(r"(access_token|client_secret|code)=[^&\s\"']+", re.I), r"\1=[redacted]"),
)


def redact(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class RedactSecrets(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:                          # noqa: BLE001 - never break logging
            return True
        clean = redact(message)
        if clean != message:
            record.msg, record.args = clean, None
        return True


def install() -> None:
    for name in ("httpx", "httpcore"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactSecrets) for f in logger.filters):
            logger.addFilter(RedactSecrets())


__all__ = ["RedactSecrets", "install", "redact"]
