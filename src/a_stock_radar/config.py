from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Settings:
    root: Path
    app: dict[str, Any]
    thresholds: dict[str, Any]
    taxonomy: dict[str, Any]
    sources: dict[str, Any]

    @property
    def history_window(self) -> int:
        return int(self.app.get("history_window", 250))

    @property
    def history_keep_days(self) -> int:
        return int(self.app.get("history_keep_days", 320))

    @property
    def minimum_percentile_samples(self) -> int:
        return int(self.app.get("minimum_percentile_samples", 60))

    @property
    def site_dir(self) -> Path:
        return self.root / self.app.get("site_output", "site")

    @property
    def reports_dir(self) -> Path:
        return self.root / self.app.get("reports_output", "reports")


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing configuration: {path}")
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def discover_root(explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    env_root = os.getenv("RADAR_ROOT")
    if env_root:
        return Path(env_root).resolve()
    current = Path.cwd().resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "config" / "app.yaml").exists():
            return candidate
    raise FileNotFoundError("Could not locate project root containing config/app.yaml")


def load_settings(root: str | Path | None = None) -> Settings:
    project_root = discover_root(root)
    return Settings(
        root=project_root,
        app=_load_yaml(project_root / "config" / "app.yaml"),
        thresholds=_load_yaml(project_root / "config" / "thresholds.yaml"),
        taxonomy=_load_yaml(project_root / "config" / "sector_taxonomy.yaml"),
        sources=_load_yaml(project_root / "config" / "sources.yaml"),
    )
