from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta

from .config import load_settings
from .pipeline import run_pipeline


def resolve_date(value: str | None) -> date:
    if value:
        result = datetime.strptime(value, "%Y-%m-%d").date()
    else:
        result = date.today()
    while result.weekday() >= 5:
        result -= timedelta(days=1)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A股市场资金证据雷达 M1")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="抓取、计算并生成静态日报")
    run.add_argument("--date", help="交易日期 YYYY-MM-DD；默认当前最近工作日")
    run.add_argument(
        "--stage",
        choices=["preliminary", "confirmed"],
        default="confirmed",
        help="报告阶段",
    )
    run.add_argument(
        "--data-mode",
        choices=["live", "auto", "mock"],
        default="live",
        help="live 不使用虚构降级；mock 仅用于演示",
    )
    run.add_argument("--root", help="项目根目录")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        settings = load_settings(args.root)
        payload = run_pipeline(settings, resolve_date(args.date), args.stage, args.data_mode)
        print(
            f"Generated {payload.report_stage} report for {payload.trade_date}; "
            f"mode={payload.data_mode}; sectors={len(payload.sector_states)}"
        )
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
