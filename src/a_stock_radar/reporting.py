from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .guardrails import validate_report
from .models import ReportPayload, SectorState
from .storage import FileStore


def format_money(value: float | None) -> str:
    if value is None:
        return "数据不足"
    absolute = abs(value)
    sign = "-" if value < 0 else ""
    if absolute >= 1e12:
        return f"{sign}{absolute / 1e12:.2f}万亿元"
    if absolute >= 1e8:
        return f"{sign}{absolute / 1e8:.2f}亿元"
    if absolute >= 1e4:
        return f"{sign}{absolute / 1e4:.2f}万元"
    return f"{value:.2f}元"


def format_pct(value: float | None) -> str:
    return "数据不足" if value is None else f"{value:.2%}"


def format_percentile(value: float | None) -> str:
    return "样本不足" if value is None else f"{value:.0f}%"


def group_states(states: list[SectorState]) -> dict[str, list[SectorState]]:
    groups: dict[str, list[SectorState]] = defaultdict(list)
    for state in states:
        groups[state.state_label].append(state)
    preferred = [
        "多证据参与增强",
        "配置型资金改善",
        "杠杆主导活跃",
        "成交情绪脉冲",
        "多证据分歧",
        "参与度收缩",
        "中性观察",
        "数据不足",
    ]
    return {label: groups[label] for label in preferred if groups.get(label)}


class ReportRenderer:
    def __init__(self, template_dir: Path):
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters.update(
            money=format_money,
            pct=format_pct,
            percentile=format_percentile,
        )

    def render(self, payload: ReportPayload) -> tuple[str, str]:
        context: dict[str, Any] = {
            "report": payload,
            "groups": group_states(payload.sector_states),
        }
        markdown = self.env.get_template("report.md.j2").render(**context)
        html = self.env.get_template("index.html.j2").render(**context)
        errors = validate_report(markdown)
        if errors:
            raise ValueError("Report guardrail validation failed: " + "; ".join(errors))
        return markdown, html

    def save(self, payload: ReportPayload, markdown: str, html: str, root: Path) -> None:
        store = FileStore(root)
        day_dir = root / "reports" / "daily"
        latest_dir = root / "reports" / "latest"
        site_dir = root / "site"
        api_dir = site_dir / "api" / "v3"
        day_dir.mkdir(parents=True, exist_ok=True)
        latest_dir.mkdir(parents=True, exist_ok=True)
        api_dir.mkdir(parents=True, exist_ok=True)

        stem = f"{payload.trade_date}_{payload.report_stage}"
        (day_dir / f"{stem}.md").write_text(markdown, encoding="utf-8")
        (latest_dir / "latest.md").write_text(markdown, encoding="utf-8")
        (site_dir / "index.html").write_text(html, encoding="utf-8")
        (site_dir / "report.md").write_text(markdown, encoding="utf-8")
        (site_dir / ".nojekyll").write_text("", encoding="utf-8")

        serialized = payload.model_dump(mode="json")
        store.write_json(latest_dir / "latest.json", serialized)
        store.write_json(api_dir / "latest.json", serialized)
        store.write_json(api_dir / "market-state.json", payload.market_state.model_dump(mode="json"))
        store.write_json(
            api_dir / "sector-states.json",
            [item.model_dump(mode="json") for item in payload.sector_states],
        )
        store.write_json(
            api_dir / "source-quality.json",
            [item.model_dump(mode="json") for item in payload.source_quality],
        )
        store.write_json(api_dir / "glossary.json", payload.glossary)
