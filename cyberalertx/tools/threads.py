"""Threads accounts: one Meta app, two accounts (EN @cyberalertx, UA @cyberalertx_ua).

    python -m cyberalertx.tools.threads setup               interactive: tokens (hidden input), validate, write .env
    python -m cyberalertx.tools.threads status [--live]     app id, accounts, tokens, queues (never a secret)
    python -m cyberalertx.tools.threads refresh             refresh tokens that are due (24 h old, < 30 days left)
    python -m cyberalertx.tools.threads maintain            verify + refresh, Threads on or off (systemd timer)
    python -m cyberalertx.tools.threads reconcile           settle outcome_unknown Threads jobs from the API
    python -m cyberalertx.tools.threads test-post SLOT --confirm
                                                            ONE clearly marked test post on that account

Only `test-post --confirm` publishes, and only when explicitly run. Tokens are
never accepted as command-line arguments and never printed.
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _env_file() -> Path:
    from ..config import DATA_DIR
    return Path(DATA_DIR).resolve().parent / ".env"


def _backups() -> Path:
    return Path.home() / "backups" / "threads"


def _stores() -> tuple[Any, Any]:
    from ..threads.accounts import ACCOUNTS_PATH, AccountStore
    from ..threads.config import ThreadsSettings
    ts = ThreadsSettings.from_env()
    return ts, AccountStore(ACCOUNTS_PATH, key=ts.token_key, mapping=ts.accounts, env_tokens=ts.env_tokens)


# ------------------------------------------------------------------ setup

def cmd_setup(args: argparse.Namespace, *, ask: Any = None, client: Any = None, store: Any = None) -> int:
    """Validate both tokens; only if BOTH map correctly, back up and update .env and the registry."""
    from ..threads.accounts import ACCOUNTS_PATH, AccountStore, SlotConflict
    from ..threads.client import ThreadsClient, ThreadsError
    from ..threads.credentials import DEFAULT_USERNAMES, ENV_TOKEN_VAR, check_pair, check_token, register
    from ..threads.envfile import EnvFileError, read_env, update_env

    ask = ask or getpass.getpass
    env_path = Path(args.env) if args.env else _env_file()
    if not env_path.is_file():
        print(f"no environment file at {env_path}", file=sys.stderr)
        return 2
    existing = read_env(env_path)
    app_id = existing.get("THREADS_APP_ID") or ask("Threads App ID (the one shared app): ").strip()
    if not app_id.isdigit():
        print("THREADS_APP_ID is missing or not numeric. Nothing was changed.", file=sys.stderr)
        return 2
    usernames = {"en": existing.get("THREADS_EN_USERNAME") or DEFAULT_USERNAMES["en"],
                 "ua": existing.get("THREADS_UA_USERNAME") or DEFAULT_USERNAMES["ua"]}
    tokens: dict[str, str] = {}
    for slot, label in (("en", "English"), ("ua", "Ukrainian")):
        entered = ask(f"{label} token for @{usernames[slot]} (hidden; Enter keeps the current one): ").strip()
        tokens[slot] = entered or existing.get(ENV_TOKEN_VAR[slot], "")
    api = client or ThreadsClient()
    secret_entered = ""
    try:
        checks = {}
        for slot in ("en", "ua"):
            c = check_token(slot, tokens[slot], usernames[slot], api)
            if c.short_lived() and not c.problems:
                secret = existing.get("THREADS_APP_SECRET") or secret_entered
                if not secret:
                    secret_entered = secret = ask("This token is short-lived. Threads App Secret, to exchange it "
                                                  "(hidden; one shared secret): ").strip()
                try:
                    tokens[slot], _ = api.long_lived(app_secret=secret, short_token=tokens[slot])
                except ThreadsError as exc:
                    c.problems.append(f"exchange for a long-lived token failed ({exc.category})")
                    c.ok = False
                else:
                    c = check_token(slot, tokens[slot], usernames[slot], api)
                    if c.short_lived():
                        c.problems.append("the exchanged token is still short-lived")
                        c.ok = False
            checks[slot] = c
    finally:
        if client is None:
            api.close()
    pair = check_pair(list(checks.values()))
    for slot, c in checks.items():
        state = "OK" if c.ok else "REFUSED"
        print(f"{slot.upper()} @{usernames[slot]}: {state}" + ("" if c.ok else " — " + "; ".join(c.problems)))
    for p in pair:
        print(f"REFUSED: {p}")
    if pair or not all(c.ok for c in checks.values()):
        print("Nothing was changed. Fix the token(s) above and run setup again.", file=sys.stderr)
        return 1

    updates = {"THREADS_APP_ID": app_id, "THREADS_EN_USERNAME": usernames["en"],
               "THREADS_UA_USERNAME": usernames["ua"],
               "THREADS_EN_ACCESS_TOKEN": tokens["en"], "THREADS_UA_ACCESS_TOKEN": tokens["ua"]}
    if secret_entered:
        updates["THREADS_APP_SECRET"] = secret_entered
    if "THREADS_ENABLED" not in existing:
        updates["THREADS_ENABLED"] = "0"               # never switched on by setup
    reg = store or AccountStore(ACCOUNTS_PATH, mapping={"en": "en", "ua": "ua"})
    for slot, c in checks.items():                     # identity check BEFORE touching .env
        acc = reg.get(slot)
        if acc.threads_user_id and acc.threads_user_id != c.user_id and not args.allow_identity_change:
            print(f"REFUSED: {slot.upper()} is registered to @{acc.username} ({acc.threads_user_id}); "
                  f"the token is for @{c.username} ({c.user_id}). Use --allow-identity-change only if "
                  "this is intended. Nothing was changed.", file=sys.stderr)
            return 1
    try:
        backup = update_env(env_path, updates, backup_dir=_backups(), label="env-before-threads-setup")
    except (EnvFileError, OSError) as exc:
        print(f"could not update {env_path}: {exc}. Nothing was changed.", file=sys.stderr)
        return 1
    now = _now()
    try:
        for slot, c in checks.items():
            register(reg, c, tokens[slot], now, allow_identity_change=args.allow_identity_change)
    except SlotConflict as exc:                         # pragma: no cover - checked above
        print(f"registry refused: {exc}", file=sys.stderr)
        return 1
    print(f"\n.env updated (previous version: {backup}, mode 600). THREADS_ENABLED is "
          f"{(read_env(env_path).get('THREADS_ENABLED') or '0')}; setup never enables publishing.")
    print(f"Shared Threads App ID: {app_id}")
    for slot, c in checks.items():
        exp = c.expires_at.date().isoformat() if c.expires_at else "not reported"
        print(f"  {slot.upper()}: @{c.username}  user id {c.user_id}  expires {exp}  "
              f"scopes {','.join(c.scopes)}  type {c.token_type or '?'}")
    return 0


# ------------------------------------------------------------------ status

def cmd_status(args: argparse.Namespace) -> int:
    from ..publish.jobs import JobStore
    from ..threads.client import ThreadsClient, scrub
    from ..threads.credentials import DEFAULT_USERNAMES, check_token

    ts, accounts = _stores()
    now = _now()
    jobs = JobStore().all()
    out: dict[str, Any] = {"threads_enabled": ts.publish_enabled, "app_id": ts.app_id or "(not set)",
                           "app_secret_configured": bool(ts.app_secret), "daily_limit": ts.daily_limit,
                           "token_source": "env" if ts.env_mode else "oauth store", "accounts": {}}
    api = ThreadsClient() if args.live else None
    try:
        for slot in ts.accounts:
            a = accounts.get(slot)
            q = Counter(j.status for j in jobs if j.destination == f"threads@{slot}")
            row: dict[str, Any] = {
                "expected_username": ts.usernames.get(slot) or DEFAULT_USERNAMES.get(slot, ""),
                "registered_username": a.username, "user_id": a.threads_user_id, "status": a.status,
                "token_present": accounts.has_token(slot), "token_type": a.token_type,
                "expires_at": a.expires_at, "scopes": a.scopes, "last_verified_at": a.last_verified_at,
                "last_published_at": a.last_published_at, "published_last_24h": accounts.published_last_24h(slot, now),
                "publishing_since": a.publishing_since, "last_error": scrub(a.last_error) if a.last_error else "",
                "queue": {"pending": q["scheduled"] + q["retrying"], "failed": q["failed"],
                          "outcome_unknown": q["outcome_unknown"], "published": q["published"]}}
            if a.expires_at:
                row["expires_in_days"] = a.to_public(now).get("expires_in_days")
            if api is not None and accounts.has_token(slot):
                c = check_token(slot, accounts.token(slot), row["expected_username"], api)
                row["live_check"] = {"ok": c.ok, "user_id": c.user_id, "username": c.username,
                                     "expires_at": c.expires_at.isoformat() if c.expires_at else "",
                                     "scopes": c.scopes, "problems": c.problems,
                                     "matches_registry": c.user_id == a.threads_user_id}
            out["accounts"][slot] = row
    finally:
        if api is not None:
            api.close()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_refresh(_: argparse.Namespace) -> int:
    from ..threads.client import ThreadsClient
    from ..threads.credentials import refresh_tokens
    from ..threads.oauth import refresh_due
    ts, accounts = _stores()
    api = ThreadsClient()
    try:
        if accounts.env_mode:
            results: list[Any] = refresh_tokens(ts, accounts, api, _now(), env_path=_env_file(), backup_dir=_backups())
        else:
            results = refresh_due(accounts, api, _now())
    finally:
        api.close()
    for r in results:
        print(f"{r.slot}: {r.outcome} {r.detail}".rstrip())
    return 1 if any(r.outcome in ("failed", "expired", "invalid") for r in results) else 0


def _lock_path() -> Path:
    from ..config import DATA_DIR
    return Path(DATA_DIR) / "threads_maintenance.lock"


def cmd_maintain(_: argparse.Namespace, *, client: Any = None) -> int:
    """Timer entry point: verify both accounts and refresh due tokens, whether or
    not Threads publishing is enabled. Never publishes; exit 1 needs an operator."""
    from ..threads.client import ThreadsClient
    from ..threads.credentials import maintain
    ts, accounts = _stores()
    if not accounts.env_mode:
        print("no THREADS_*_ACCESS_TOKEN in the environment; nothing to maintain")
        return 0
    api = client or ThreadsClient()
    try:
        results = maintain(ts, accounts, api, _now(), env_path=_env_file(), backup_dir=_backups(),
                           lock_path=_lock_path())
    finally:
        if client is None:
            api.close()
    if results is None:
        print("another token maintenance run is in progress; skipped")
        return 0
    for r in results:
        print(f"{r.slot}: {r.outcome} {r.detail}".rstrip())
    return 1 if any(r.outcome in ("invalid", "mismatch", "failed") for r in results) else 0


def cmd_reconcile(_: argparse.Namespace) -> int:
    from ..publish.config import build_telegram_settings
    from ..publish.jobs import JobStore
    from ..threads.destination import auto_reconcile
    from .publish import _threads_destinations

    dests = _threads_destinations(build_telegram_settings().public_base_url)
    if not dests:
        print("Threads publishing is off (THREADS_ENABLED=0); nothing to reconcile.", file=sys.stderr)
        return 0
    for r in auto_reconcile(JobStore(), dests, _now()):
        print(f"{r['job_id']}: {r['result']}")
    return 0


# ------------------------------------------------------------------ the authorized test post

TEST_TEXT = {
    "en": "Test post: CyberAlertX is connecting its Threads account. Cyber threat briefs in English will follow "
          "here.\n\n{url}",
    "ua": "Тестовий допис: CyberAlertX під'єднує свій акаунт у Threads. Тут з'являтимуться короткі розбори "
          "кіберзагроз українською.\n\n{url}",
}


def story_post(payload: dict[str, Any], locale: str, base: str) -> dict[str, Any]:
    """Exactly what scheduled publishing would post for this story on this
    account: the Threads formatter's text, the story's canonical illustration
    (Threads variant) and its alt text. Pure; raises ValueError when the story
    cannot be posted (no text, no illustration)."""
    from ..publish.format import deep_link
    from ..threads.destination import IMAGE_VARIANT
    from ..threads.format import render_post, threads_length

    url = deep_link(base, locale, str(payload["id"]))
    post = render_post(payload, locale=locale, url=url)
    ill = (payload.get("media") or {}).get("illustration") or {}
    if not ill.get("asset_id"):
        raise ValueError("the story has no canonical illustration yet")
    return {"text": post.text, "length": threads_length(post.text), "url": url,
            "image": f"{base}/media/{ill['asset_id']}/{IMAGE_VARIANT}",
            "alt": str((ill.get("alt") or {}).get(locale) or ""), "topic_tag": post.topic_tag,
            "dropped": list(post.dropped)}


def _story_payload(story: str, locale: str) -> dict[str, Any]:
    from ..api.app import _PostService
    from ..publish.orchestrator import EditionSource

    source = EditionSource(_PostService())
    items = [i for i in source.items() if i.fingerprint == story or getattr(i, "story_key", "") == story]
    for item in sorted(items, key=lambda i: i.published_at, reverse=True):
        payload = source.payload(item, locale)
        if payload:
            return payload
    raise ValueError(f"no {locale} edition for {story}")


def cmd_test_post(args: argparse.Namespace, *, client: Any = None) -> int:
    """One clearly marked test post with a canonical illustration. Requires --confirm.

    With --story, the post is that story exactly as scheduled publishing would
    send it (genuine CyberAlertX content). The story predates the account's
    `publishing_since`, so the scheduler can never post it a second time.
    --preview prints what would be posted and touches nothing."""
    from ..publish.config import build_telegram_settings
    from ..threads.client import ThreadsClient, ThreadsError
    from ..threads.credentials import DEFAULT_USERNAMES, check_token
    from ..threads.destination import IMAGE_VARIANT, http_image_check

    ts, accounts = _stores()
    slot = args.slot
    base = build_telegram_settings().public_base_url.rstrip("/")
    story: dict[str, Any] = {}
    if args.story:
        try:
            story = story_post(_story_payload(args.story, ts.accounts[slot]), ts.accounts[slot], base)
        except (ValueError, KeyError) as exc:
            print(f"cannot post {args.story}: {exc}", file=sys.stderr)
            return 2
    if args.preview:
        if story:
            http_image_check(story["image"])                  # the public image must already serve
        print(json.dumps({"account": slot, "mode": "story" if story else "test text", "preview": story or {
            "text": TEST_TEXT[ts.accounts[slot]].format(url=f"{base}/{ts.accounts[slot]}")}},
            ensure_ascii=False, indent=2))
        return 0
    if not args.confirm:
        print("Refusing: add --confirm to publish ONE test post (or --preview to see it).", file=sys.stderr)
        return 2
    if slot not in ts.accounts or not accounts.has_token(slot):
        print(f"no token for {slot}", file=sys.stderr)
        return 2
    acc = accounts.get(slot)
    expected = ts.usernames.get(slot) or DEFAULT_USERNAMES.get(slot, "")
    image = story["image"] if story else (f"{base}/media/{args.asset}/{IMAGE_VARIANT}" if args.asset else "")
    api = client or ThreadsClient()
    try:
        c = check_token(slot, accounts.token(slot), expected, api)
        if not c.ok or c.user_id != acc.threads_user_id:
            print(f"Refusing: {slot} does not verify ({'; '.join(c.problems) or 'registry mismatch'})", file=sys.stderr)
            return 1
        if image:
            http_image_check(image)
        text = story["text"] if story else TEST_TEXT[ts.accounts[slot]].format(url=f"{base}/{ts.accounts[slot]}")
        alt = story["alt"] if story else (args.alt or "")
        token = accounts.token(slot)
        cid = api.create_container(acc.threads_user_id, token, text=text, image_url=image, alt_text=alt)
        import time
        for _ in range(10):
            status, err = api.container_status(cid, token)
            if status == "FINISHED":
                break
            if status in ("ERROR", "EXPIRED"):
                print(f"container {status}: {err}", file=sys.stderr)
                return 1
            time.sleep(6)
        media_id = api.publish(acc.threads_user_id, token, cid)
        link = api.permalink(media_id, token)
    except (ThreadsError, ValueError) as exc:
        print(f"test post failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if client is None:
            api.close()
    accounts.record_publication(slot, _now())
    print(json.dumps({"account": f"@{acc.username}", "user_id": acc.threads_user_id, "container_id": cid,
                      "post_id": media_id, "permalink": link, "image": image}, ensure_ascii=False, indent=2))
    return 0


# ------------------------------------------------------------------ editorial review (drafts only)

def cmd_editorial_review(args: argparse.Namespace, *, provider: Any = None) -> int:
    """Draft the EN and UA posts for the given stories into OUT and print a
    summary. Review only: nothing is queued, published or recorded, and the
    production draft cache is never read or written (OUT has its own)."""
    from ..config import DATA_DIR
    from ..publish.config import build_telegram_settings
    from ..publish.format import deep_link
    from ..storage.json_store import JsonNewsStore
    from ..threads import editorial as E
    from ..threads.destination import IMAGE_VARIANT
    from ..threads.format import TOPIC_TAG, threads_length

    out = Path(args.out)
    if out.resolve() == Path(DATA_DIR).resolve() or (out / "threads_editorial.json").resolve() == \
            (Path(DATA_DIR) / "threads_editorial.json").resolve():
        print("refusing to write the review into the production data directory", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    base = build_telegram_settings().public_base_url
    items = {i.fingerprint: i for i in JsonNewsStore(Path(DATA_DIR) / "items.json").all()}
    model = ""
    if provider is None:
        provider, model = E.default_provider()
    writer = E.Editorial(E.DraftStore(out / "drafts.json"), provider_factory=lambda: provider,
                         items=items.get, model=model)
    results: list[dict[str, Any]] = []
    for story in args.story:
        try:
            payloads = {loc: _story_payload(story, loc) for loc in ("en", "ua")}
        except ValueError as exc:
            results.append({"story": story, "error": str(exc)})
            continue
        pid = str(payloads["en"]["id"])
        ev = E.evidence_from(payloads["en"], items.get(pid))
        try:
            resp, review = writer.draft(ev)                 # re-checked against the current gates
        except Exception as exc:                            # noqa: BLE001 - record it, review the rest
            results.append({"story": story, "article_id": pid, "error": f"{type(exc).__name__}: {exc}"[:300]})
            print(f"{story}: writer error {type(exc).__name__}", file=sys.stderr)
            continue
        draft_d = {**(writer.store.get(ev.article_id, ev.digest()) or {}), "scores": review.scores,
                   "problems": review.problems, "publishable": review.publishable}
        row: dict[str, Any] = {"story": story, "article_id": pid, "evidence": {
            "outlet": ev.outlet, "headline": ev.headline, "text": ev.text, "url": ev.url,
            "published": ev.published_label()}, "status": resp.status, "facts": [f.model_dump() for f in resp.facts],
            "scores": draft_d["scores"], "problems": draft_d["problems"], "publishable": draft_d["publishable"],
            "attempts": draft_d.get("attempts", 0), "history": draft_d.get("history", []), "omitted": resp.omitted,
            "discussion_prompt": resp.discussion_prompt.model_dump(), "posts": {}}
        for loc in ("en", "ua"):
            url = deep_link(base, loc, pid)
            text = E.compose(resp, loc, outlet=ev.outlet, url=url)
            ill = (payloads[loc].get("media") or {}).get("illustration") or {}
            try:
                old = story_post(payloads[loc], loc, base)["text"]
            except ValueError:
                old = ""
            row["posts"][loc] = {"text": text, "length": threads_length(text), "topic_tag": TOPIC_TAG.get(loc, ""),
                                 "image": f"{base}/media/{ill['asset_id']}/{IMAGE_VARIANT}" if ill.get("asset_id")
                                 else "", "alt": str((ill.get("alt") or {}).get(loc) or ""),
                                 "edition_title": str(((payloads[loc].get("translations") or {}).get(loc) or {})
                                                      .get("title") or ""), "old_text": old,
                                 "old_length": threads_length(old) if old else 0}
        results.append(row)
        print(f"{story}: publishable={row['publishable']} en={row['posts']['en']['length']} "
              f"ua={row['posts']['ua']['length']} scores={row['scores']}", file=sys.stderr)
    (out / "review.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"stories": len(results), "publishable": sum(bool(r.get("publishable")) for r in results),
                      "out": str(out / "review.json")}))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cyberalertx.tools.threads", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup", help="interactive; tokens are read with hidden input")
    s.add_argument("--env", default="", help="environment file (default: the app's .env)")
    s.add_argument("--allow-identity-change", action="store_true",
                   help="allow an account to map to a different Threads user than registered")
    s.set_defaults(fn=cmd_setup)
    st = sub.add_parser("status")
    st.add_argument("--live", action="store_true", help="also validate each token against the API (read-only)")
    st.set_defaults(fn=cmd_status)
    sub.add_parser("refresh").set_defaults(fn=cmd_refresh)
    sub.add_parser("maintain", help="verify accounts + refresh due tokens (timer; never publishes)").set_defaults(
        fn=cmd_maintain)
    sub.add_parser("reconcile").set_defaults(fn=cmd_reconcile)
    t = sub.add_parser("test-post")
    t.add_argument("slot", choices=["en", "ua"])
    t.add_argument("--asset", default="", help="canonical illustration asset id (16 hex) to attach")
    t.add_argument("--alt", default="", help="alt text for the image")
    t.add_argument("--story", default="", help="post this story (story key or article fingerprint) exactly as "
                                               "scheduled publishing would")
    t.add_argument("--preview", action="store_true", help="print what would be posted; publish nothing")
    t.add_argument("--confirm", action="store_true")
    t.set_defaults(fn=cmd_test_post)
    r = sub.add_parser("editorial-review", help="draft EN/UA posts for review; publishes and queues nothing")
    r.add_argument("story", nargs="+", help="story keys or article fingerprints")
    r.add_argument("--out", required=True, help="review directory (never the data directory)")
    r.set_defaults(fn=cmd_editorial_review)
    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
