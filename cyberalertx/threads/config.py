"""Threads settings, read from the environment like every other CyberAlertX setting.

One Meta app, two Threads accounts (one per language):

    THREADS_ENABLED            1 to let the Publication Engine post to Threads (default 0: off)
    THREADS_APP_ID             the one shared Threads App ID (not a secret, not a user id)
    THREADS_APP_SECRET         optional; only for exchanging a short-lived token
    THREADS_EN_USERNAME        expected username of the English account (cyberalertx)
    THREADS_EN_ACCESS_TOKEN    its Threads user access token
    THREADS_UA_USERNAME        expected username of the Ukrainian account (cyberalertx_ua)
    THREADS_UA_ACCESS_TOKEN    its Threads user access token
    THREADS_DAILY_LIMIT        posts per account per 24 h (default 3, pilot)
    CYBERALERTX_THREADS_MIN_LEVEL / _LIMIT   severity bar / posts per account per run

Threads user ids are never configured: each is read from `/me` with that
account's own token and kept in the account registry (data/threads_accounts.json,
no secrets). The older CYBERALERTX_THREADS_* names (web OAuth flow with
encrypted tokens) still work as fallbacks.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

#: Official endpoints (checked against developers.facebook.com/docs/threads, Nov 2026).
AUTHORIZE_URL = "https://threads.com/oauth/authorize"
GRAPH_ROOT = "https://graph.threads.com"
GRAPH_VERSION = "v1.0"
SCOPES = ("threads_basic", "threads_content_publish")

LOCALES = ("en", "ua")
_LOCALE_ALIASES = {"uk": "ua", "ua": "ua", "en": "en"}


def normalize_locale(value: str) -> str:
    loc = _LOCALE_ALIASES.get(value.strip().lower())
    if loc is None:
        raise ValueError(f"unsupported Threads locale {value!r} (en, ua/uk)")
    return loc


def parse_accounts(raw: str) -> dict[str, str]:
    """"en:en,ua:uk" → {"en": "en", "ua": "ua"} (slot → locale).

    A slot names one Threads profile; each slot serves exactly one locale and
    a locale is served by at most one slot, so content can never be routed to
    the wrong profile by configuration."""
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        if not part.strip():
            continue
        slot, sep, loc = part.partition(":")
        slot = slot.strip().lower()
        if not sep or not slot or not slot.replace("-", "").replace("_", "").isalnum() or len(slot) > 32:
            raise ValueError(f"bad CYBERALERTX_THREADS_ACCOUNTS entry {part!r} (want slot:locale)")
        locale = normalize_locale(loc)
        if slot in out:
            raise ValueError(f"Threads slot {slot!r} listed twice")
        if locale in out.values():
            raise ValueError(f"locale {locale!r} is mapped to two Threads slots")
        out[slot] = locale
    return out


def _env(*names: str) -> str:
    for n in names:
        v = (os.getenv(n) or "").strip()
        if v:
            return v
    return ""


def _flag(*names: str) -> bool:
    return _env(*names).lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class ThreadsSettings:
    app_id: str = ""
    app_secret: str = field(default="", repr=False)
    redirect_uri: str = ""
    token_key: str = field(default="", repr=False)
    accounts: dict[str, str] = field(default_factory=lambda: {"en": "en", "ua": "ua"})
    publish_enabled: bool = False
    min_level: str = "High"
    graph_root: str = GRAPH_ROOT
    authorize_url: str = AUTHORIZE_URL
    #: slot -> expected username (THREADS_EN_USERNAME / THREADS_UA_USERNAME)
    usernames: dict[str, str] = field(default_factory=dict)
    #: slot -> access token from the environment; never logged or stored elsewhere
    env_tokens: dict[str, str] = field(default_factory=dict, repr=False)
    daily_limit: int = 3

    @property
    def env_mode(self) -> bool:
        """Tokens come from THREADS_*_ACCESS_TOKEN (not the encrypted web-OAuth store)."""
        return any(self.env_tokens.values())

    @property
    def oauth_configured(self) -> bool:
        return bool(self.app_id and self.app_secret and self.redirect_uri.startswith("https://")
                    and self.token_key)

    def slot_for(self, locale: str) -> str | None:
        return next((s for s, loc in self.accounts.items() if loc == locale), None)

    @classmethod
    def from_env(cls) -> "ThreadsSettings":
        level = (os.getenv("CYBERALERTX_THREADS_MIN_LEVEL") or "High").strip().title()
        try:
            daily = max(0, int(_env("THREADS_DAILY_LIMIT") or "3"))
        except ValueError:
            daily = 3
        return cls(
            app_id=_env("THREADS_APP_ID", "CYBERALERTX_THREADS_APP_ID"),
            app_secret=_env("THREADS_APP_SECRET", "CYBERALERTX_THREADS_APP_SECRET"),
            redirect_uri=_env("CYBERALERTX_THREADS_REDIRECT_URI"),
            token_key=_env("CYBERALERTX_THREADS_TOKEN_KEY"),
            accounts=parse_accounts(os.getenv("CYBERALERTX_THREADS_ACCOUNTS") or "en:en,ua:ua"),
            publish_enabled=_flag("THREADS_ENABLED") if os.getenv("THREADS_ENABLED") is not None
            else _flag("CYBERALERTX_THREADS_PUBLISH"),
            min_level=level if level in ("Low", "Medium", "High", "Critical") else "High",
            usernames={k: v for k, v in (("en", _env("THREADS_EN_USERNAME")),
                                         ("ua", _env("THREADS_UA_USERNAME"))) if v},
            env_tokens={k: v for k, v in (("en", _env("THREADS_EN_ACCESS_TOKEN")),
                                          ("ua", _env("THREADS_UA_ACCESS_TOKEN"))) if v},
            daily_limit=daily,
        )

__all__ = ["AUTHORIZE_URL", "GRAPH_ROOT", "GRAPH_VERSION", "LOCALES", "SCOPES", "ThreadsSettings",
           "normalize_locale", "parse_accounts"]
