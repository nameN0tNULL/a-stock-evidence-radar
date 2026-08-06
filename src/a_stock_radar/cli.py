from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import discover_root, load_settings
from .pipeline import run_pipeline
from .tick_fetcher import (
    AkshareTencentTickCollector,
    assess_tick_quality,
    compute_trade_print_features,
    normalize_security_symbol,
    write_tick_bundle,
)


def resolve_date(value: str | None) -> date:
    if value:
        result = date.fromisoformat(value)
    else:
        result = datetime.now(ZoneInfo("Asia/Shanghai")).date()
    while result.weekday() >= 5:
        result -= timedelta(days=1)
    return result


def parse_official_turnover(values: list[str] | None) -> dict[str, float]:
    result: dict[str, float] = {}
    for item in values or []:
        if "=" not in item:
            raise ValueError("Official turnover must use SYMBOL=VALUE format")
        raw_symbol, raw_value = item.split("=", 1)
        _, _, canonical = normalize_security_symbol(raw_symbol)
        value = float(raw_value)
        if value <= 0:
            raise ValueError(f"Official turnover must be positive: {item}")
        result[canonical] = value
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="A股市场参与者与证据复盘")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="读取产品源、计算并生成静态日报")
    run.add_argument("--date", help="交易日期 YYYY-MM-DD；默认当前最近工作日")
    run.add_argument(
        "--stage",
        choices=["preliminary", "confirmed"],
        default="confirmed",
        help="报告阶段",
    )
    run.add_argument(
        "--data-mode",
        choices=["live", "auto", "curated", "legacy", "mock"],
        default="live",
        help=(
            "live/curated 使用开盘啦、东方财富龙虎榜、大智慧、财联社及外部分析产物；"
            "legacy 仅用于旧行情聚合兼容；mock 仅用于演示"
        ),
    )
    run.add_argument("--root", help="项目根目录")

    ticks = subparsers.add_parser(
        "collect-ticks",
        help="旧兼容工具：采集免费分笔成交；不会标记为完整Level-2或替代大智慧DDE/ACE",
    )
    ticks.add_argument("--date", required=True, help="由操作方确认的交易日期 YYYY-MM-DD")
    ticks.add_argument("--symbols", nargs="+", required=True, help="例如 sz000001 sh600000")
    ticks.add_argument("--root", help="项目根目录")
    ticks.add_argument("--retries", type=int, default=3, help="单证券最大尝试次数")
    ticks.add_argument("--delay-seconds", type=float, default=0.5, help="证券之间的请求间隔")
    ticks.add_argument(
        "--official-turnover",
        action="append",
        help="可选盘后成交额核验，格式 SYMBOL=VALUE；可重复",
    )
    ticks.add_argument(
        "--turnover-tolerance",
        type=float,
        default=0.03,
        help="分笔成交额与官方成交额的最大允许偏差比例",
    )
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
    if args.command == "collect-ticks":
        root = discover_root(args.root)
        trade_date = date.fromisoformat(args.date)
        official_turnover = parse_official_turnover(args.official_turnover)
        collector = AkshareTencentTickCollector(retries=args.retries)
        failures = 0
        for index, symbol in enumerate(args.symbols):
            try:
                frame = collector.collect(symbol, trade_date)
                canonical = str(frame.iloc[0]["symbol"])
                quality = assess_tick_quality(
                    frame,
                    official_turnover=official_turnover.get(canonical),
                    turnover_tolerance=args.turnover_tolerance,
                )
                features = compute_trade_print_features(frame)
                paths = write_tick_bundle(root, frame, quality, features)
                print(
                    f"Collected {canonical}: rows={len(frame)}; status={quality.status}; "
                    f"coverage={quality.classification_coverage:.2%}; "
                    f"manifest={paths.manifest_path}"
                )
            except Exception as exc:
                failures += 1
                print(f"Failed {symbol}: {exc}", file=sys.stderr)
            if index + 1 < len(args.symbols) and args.delay_seconds > 0:
                time.sleep(args.delay_seconds)
        return 1 if failures else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
