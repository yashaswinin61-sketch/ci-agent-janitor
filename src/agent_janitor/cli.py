"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import logging
import socket
import sys
from pathlib import Path

from . import __version__, metrics
from .cleaner import Cleaner
from .config import Config


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="agent-janitor", description=__doc__)
    p.add_argument("roots", nargs="*", type=Path, help="workspace root directories")
    p.add_argument("-c", "--config", type=Path, help="TOML config file")
    p.add_argument("--max-age-days", type=float)
    p.add_argument("--min-free-percent", type=float)
    p.add_argument(
        "--metrics-file", type=Path, help="write Prometheus metrics here (textfile collector)"
    )
    p.add_argument("-n", "--dry-run", action="store_true", help="report only, delete nothing")
    p.add_argument("--json", action="store_true", help="print a JSON summary for log shipping")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p.parse_args(argv)


def build_config(args: argparse.Namespace) -> Config:
    cfg = Config.from_toml(args.config) if args.config else Config()
    if args.roots:
        cfg.roots = args.roots
    for name in ("max_age_days", "min_free_percent", "metrics_file"):
        if getattr(args, name) is not None:
            setattr(cfg, name, getattr(args, name))
    cfg.dry_run = cfg.dry_run or args.dry_run
    if cfg.agent_name == "unknown":
        cfg.agent_name = socket.gethostname()
    cfg.validate()
    return cfg


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    try:
        cfg = build_config(args)
    except (ValueError, OSError) as exc:
        logging.error("%s", exc)
        return 2

    report = Cleaner(cfg).run()

    if cfg.metrics_file:
        metrics.write_atomic(cfg.metrics_file, metrics.render(report, cfg.agent_name, cfg.dry_run))
    summary = {
        "event": "agent_janitor_run",
        "agent": cfg.agent_name,
        "dry_run": cfg.dry_run,
        "removed": len(report.removed),
        "protected": report.skipped_protected,
        "errors": report.errors,
        "bytes_reclaimed": report.bytes_reclaimed,
        "free_percent_before": round(report.free_percent_before, 2),
        "free_percent_after": round(report.free_percent_after, 2),
        "duration_seconds": round(report.duration_seconds, 3),
    }
    if args.json:
        print(json.dumps(summary))
    else:
        logging.info(
            "removed %(removed)d workspaces, reclaimed %(bytes_reclaimed)d bytes, "
            "free %(free_percent_before).1f%% -> %(free_percent_after).1f%%",
            summary,
        )
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
