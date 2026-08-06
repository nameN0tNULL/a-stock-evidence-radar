from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import requests

from a_stock_radar.product_io import first_column, read_table


def validate_dazhihui(path: Path) -> dict[str, Any]:
    frame, error = read_table(path)
    if error:
        raise ValueError(error)
    net_column = first_column(
        frame,
        ("dde_net_amount", "dde净额", "大单净额", "超大单净额", "主力净额"),
    )
    amount_column = first_column(
        frame,
        ("amount", "turnover", "成交额", "成交金额"),
    )
    if not net_column or not amount_column:
        raise ValueError("大智慧导出必须同时包含DDE/大单净额和成交额字段")
    if frame.empty:
        raise ValueError("大智慧导出为空")
    return {
        "row_count": len(frame),
        "net_column": net_column,
        "amount_column": amount_column,
    }


def publish(
    path: Path,
    url: str,
    trade_date: date,
    *,
    method: str = "PUT",
    bearer_token: str | None = None,
    kind: str = "generic",
    timeout: float = 120,
) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(path)
    validation = validate_dazhihui(path) if kind == "dazhihui" else {}
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    target = url.format(
        date=trade_date.isoformat(),
        compact_date=trade_date.strftime("%Y%m%d"),
        sha256=digest,
        filename=path.name,
    )
    headers = {
        "Content-Type": "application/octet-stream",
        "X-Radar-Trade-Date": trade_date.isoformat(),
        "X-Radar-SHA256": digest,
        "X-Radar-Source-Kind": kind,
    }
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    response = requests.request(
        method.upper(),
        target,
        data=payload,
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    return {
        "source_file": str(path),
        "target_url": target,
        "method": method.upper(),
        "trade_date": trade_date.isoformat(),
        "bytes": len(payload),
        "sha256": digest,
        "validation": validation,
        "published_at": datetime.now(UTC).isoformat(),
        "status_code": response.status_code,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="发布授权产品导出文件")
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--url", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--method", choices=["PUT", "POST"], default="PUT")
    parser.add_argument("--token")
    parser.add_argument("--kind", choices=["generic", "dazhihui"], default="generic")
    parser.add_argument("--manifest", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = publish(
        args.file,
        args.url,
        date.fromisoformat(args.date),
        method=args.method,
        bearer_token=args.token,
        kind=args.kind,
    )
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
