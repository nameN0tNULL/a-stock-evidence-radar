from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import venv
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

DSA_REPO = "https://github.com/ZhuLinsen/daily_stock_analysis.git"
DSA_REF = "ed848da6f0fc1080e1a61a1799b9c7d510a3eaca"
TRADING_AGENTS_REPO = "https://github.com/hsliuping/TradingAgents-CN.git"
TRADING_AGENTS_REF = "74783e8817d6cf6de29867880631cc555153f36b"


def _enabled(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() in {"1", "true", "yes", "on"}


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _clone(repo: str, ref: str, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    subprocess.run(
        ["git", "clone", "--filter=blob:none", "--no-checkout", repo, str(destination)],
        check=True,
        text=True,
    )
    subprocess.run(["git", "checkout", ref], cwd=destination, check=True, text=True)


def _venv_python(path: Path) -> Path:
    return path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _install(repo: Path, environment: Path, timeout: int) -> Path:
    venv.EnvBuilder(with_pip=True, clear=True).create(environment)
    python = _venv_python(environment)
    subprocess.run(
        [str(python), "-m", "pip", "install", "--upgrade", "pip"],
        check=True,
        timeout=timeout,
    )
    requirements = repo / "requirements.txt"
    if requirements.exists():
        subprocess.run(
            [str(python), "-m", "pip", "install", "-r", str(requirements)],
            cwd=repo,
            check=True,
            timeout=timeout,
        )
    else:
        subprocess.run(
            [str(python), "-m", "pip", "install", "-e", "."],
            cwd=repo,
            check=True,
            timeout=timeout,
        )
    return python


def _artifact_header(name: str, trade_date: date, ref: str) -> str:
    return (
        f"# {name}\n\n"
        f"- trade_date: {trade_date.isoformat()}\n"
        f"- upstream_ref: `{ref}`\n"
        f"- generated_at: {datetime.now(UTC).isoformat()}\n"
        "- role: external analysis reference; not a market fact source\n\n"
    )


def run_daily_stock_analysis(root: Path, trade_date: date, timeout: int) -> dict[str, Any]:
    if not _enabled("RADAR_ENABLE_DAILY_STOCK_ANALYSIS"):
        return {"enabled": False, "reason": "RADAR_ENABLE_DAILY_STOCK_ANALYSIS is false"}
    ref = os.getenv("RADAR_DSA_REF", DSA_REF)
    repo = root / "runtime" / "external" / "daily_stock_analysis"
    environment = root / "runtime" / "venvs" / "daily_stock_analysis"
    output = root / "imports" / "daily_stock_analysis" / f"{trade_date.isoformat()}.md"
    try:
        _clone(DSA_REPO, ref, repo)
        python = _install(repo, environment, timeout)
        command_text = os.getenv(
            "RADAR_DSA_COMMAND",
            "main.py --market-review --no-notify --force-run",
        )
        command = [str(python), *shlex.split(command_text)]
        env = os.environ.copy()
        env.setdefault("TRADING_DAY_CHECK_ENABLED", "false")
        env.setdefault("STOCK_LIST", os.getenv("RADAR_ANALYSIS_SYMBOLS", ""))
        completed = _run(command, cwd=repo, env=env, timeout=timeout)
        if completed.returncode != 0:
            raise RuntimeError(
                f"daily_stock_analysis exited {completed.returncode}: "
                f"{completed.stderr[-2000:]}"
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            _artifact_header("daily_stock_analysis 自动日报", trade_date, ref)
            + "## 标准输出\n\n```text\n"
            + completed.stdout[-30000:]
            + "\n```\n",
            encoding="utf-8",
        )
        return {"enabled": True, "success": True, "ref": ref, "output": str(output)}
    except Exception as exc:
        return {"enabled": True, "success": False, "ref": ref, "error": f"{type(exc).__name__}: {exc}"}


def _trading_agents_runner() -> str:
    return '''from __future__ import annotations
import json
import os
from pathlib import Path
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

trade_date = os.environ["RADAR_EXTERNAL_TRADE_DATE"]
symbols = [item.strip() for item in os.environ.get("RADAR_TRADINGAGENTS_SYMBOLS", "").split(",") if item.strip()]
if not symbols:
    raise SystemExit("RADAR_TRADINGAGENTS_SYMBOLS is empty")
config = DEFAULT_CONFIG.copy()
config["llm_provider"] = os.environ.get("RADAR_TRADINGAGENTS_PROVIDER", config.get("llm_provider", "openai"))
config["deep_think_llm"] = os.environ.get("RADAR_TRADINGAGENTS_DEEP_MODEL", "gpt-4o-mini")
config["quick_think_llm"] = os.environ.get("RADAR_TRADINGAGENTS_QUICK_MODEL", "gpt-4o-mini")
config["max_debate_rounds"] = int(os.environ.get("RADAR_TRADINGAGENTS_DEBATE_ROUNDS", "1"))
config["max_risk_discuss_rounds"] = int(os.environ.get("RADAR_TRADINGAGENTS_RISK_ROUNDS", "1"))
config["online_tools"] = True
results = []
for symbol in symbols:
    graph = TradingAgentsGraph(
        selected_analysts=["market", "news", "fundamentals"],
        debug=False,
        config=config,
    )
    state, decision = graph.propagate(symbol, trade_date)
    results.append({"symbol": symbol, "decision": decision, "state": state})
Path(os.environ["RADAR_TRADINGAGENTS_OUTPUT"]).write_text(
    json.dumps({"trade_date": trade_date, "results": results}, ensure_ascii=False, indent=2, default=str),
    encoding="utf-8",
)
'''


def run_tradingagents_cn(root: Path, trade_date: date, timeout: int) -> dict[str, Any]:
    if not _enabled("RADAR_ENABLE_TRADINGAGENTS_CN"):
        return {"enabled": False, "reason": "RADAR_ENABLE_TRADINGAGENTS_CN is false"}
    if not os.getenv("RADAR_TRADINGAGENTS_SYMBOLS"):
        return {"enabled": True, "success": False, "error": "RADAR_TRADINGAGENTS_SYMBOLS is empty"}
    ref = os.getenv("RADAR_TRADINGAGENTS_REF", TRADING_AGENTS_REF)
    repo = root / "runtime" / "external" / "tradingagents_cn"
    environment = root / "runtime" / "venvs" / "tradingagents_cn"
    output = root / "imports" / "tradingagents_cn" / f"{trade_date.isoformat()}.json"
    try:
        _clone(TRADING_AGENTS_REPO, ref, repo)
        python = _install(repo, environment, timeout)
        runner = repo / ".radar_runner.py"
        runner.write_text(_trading_agents_runner(), encoding="utf-8")
        output.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["RADAR_EXTERNAL_TRADE_DATE"] = trade_date.isoformat()
        env["RADAR_TRADINGAGENTS_OUTPUT"] = str(output)
        env.setdefault("MONGODB_ENABLED", "false")
        env.setdefault("REDIS_ENABLED", "false")
        completed = _run([str(python), str(runner)], cwd=repo, env=env, timeout=timeout)
        if completed.returncode != 0 or not output.exists():
            raise RuntimeError(
                f"TradingAgents-CN exited {completed.returncode}: "
                f"{completed.stderr[-3000:]}"
            )
        payload = json.loads(output.read_text(encoding="utf-8"))
        payload.update(
            {
                "source": "TradingAgents-CN",
                "upstream_ref": ref,
                "role": "debate_reference",
                "license_note": "User is responsible for complying with upstream personal/commercial licensing terms.",
            }
        )
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"enabled": True, "success": True, "ref": ref, "output": str(output)}
    except Exception as exc:
        return {"enabled": True, "success": False, "ref": ref, "error": f"{type(exc).__name__}: {exc}"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行外部开源分析项目")
    parser.add_argument("--date", required=True, help="交易日期 YYYY-MM-DD")
    parser.add_argument("--root", default=".", help="项目根目录")
    parser.add_argument("--timeout", type=int, default=1800, help="每个项目最大运行秒数")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = Path(args.root).resolve()
    trade_date = date.fromisoformat(args.date)
    result = {
        "trade_date": trade_date.isoformat(),
        "daily_stock_analysis": run_daily_stock_analysis(root, trade_date, args.timeout),
        "tradingagents_cn": run_tradingagents_cn(root, trade_date, args.timeout),
    }
    diagnostics = root / "diagnostics" / "external_analyses.json"
    diagnostics.parent.mkdir(parents=True, exist_ok=True)
    diagnostics.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    failures = [
        item
        for item in result.values()
        if isinstance(item, dict) and item.get("enabled") and item.get("success") is False
    ]
    strict = _enabled("RADAR_EXTERNAL_ANALYSES_STRICT")
    return 1 if strict and failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
