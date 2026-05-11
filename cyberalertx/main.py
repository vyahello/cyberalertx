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
from .storage.json_store import JsonNewsStore


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def _build_pipeline() -> Pipeline:
    repo = JsonNewsStore(SETTINGS.storage_path, max_items=SETTINGS.max_items_retained)
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
    scheduler.add_job(
        pipeline.run_once,
        "interval",
        minutes=interval,
        next_run_time=None,
        id="cyberalertx-cycle",
        max_instances=1,
        coalesce=True,
    )
    # Kick one cycle immediately so the first run doesn't wait `interval` min.
    pipeline.run_once()

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
    """Generate ThreatPosts for the top-N stored items.

    MVP default is offline — rule-based, no API calls. Pass `--use-llm` to
    enable the configured provider (Anthropic by default; an `ANTHROPIC_API_KEY`
    must also be set).
    """
    from .ai import ContentGenerator
    from .ai.generator import build_default_generator, describe_mode

    repo = JsonNewsStore(SETTINGS.storage_path, max_items=SETTINGS.max_items_retained)
    items = sorted(repo.all(), key=lambda i: i.threat_score, reverse=True)
    if args.limit:
        items = items[: args.limit]
    if not items:
        print("no items in store — run `once` first", file=sys.stderr)
        return 1

    generator: ContentGenerator = build_default_generator(use_llm=args.use_llm or None)
    if args.audience:
        generator._prefer_audience = args.audience  # noqa: SLF001 — CLI override
    if args.language:
        generator._force_language = args.language   # noqa: SLF001

    # Mode banner — stderr so it doesn't contaminate stdout JSON.
    cache_state = "on" if generator._cache is not None else "off"  # noqa: SLF001
    print(
        f"[cyberalertx generate] {describe_mode(generator)}  "
        f"items={len(items)}  cache={cache_state}",
        file=sys.stderr,
    )

    posts = generator.generate_many(items)

    if args.print_only:
        json.dump([p.to_dict() for p in posts], sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        summary = [
            {
                "title": p.title,
                "threat_level": p.threat_level,
                "audiences": p.affected_users,
                "generated_by": p.generated_by,
                "emotional_weight": p.emotional_weight,
            }
            for p in posts
        ]
        json.dump(summary, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")
        # Stderr provenance line so pipelines can see source distribution.
        by_source = {}
        for p in posts:
            by_source[p.generated_by] = by_source.get(p.generated_by, 0) + 1
        print(
            "[cyberalertx generate] generated_by: " +
            ", ".join(f"{k}={v}" for k, v in sorted(by_source.items())),
            file=sys.stderr,
        )
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
    gen_p.add_argument("--limit", type=int, default=5, help="Items to process (top-N by threat_score)")
    gen_p.add_argument("--language", choices=["en", "uk"], default=None,
                       help="Force output language (default: per item)")
    gen_p.add_argument("--audience", default=None,
                       help="Prefer a specific audience template (e.g. developers)")
    gen_p.add_argument("--print-only", action="store_true",
                       help="Print full ThreatPosts instead of compact summary")
    gen_p.add_argument("--use-llm", action="store_true",
                       help="Opt in to the configured LLM provider for this run "
                            "(default: offline rule-based generation)")

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
        "serve": cmd_serve,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
