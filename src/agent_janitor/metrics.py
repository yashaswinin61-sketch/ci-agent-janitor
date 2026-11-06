"""Prometheus text-format output for node_exporter's textfile collector."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from .cleaner import Report


def render(report: Report, agent: str, dry_run: bool, now: float | None = None) -> str:
    now = time.time() if now is None else now
    labels = f'agent="{agent}",dry_run="{str(dry_run).lower()}"'
    metrics = [
        (
            "agent_janitor_last_run_timestamp_seconds",
            "gauge",
            "Unix time of the last janitor run",
            now,
        ),
        (
            "agent_janitor_last_run_duration_seconds",
            "gauge",
            "How long the last run took",
            report.duration_seconds,
        ),
        (
            "agent_janitor_workspaces_removed",
            "gauge",
            "Workspaces removed in the last run",
            len(report.removed),
        ),
        (
            "agent_janitor_workspaces_protected",
            "gauge",
            "Workspaces skipped because they were locked or matched a keep pattern",
            report.skipped_protected,
        ),
        ("agent_janitor_errors", "gauge", "Removal failures in the last run", report.errors),
        (
            "agent_janitor_bytes_reclaimed",
            "gauge",
            "Bytes freed in the last run",
            report.bytes_reclaimed,
        ),
        (
            "agent_janitor_free_percent_before",
            "gauge",
            "Lowest free-space percent across roots before the run",
            report.free_percent_before,
        ),
        (
            "agent_janitor_free_percent_after",
            "gauge",
            "Lowest free-space percent across roots after the run",
            report.free_percent_after,
        ),
    ]
    lines = []
    for name, kind, help_text, value in metrics:
        lines += [
            f"# HELP {name} {help_text}",
            f"# TYPE {name} {kind}",
            f"{name}{{{labels}}} {value:g}",
        ]
    return "\n".join(lines) + "\n"


def write_atomic(path: Path, content: str) -> None:
    """Write via rename so node_exporter never reads a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".agent_janitor.")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
