"""Configuration loading. Values come from a TOML file, overridden by CLI flags."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    roots: list[Path] = field(default_factory=list)
    max_age_days: float = 3.0
    min_free_percent: float = 20.0
    keep_patterns: list[str] = field(default_factory=lambda: ["*@tmp", "*.lock"])
    lock_file_name: str = ".janitor-keep"
    dry_run: bool = False
    metrics_file: Path | None = None
    agent_name: str = "unknown"

    @classmethod
    def from_toml(cls, path: Path) -> Config:
        data = tomllib.loads(path.read_text())
        cfg = cls()
        for key, value in data.get("janitor", {}).items():
            if not hasattr(cfg, key):
                raise ValueError(f"unknown config key: {key}")
            setattr(cfg, key, value)
        cfg.roots = [Path(r) for r in cfg.roots]
        if cfg.metrics_file is not None:
            cfg.metrics_file = Path(cfg.metrics_file)
        return cfg

    def validate(self) -> None:
        if not self.roots:
            raise ValueError("at least one workspace root is required")
        if self.max_age_days < 0:
            raise ValueError("max_age_days must be >= 0")
        if not 0 <= self.min_free_percent < 100:
            raise ValueError("min_free_percent must be in [0, 100)")
