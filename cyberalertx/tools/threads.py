"""Threads account operations (connecting itself happens in /admin/threads).

    python -m cyberalertx.tools.threads gen-key           print a new Fernet key for CYBERALERTX_THREADS_TOKEN_KEY
    python -m cyberalertx.tools.threads status            slots, profiles, token expiry (never tokens)
    python -m cyberalertx.tools.threads verify SLOT       one authenticated /me call
    python -m cyberalertx.tools.threads refresh           refresh tokens that are due (24 h old, < 30 days left)
    python -m cyberalertx.tools.threads disconnect SLOT   forget the slot's token (history is kept)
    python -m cyberalertx.tools.threads reconcile         settle outcome_unknown Threads jobs from the API

None of these publishes anything.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stores() -> tuple[Any, Any]:
    from ..threads.accounts import ACCOUNTS_PATH, AccountStore
    from ..threads.config import ThreadsSettings
    ts = ThreadsSettings.from_env()
    return ts, AccountStore(ACCOUNTS_PATH, key=ts.token_key, mapping=ts.accounts)


def cmd_gen_key(_: argparse.Namespace) -> int:
    from cryptography.fernet import Fernet  # type: ignore[import-not-found,unused-ignore]
    print(Fernet.generate_key().decode())
    print("Put it in the server's .env as CYBERALERTX_THREADS_TOKEN_KEY. Losing it means reconnecting "
          "both accounts; changing it makes stored tokens unreadable.", file=sys.stderr)
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    ts, accounts = _stores()
    print(json.dumps({"publish_enabled": ts.publish_enabled, "oauth_configured": ts.oauth_configured,
                      "accounts": [a.to_public(_now()) for a in accounts.all()]}, ensure_ascii=False, indent=2))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from ..threads.client import ThreadsClient
    from ..threads.oauth import verify
    _, accounts = _stores()
    api = ThreadsClient()
    try:
        acc = verify(args.slot, accounts, api, _now())
    finally:
        api.close()
    print(json.dumps(acc.to_public(_now()), ensure_ascii=False, indent=2))
    return 1 if acc.last_error else 0


def cmd_refresh(_: argparse.Namespace) -> int:
    from ..threads.client import ThreadsClient
    from ..threads.oauth import refresh_due
    _, accounts = _stores()
    api = ThreadsClient()
    try:
        results = refresh_due(accounts, api, _now())
    finally:
        api.close()
    for r in results:
        print(f"{r.slot}: {r.outcome} {r.detail}".rstrip())
    return 1 if any(r.outcome in ("failed", "expired") for r in results) else 0


def cmd_disconnect(args: argparse.Namespace) -> int:
    _, accounts = _stores()
    accounts.disconnect(args.slot, _now())
    print(f"{args.slot}: disconnected (publication history kept)")
    return 0


def cmd_reconcile(_: argparse.Namespace) -> int:
    from ..publish.jobs import JobStore
    from ..threads.destination import auto_reconcile
    from .publish import _threads_destinations
    from ..publish.config import build_telegram_settings

    dests = _threads_destinations(build_telegram_settings().public_base_url)
    if not dests:
        print("Threads publishing is off (CYBERALERTX_THREADS_PUBLISH); nothing to reconcile.", file=sys.stderr)
        return 0
    for r in auto_reconcile(JobStore(), dests, _now()):
        print(f"{r['job_id']}: {r['result']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cyberalertx.tools.threads", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("gen-key").set_defaults(fn=cmd_gen_key)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    v = sub.add_parser("verify")
    v.add_argument("slot")
    v.set_defaults(fn=cmd_verify)
    sub.add_parser("refresh").set_defaults(fn=cmd_refresh)
    d = sub.add_parser("disconnect")
    d.add_argument("slot")
    d.set_defaults(fn=cmd_disconnect)
    sub.add_parser("reconcile").set_defaults(fn=cmd_reconcile)
    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
