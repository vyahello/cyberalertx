"""Publication jobs: plan, inspect, run, recover.

    python -m cyberalertx.tools.publish plan [--dry-run] [--story FP]
    python -m cyberalertx.tools.publish run [--send] [--limit N]     preview unless --send
    python -m cyberalertx.tools.publish cycle [--send] [--limit N]   plan + run (for the timer)
    python -m cyberalertx.tools.publish status | pending | failed | unknown
    python -m cyberalertx.tools.publish show JOB_ID
    python -m cyberalertx.tools.publish retry JOB_ID
    python -m cyberalertx.tools.publish reconcile JOB_ID (--sent MESSAGE_ID | --not-sent)
    python -m cyberalertx.tools.publish cancel JOB_ID
    python -m cyberalertx.tools.publish prune [--older-than-days 90]

Only `run --send` and `cycle --send` can deliver anything externally.
`plan` writes the job store and nothing else; `status`/`pending`/`failed`/
`unknown`/`show` only read; `run` and `cycle` without `--send` print what
would be delivered, claim nothing and send nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..publish.config import TelegramSettings, build_telegram_settings
from ..publish.jobs import JOBS_PATH, JobStore, PublicationJob


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _destinations(settings: TelegramSettings) -> dict[str, Any]:
    from ..publish.destinations import TelegramDestination, WebsiteDestination
    from ..publish.service import DEFAULT_LEDGER_PATH

    out: dict[str, Any] = {"website": WebsiteDestination(settings.public_base_url)}
    if settings.channels:
        out["telegram"] = TelegramDestination(settings, ledger_path=DEFAULT_LEDGER_PATH)
    out.update(_threads_destinations(settings.public_base_url))
    return out


def _threads_destinations(base_url: str) -> dict[str, Any]:
    """One destination per mapped Threads slot — only with CYBERALERTX_THREADS_PUBLISH=1."""
    from ..threads.accounts import AccountStore
    from ..threads.config import ThreadsSettings
    from ..threads.destination import ThreadsDestination, http_image_check

    ts = ThreadsSettings.from_env()
    if not ts.publish_enabled:
        return {}
    accounts = AccountStore(key=ts.token_key, mapping=ts.accounts)
    return {f"threads@{slot}": ThreadsDestination(slot, settings=ts, accounts=accounts, public_base_url=base_url,
                                                  image_check=http_image_check)
            for slot in ts.accounts}


def _source() -> Any:
    from ..api.app import _PostService
    from ..publish.orchestrator import EditionSource
    return EditionSource(_PostService())


def _ledger_has() -> Any:
    from ..publish.ledger import PublishLedger
    from ..publish.service import DEFAULT_LEDGER_PATH
    ledger = PublishLedger(DEFAULT_LEDGER_PATH)
    return ledger.is_published


def _line(j: PublicationJob) -> str:
    when = j.next_attempt_at if j.status == "retrying" else j.scheduled_at
    tail = j.published_url or j.last_error
    return (f"{j.status:15} p{j.priority:<3} {j.destination:8} {j.locale}  {j.job_id}\n"
            f"{'':20}attempts {j.attempts}/{j.max_attempts} · due {when or '—'} · ext {j.external_id or '—'}"
            + (f"\n{'':20}{tail}" if tail else ""))


def cmd_plan(args: argparse.Namespace) -> int:
    from ..publish.orchestrator import plan

    settings = build_telegram_settings()
    store = JobStore(Path(args.jobs))
    res = plan(_source(), store, now=_now(), settings=settings, destinations=_destinations(settings),
               ledger_has=_ledger_has(), dry_run=args.dry_run)
    out: dict[str, Any] = {"dry_run": args.dry_run, **res.summary()}
    jobs = [j for j in res.created if not args.story or j.fingerprint == args.story or args.story in j.members]
    out["jobs"] = [{"job_id": j.job_id, "status": j.status, "priority": j.priority, "reasons": j.reasons,
                    "scheduled_at": j.scheduled_at} for j in jobs[: args.show]]
    if args.story:
        out["skipped_for_story"] = [s for s in res.skipped if s["fingerprint"] == args.story]
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def _run(args: argparse.Namespace, *, with_plan: bool) -> int:
    from ..publish.orchestrator import PublishPolicy, plan, run

    settings = build_telegram_settings()
    store = JobStore(Path(args.jobs))
    dests = _destinations(settings)
    # Refuse BEFORE anything is written: a refused --send must leave the job
    # store exactly as it was (found in the Stage B rehearsal).
    if args.send and "telegram" in dests and not settings.bot_token:
        print("refusing --send: Telegram channels are configured but no bot token is set", file=sys.stderr)
        return 2
    source = _source()
    if with_plan:
        res = plan(source, store, now=_now(), settings=settings, destinations=dests,
                   ledger_has=_ledger_has(), dry_run=not args.send)
        print(f"[plan] {json.dumps(res.summary(), ensure_ascii=False)}", file=sys.stderr)
    if args.send and any(k.startswith("threads@") for k in dests):
        # Keep tokens fresh and settle what the API can settle, before sending.
        from ..threads.client import ThreadsClient
        from ..threads.destination import auto_reconcile
        from ..threads.oauth import refresh_due
        first = next(d for k, d in dests.items() if k.startswith("threads@"))
        api = ThreadsClient()
        try:
            for r in refresh_due(first.accounts, api, _now()):
                print(f"[threads] token {r.slot}: {r.outcome} {r.detail}".rstrip(), file=sys.stderr)
        finally:
            api.close()
        for r2 in auto_reconcile(store, dests, _now()):
            print(f"[threads] reconcile {r2['job_id']}: {r2['result']}", file=sys.stderr)
    report = run(source, store, dests, policy=PublishPolicy.from_env(settings),
                 limit=args.limit, dry_run=not args.send, send_delay_s=settings.send_delay_seconds)
    print(json.dumps(report.summary(), ensure_ascii=False, indent=2))
    previews = [p for p in report.previews if not args.story or p.get("fingerprint") == args.story
                or p["job_id"].startswith(args.story)]
    for p in previews[: args.show]:
        print(json.dumps(p, ensure_ascii=False, indent=2))
    if not args.send:
        print("(preview only — nothing was claimed or sent; add --send to deliver)", file=sys.stderr)
    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    """Activation baseline: nothing published before `--before` is ever posted.

    Runs `plan` (which imports the publish ledger as published), then cancels
    every Telegram job that is still scheduled or retrying for an article
    published before the cutoff — the stories that came in while publishing
    was held. Cancelled jobs are never re-planned, so the backlog cannot
    flood the channels later. Website jobs are untouched.
    """
    from ..publish.orchestrator import plan

    try:
        cutoff = datetime.fromisoformat(args.before)
    except ValueError:
        print(f"--before must be an ISO timestamp, got {args.before!r}", file=sys.stderr)
        return 2
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    settings = build_telegram_settings()
    store = JobStore(Path(args.jobs))
    source = _source()
    res = plan(source, store, now=_now(), settings=settings, destinations=_destinations(settings),
               ledger_has=_ledger_has(), dry_run=args.dry_run)
    by_fp = {i.fingerprint: i for i in source.items()}
    pending = [j for j in (res.created if args.dry_run else store.all())
               if j.destination == "telegram" and j.status in ("scheduled", "retrying")]
    old = [j for j in pending if (it := by_fp.get(j.fingerprint)) is None or it.published_at < cutoff]
    if not args.dry_run:
        now = _now()
        for j in old:
            def cancel(x: PublicationJob) -> None:
                x.status, x.claimed_by, x.lease_until = "cancelled", "", ""
                x.last_error = f"activation baseline: published before {cutoff.isoformat()}"
                x.completed_at = now.isoformat(timespec="seconds")
                x.note(now, "cancelled", reason="activation baseline")
            store.update(j.job_id, cancel, now)
    print(json.dumps({"dry_run": args.dry_run, "cutoff": cutoff.isoformat(), "plan": res.summary(),
                      "telegram_pending": len(pending), "cancelled_as_backlog": len(old),
                      "kept": [j.job_id for j in pending if j not in old][: args.show]},
                     ensure_ascii=False, indent=2))
    return 0


def check_telegram(settings: TelegramSettings, client: Any = None) -> dict[str, Any]:
    """Read-only Bot API checks: getMe, getChat and the bot's rights in each
    configured channel. Sends nothing; never prints the token or chat ids."""
    import httpx

    out: dict[str, Any] = {"ok": False, "bot": None, "channels": {}}
    if not settings.bot_token:
        out["error"] = "no bot token configured"
        return out
    base = f"{settings.api_base}/bot{settings.bot_token}"
    own = client is None
    c = client or httpx.Client(timeout=settings.request_timeout_seconds)
    try:
        def call(method: str, **params: Any) -> dict[str, Any]:
            r = c.get(f"{base}/{method}", params=params)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if r.status_code != 200 or not body.get("ok"):
                raise RuntimeError(f"{method}: HTTP {r.status_code} {str(body.get('description') or '')[:120]}")
            return dict(body["result"])
        me = call("getMe")
        out["bot"] = {"username": me.get("username"), "is_bot": me.get("is_bot")}
        ok = bool(me.get("is_bot"))
        for loc, chat in sorted(settings.channels.items()):
            entry: dict[str, Any] = {}
            try:
                info = call("getChat", chat_id=chat)
                member = call("getChatMember", chat_id=chat, user_id=me["id"])
                entry = {"type": info.get("type"), "title": info.get("title"),
                         "bot_status": member.get("status"),
                         "can_post_messages": bool(member.get("can_post_messages"))
                         or member.get("status") == "creator"}
                entry["ok"] = entry["type"] == "channel" and entry["bot_status"] in ("administrator", "creator") \
                    and entry["can_post_messages"]
            except (RuntimeError, httpx.HTTPError, ValueError) as exc:
                entry = {"ok": False, "error": str(exc).replace(settings.bot_token, "<token>")}
            out["channels"][loc] = entry
            ok = ok and bool(entry.get("ok"))
        out["ok"] = ok
    except (RuntimeError, httpx.HTTPError, ValueError) as exc:
        out["error"] = str(exc).replace(settings.bot_token, "<token>")
    finally:
        if own:
            c.close()
    return out


def cmd_check_telegram(_: argparse.Namespace) -> int:
    res = check_telegram(build_telegram_settings())
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 1


def cmd_status(args: argparse.Namespace) -> int:
    from ..publish.orchestrator import status_counts

    jobs = JobStore(Path(args.jobs)).all()
    print(json.dumps(status_counts(jobs), indent=2, sort_keys=True))
    attention = [j for j in jobs if j.status in ("failed", "outcome_unknown")]
    if attention:
        print(f"\n{len(attention)} job(s) need attention — see `failed` and `unknown`.")
    return 0


def _list(args: argparse.Namespace, statuses: tuple[str, ...]) -> int:
    jobs = sorted((j for j in JobStore(Path(args.jobs)).all() if j.status in statuses),
                  key=lambda j: (-j.priority, j.scheduled_at))
    for j in jobs[: args.show]:
        print(_line(j))
    print(f"{len(jobs)} job(s)")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    j = JobStore(Path(args.jobs)).get(args.job)
    if j is None:
        print(f"no job {args.job}", file=sys.stderr)
        return 1
    print(json.dumps(j.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _action(fn: Any, *a: Any, **kw: Any) -> int:
    from ..publish.orchestrator import ActionError
    try:
        j = fn(*a, **kw)
    except ActionError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(_line(j))
    return 0


def cmd_retry(args: argparse.Namespace) -> int:
    from ..publish.orchestrator import retry_job
    return _action(retry_job, JobStore(Path(args.jobs)), args.job, _now())


def cmd_cancel(args: argparse.Namespace) -> int:
    from ..publish.orchestrator import cancel_job
    return _action(cancel_job, JobStore(Path(args.jobs)), args.job, _now(), args.reason)


def cmd_reconcile(args: argparse.Namespace) -> int:
    from ..publish.ledger import PublishLedger
    from ..publish.orchestrator import reconcile_job
    from ..publish.service import DEFAULT_LEDGER_PATH

    settings = build_telegram_settings()

    def record(job: PublicationJob, message_id: str) -> None:
        if job.destination == "telegram" and message_id.isdigit():
            PublishLedger(DEFAULT_LEDGER_PATH).record(
                fingerprint=job.fingerprint, locale=job.locale,
                channel=settings.chat_id_for(job.locale) or "", message_id=int(message_id))

    return _action(reconcile_job, JobStore(Path(args.jobs)), args.job, _now(),
                   sent_id=args.sent or "", not_sent=args.not_sent, ledger_record=record)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cyberalertx.tools.publish", description=__doc__.splitlines()[0])
    ap.add_argument("--jobs", default=str(JOBS_PATH), help=argparse.SUPPRESS)
    ap.add_argument("--show", type=int, default=50, help="max rows to print")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="create due publication jobs (writes the job store only)")
    p.add_argument("--dry-run", action="store_true", help="print the plan; write nothing")
    p.add_argument("--story", default="", help="only show jobs for this article fingerprint")
    p.set_defaults(fn=cmd_plan)
    for name, with_plan in (("run", False), ("cycle", True)):
        r = sub.add_parser(name, help=("execute due jobs" if name == "run" else "plan, then execute due jobs")
                           + " (preview unless --send)")
        r.add_argument("--send", action="store_true", help="actually deliver (external side effects)")
        r.add_argument("--limit", type=int, default=None, help="Telegram jobs per channel this run")
        r.add_argument("--story", default="", help="only print previews for this fingerprint / story key")
        r.set_defaults(fn=lambda a, wp=with_plan: _run(a, with_plan=wp))
    sub.add_parser("check-telegram", help="read-only: bot identity and channel rights (sends nothing)").set_defaults(
        fn=cmd_check_telegram)
    bl = sub.add_parser("baseline", help="cancel Telegram jobs for articles published before a cutoff (activation)")
    bl.add_argument("--before", required=True, help="ISO timestamp, e.g. 2026-11-05T14:00:00+00:00")
    bl.add_argument("--dry-run", action="store_true", help="report what would be cancelled; write nothing")
    bl.set_defaults(fn=cmd_baseline)
    sub.add_parser("status", help="job counts per destination").set_defaults(fn=cmd_status)
    sub.add_parser("pending", help="scheduled / retrying jobs").set_defaults(
        fn=lambda a: _list(a, ("scheduled", "retrying", "processing")))
    sub.add_parser("failed", help="failed jobs").set_defaults(fn=lambda a: _list(a, ("failed",)))
    sub.add_parser("unknown", help="jobs with an unknown delivery outcome").set_defaults(
        fn=lambda a: _list(a, ("outcome_unknown",)))
    s = sub.add_parser("show", help="one job, with its history")
    s.add_argument("job")
    s.set_defaults(fn=cmd_show)
    rt = sub.add_parser("retry", help="re-queue a failed or cancelled job")
    rt.add_argument("job")
    rt.set_defaults(fn=cmd_retry)
    c = sub.add_parser("cancel", help="cancel a job that has not been delivered")
    c.add_argument("job")
    c.add_argument("--reason", default="operator")
    c.set_defaults(fn=cmd_cancel)
    pr = sub.add_parser("prune", help="archive published/cancelled jobs older than N days")
    pr.add_argument("--older-than-days", type=float, default=90.0)
    pr.set_defaults(fn=lambda a: print(f"archived {JobStore(Path(a.jobs)).prune(_now(), older_than_days=a.older_than_days)} job(s)") or 0)
    rc = sub.add_parser("reconcile", help="resolve an outcome_unknown job after checking the channel")
    rc.add_argument("job")
    g = rc.add_mutually_exclusive_group(required=True)
    g.add_argument("--sent", default="", help="it was delivered: the message id seen in the channel")
    g.add_argument("--not-sent", action="store_true", help="it was not delivered: send it again")
    rc.set_defaults(fn=cmd_reconcile)

    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
