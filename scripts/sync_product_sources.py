from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from a_stock_radar.public_products import PublicProductClient, download_authorized_artifact


def _suffix(url: str, default: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in {".csv", ".json", ".jsonl", ".xlsx", ".xls", ".md"} else default


def _download_from_env(
    name: str,
    root: Path,
    trade_date: date,
    directory: str,
    default_suffix: str,
) -> dict[str, object] | None:
    url = os.getenv(f"RADAR_{name}_URL")
    if not url:
        return None
    suffix = _suffix(url, default_suffix)
    output = root / directory / f"{trade_date.isoformat()}{suffix}"
    token = os.getenv(f"RADAR_{name}_TOKEN")
    sha256 = os.getenv(f"RADAR_{name}_SHA256")
    return download_authorized_artifact(
        url,
        output,
        bearer_token=token,
        expected_sha256=sha256,
    )


def sync(root: Path, trade_date: date) -> dict[str, object]:
    root = root.resolve()
    client = PublicProductClient()
    manifest: dict[str, object] = {
        "trade_date": trade_date.isoformat(),
        "public_sources": {},
        "authorized_artifacts": {},
    }

    kaipanla = client.fetch_kaipanla_review(trade_date)
    kaipanla_path = root / "imports" / "kaipanla_public" / f"{trade_date.isoformat()}.json"
    kaipanla_path.parent.mkdir(parents=True, exist_ok=True)
    if kaipanla.payload:
        kaipanla_path.write_text(
            json.dumps(kaipanla.payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    manifest["public_sources"]["kaipanla"] = {
        "available": kaipanla.payload is not None,
        "path": str(kaipanla_path) if kaipanla.payload else None,
        "error": kaipanla.error,
    }

    cls = client.fetch_cls_lhb(trade_date)
    cls_path = root / "imports" / "cls" / f"{trade_date.isoformat()}.csv"
    cls_path.parent.mkdir(parents=True, exist_ok=True)
    cls_rows = list((cls.payload or {}).get("rows") or [])
    if cls_rows:
        pd.DataFrame(cls_rows).to_csv(cls_path, index=False, encoding="utf-8-sig")
    manifest["public_sources"]["cls"] = {
        "available": bool(cls_rows),
        "path": str(cls_path) if cls_rows else None,
        "row_count": len(cls_rows),
        "error": cls.error,
    }

    downloads = [
        ("KAIPANLA_EXPORT", "imports/kaipanla", ".csv"),
        ("CLS_LHB_EXPORT", "imports/cls", ".csv"),
        ("DAZHIHUI_DDE_EXPORT", "imports/dazhihui", ".csv"),
        ("DAILY_STOCK_ANALYSIS_ARTIFACT", "imports/daily_stock_analysis", ".md"),
        ("TRADINGAGENTS_CN_ARTIFACT", "imports/tradingagents_cn", ".md"),
    ]
    for name, directory, default_suffix in downloads:
        try:
            item = _download_from_env(
                name,
                root,
                trade_date,
                directory,
                default_suffix,
            )
            manifest["authorized_artifacts"][name.lower()] = item or {
                "available": False,
                "reason": "URL not configured",
            }
        except Exception as exc:
            manifest["authorized_artifacts"][name.lower()] = {
                "available": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

    manifest_path = root / "diagnostics" / "product_source_sync.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="同步公开及授权产品数据源")
    parser.add_argument("--date", required=True, help="交易日期 YYYY-MM-DD")
    parser.add_argument("--root", default=".", help="项目根目录")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifest = sync(Path(args.root), date.fromisoformat(args.date))
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
