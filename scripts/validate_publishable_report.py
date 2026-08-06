from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from a_stock_radar.publish_gate import validate_publishable_payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reject incomplete reports before they replace production latest outputs."
    )
    parser.add_argument(
        "--report",
        default="reports/latest/latest.json",
        help="Generated report JSON path",
    )
    parser.add_argument("--expected-stage", choices=["preliminary", "confirmed"])
    parser.add_argument(
        "--minimum-market-rows",
        type=int,
        default=4000,
        help="Minimum unique market rows required for publication",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = Path(args.report)
    if not path.exists():
        print(f"Publish gate failed: report does not exist: {path}", file=sys.stderr)
        return 1
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Publish gate failed: cannot read {path}: {exc}", file=sys.stderr)
        return 1

    result = validate_publishable_payload(
        payload,
        expected_stage=args.expected_stage,
        minimum_market_rows=args.minimum_market_rows,
    )
    if not result.publishable:
        print("Publish gate rejected the generated report:", file=sys.stderr)
        for error in result.errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(
        "Publish gate passed: "
        f"date={payload.get('trade_date')}; "
        f"stage={payload.get('report_stage')}; "
        f"mode={payload.get('data_mode')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
