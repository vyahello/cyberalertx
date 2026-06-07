"""CLI entry point.

Usage:
    python -m cyberalertx.main once          # one fetch cycle, exit
    python -m cyberalertx.main run           # scheduled loop (default)
    python -m cyberalertx.main top --limit 10
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
from typing import Sequence

from apscheduler.schedulers.blocking import BlockingScheduler

from .config import SETTINGS
from .pipeline.orchestrator import Pipeline
from .sources.registry import build_sources
from .storage import build_news_repository
from .storage.json_store import JsonNewsStore


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    # httpx logs every request URL at INFO. For the Telegram publisher that URL
    # embeds the bot token (`/bot<token>/sendMessage`), which would leak the
    # secret into journald. Quiet it to WARNING — the request URLs carry no
    # diagnostic value the app doesn't already log itself.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def _build_pipeline() -> Pipeline:
    """Build the ingest pipeline used by `once` and `run`.

    This pipeline is **deterministic-only**. It never calls Anthropic
    under any env configuration. The single AI entry point in the system
    is `generate --use-llm`; keeping that as the only place AI runs makes
    cost predictable and the mental model simple:

        once       →  free (RSS + keyword scoring + ranking)
        generate   →  LLM journalist render, requires --use-llm (default
                      engine: local `claude` CLI; legacy Haiku API path
                      available via CYBERALERTX_AI_PROVIDER=anthropic)
        serve      →  free (cache + rule-based fallback)

    The legacy AI relevance classifier in `pipeline/relevance.py` is
    intact for possible revival but no longer wired in. The deterministic
    scoring layer (NEGATIVE_TOKENS + threshold 3) filters cleanly enough
    for the gray zone in practice.
    """
    # Storage backend chosen by CYBERALERTX_STORAGE_BACKEND. Default = JSON
    # (current behavior). When set to `dual`, every upsert fans out to
    # Postgres as a shadow write — reads stay on JSON.
    repo = build_news_repository(
        storage_path=SETTINGS.storage_path,
        max_items=SETTINGS.max_items_retained,
    )
    sources = build_sources()
    return Pipeline(sources=sources, repository=repo)


def cmd_once(_args: argparse.Namespace) -> int:
    pipeline = _build_pipeline()
    result = pipeline.run_once()
    print(result)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    pipeline = _build_pipeline()
    interval = args.interval or SETTINGS.fetch_interval_minutes
    if not 1 <= interval <= 240:
        print(f"interval out of range (1-240): {interval}", file=sys.stderr)
        return 2

    scheduler = BlockingScheduler(timezone="UTC")
    # Kick one cycle immediately so the first run doesn't wait `interval` min.
    # Done BEFORE add_job so its log line appears before "scheduler started".
    pipeline.run_once()
    # NB: do NOT pass `next_run_time=None` — that tells APScheduler "never
    # fire this job," which is exactly the bug we hit (job sat dormant for
    # 10h while only the explicit kick above had ever run). Letting the
    # parameter default to undefined makes APScheduler compute the next
    # fire time as `now + interval`, which is what we actually want.
    scheduler.add_job(
        pipeline.run_once,
        "interval",
        minutes=interval,
        id="cyberalertx-cycle",
        max_instances=1,
        coalesce=True,
    )

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: scheduler.shutdown(wait=False))

    logging.getLogger(__name__).info("scheduler started; interval=%dmin", interval)
    scheduler.start()
    return 0


def cmd_top(args: argparse.Namespace) -> int:
    repo = JsonNewsStore(SETTINGS.storage_path, max_items=SETTINGS.max_items_retained)
    items = sorted(repo.all(), key=lambda i: i.threat_score, reverse=True)[: args.limit]
    output = [i.to_public_dict() for i in items]
    json.dump(output, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Start the FastAPI server (uvicorn).

    Reads the current items.json on every request, so a pipeline cycle
    running alongside the API is picked up without restart.
    """
    import uvicorn

    uvicorn.run(
        "cyberalertx.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info" if not args.verbose else "debug",
    )
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    """Render any missing (fingerprint, locale) pairs into the AI cache.

    Token-thrift contract (the reason this command exists):
      * We walk the store, compute the `(fingerprint, required_locales)`
        manifest each item needs (asymmetric multilingual rule — EN-source
        items need en+ua, UA-source items need ua only).
      * For every (fingerprint, locale) pair, we check the AI cache. If
        it's there → SKIP (zero API calls).
      * Only the genuinely-missing pairs get rendered. The renderer goes
        through `_PostService.render()` so cache keys match what `/posts`
        will read.
      * `--dry-run` reports what would be rendered without touching the
        API. Use this before every real run to confirm the budget.

    Default scope is the WHOLE store. `--limit N` narrows to the top-N
    items by `_homepage_score` (useful when you only want the homepage
    warm and don't care about the long tail).

    MVP default is offline — rule-based, no API calls. Pass `--use-llm`
    to enable the configured provider. The default engine is the local
    `claude` CLI (Claude Code headless, reusing its own login — no
    ANTHROPIC_API_KEY). Set CYBERALERTX_AI_PROVIDER=anthropic to switch
    back to the Haiku 4.5 API path (requires `ANTHROPIC_API_KEY`).
    """
    from datetime import datetime, timezone

    from .ai.generator import build_default_generator, describe_mode
    from .api.app import _PostService, _within_homepage_window

    generator = build_default_generator(use_llm=args.use_llm or None)
    if args.audience:
        generator._prefer_audience = args.audience  # noqa: SLF001
    if args.language:
        generator._force_language = args.language   # noqa: SLF001
    svc = _PostService(generator=generator)

    now = datetime.now(timezone.utc)
    all_items = svc.list_items()
    in_window = [i for i in all_items if _within_homepage_window(i, now)]
    # Reverse-chronological — matches the homepage sort order so the
    # AI-warm set is exactly the set the reader sees.
    in_window.sort(key=lambda i: i.published_at, reverse=True)

    if not in_window:
        print("no items in store — run `once` first", file=sys.stderr)
        return 1

    # Build the "missing manifest" by walking items newest-first and
    # accumulating only those with at least one un-cached locale. `--limit`
    # then caps the number of *new* items we render, not the number of
    # items we scan. This lets `generate --limit 5` always produce 5 fresh
    # AI posts (assuming the store has 5 uncached items in the window),
    # which is the intuitive "give me 5 more" semantics operators expect.
    #
    # Previously `--limit N` meant "top-N newest, render any of them that
    # need it" — which produced 0 work whenever the newest N were already
    # cached, even though items #6, #7, ... were still missing.
    cache = getattr(generator, "_cache", None)
    target_new = args.limit if args.limit and args.limit > 0 else None

    missing_pairs: list[tuple[object, str]] = []
    cache_hits = 0
    items_to_render: list = []  # ordered, deduped, capped at target_new

    for item in in_window:
        required = _required_locales_for(item, args.language)
        item_missing: list[str] = []
        for locale in required:
            if cache is not None and cache.get(item.fingerprint, locale) is not None:
                cache_hits += 1
                continue
            item_missing.append(locale)
        if not item_missing:
            continue
        # This item needs at least one new render.
        items_to_render.append(item)
        for locale in item_missing:
            missing_pairs.append((item, locale))
        if target_new is not None and len(items_to_render) >= target_new:
            break

    missing_items = items_to_render

    scope_label = (
        f"limit {target_new} new" if target_new else f"all {len(in_window)} window items"
    )
    print(
        f"[cyberalertx generate] {describe_mode(generator)}  scope={scope_label}\n"
        f"                       cache_hits={cache_hits}  "
        f"missing_keys={len(missing_pairs)}  "
        f"items_to_render={len(missing_items)}",
        file=sys.stderr,
    )

    if args.dry_run:
        print(
            "[cyberalertx generate] --dry-run: not calling API. "
            f"Would render {len(missing_pairs)} (fingerprint, locale) pairs.",
            file=sys.stderr,
        )
        return 0

    if not missing_pairs:
        print("[cyberalertx generate] nothing to do — every required key is cached.", file=sys.stderr)
        return 0

    # Drive only items that have at least one missing locale through
    # render(). render() iterates all required locales for the item, but
    # generate() inside it will cache-hit anything already populated, so
    # we never burn tokens on an already-rendered locale.
    rendered: list[dict] = []
    by_provenance: dict[str, int] = {}
    for item in missing_items:
        try:
            payload = svc.render(item)
        except Exception as exc:
            print(f"  render failed for {item.fingerprint}: {exc}", file=sys.stderr)
            continue
        rendered.append(payload)
        prov = payload.get("generated_by", "?")
        by_provenance[prov] = by_provenance.get(prov, 0) + 1

    if args.print_only:
        json.dump(rendered, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        summary = [
            {
                "id": r["id"],
                "source": r["source"],
                "source_language": r["source_language"],
                "available_locales": r["available_locales"],
                "threat_level": r["threat_level"],
                "generated_by": r["generated_by"],
            }
            for r in rendered
        ]
        json.dump(summary, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        print(
            "[cyberalertx generate] generated_by: " +
            ", ".join(f"{k}={v}" for k, v in sorted(by_provenance.items())),
            file=sys.stderr,
        )
    return 0


def _required_locales_for(item, forced_language: str | None) -> tuple[str, ...]:
    """Mirror the asymmetric render rule in api/app.py:render(). Kept here
    as a private helper so `cmd_generate` doesn't need to import the full
    `_PostService.render` machinery just to introspect required locales."""
    if forced_language in ("en", "ua"):
        return (forced_language,)
    source_lang = item.language if item.language in ("en", "ua") else "en"
    return ("ua",) if source_lang == "ua" else ("en", "ua")


def cmd_publish_telegram(args: argparse.Namespace) -> int:
    """Publish qualifying AI-rendered posts to the Telegram channels.

    Selects already-rendered posts above the configured severity/urgency bar
    from trusted/verified sources, skips anything already in the publish
    ledger, and sends the rest. Never calls Anthropic (reuses the cost-safe
    `_PostService`). `--dry-run` prints what would be sent without touching
    Telegram — run it before the first real fire to confirm the selection.
    """
    from .publish.service import publish_once

    result = publish_once(
        limit=args.limit if args.limit and args.limit > 0 else None,
        language=args.language,
        dry_run=args.dry_run,
    )
    print(f"[cyberalertx publish-telegram] {result}", file=sys.stderr)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cyberalertx", description="CyberAlertX data layer")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("once", help="Run one fetch/filter/rank cycle and exit")

    run_p = sub.add_parser("run", help="Run continuously on a schedule")
    run_p.add_argument("--interval", type=int, default=None, help="Minutes between cycles (1-240)")

    top_p = sub.add_parser("top", help="Print top-N stored items as JSON")
    top_p.add_argument("--limit", type=int, default=10)

    gen_p = sub.add_parser(
        "generate",
        help="Run the AI layer over stored items to produce ThreatPosts",
    )
    gen_p.add_argument(
        "--limit", type=int, default=0,
        help="If >0, narrow scope to top-N items by homepage_score. "
             "Default (0) processes the WHOLE store, but already-cached "
             "(fingerprint, locale) pairs are skipped — so it's still cheap.",
    )
    gen_p.add_argument("--language", choices=["en", "ua"], default=None,
                       help="Force output language (default: per item)")
    gen_p.add_argument("--audience", default=None,
                       help="Prefer a specific audience template (e.g. developers)")
    gen_p.add_argument("--print-only", action="store_true",
                       help="Print full ThreatPosts instead of compact summary")
    gen_p.add_argument("--use-llm", action="store_true",
                       help="Opt in to the configured LLM provider for this run "
                            "(default: offline rule-based generation)")
    gen_p.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be rendered without calling any API. "
             "Use this before every real run to confirm the token budget.",
    )

    tg_p = sub.add_parser(
        "publish-telegram",
        help="Publish qualifying AI-rendered posts to the Telegram channels",
    )
    tg_p.add_argument(
        "--limit", type=int, default=0,
        help="Max sends per channel this run (default: from "
             "CYBERALERTX_TELEGRAM_LIMIT / 5).",
    )
    tg_p.add_argument("--language", choices=["en", "ua"], default=None,
                      help="Restrict to a single channel locale (default: all "
                           "configured channels).")
    tg_p.add_argument(
        "--dry-run", action="store_true",
        help="Print the messages that would be sent without calling Telegram. "
             "Run this before the first real publish to confirm selection.",
    )

    serve_p = sub.add_parser("serve", help="Start the HTTP API (FastAPI/uvicorn)")
    serve_p.add_argument("--host", default="127.0.0.1",
                         help="Bind address (default 127.0.0.1; use 0.0.0.0 to expose)")
    serve_p.add_argument("--port", type=int, default=8000)
    serve_p.add_argument("--reload", action="store_true",
                         help="Auto-reload on code changes (dev only)")

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    return {
        "once": cmd_once,
        "run": cmd_run,
        "top": cmd_top,
        "generate": cmd_generate,
        "publish-telegram": cmd_publish_telegram,
        "serve": cmd_serve,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
