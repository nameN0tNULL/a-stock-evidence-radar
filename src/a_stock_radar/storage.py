from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd


class FileStore:
    def __init__(self, root: Path, keep_days: int = 320):
        self.root = root
        self.keep_days = keep_days
        self.history_dir = root / "data" / "history"
        self.raw_dir = root / "data" / "raw"
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def save_raw(self, trade_date: date, source_id: str, frame: pd.DataFrame) -> Path:
        target_dir = self.raw_dir / trade_date.isoformat()
        target_dir.mkdir(parents=True, exist_ok=True)
        path = target_dir / f"{source_id}.csv"
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        return path

    def history_path(self, name: str) -> Path:
        return self.history_dir / f"{name}.csv"

    def load_history(self, name: str) -> pd.DataFrame:
        path = self.history_path(name)
        if not path.exists() or path.stat().st_size == 0:
            return pd.DataFrame()
        frame = pd.read_csv(path, dtype={"fund_code": str, "security_code": str})
        if "trade_date" in frame.columns:
            frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.date
        return frame

    def replace_date_rows(
        self,
        name: str,
        incoming: pd.DataFrame,
        key_columns: Iterable[str],
    ) -> pd.DataFrame:
        existing = self.load_history(name)
        if incoming.empty:
            return existing
        incoming = incoming.copy()
        incoming["trade_date"] = pd.to_datetime(incoming["trade_date"]).dt.date
        if existing.empty:
            combined = incoming
        else:
            combined = pd.concat([existing, incoming], ignore_index=True, sort=False)
            combined = combined.drop_duplicates(subset=list(key_columns), keep="last")
        combined = combined.sort_values(list(key_columns)).reset_index(drop=True)
        dates = sorted(pd.Series(combined["trade_date"].dropna().unique()).tolist())
        if len(dates) > self.keep_days:
            cutoff = dates[-self.keep_days]
            combined = combined[combined["trade_date"] >= cutoff].copy()
        path = self.history_path(name)
        combined.to_csv(path, index=False, encoding="utf-8-sig")
        return combined

    @staticmethod
    def write_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
