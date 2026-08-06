from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .models import SourceQuality
from .product_io import (
    first_column,
    labels,
    normalize_kaipanla,
    number,
    read_analysis,
    read_table,
    resolve_product_path,
    write_frame,
    write_json,
)
from .sources import SourceBundle


def _quality(
    source_id: str,
    display_name: str,
    trade_date: date,
    frame: pd.DataFrame,
    evidence_level: str,
    *,
    available: bool | None = None,
    error: str | None = None,
) -> SourceQuality:
    is_available = not frame.empty if available is None else available
    return SourceQuality(
        source_id=source_id,
        display_name=display_name,
        trade_date=trade_date,
        available=is_available,
        expected_date=trade_date,
        actual_date=trade_date if is_available else None,
        freshness_ok=is_available,
        schema_ok=is_available,
        row_count=len(frame),
        official=False,
        evidence_level=evidence_level,  # type: ignore[arg-type]
        error_message=error,
    )


def _eastmoney_facts(
    detail: pd.DataFrame,
    institution: pd.DataFrame,
    trade_date: date,
) -> list[dict[str, Any]]:
    institution_by_code: dict[str, dict[str, Any]] = {}
    if not institution.empty and "代码" in institution:
        for _, row in institution.iterrows():
            institution_by_code[str(row.get("代码", "")).zfill(6)] = row.to_dict()
    result: list[dict[str, Any]] = []
    for index, row in detail.reset_index(drop=True).iterrows():
        code = str(row.get("代码", "")).zfill(6)
        if len(code) != 6 or not code.isdigit():
            continue
        inst = institution_by_code.get(code, {})
        buyer_count = int(number(inst.get("买方机构数")) or 0)
        seller_count = int(number(inst.get("卖方机构数")) or 0)
        result.append(
            {
                "fact_id": f"eastmoney:{trade_date}:{code}:{index}",
                "security_code": code,
                "security_name": str(row.get("名称") or "").strip() or None,
                "fact_type": str(row.get("上榜原因") or "龙虎榜上榜"),
                "buyer_labels": [f"机构专用×{buyer_count}"] if buyer_count else [],
                "seller_labels": [f"机构专用×{seller_count}"] if seller_count else [],
                "net_amount": number(row.get("龙虎榜净买额")),
                "source_id": "eastmoney_lhb",
                "source_date": str(row.get("上榜日") or trade_date),
                "official": False,
                "limitations": [
                    "东方财富为交易所龙虎榜披露的结构化整理来源。",
                    "营业部、机构专用或交易单元不等于最终投资者。",
                    "历史后续表现不是当前席位的未来承诺。",
                ],
            }
        )
    return result


def _cls_facts(frame: pd.DataFrame, trade_date: date) -> list[dict[str, Any]]:
    code_column = first_column(frame, ("security_code", "code", "股票代码", "代码"))
    if frame.empty or not code_column:
        return []
    name_column = first_column(frame, ("security_name", "name", "股票简称", "名称"))
    title_column = first_column(frame, ("title", "headline", "标题", "事实类型"))
    net_column = first_column(frame, ("net_amount", "机构净买额", "净买额"))
    buy_column = first_column(frame, ("buyer_labels", "买方席位", "买方标签"))
    sell_column = first_column(frame, ("seller_labels", "卖方席位", "卖方标签"))
    result: list[dict[str, Any]] = []
    for index, row in frame.reset_index(drop=True).iterrows():
        raw_code = "".join(character for character in str(row.get(code_column, "")) if character.isdigit())
        code = raw_code[-6:]
        if len(code) != 6:
            continue
        result.append(
            {
                "fact_id": f"cls:{trade_date}:{code}:{index}",
                "security_code": code,
                "security_name": str(row.get(name_column) or "").strip() or None,
                "fact_type": str(row.get(title_column) or "财联社龙虎榜快讯"),
                "buyer_labels": labels(row.get(buy_column)) if buy_column else [],
                "seller_labels": labels(row.get(sell_column)) if sell_column else [],
                "net_amount": number(row.get(net_column)) if net_column else None,
                "source_id": "cls_lhb_authorized",
                "source_date": trade_date.isoformat(),
                "official": False,
                "limitations": [
                    "只读取用户提供的财联社授权导出或授权端点产物。",
                    "快讯用于交叉核实，不覆盖东方财富结构化明细。",
                ],
            }
        )
    return result


def _dde_summary(frame: pd.DataFrame, trade_date: date) -> dict[str, Any] | None:
    net_column = first_column(
        frame,
        ("dde_net_amount", "dde净额", "大单净额", "超大单净额", "主力净额"),
    )
    amount_column = first_column(frame, ("amount", "turnover", "成交额", "成交金额"))
    if frame.empty or not net_column or not amount_column:
        return None
    net = frame[net_column].map(number)
    amount = frame[amount_column].map(number)
    valid = net.notna() & amount.notna() & (amount > 0)
    if not valid.any():
        return None
    total = float(amount[valid].sum())
    return {
        "trade_date": trade_date.isoformat(),
        "source_id": "dazhihui_dde_ace",
        "symbol_count": int(valid.sum()),
        "confirmed_symbol_count": int(valid.sum()),
        "provisional_symbol_count": 0,
        "total_notional": total,
        "signed_notional_imbalance": float(net[valid].sum()) / total if total else None,
        "classification_coverage": float(valid.mean()),
        "closing_auction_notional_share": None,
        "limitations": [
            "DDE/ACE来自大智慧产品导出或授权接口，取决于用户订阅权限。",
            "订单规模分类不等于具体交易者身份。",
            "DDE净额是产品口径下的大单差，不是市场资金净流入。",
        ],
    }


class ProductSourceProvider:
    """Curated sources only; private product interfaces are never reverse engineered."""

    def __init__(
        self,
        root: Path,
        source_config: dict[str, Any] | None = None,
        *,
        ak_module: Any | None = None,
    ):
        self.root = root
        config = source_config or {}
        self.products = config.get("products") or config.get("sources") or config
        if ak_module is not None:
            self.ak = ak_module
        else:
            try:
                import akshare as ak
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("akshare is required for Eastmoney LHB adapters") from exc
            self.ak = ak

    def _safe_ak(self, name: str, **kwargs: Any) -> tuple[pd.DataFrame, str | None]:
        function = getattr(self.ak, name, None)
        if function is None:
            return pd.DataFrame(), f"AKShare does not expose {name}"
        try:
            frame = function(**kwargs)
            return (frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()), None
        except Exception as exc:
            return pd.DataFrame(), f"{type(exc).__name__}: {exc}"

    def _path(
        self,
        trade_date: date,
        key: str,
        default_dir: str,
        env_name: str,
    ) -> Path | None:
        return resolve_product_path(
            self.root,
            trade_date,
            self.products.get(key) or {},
            default_dir,
            env_name,
        )

    def fetch(self, trade_date: date) -> SourceBundle:
        directory = (
            self.root
            / "data"
            / "raw"
            / "product_sources"
            / f"date={trade_date.strftime('%Y%m%d')}"
        )
        directory.mkdir(parents=True, exist_ok=True)
        qualities: list[SourceQuality] = []

        kpl_raw, kpl_error = read_table(
            self._path(
                trade_date,
                "kaipanla",
                "imports/kaipanla",
                "RADAR_KAIPANLA_EXPORT",
            )
        )
        market = normalize_kaipanla(kpl_raw, trade_date)
        if not kpl_raw.empty:
            write_frame(directory / "kaipanla_export.csv", kpl_raw)
        if not kpl_raw.empty and market.empty:
            kpl_error = "开盘啦导出缺少代码、名称、价格、涨跌幅或成交额字段"
        qualities.append(
            _quality(
                "kaipanla_review",
                "开盘啦每日复盘与市场概况",
                trade_date,
                market,
                "L2",
                error=kpl_error,
            )
        )

        day = trade_date.strftime("%Y%m%d")
        calls = {
            "eastmoney_lhb_detail.csv": (
                "stock_lhb_detail_em",
                {"start_date": day, "end_date": day},
            ),
            "eastmoney_lhb_institution.csv": (
                "stock_lhb_jgmmtj_em",
                {"start_date": day, "end_date": day},
            ),
            "eastmoney_lhb_active_departments.csv": (
                "stock_lhb_hyyyb_em",
                {"start_date": day, "end_date": day},
            ),
            "eastmoney_department_followup.csv": (
                "stock_lhb_yybph_em",
                {"symbol": "近一年"},
            ),
            "eastmoney_department_style.csv": (
                "stock_lhb_traderstatistic_em",
                {"symbol": "近一年"},
            ),
        }
        fetched: dict[str, pd.DataFrame] = {}
        errors: dict[str, str | None] = {}
        for filename, (function, kwargs) in calls.items():
            frame, error = self._safe_ak(function, **kwargs)
            fetched[function] = frame
            errors[function] = error
            if not frame.empty:
                write_frame(directory / filename, frame)
        source_definitions = [
            ("eastmoney_lhb", "东方财富龙虎榜详情", "stock_lhb_detail_em", "L2"),
            (
                "eastmoney_lhb_institution",
                "东方财富机构买卖每日统计",
                "stock_lhb_jgmmtj_em",
                "L2",
            ),
            (
                "eastmoney_lhb_departments",
                "东方财富每日活跃营业部",
                "stock_lhb_hyyyb_em",
                "L2",
            ),
            (
                "eastmoney_department_followup",
                "东方财富营业部历史后续表现",
                "stock_lhb_yybph_em",
                "L3",
            ),
            (
                "eastmoney_department_style",
                "东方财富营业部历史交易统计",
                "stock_lhb_traderstatistic_em",
                "L3",
            ),
        ]
        for source_id, display_name, function, level in source_definitions:
            qualities.append(
                _quality(
                    source_id,
                    display_name,
                    trade_date,
                    fetched[function],
                    level,
                    error=errors[function],
                )
            )
        seat_facts = _eastmoney_facts(
            fetched["stock_lhb_detail_em"],
            fetched["stock_lhb_jgmmtj_em"],
            trade_date,
        )

        cls_frame, cls_error = read_table(
            self._path(trade_date, "cls", "imports/cls", "RADAR_CLS_LHB_EXPORT")
        )
        cls_facts = _cls_facts(cls_frame, trade_date)
        if not cls_frame.empty:
            write_frame(directory / "cls_lhb_authorized.csv", cls_frame)
        seat_facts.extend(cls_facts)
        qualities.append(
            _quality(
                "cls_lhb_authorized",
                "财联社龙虎榜授权导出",
                trade_date,
                cls_frame,
                "L2",
                available=bool(cls_facts),
                error=cls_error if not cls_facts else None,
            )
        )
        write_json(directory / "seat_facts.json", seat_facts)

        dzh_frame, dzh_error = read_table(
            self._path(
                trade_date,
                "dazhihui",
                "imports/dazhihui",
                "RADAR_DAZHIHUI_DDE_EXPORT",
            )
        )
        dde = _dde_summary(dzh_frame, trade_date)
        if not dzh_frame.empty:
            write_frame(directory / "dazhihui_dde_ace.csv", dzh_frame)
        if dde:
            write_json(directory / "dde_summary.json", dde)
        qualities.append(
            _quality(
                "dazhihui_dde_ace",
                "大智慧DDE/ACE授权数据",
                trade_date,
                dzh_frame,
                "L3",
                available=dde is not None,
                error=dzh_error if dde is None else None,
            )
        )

        analyses: list[dict[str, Any]] = []
        external = [
            (
                "daily_stock_analysis",
                "daily_stock_analysis自动日报",
                "imports/daily_stock_analysis",
                "RADAR_DAILY_STOCK_ANALYSIS_ARTIFACT",
                "report_architecture",
            ),
            (
                "tradingagents_cn",
                "TradingAgents-CN多空辩论",
                "imports/tradingagents_cn",
                "RADAR_TRADINGAGENTS_CN_ARTIFACT",
                "debate_reference",
            ),
        ]
        for source_id, display_name, default_dir, env_name, role in external:
            artifact, artifact_error = read_analysis(
                self._path(trade_date, source_id, default_dir, env_name)
            )
            if artifact:
                artifact.update(
                    {
                        "source_id": source_id,
                        "display_name": display_name,
                        "role": role,
                        "trade_date": trade_date.isoformat(),
                    }
                )
                analyses.append(artifact)
            frame = pd.DataFrame([artifact]) if artifact else pd.DataFrame()
            qualities.append(
                _quality(
                    source_id,
                    display_name,
                    trade_date,
                    frame,
                    "L4",
                    available=artifact is not None,
                    error=artifact_error,
                )
            )
        write_json(directory / "external_analyses.json", analyses)
        write_json(
            directory / "manifest.json",
            {
                "trade_date": trade_date.isoformat(),
                "strategy": "curated_products",
                "generated_at": datetime.now(UTC).isoformat(),
                "sources": [item.model_dump(mode="json") for item in qualities],
                "rules": [
                    "开盘啦缺失时不回退到腾讯、新浪或自建行情。",
                    "东方财富龙虎榜通过AKShare现成适配器获取。",
                    "大智慧与财联社只接受官方导出或授权产物。",
                    "两个开源项目只作为报告和辩论参考，不作为事实源。",
                ],
            },
        )
        return SourceBundle(
            market=market,
            etf=pd.DataFrame(),
            margin=pd.DataFrame(),
            margin_detail=pd.DataFrame(),
            qualities=qualities,
            data_mode="curated",
        )
