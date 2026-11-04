"""`/admin/threads` — Threads account slots: status, health, connect/disconnect/verify.

Shows each slot (EN, UA, …) with its profile, connection health, token
expiry (never the token), last refresh and verification, last error and any
rate-limit pause. Actions are POST forms with the admin CSRF token (see
guard.py); "Connect" answers with a page holding a plain link to Threads, so
the browser leaves our origin by navigation, not by a cross-site form
redirect (which the admin CSP's `form-action 'self'` would block).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from .ui import esc, page, panel, pill, tile

_TONE = {"connected": "ok", "needs_reconnect": "bad", "disconnected": "neutral"}
_LABEL = {"en": "English", "ua": "Ukrainian"}


def _form(action: str, slot: str, csrf: str, label: str, *, tone: str = "") -> str:
    """One action button, styled like the review queue's (`button.btn`)."""
    return (f'<form method="post" action="{esc(action)}" style="display:inline-block;margin:0 8px 8px 0">'
            f'<input type="hidden" name="csrf" value="{esc(csrf)}">'
            f'<input type="hidden" name="slot" value="{esc(slot)}">'
            f'<button type="submit" class="btn {esc(tone)}">{esc(label)}</button></form>')


def _telegram_panel(tg: Mapping[str, Any]) -> str:
    rows = [("Bot token", pill("set", "ok") if tg.get("token_set") else pill("missing", "neutral")),
            ("Channels", " ".join(pill(f"{loc.upper()} {lbl}", "ok" if lbl != "not configured" else "neutral")
                                  for loc, lbl in tg.get("channels", {}).items()) or "—"),
            ("Images", "card attached as photo" if tg.get("attach_images") else "off (text + link preview)"),
            ("Severity bar", esc(tg.get("min_level", ""))), ("Per run", esc(tg.get("limit", "")))]
    body = "<table><tbody>" + "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows) + "</tbody></table>"
    return panel("Telegram", body, cls="full",
                 aside="configured in .env; the bot token is never displayed")


def render_threads(accounts: Sequence[Mapping[str, Any]], status: Mapping[str, Any], *, csrf: str,
                   now: datetime, notice: str = "", error: str = "", telegram: Mapping[str, Any] | None = None) -> str:
    tiles = "".join(
        tile(f"Threads {a['slot'].upper()} · {_LABEL.get(a['locale'], a['locale'])}",
             esc(a["status"].replace("_", " ")),
             (f"@{esc(a['username'])}" if a.get("username") else "no profile")
             + (f" · token {esc(a['expires_in_days'])} days left" if a.get("expires_in_days") is not None else ""),
             tone=_TONE.get(a["status"], "neutral"))
        for a in accounts)

    def card(a: Mapping[str, Any]) -> str:
        connected = a["status"] == "connected"
        actions = [_form("/admin/threads/connect", a["slot"], csrf,
                         "Reconnect" if a.get("threads_user_id") else "Connect", tone="" if connected else "ok")]
        if a.get("has_token"):
            actions.append(_form("/admin/threads/verify", a["slot"], csrf, "Verify connection"))
            actions.append(_form("/admin/threads/disconnect", a["slot"], csrf, "Disconnect", tone="bad"))
        rows = [
            ("Status", pill(a["status"].replace("_", " "), _TONE.get(a["status"], "neutral"))),
            ("Publishing", pill("enabled", "warn") if status.get("publish_enabled") and connected else
             pill("off", "neutral") + (" <small>connected, but CYBERALERTX_THREADS_PUBLISH is off</small>"
                                       if connected and not status.get("publish_enabled") else "")),
            ("Locale", esc(_LABEL.get(a["locale"], a["locale"])) + f" (<code>{esc(a['locale'])}</code>)"),
            ("Profile", (f"{esc(a.get('name') or '')} @{esc(a['username'])} · id "
                         f"<code style=\"overflow-wrap:anywhere\">{esc(a['threads_user_id'])}</code>"
                         if a.get("username") else "—")),
            ("Token expires", (f"{esc(a.get('expires_at'))} ({esc(a.get('expires_in_days'))} days)"
                               if a.get("expires_at") else "—")),
            ("Last refresh", esc(a.get("last_refresh_at") or "—")),
            ("Last verified", esc(a.get("last_verified_at") or "—")),
            ("Rate-limited until", esc(a.get("rate_limited_until") or "—")),
            ("Last error", esc(a.get("last_error") or "—")),
        ]
        body = "<table><tbody>" + "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in rows) + "</tbody></table>"
        hint = "" if connected else ('<p class="empty">Not publishing. Connecting needs a Threads tester role '
                                     'while the Meta app is in development mode.</p>')
        return panel(f"Slot {a['slot']}", body + hint + f'<div style="margin-top:14px">{"".join(actions)}</div>',
                     cls="full")

    checks = [
        ("App ID", status.get("app_id_set")), ("App secret", status.get("app_secret_set")),
        ("HTTPS redirect URI", status.get("redirect_ok")), ("Token encryption key", status.get("key_set")),
        ("cryptography package", status.get("crypto_available")),
    ]
    cfg = "".join(f"<tr><th>{esc(k)}</th><td>{pill('set', 'ok') if v else pill('missing', 'bad')}</td></tr>"
                  for k, v in checks)
    cfg += (f"<tr><th>Redirect URI</th><td><code style=\"overflow-wrap:anywhere\">"
            f"{esc(status.get('redirect_uri') or '—')}</code></td></tr>"
            f"<tr><th>Publishing</th><td>{pill('enabled', 'warn') if status.get('publish_enabled') else pill('off', 'neutral')}"
            " <small style=\"overflow-wrap:anywhere\">CYBERALERTX_THREADS_PUBLISH</small></td></tr>")
    banner = ""
    if notice:
        banner += panel("Done", f"<p>{esc(notice)}</p>", cls="full")
    if error:
        banner += panel("Not done", f'<p style="color:var(--bad)">{esc(error)}</p>', cls="full")
    body = (banner + f'<div class="grid">{tiles}</div>' + "".join(card(a) for a in accounts)
            + (_telegram_panel(telegram) if telegram is not None else "")
            + panel("Configuration", f"<table><tbody>{cfg}</tbody></table>", cls="full",
                    aside="values are never shown — see docs/threads/THREADS_SETUP.md"))
    return page(active="threads", title="Social accounts", body=body, now=now, json_href="/admin/threads.json",
                subtitle="Each slot is one Threads profile for one language. Disconnecting a slot stops it "
                         "publishing; its history stays in Publishing.")


def render_connect(slot: str, url: str, *, now: datetime) -> str:
    body = panel(f"Connect slot {slot}",
                 f"<p>Sign in to the Threads profile that should publish the <b>{esc(slot.upper())}</b> edition, "
                 "then approve the permissions. This link works once and expires in 10 minutes.</p>"
                 f'<p><a href="{esc(url)}" rel="noopener noreferrer">Continue to Threads →</a></p>')
    return page(active="threads", title="Connect Threads", subtitle="", body=body, now=now)


__all__ = ["render_connect", "render_threads"]
