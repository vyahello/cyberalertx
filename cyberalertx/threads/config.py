"""Threads settings, read from the environment like every other CyberAlertX setting.

    CYBERALERTX_THREADS_APP_ID        Threads App ID (App Dashboard → Use cases → Threads API)
    CYBERALERTX_THREADS_APP_SECRET    Threads App Secret (server-side only)
    CYBERALERTX_THREADS_REDIRECT_URI  exact OAuth redirect URI registered in the app,
                                      e.g. https://cyberalertx.com/admin/threads/callback
    CYBERALERTX_THREADS_TOKEN_KEY     Fernet key encrypting stored tokens
                                      (`python -m cyberalertx.tools.threads gen-key`)
    CYBERALERTX_THREADS_ACCOUNTS      slot:locale pairs, default "en:en,ua:ua"
    CYBERALERTX_THREADS_PUBLISH       1 to let the Publication Engine use Threads (default off)
    CYBERALERTX_THREADS_MIN_LEVEL     Low|Medium|High|Critical (default High), like Telegram
    CYBERALERTX_THREADS_LIMIT         posts per account per run (default 1)

Nothing here is required for the rest of the platform: with no settings the
integration is simply disconnected and disabled.
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

    @property
    def oauth_configured(self) -> bool:
        return bool(self.app_id and self.app_secret and self.redirect_uri.startswith("https://")
                    and self.token_key)

    def slot_for(self, locale: str) -> str | None:
        return next((s for s, loc in self.accounts.items() if loc == locale), None)

    @classmethod
    def from_env(cls) -> "ThreadsSettings":
        level = (os.getenv("CYBERALERTX_THREADS_MIN_LEVEL") or "High").strip().title()
        return cls(
            app_id=(os.getenv("CYBERALERTX_THREADS_APP_ID") or "").strip(),
            app_secret=(os.getenv("CYBERALERTX_THREADS_APP_SECRET") or "").strip(),
            redirect_uri=(os.getenv("CYBERALERTX_THREADS_REDIRECT_URI") or "").strip(),
            token_key=(os.getenv("CYBERALERTX_THREADS_TOKEN_KEY") or "").strip(),
            accounts=parse_accounts(os.getenv("CYBERALERTX_THREADS_ACCOUNTS") or "en:en,ua:ua"),
            publish_enabled=(os.getenv("CYBERALERTX_THREADS_PUBLISH") or "").strip().lower()
            in ("1", "true", "yes", "on"),
            min_level=level if level in ("Low", "Medium", "High", "Critical") else "High",
        )


__all__ = ["AUTHORIZE_URL", "GRAPH_ROOT", "GRAPH_VERSION", "LOCALES", "SCOPES", "ThreadsSettings",
           "normalize_locale", "parse_accounts"]
