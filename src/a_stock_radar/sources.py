from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Callable

import numpy as np
import pandas as pd

from .models import SourceQuality
from .taxonomy import ThemeMapper


@dataclass
class SourceBundle:
    market: pd.DataFrame
    etf: pd.DataFrame
    margin: pd.DataFrame
    margin_detail: pd.DataFrame
    qualities: list[SourceQuality]
    data_mode: str


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype(str).str.replace(",", "", regex=False), errors="coerce")


def _quality(
    source_id: str,
    display_name: str,
    trade_date: date,
    available: bool,
    row_count: int,
    official: bool,
    evidence_level: str,
    actual_date: date | None = None,
    error: str | None = None,
) -> SourceQuality:
    freshness_ok = actual_date == trade_date if actual_date else available
    return SourceQuality(
        source_id=source_id,
        display_name=display_name,
        trade_date=trade_date,
        available=available,
        expected_date=trade_date,
        actual_date=actual_date,
        freshness_ok=freshness_ok,
        schema_ok=available and row_count > 0,
        row_count=row_count,
        official=official,
        evidence_level=evidence_level,  # type: ignore[arg-type]
        error_message=error,
    )


class AkshareProvider:
    """Live adapter. Each source fails independently and returns explicit quality metadata."""

    def __init__(self, theme_mapper: ThemeMapper):
        self.theme_mapper = theme_mapper
        try:
            import akshare as ak
        except ImportError as exc:  # pragma: no cover - installation issue
            raise RuntimeError("akshare is required for live mode") from exc
        self.ak = ak

    def _safe(self, fn: Callable[[], pd.DataFrame]) -> tuple[pd.DataFrame, str | None]:
        try:
            frame = fn()
            if frame is None:
                return pd.DataFrame(), "source returned None"
            return frame, None
        except Exception as exc:  # network and upstream schema errors must not crash the report
            return pd.DataFrame(), f"{type(exc).__name__}: {exc}"

    def fetch(self, trade_date: date) -> SourceBundle:
        qualities: list[SourceQuality] = []
        market, market_error = self._safe(self.ak.stock_zh_a_spot_em)
        market_norm = self._normalize_market(market, trade_date)
        qualities.append(
            _quality(
                "market_spot",
                "A股实时行情聚合",
                trade_date,
                not market_norm.empty,
                len(market_norm),
                False,
                "L2",
                trade_date if not market_norm.empty else None,
                market_error,
            )
        )

        etf_spot, etf_spot_error = self._safe(self.ak.fund_etf_spot_em)
        sse_scale, sse_error = self._safe(
            lambda: self.ak.fund_etf_scale_sse(date=trade_date.strftime("%Y%m%d"))
        )
        szse_scale, szse_error = self._safe(
            lambda: self.ak.fund_scale_daily_szse(
                start_date=trade_date.strftime("%Y%m%d"),
                end_date=trade_date.strftime("%Y%m%d"),
                symbol="ETF",
            )
        )
        etf_norm = self._normalize_etf(etf_spot, sse_scale, szse_scale, trade_date)
        qualities.extend(
            [
                _quality(
                    "etf_spot",
                    "ETF行情与IOPV聚合",
                    trade_date,
                    not etf_spot.empty,
                    len(etf_spot),
                    False,
                    "L2",
                    trade_date if not etf_spot.empty else None,
                    etf_spot_error,
                ),
                _quality(
                    "sse_etf_shares",
                    "上交所ETF基金份额",
                    trade_date,
                    not sse_scale.empty,
                    len(sse_scale),
                    True,
                    "L1",
                    trade_date if not sse_scale.empty else None,
                    sse_error,
                ),
                _quality(
                    "szse_etf_shares",
                    "深交所ETF基金份额",
                    trade_date,
                    not szse_scale.empty,
                    len(szse_scale),
                    True,
                    "L1",
                    trade_date if not szse_scale.empty else None,
                    szse_error,
                ),
            ]
        )

        date_text = trade_date.strftime("%Y%m%d")
        margin_sse, margin_sse_error = self._safe(
            lambda: self.ak.stock_margin_sse(start_date=date_text, end_date=date_text)
        )
        margin_szse, margin_szse_error = self._safe(lambda: self.ak.stock_margin_szse(date=date_text))
        detail_sse, detail_sse_error = self._safe(lambda: self.ak.stock_margin_detail_sse(date=date_text))
        detail_szse, detail_szse_error = self._safe(lambda: self.ak.stock_margin_detail_szse(date=date_text))
        margin_norm = self._normalize_margin(margin_sse, margin_szse, trade_date)
        detail_norm = self._normalize_margin_detail(detail_sse, detail_szse, trade_date)
        qualities.extend(
            [
                _quality(
                    "sse_margin",
                    "上交所融资融券汇总",
                    trade_date,
                    not margin_sse.empty,
                    len(margin_sse),
                    True,
                    "L1",
                    trade_date if not margin_sse.empty else None,
                    margin_sse_error,
                ),
                _quality(
                    "szse_margin",
                    "深交所融资融券汇总",
                    trade_date,
                    not margin_szse.empty,
                    len(margin_szse),
                    True,
                    "L1",
                    trade_date if not margin_szse.empty else None,
                    margin_szse_error,
                ),
                _quality(
                    "margin_detail",
                    "沪深融资融券明细",
                    trade_date,
                    not detail_norm.empty,
                    len(detail_norm),
                    True,
                    "L1",
                    trade_date if not detail_norm.empty else None,
                    "; ".join(filter(None, [detail_sse_error, detail_szse_error])) or None,
                ),
            ]
        )
        return SourceBundle(market_norm, etf_norm, margin_norm, detail_norm, qualities, "live")

    @staticmethod
    def _normalize_market(frame: pd.DataFrame, trade_date: date) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame()
        rename = {
            "代码": "security_code",
            "名称": "security_name",
            "最新价": "close",
            "涨跌幅": "pct_change",
            "成交额": "amount",
            "流通市值": "float_market_cap",
            "换手率": "turnover_rate",
        }
        result = frame.rename(columns=rename)
        required = ["security_code", "security_name", "close", "pct_change", "amount"]
        if any(column not in result for column in required):
            return pd.DataFrame()
        result = result[[c for c in [*required, "float_market_cap", "turnover_rate"] if c in result]].copy()
        result["security_code"] = result["security_code"].astype(str).str.zfill(6)
        for column in ["close", "pct_change", "amount", "float_market_cap", "turnover_rate"]:
            if column in result:
                result[column] = _numeric(result[column])
        result["trade_date"] = trade_date
        result["source_id"] = "market_spot"
        return result.dropna(subset=["security_code", "pct_change"])

    def _normalize_etf(
        self,
        spot: pd.DataFrame,
        sse_scale: pd.DataFrame,
        szse_scale: pd.DataFrame,
        trade_date: date,
    ) -> pd.DataFrame:
        pieces: list[pd.DataFrame] = []
        if not sse_scale.empty and {"基金代码", "基金简称", "基金份额"}.issubset(sse_scale.columns):
            sse = sse_scale.rename(
                columns={"基金代码": "fund_code", "基金简称": "fund_name", "基金份额": "total_shares"}
            )[["fund_code", "fund_name", "total_shares"]].copy()
            sse["total_shares"] = _numeric(sse["total_shares"]) * 10000.0
            sse["share_source_id"] = "sse_etf_shares"
            sse["share_is_official"] = True
            pieces.append(sse)
        if not szse_scale.empty and {"基金代码", "基金简称", "基金份额"}.issubset(szse_scale.columns):
            sz = szse_scale.rename(
                columns={"基金代码": "fund_code", "基金简称": "fund_name", "基金份额": "total_shares"}
            )[["fund_code", "fund_name", "total_shares"]].copy()
            sz["total_shares"] = _numeric(sz["total_shares"])
            sz["share_source_id"] = "szse_etf_shares"
            sz["share_is_official"] = True
            pieces.append(sz)
        shares = pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()

        spot_norm = pd.DataFrame()
        if not spot.empty and {"代码", "名称"}.issubset(spot.columns):
            spot_norm = spot.rename(
                columns={
                    "代码": "fund_code",
                    "名称": "fund_name_spot",
                    "最新价": "price",
                    "IOPV实时估值": "nav_proxy",
                    "成交额": "amount",
                    "最新份额": "spot_shares",
                    "基金折价率": "discount_rate",
                }
            )
            wanted = [
                "fund_code",
                "fund_name_spot",
                "price",
                "nav_proxy",
                "amount",
                "spot_shares",
                "discount_rate",
            ]
            spot_norm = spot_norm[[c for c in wanted if c in spot_norm]].copy()
            for column in ["price", "nav_proxy", "amount", "spot_shares", "discount_rate"]:
                if column in spot_norm:
                    spot_norm[column] = _numeric(spot_norm[column])

        if shares.empty and spot_norm.empty:
            return pd.DataFrame()
        if shares.empty:
            result = spot_norm.rename(columns={"fund_name_spot": "fund_name", "spot_shares": "total_shares"})
            result["share_source_id"] = "etf_spot"
            result["share_is_official"] = False
        elif spot_norm.empty:
            result = shares
        else:
            result = shares.merge(spot_norm, on="fund_code", how="outer")
            result["fund_name"] = result["fund_name"].fillna(result.get("fund_name_spot"))
            if "total_shares" not in result:
                result["total_shares"] = result.get("spot_shares")
            else:
                result["total_shares"] = result["total_shares"].fillna(result.get("spot_shares"))
            result["share_source_id"] = result["share_source_id"].fillna("etf_spot")
            result["share_is_official"] = result["share_is_official"].fillna(False)
        result["fund_code"] = result["fund_code"].astype(str).str.zfill(6)
        for column in ["price", "nav_proxy", "amount", "discount_rate"]:
            if column not in result:
                result[column] = np.nan
        result["nav"] = result["nav_proxy"].fillna(result["price"])
        result["nav_is_proxy"] = True
        mapped = result["fund_name"].fillna("").map(self.theme_mapper.map_name)
        result["theme_id"] = mapped.map(lambda item: item.theme_id)
        result["theme_name"] = mapped.map(lambda item: item.theme_name)
        result["trade_date"] = trade_date
        result["source_id"] = result["share_source_id"]
        keep = [
            "trade_date",
            "fund_code",
            "fund_name",
            "theme_id",
            "theme_name",
            "total_shares",
            "nav",
            "price",
            "amount",
            "discount_rate",
            "share_source_id",
            "share_is_official",
            "nav_is_proxy",
            "source_id",
        ]
        for column in keep:
            if column not in result:
                result[column] = np.nan
        return result[keep].dropna(subset=["fund_code", "total_shares"])

    @staticmethod
    def _normalize_margin(sse: pd.DataFrame, szse: pd.DataFrame, trade_date: date) -> pd.DataFrame:
        rows = []
        if not sse.empty:
            row = sse.iloc[-1]
            rows.append(
                {
                    "trade_date": trade_date,
                    "market": "SSE",
                    "financing_balance": float(row.get("融资余额", np.nan)),
                    "financing_buy": float(row.get("融资买入额", np.nan)),
                    "securities_lending_balance": float(row.get("融券余量金额", np.nan)),
                    "margin_total": float(row.get("融资融券余额", np.nan)),
                    "source_id": "sse_margin",
                }
            )
        if not szse.empty:
            row = szse.iloc[-1]
            rows.append(
                {
                    "trade_date": trade_date,
                    "market": "SZSE",
                    "financing_balance": float(row.get("融资余额", np.nan)),
                    "financing_buy": float(row.get("融资买入额", np.nan)),
                    "securities_lending_balance": float(row.get("融券余额", np.nan)),
                    "margin_total": float(row.get("融资融券余额", np.nan)),
                    "source_id": "szse_margin",
                }
            )
        return pd.DataFrame(rows)

    @staticmethod
    def _normalize_margin_detail(sse: pd.DataFrame, szse: pd.DataFrame, trade_date: date) -> pd.DataFrame:
        frames = []
        for market, frame in [("SSE", sse), ("SZSE", szse)]:
            if frame.empty:
                continue
            renamed = frame.rename(
                columns={
                    "标的证券代码": "security_code",
                    "证券代码": "security_code",
                    "标的证券简称": "security_name",
                    "证券简称": "security_name",
                    "融资余额": "financing_balance",
                    "融资买入额": "financing_buy",
                    "融资偿还额": "financing_repayment",
                }
            )
            required = ["security_code", "security_name", "financing_balance", "financing_buy"]
            if not all(c in renamed for c in required):
                continue
            normalized = renamed[[c for c in [*required, "financing_repayment"] if c in renamed]].copy()
            normalized["security_code"] = normalized["security_code"].astype(str).str.zfill(6)
            for column in ["financing_balance", "financing_buy", "financing_repayment"]:
                if column in normalized:
                    normalized[column] = _numeric(normalized[column])
            normalized["trade_date"] = trade_date
            normalized["market"] = market
            normalized["source_id"] = "margin_detail"
            frames.append(normalized)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


class MockProvider:
    """Deterministic demo source. Every output is visibly marked as demo."""

    FUNDS = [
        ("510300", "沪深300ETF", "broad_market", "宽基指数"),
        ("588000", "科创50ETF", "broad_market", "宽基指数"),
        ("512480", "半导体ETF", "semiconductor", "半导体与芯片"),
        ("159995", "芯片ETF", "semiconductor", "半导体与芯片"),
        ("515790", "光伏ETF", "new_energy", "新能源"),
        ("159992", "创新药ETF", "healthcare", "医药医疗"),
        ("512000", "券商ETF", "finance", "金融"),
        ("512660", "军工ETF", "defense", "军工"),
    ]

    SECURITIES = [
        ("600000", "浦发银行", "finance", "金融"),
        ("601398", "工商银行", "finance", "金融"),
        ("000001", "平安银行", "finance", "金融"),
        ("600519", "贵州茅台", "consumption", "消费"),
        ("000858", "五粮液", "consumption", "消费"),
        ("600276", "恒瑞医药", "healthcare", "医药医疗"),
        ("300760", "迈瑞医疗", "healthcare", "医药医疗"),
        ("688981", "中芯国际", "semiconductor", "半导体与芯片"),
        ("002371", "北方华创", "semiconductor", "半导体与芯片"),
        ("300750", "宁德时代", "new_energy", "新能源"),
        ("601012", "隆基绿能", "new_energy", "新能源"),
        ("600893", "航发动力", "defense", "军工"),
    ]

    def __init__(self, seed: int = 20260720):
        self.seed = seed

    def fetch(self, trade_date: date) -> SourceBundle:
        rng = np.random.default_rng(self.seed + trade_date.toordinal())
        market = self._market(trade_date, rng)
        etf = self._etf(trade_date, rng)
        margin, detail = self._margin(trade_date, rng)
        qualities = [
            _quality("mock_market", "演示市场数据", trade_date, True, len(market), False, "L2", trade_date),
            _quality("mock_etf", "演示ETF数据", trade_date, True, len(etf), False, "L1", trade_date),
            _quality("mock_margin", "演示融资数据", trade_date, True, len(margin), False, "L1", trade_date),
            _quality("mock_margin_detail", "演示融资明细", trade_date, True, len(detail), False, "L1", trade_date),
        ]
        return SourceBundle(market, etf, margin, detail, qualities, "mock")

    def seed_history(self, end_date: date, periods: int = 260) -> dict[str, pd.DataFrame]:
        dates = pd.bdate_range(end=end_date, periods=periods).date
        market_rows = []
        etf_frames = []
        margin_frames = []
        detail_frames = []
        for current_date in dates:
            rng = np.random.default_rng(self.seed + current_date.toordinal())
            market = self._market(current_date, rng)
            pct = pd.to_numeric(market["pct_change"], errors="coerce").dropna()
            caps = pd.to_numeric(market["float_market_cap"], errors="coerce")
            market_rows.append(
                {
                    "trade_date": current_date,
                    "total_amount": float(pd.to_numeric(market["amount"], errors="coerce").sum()),
                    "advancers": int((pct > 0).sum()),
                    "decliners": int((pct < 0).sum()),
                    "unchanged": int((pct == 0).sum()),
                    "breadth_ratio": float((pct > 0).mean()),
                    "median_return": float(pct.median()),
                    "cap_weighted_return": float(np.average(pct, weights=caps)),
                    "limit_up_count": int((pct >= 9.5).sum()),
                    "limit_down_count": int((pct <= -9.5).sum()),
                }
            )
            etf_frames.append(self._etf(current_date, rng))
            margin, detail = self._margin(current_date, rng)
            margin_frames.append(margin)
            detail_frames.append(detail)
        return {
            "market_history": pd.DataFrame(market_rows),
            "etf_history": pd.concat(etf_frames, ignore_index=True),
            "margin_history": pd.concat(margin_frames, ignore_index=True),
            "margin_detail_history": pd.concat(detail_frames, ignore_index=True),
        }

    @staticmethod
    def _market(trade_date: date, rng: np.random.Generator) -> pd.DataFrame:
        day = (trade_date - date(2025, 1, 1)).days
        mean_return = 0.25 * math.sin(day / 19) + 0.08 * math.cos(day / 7)
        pct = rng.normal(mean_return, 1.7, 600)
        return pd.DataFrame(
            {
                "trade_date": trade_date,
                "security_code": [f"{i:06d}" for i in range(1, 601)],
                "security_name": [f"演示证券{i}" for i in range(1, 601)],
                "close": rng.uniform(3, 120, 600),
                "pct_change": pct,
                "amount": rng.lognormal(19.4 + 0.08 * math.sin(day / 23), 0.8, 600),
                "float_market_cap": rng.lognormal(22.5, 1.0, 600),
                "turnover_rate": rng.uniform(0.2, 8, 600),
                "source_id": "mock_market",
            }
        )

    def _etf(self, trade_date: date, rng: np.random.Generator) -> pd.DataFrame:
        rows = []
        day = (trade_date - date(2025, 1, 1)).days
        for idx, (code, name, theme_id, theme_name) in enumerate(self.FUNDS):
            base = 1.5e9 + idx * 2e8
            daily_drift = {
                "semiconductor": 0.00055,
                "new_energy": -0.00018,
                "healthcare": 0.00008,
                "finance": 0.00020,
                "defense": -0.00003,
                "broad_market": 0.00010,
            }.get(theme_id, 0.0)
            cycle = 0.018 * math.sin((day + idx * 9) / (17 + idx))
            shares = base * math.exp(daily_drift * day + cycle)
            nav = max(0.45, 1.0 + 0.08 * math.sin((day + idx * 5) / (24 + idx)) + idx * 0.035)
            price = nav * (1 + rng.normal(0, 0.0015))
            rows.append(
                {
                    "trade_date": trade_date,
                    "fund_code": code,
                    "fund_name": name,
                    "theme_id": theme_id,
                    "theme_name": theme_name,
                    "total_shares": shares * (1 + rng.normal(0, 0.00035)),
                    "nav": nav,
                    "price": price,
                    "amount": float(rng.lognormal(19.8 + 0.12 * math.sin(day / 15), 0.5)),
                    "discount_rate": (price / nav - 1) * 100,
                    "share_source_id": "mock_etf",
                    "share_is_official": False,
                    "nav_is_proxy": False,
                    "source_id": "mock_etf",
                }
            )
        return pd.DataFrame(rows)

    def _margin(self, trade_date: date, rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
        day = (trade_date - date(2025, 1, 1)).days
        market_rows = []
        for market, base, daily_drift in [("SSE", 8e11, 0.00012), ("SZSE", 7e11, 0.00015)]:
            balance = base * math.exp(daily_drift * day + 0.012 * math.sin(day / 21))
            market_rows.append(
                {
                    "trade_date": trade_date,
                    "market": market,
                    "financing_balance": balance * (1 + rng.normal(0, 0.00025)),
                    "financing_buy": balance * (0.042 + 0.004 * math.sin(day / 11)),
                    "securities_lending_balance": balance * 0.003,
                    "margin_total": balance * 1.003,
                    "source_id": "mock_margin",
                }
            )
        detail = []
        for idx, (code, name, theme_id, theme_name) in enumerate(self.SECURITIES):
            daily_drift = {
                "semiconductor": 0.00042,
                "new_energy": -0.00020,
                "finance": 0.00018,
                "healthcare": 0.00004,
                "consumption": -0.00002,
                "defense": 0.00010,
            }.get(theme_id, 0.0)
            base = 1e9 + idx * 1e8
            balance = base * math.exp(daily_drift * day + 0.014 * math.sin((day + idx) / 19))
            detail.append(
                {
                    "trade_date": trade_date,
                    "security_code": code,
                    "security_name": name,
                    "financing_balance": balance * (1 + rng.normal(0, 0.0004)),
                    "financing_buy": balance * 0.04,
                    "financing_repayment": np.nan,
                    "market": "SSE" if code.startswith("6") else "SZSE",
                    "source_id": "mock_margin_detail",
                    "theme_id": theme_id,
                    "theme_name": theme_name,
                }
            )
        return pd.DataFrame(market_rows), pd.DataFrame(detail)


class UnavailableProvider:
    """Produces an honest data-insufficient payload when live adapters are unavailable."""

    def __init__(self, error_message: str):
        self.error_message = error_message

    def fetch(self, trade_date: date) -> SourceBundle:
        q = [
            _quality(
                "live_sources",
                "实时数据源",
                trade_date,
                False,
                0,
                False,
                "L1",
                None,
                self.error_message,
            )
        ]
        return SourceBundle(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), q, "unavailable")
