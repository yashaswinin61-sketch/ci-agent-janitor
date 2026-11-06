"""Core cleanup logic.

Two passes over each workspace root:
  1. age pass   - remove workspaces not modified for more than max_age_days
  2. space pass - if free space is still below min_free_percent, remove the
                  least-recently-used remaining workspaces until it is not

A workspace is protected if it matches a keep pattern or contains the lock
file (CI jobs drop that file while they run, so live builds are never touched).
"""

from __future__ import annotations

import contextlib
import fnmatch
import logging
import os
import shutil
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config

log = logging.getLogger(__name__)

DiskUsage = Callable[[Path], tuple[int, int]]  # -> (total_bytes, free_bytes)


def _disk_usage(path: Path) -> tuple[int, int]:
    usage = shutil.disk_usage(path)
    return usage.total, usage.free


@dataclass
class Workspace:
    path: Path
    mtime: float
    size: int


@dataclass
class Report:
    removed: list[Path] = field(default_factory=list)
    skipped_protected: int = 0
    errors: int = 0
    bytes_reclaimed: int = 0
    free_percent_before: float = 0.0
    free_percent_after: float = 0.0
    duration_seconds: float = 0.0


def dir_size(path: Path) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path, onerror=lambda _e: None):
        for name in filenames:
            with contextlib.suppress(OSError):
                total += os.lstat(os.path.join(dirpath, name)).st_size
    return total


def newest_mtime(path: Path) -> float:
    """Most recent mtime of the directory or anything directly inside it.

    Checking one level deep is a cheap but good signal: CI tools touch
    files at the top of a workspace on every checkout.
    """
    newest = path.stat().st_mtime
    try:
        for entry in os.scandir(path):
            with contextlib.suppress(OSError):
                newest = max(newest, entry.stat(follow_symlinks=False).st_mtime)
    except OSError:
        pass
    return newest


class Cleaner:
    def __init__(
        self,
        cfg: Config,
        disk_usage: DiskUsage = _disk_usage,
        now: Callable[[], float] = time.time,
    ):
        self.cfg = cfg
        self.disk_usage = disk_usage
        self.now = now

    def is_protected(self, path: Path) -> bool:
        if any(fnmatch.fnmatch(path.name, pat) for pat in self.cfg.keep_patterns):
            return True
        return (path / self.cfg.lock_file_name).exists()

    def discover(self, root: Path) -> tuple[list[Workspace], int]:
        workspaces, protected = [], 0
        if not root.is_dir():
            log.warning("workspace root does not exist: %s", root)
            return workspaces, protected
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.is_symlink():
                continue
            if self.is_protected(entry):
                protected += 1
                continue
            workspaces.append(Workspace(entry, newest_mtime(entry), dir_size(entry)))
        return workspaces, protected

    def free_percent(self, root: Path) -> float:
        total, free = self.disk_usage(root)
        return 100.0 * free / total if total else 100.0

    def _remove(self, ws: Workspace, report: Report) -> bool:
        log.info(
            "%s %s (%.1f MiB)",
            "would remove" if self.cfg.dry_run else "removing",
            ws.path,
            ws.size / 2**20,
        )
        if not self.cfg.dry_run:
            try:
                shutil.rmtree(ws.path)
            except OSError as exc:
                log.error("failed to remove %s: %s", ws.path, exc)
                report.errors += 1
                return False
        report.removed.append(ws.path)
        report.bytes_reclaimed += ws.size
        return True

    def run(self, roots: Iterable[Path] | None = None) -> Report:
        start = self.now()
        report = Report()
        roots = list(roots or self.cfg.roots)
        max_age = self.cfg.max_age_days * 86400
        report.free_percent_before = min(self.free_percent(r) for r in roots)

        for root in roots:
            workspaces, protected = self.discover(root)
            report.skipped_protected += protected

            survivors = []
            for ws in workspaces:
                if self.now() - ws.mtime > max_age and self._remove(ws, report):
                    continue
                survivors.append(ws)

            # Space pass: LRU first. In dry-run mode the disk doesn't actually
            # change, so estimate free space from bytes we would have reclaimed.
            survivors.sort(key=lambda w: w.mtime)
            total, free = self.disk_usage(root)
            reclaimed_here = 0
            for ws in survivors:
                if self.cfg.dry_run:
                    free_pct = 100.0 * (free + reclaimed_here) / total if total else 100.0
                else:
                    free_pct = self.free_percent(root)
                if free_pct >= self.cfg.min_free_percent:
                    break
                if self._remove(ws, report):
                    reclaimed_here += ws.size

        report.free_percent_after = min(self.free_percent(r) for r in roots)
        report.duration_seconds = self.now() - start
        return report
