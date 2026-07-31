from __future__ import annotations

import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd
import requests


MARKET_COLUMNS = [
    "代码",
    "名称",
    "最新价",
    "涨跌幅",
    "成交额",
    "流通市值",
    "换手率",
]


@dataclass(frozen=True)
class MarketSourceAttempt:
    source_id: str
    display_name: str
    frame: pd.DataFrame
    error: str | None = None
    expected_rows: int | None = None

    @property
    def complete(self) -> bool:
        if self.frame.empty or "代码" not in self.frame:
            return False
        expected = self.expected_rows
        if not expected:
            return len(self.frame) >= 5000
        return self.frame["代码"].nunique() >= math.ceil(expected * 0.99)


@dataclass(frozen=True)
class MarketAggregateResult:
    frame: pd.DataFrame
    attempts: tuple[MarketSourceAttempt, ...]


class TencentMarketAdapter:
    """Fetch the Shanghai, Shenzhen and Beijing stock snapshot from Tencent."""

    URL = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList"

    def __init__(
        self,
        session: requests.Session | None = None,
        page_size: int | None = None,
        timeout: float | None = None,
        retries: int | None = None,
        retry_delay: float | None = None,
    ) -> None:
        self.session = session or requests.Session()
        self.page_size = page_size or int(os.getenv("RADAR_TENCENT_PAGE_SIZE", "200"))
        self.timeout = timeout or float(os.getenv("RADAR_TENCENT_TIMEOUT", "15"))
        self.retries = retries or int(os.getenv("RADAR_TENCENT_RETRIES", "3"))
        self.retry_delay = retry_delay or float(os.getenv("RADAR_TENCENT_RETRY_DELAY", "0.4"))
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (compatible; a-stock-evidence-radar/1.0)",
                "Referer": "https://stockapp.finance.qq.com/",
            }
        )

    def _request_page(self, offset: int) -> dict[str, Any]:
        params = {
            "_appver": "11.17.0",
            "board_code": "aStock",
            "sort_type": "price",
            "direct": "down",
            "offset": str(offset),
            "count": str(self.page_size),
        }
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = self.session.get(self.URL, params=params, timeout=self.timeout)
                response.raise_for_status()
                payload = response.json()
                if int(payload.get("code", 0)) != 0:
                    message = payload.get("msg") or payload.get("message")
                    raise RuntimeError(f"Tencent API error: {message}")
                data = payload.get("data")
                if not isinstance(data, dict):
                    raise ValueError("Tencent response has no data object")
                return data
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(self.retry_delay * (attempt + 1))
        assert last_error is not None
        raise last_error

    def fetch_market_spot(self) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        expected_rows: int | None = None
        page_count: int | None = None
        seen_page_signatures: set[tuple[str, ...]] = set()

        for page in range(100):
            data = self._request_page(page * self.page_size)
            if expected_rows is None:
                expected_rows = int(data.get("total") or 0)
                if expected_rows <= 0:
                    raise ValueError("Tencent returned an invalid total")
                page_count = math.ceil(expected_rows / self.page_size)
            page_rows = data.get("rank_list") or []
            if not isinstance(page_rows, list):
                raise ValueError("Tencent rank_list is not a list")
            signature = tuple(str(item.get("code") or "") for item in page_rows)
            if signature in seen_page_signatures and signature:
                offset = page * self.page_size
                raise RuntimeError(f"Tencent repeated page at offset {offset}")
            seen_page_signatures.add(signature)
            rows.extend(item for item in page_rows if isinstance(item, dict))
            if page + 1 >= (page_count or 0):
                break
            if not page_rows:
                offset = page * self.page_size
                raise RuntimeError(f"Tencent returned an empty page at offset {offset}")

        frame = self._normalize(rows)
        unique_rows = frame["代码"].nunique() if not frame.empty else 0
        required = math.ceil((expected_rows or 0) * 0.99)
        if expected_rows and unique_rows < required:
            raise RuntimeError(
                f"Tencent snapshot incomplete: got {unique_rows}/{expected_rows} unique securities"
            )
        frame.attrs["expected_rows"] = expected_rows
        frame.attrs["source_id"] = "market_tencent"
        return frame

    @staticmethod
    def _normalize(rows: list[dict[str, Any]]) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame(columns=[*MARKET_COLUMNS, "source_id"])
        frame = pd.DataFrame(rows).rename(
            columns={
                "code": "代码",
                "name": "名称",
                "zxj": "最新价",
                "zdf": "涨跌幅",
                "turnover": "成交额",
                "ltsz": "流通市值",
                "hsl": "换手率",
            }
        )
        required = ["代码", "名称", "最新价", "涨跌幅", "成交额"]
        missing = [column for column in required if column not in frame]
        if missing:
            raise ValueError(f"Tencent response missing columns: {', '.join(missing)}")
        for column in ["最新价", "涨跌幅", "成交额", "流通市值", "换手率"]:
            if column in frame:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        # Tencent rank-list monetary fields are expressed in ten-thousand yuan.
        for column in ["成交额", "流通市值"]:
            if column in frame:
                frame[column] = frame[column] * 10_000
        frame["代码"] = frame["代码"].astype(str).str.extract(r"(\d{6})", expand=False)
        frame = frame.dropna(subset=["代码"]).drop_duplicates("代码", keep="first")
        for column in MARKET_COLUMNS:
            if column not in frame:
                frame[column] = pd.NA
        frame["source_id"] = "market_tencent"
        return frame[[*MARKET_COLUMNS, "source_id"]].reset_index(drop=True)


class FreeMarketAggregator:
    """Combine free market sources and call slow sources only to repair coverage."""

    def __init__(self, minimum_rows: int = 5000) -> None:
        self.minimum_rows = minimum_rows

    def fetch(
        self,
        tencent_fetch: Callable[[], pd.DataFrame],
        eastmoney_fetch: Callable[[], pd.DataFrame],
        browser_fetch: Callable[[], pd.DataFrame] | None,
        sina_fetch: Callable[[], pd.DataFrame],
    ) -> MarketAggregateResult:
        attempts: list[MarketSourceAttempt] = []
        frames: list[pd.DataFrame] = []

        tencent = self._attempt("market_tencent", "腾讯沪深京行情", tencent_fetch)
        attempts.append(tencent)
        if not tencent.frame.empty:
            frames.append(tencent.frame)

        if not tencent.complete:
            eastmoney = self._attempt("market_eastmoney", "东方财富A股行情", eastmoney_fetch)
            attempts.append(eastmoney)
            if not eastmoney.frame.empty:
                frames.append(self._tag(eastmoney.frame, eastmoney.source_id))

            if eastmoney.frame.empty and browser_fetch is not None:
                browser = self._attempt(
                    "market_eastmoney_browser",
                    "东方财富A股行情（浏览器回退）",
                    browser_fetch,
                )
                attempts.append(browser)
                if not browser.frame.empty:
                    frames.append(self._tag(browser.frame, browser.source_id))

        merged = merge_market_frames(frames)
        needs_sina = merged.empty or merged["代码"].nunique() < self.minimum_rows
        if needs_sina:
            sina = self._attempt("market_sina", "新浪A股行情", sina_fetch)
            attempts.append(sina)
            if not sina.frame.empty:
                frames.append(self._tag(sina.frame, sina.source_id))
                merged = merge_market_frames(frames)

        return MarketAggregateResult(merged, tuple(attempts))

    @staticmethod
    def _tag(frame: pd.DataFrame, source_id: str) -> pd.DataFrame:
        tagged = frame.copy()
        tagged["source_id"] = source_id
        return tagged

    def _attempt(
        self,
        source_id: str,
        display_name: str,
        fetch: Callable[[], pd.DataFrame],
    ) -> MarketSourceAttempt:
        try:
            frame = fetch()
            if frame is None:
                raise ValueError("source returned None")
            tagged = self._tag(frame, source_id)
            expected = frame.attrs.get("expected_rows")
            return MarketSourceAttempt(source_id, display_name, tagged, expected_rows=expected)
        except Exception as exc:
            return MarketSourceAttempt(
                source_id,
                display_name,
                pd.DataFrame(),
                error=f"{type(exc).__name__}: {exc}",
            )


def merge_market_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Union snapshots by security code and fill fields in source-priority order."""
    prepared: list[pd.DataFrame] = []
    for frame in frames:
        if frame.empty or "代码" not in frame:
            continue
        item = frame.copy()
        item["代码"] = item["代码"].astype(str).str.extract(r"(\d{6})", expand=False)
        item = item.dropna(subset=["代码"]).drop_duplicates("代码", keep="first")
        if "source_id" not in item:
            item["source_id"] = "market_unknown"
        for column in MARKET_COLUMNS:
            if column not in item:
                item[column] = pd.NA
        prepared.append(item[[*MARKET_COLUMNS, "source_id"]])
    if not prepared:
        return pd.DataFrame(columns=[*MARKET_COLUMNS, "source_id", "source_count"])

    codes = pd.Index([], dtype="object")
    for frame in prepared:
        codes = codes.union(pd.Index(frame["代码"]))
    result = pd.DataFrame(index=codes)
    provenance: dict[str, list[str]] = {str(code): [] for code in codes}

    for frame in prepared:
        indexed = frame.set_index("代码")
        for code, source in indexed["source_id"].items():
            source_text = str(source)
            if source_text not in provenance[str(code)]:
                provenance[str(code)].append(source_text)
        for column in [item for item in MARKET_COLUMNS if item != "代码"]:
            values = indexed[column].reindex(codes)
            if column not in result:
                result[column] = values
            else:
                result[column] = result[column].combine_first(values)

    result.index.name = "代码"
    result.reset_index(inplace=True)
    result["source_id"] = result["代码"].map(lambda code: "+".join(provenance[str(code)]))
    result["source_count"] = result["代码"].map(lambda code: len(provenance[str(code)]))
    return result[[*MARKET_COLUMNS, "source_id", "source_count"]]
