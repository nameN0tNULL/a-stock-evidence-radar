from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .browser_fetcher import BrowserJsonFetcher


class ExchangeFetchError(RuntimeError):
    """Raised when an official exchange response is unavailable or malformed."""


@dataclass(frozen=True)
class OfficialFetchResult:
    frame: pd.DataFrame
    actual_date: date | None
    error: str | None = None
    route: str | None = None


class _BrowserJsonResponse:
    def __init__(self, payload: dict[str, Any], url: str) -> None:
        self._payload = payload
        self.url = url
        self.status_code = 200
        self.headers = {"content-type": "application/json"}
        self.content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.text = self.content.decode("utf-8")

    def json(self) -> dict[str, Any]:
        return self._payload


class OfficialExchangeFetcher:
    """Robust SSE/SZSE fetcher with empty-response and publication-delay handling.

    Eastmoney traffic may need the local proxy, but the official exchange endpoints are
    normally more reliable over a direct connection. The default route is therefore
    direct-first, with the environment proxy as a fallback. Set RADAR_EXCHANGE_ROUTE to
    proxy-first or direct-only to override this behavior.
    """

    SSE_QUERY_URL = "https://query.sse.com.cn/commonQuery.do"
    SSE_MARGIN_URL = "https://query.sse.com.cn/marketdata/tradedata/queryMargin.do"
    SZSE_REPORT_URL = "https://www.szse.cn/api/report/ShowReport"
    SZSE_REPORT_DATA_URL = "https://www.szse.cn/api/report/ShowReport/data"

    def __init__(self) -> None:
        self.timeout = float(os.getenv("RADAR_EXCHANGE_TIMEOUT", "20"))
        self.lookback_days = max(0, int(os.getenv("RADAR_EXCHANGE_LOOKBACK_DAYS", "7")))
        self.route_mode = os.getenv("RADAR_EXCHANGE_ROUTE", "direct-first").strip().lower()
        self.diagnostics = Path(os.getenv("RADAR_DIAGNOSTICS_DIR", "diagnostics")) / "exchange"
        self.diagnostics.mkdir(parents=True, exist_ok=True)
        self.direct_session = self._session(trust_env=False)
        self.proxy_session = self._session(trust_env=True)
        self.browser_fetcher = (
            BrowserJsonFetcher()
            if os.getenv("RADAR_BROWSER_FALLBACK", "false").lower() in {"1", "true", "yes"}
            else None
        )

    @staticmethod
    def _session(*, trust_env: bool) -> requests.Session:
        retry = Retry(
            total=2,
            connect=2,
            read=2,
            status=2,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        session = requests.Session()
        session.trust_env = trust_env
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _routes(self) -> list[tuple[str, requests.Session]]:
        if self.route_mode == "proxy-first":
            return [("environment-proxy", self.proxy_session), ("direct", self.direct_session)]
        if self.route_mode == "direct-only":
            return [("direct", self.direct_session)]
        return [("direct", self.direct_session), ("environment-proxy", self.proxy_session)]

    def _record(self, source: str, candidate: date, payload: dict[str, Any]) -> None:
        target = self.diagnostics / f"{source}-{candidate.isoformat()}.json"
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def _get(
        self,
        source: str,
        candidate: date,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
        expected: str,
    ) -> tuple[requests.Response, str]:
        errors: list[str] = []
        for route, session in self._routes():
            try:
                response = session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                if expected == "json":
                    try:
                        response.json()
                    except ValueError as exc:
                        raise ExchangeFetchError("response was not JSON") from exc
                elif expected == "xlsx" and not response.content.startswith(b"PK"):
                    raise ExchangeFetchError("response was not XLSX")
                self._record(
                    source,
                    candidate,
                    {
                        "ok": True,
                        "route": route,
                        "url": response.url,
                        "status": response.status_code,
                        "content_type": response.headers.get("content-type"),
                        "content_length": len(response.content),
                    },
                )
                return response, route
            except (requests.RequestException, ExchangeFetchError) as exc:
                errors.append(f"{route}: {type(exc).__name__}: {exc}")
        if (
            expected == "json"
            and self.browser_fetcher is not None
            and url.startswith("https://query.sse.com.cn/")
        ):
            try:
                with self.browser_fetcher.session() as browser_session:
                    page = getattr(browser_session, "page", None)
                    if page is not None:
                        page.set_extra_http_headers(
                            {
                                key: value
                                for key, value in headers.items()
                                if key.lower() != "host"
                            }
                        )
                    payload = browser_session.fetch_json(url, params)
                prepared = requests.Request("GET", url, params=params).prepare()
                route = (
                    "browser-proxy"
                    if self.browser_fetcher.config.proxy_server
                    else "browser-direct"
                )
                response = _BrowserJsonResponse(payload, prepared.url or url)
                self._record(
                    source,
                    candidate,
                    {
                        "ok": True,
                        "route": route,
                        "url": response.url,
                        "status": response.status_code,
                        "content_type": response.headers.get("content-type"),
                        "content_length": len(response.content),
                    },
                )
                return response, route
            except Exception as exc:
                errors.append(f"browser-fallback: {type(exc).__name__}: {exc}")
        self._record(source, candidate, {"ok": False, "errors": errors, "url": url})
        raise ExchangeFetchError("; ".join(errors))

    def _candidate_dates(self, requested: date) -> list[date]:
        candidates: list[date] = []
        for offset in range(self.lookback_days + 1):
            candidate = requested - timedelta(days=offset)
            if candidate.weekday() < 5:
                candidates.append(candidate)
        return candidates

    @staticmethod
    def _fallback_message(requested: date, actual: date, route: str) -> str | None:
        if requested == actual:
            return None
        return (
            f"requested {requested.isoformat()} was not published; "
            f"using {actual.isoformat()} via {route}"
        )

    @staticmethod
    def _json(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            preview = response.text[:200].replace("\n", " ")
            raise ExchangeFetchError(f"response was not JSON: {preview}") from exc

    @staticmethod
    def _xlsx(response: requests.Response) -> pd.DataFrame:
        if not response.content.startswith(b"PK"):
            content_type = response.headers.get("content-type", "")
            preview = response.text[:200].replace("\n", " ")
            raise ExchangeFetchError(
                f"response was not XLSX: content-type={content_type!r}, preview={preview!r}"
            )
        try:
            return pd.read_excel(BytesIO(response.content), engine="openpyxl")
        except (OSError, ValueError) as exc:
            raise ExchangeFetchError(f"could not parse XLSX: {exc}") from exc

    def fetch_sse_etf_shares(self, requested: date) -> OfficialFetchResult:
        errors: list[str] = []
        for candidate in self._candidate_dates(requested):
            params = {
                "isPagination": "true",
                "pageHelp.pageSize": "10000",
                "pageHelp.pageNo": "1",
                "pageHelp.beginPage": "1",
                "pageHelp.cacheSize": "1",
                "pageHelp.endPage": "1",
                "sqlId": "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L",
                "STAT_DATE": candidate.strftime("%Y-%m-%d"),
            }
            headers = {
                "Referer": "https://www.sse.com.cn/",
                "User-Agent": "Mozilla/5.0 Chrome/132.0.0.0 Safari/537.36",
            }
            try:
                response, route = self._get(
                    "sse-etf-shares",
                    candidate,
                    self.SSE_QUERY_URL,
                    params=params,
                    headers=headers,
                    expected="json",
                )
                payload = self._json(response)
                records = payload.get("result") if isinstance(payload, dict) else None
                if not isinstance(records, list):
                    raise ExchangeFetchError("SSE ETF payload did not contain a result list")
                if not records:
                    errors.append(f"{candidate.isoformat()}: not published")
                    continue
                frame = pd.DataFrame(records).rename(
                    columns={
                        "NUM": "序号",
                        "SEC_CODE": "基金代码",
                        "SEC_NAME": "基金简称",
                        "ETF_TYPE": "ETF类型",
                        "STAT_DATE": "统计日期",
                        "TOT_VOL": "基金份额",
                    }
                )
                required = ["基金代码", "基金简称", "统计日期", "基金份额"]
                missing = [column for column in required if column not in frame.columns]
                if missing:
                    raise ExchangeFetchError(
                        f"SSE ETF schema missing {missing}; columns={list(frame.columns)}"
                    )
                frame = frame[[c for c in ["序号", *required, "ETF类型"] if c in frame]].copy()
                frame["基金代码"] = frame["基金代码"].astype(str).str.zfill(6)
                frame["统计日期"] = pd.to_datetime(frame["统计日期"], errors="coerce").dt.date
                frame["基金份额"] = pd.to_numeric(frame["基金份额"], errors="coerce") * 10000
                frame = frame.dropna(subset=["基金代码", "基金份额"])
                if frame.empty:
                    errors.append(f"{candidate.isoformat()}: parsed zero rows")
                    continue
                actual = frame["统计日期"].dropna().max() if frame["统计日期"].notna().any() else candidate
                return OfficialFetchResult(
                    frame=frame,
                    actual_date=actual,
                    error=self._fallback_message(requested, actual, route),
                    route=route,
                )
            except (ExchangeFetchError, KeyError, TypeError, ValueError) as exc:
                errors.append(f"{candidate.isoformat()}: {type(exc).__name__}: {exc}")
        return OfficialFetchResult(pd.DataFrame(), None, "; ".join(errors) or "no data")

    def fetch_szse_etf_shares(self, requested: date) -> OfficialFetchResult:
        errors: list[str] = []
        for candidate in self._candidate_dates(requested):
            params = {
                "SHOWTYPE": "xlsx",
                "CATALOGID": "scsj_fund_jjgm",
                "TABKEY": "tab1",
                "txtStart": candidate.strftime("%Y-%m-%d"),
                "txtEnd": candidate.strftime("%Y-%m-%d"),
                "jjlb": "ETF",
                "random": "0.6180339887",
            }
            headers = {
                "Host": "www.szse.cn",
                "Referer": "https://www.szse.cn/market/fund/volume/etf/index.html",
                "User-Agent": "Mozilla/5.0 Chrome/132.0.0.0 Safari/537.36",
            }
            try:
                response, route = self._get(
                    "szse-etf-shares",
                    candidate,
                    self.SZSE_REPORT_URL,
                    params=params,
                    headers=headers,
                    expected="xlsx",
                )
                frame = self._xlsx(response).dropna(how="all")
                if frame.empty:
                    errors.append(f"{candidate.isoformat()}: not published")
                    continue
                frame = frame.rename(columns={"基金规模(份)": "基金份额"})
                required = ["日期", "基金代码", "基金简称", "基金份额"]
                missing = [column for column in required if column not in frame.columns]
                if missing:
                    raise ExchangeFetchError(
                        f"SZSE ETF schema missing {missing}; columns={list(frame.columns)}"
                    )
                frame = frame[required].copy()
                numeric_codes = pd.to_numeric(frame["基金代码"], errors="coerce")
                frame = frame[numeric_codes.notna()].copy()
                frame["基金代码"] = numeric_codes[numeric_codes.notna()].astype(int).astype(str).str.zfill(6)
                frame["日期"] = pd.to_datetime(frame["日期"], errors="coerce").dt.date
                frame["基金份额"] = pd.to_numeric(
                    frame["基金份额"].astype(str).str.replace(",", "", regex=False),
                    errors="coerce",
                )
                frame = frame.dropna(subset=["日期", "基金代码", "基金份额"])
                if frame.empty:
                    errors.append(f"{candidate.isoformat()}: parsed zero rows")
                    continue
                actual = frame["日期"].max()
                return OfficialFetchResult(
                    frame=frame,
                    actual_date=actual,
                    error=self._fallback_message(requested, actual, route),
                    route=route,
                )
            except (ExchangeFetchError, KeyError, TypeError, ValueError) as exc:
                errors.append(f"{candidate.isoformat()}: {type(exc).__name__}: {exc}")
        return OfficialFetchResult(pd.DataFrame(), None, "; ".join(errors) or "no data")

    def _fetch_sse_margin(self, requested: date, *, detail: bool) -> OfficialFetchResult:
        errors: list[str] = []
        source = "sse-margin-detail" if detail else "sse-margin-summary"
        for candidate in self._candidate_dates(requested):
            date_text = candidate.strftime("%Y%m%d")
            params = {
                "isPagination": "true",
                "tabType": "mxtype" if detail else "",
                "detailsDate": date_text if detail else "",
                "stockCode": "",
                "beginDate": "" if detail else date_text,
                "endDate": "" if detail else date_text,
                "pageHelp.pageSize": "5000",
                "pageHelp.pageNo": "1",
                "pageHelp.beginPage": "1",
                "pageHelp.cacheSize": "1",
                "pageHelp.endPage": "21" if detail else "5",
            }
            headers = {
                "Referer": "https://www.sse.com.cn/",
                "User-Agent": "Mozilla/5.0 Chrome/132.0.0.0 Safari/537.36",
            }
            try:
                response, route = self._get(
                    source,
                    candidate,
                    self.SSE_MARGIN_URL,
                    params=params,
                    headers=headers,
                    expected="json",
                )
                payload = self._json(response)
                records = payload.get("result") if isinstance(payload, dict) else None
                if not isinstance(records, list):
                    raise ExchangeFetchError("SSE margin payload did not contain a result list")
                if not records:
                    errors.append(f"{candidate.isoformat()}: not published")
                    continue
                frame = pd.DataFrame(records)
                if frame.shape[1] != 13:
                    raise ExchangeFetchError(
                        f"SSE margin expected 13 fields, received {frame.shape[1]}"
                    )
                frame.columns = (
                    [
                        "_0",
                        "信用交易日期",
                        "融券偿还量",
                        "融券卖出量",
                        "融券余量",
                        "_5",
                        "_6",
                        "融资偿还额",
                        "融资买入额",
                        "_9",
                        "融资余额",
                        "标的证券简称",
                        "标的证券代码",
                    ]
                    if detail
                    else [
                        "_0",
                        "信用交易日期",
                        "_2",
                        "融券卖出量",
                        "融券余量",
                        "融券余量金额",
                        "_6",
                        "_7",
                        "融资买入额",
                        "融资融券余额",
                        "融资余额",
                        "_11",
                        "_12",
                    ]
                )
                keep = (
                    [
                        "信用交易日期",
                        "标的证券代码",
                        "标的证券简称",
                        "融资余额",
                        "融资买入额",
                        "融资偿还额",
                        "融券余量",
                        "融券卖出量",
                        "融券偿还量",
                    ]
                    if detail
                    else [
                        "信用交易日期",
                        "融资余额",
                        "融资买入额",
                        "融券余量",
                        "融券余量金额",
                        "融券卖出量",
                        "融资融券余额",
                    ]
                )
                frame = frame[keep].copy()
                frame["信用交易日期"] = pd.to_datetime(
                    frame["信用交易日期"], errors="coerce"
                ).dt.date
                if detail:
                    frame["标的证券代码"] = frame["标的证券代码"].astype(str).str.zfill(6)
                for column in keep:
                    if column not in {"信用交易日期", "标的证券代码", "标的证券简称"}:
                        frame[column] = pd.to_numeric(
                            frame[column].astype(str).str.replace(",", "", regex=False),
                            errors="coerce",
                        )
                frame = frame.dropna(subset=["信用交易日期"])
                if frame.empty:
                    errors.append(f"{candidate.isoformat()}: parsed zero rows")
                    continue
                actual = frame["信用交易日期"].max()
                return OfficialFetchResult(
                    frame=frame,
                    actual_date=actual,
                    error=self._fallback_message(requested, actual, route),
                    route=route,
                )
            except (ExchangeFetchError, KeyError, TypeError, ValueError) as exc:
                errors.append(f"{candidate.isoformat()}: {type(exc).__name__}: {exc}")
        return OfficialFetchResult(pd.DataFrame(), None, "; ".join(errors) or "no data")

    def fetch_sse_margin_summary(self, requested: date) -> OfficialFetchResult:
        return self._fetch_sse_margin(requested, detail=False)

    def fetch_sse_margin_detail(self, requested: date) -> OfficialFetchResult:
        return self._fetch_sse_margin(requested, detail=True)

    def fetch_szse_margin_summary(self, requested: date) -> OfficialFetchResult:
        errors: list[str] = []
        for candidate in self._candidate_dates(requested):
            params = {
                "SHOWTYPE": "JSON",
                "CATALOGID": "1837_xxpl",
                "txtDate": candidate.strftime("%Y-%m-%d"),
                "tab1PAGENO": "1",
                "random": "0.6180339887",
            }
            headers = {
                "Referer": "https://www.szse.cn/disclosure/margin/margin/index.html",
                "User-Agent": "Mozilla/5.0 Chrome/132.0.0.0 Safari/537.36",
            }
            try:
                response, route = self._get(
                    "szse-margin-summary",
                    candidate,
                    self.SZSE_REPORT_DATA_URL,
                    params=params,
                    headers=headers,
                    expected="json",
                )
                payload = self._json(response)
                records = payload[0].get("data") if isinstance(payload, list) and payload else None
                if not isinstance(records, list):
                    raise ExchangeFetchError("SZSE margin payload did not contain a data list")
                if not records:
                    errors.append(f"{candidate.isoformat()}: not published")
                    continue
                frame = pd.DataFrame(records)
                if frame.shape[1] != 6:
                    raise ExchangeFetchError(
                        f"SZSE margin expected 6 fields, received {frame.shape[1]}"
                    )
                # The SZSE summary endpoint publishes monetary values in 亿元 and
                # lending quantities in 亿股/亿份. Normalize them to yuan and shares
                # so they can be aggregated with the SSE series without a unit mismatch.
                frame.columns = [
                    "融资买入额",
                    "融资余额",
                    "融券卖出量",
                    "融券余量",
                    "融券余额",
                    "融资融券余额",
                ]
                for column in frame.columns:
                    frame[column] = pd.to_numeric(
                        frame[column].astype(str).str.replace(",", "", regex=False),
                        errors="coerce",
                    ) * 100_000_000
                if frame.empty:
                    errors.append(f"{candidate.isoformat()}: parsed zero rows")
                    continue
                return OfficialFetchResult(
                    frame=frame,
                    actual_date=candidate,
                    error=self._fallback_message(requested, candidate, route),
                    route=route,
                )
            except (ExchangeFetchError, KeyError, IndexError, TypeError, ValueError) as exc:
                errors.append(f"{candidate.isoformat()}: {type(exc).__name__}: {exc}")
        return OfficialFetchResult(pd.DataFrame(), None, "; ".join(errors) or "no data")

    def fetch_szse_margin_detail(self, requested: date) -> OfficialFetchResult:
        errors: list[str] = []
        for candidate in self._candidate_dates(requested):
            params = {
                "SHOWTYPE": "xlsx",
                "CATALOGID": "1837_xxpl",
                "txtDate": candidate.strftime("%Y-%m-%d"),
                "tab2PAGENO": "1",
                "random": "0.6180339887",
                "TABKEY": "tab2",
            }
            headers = {
                "Referer": "https://www.szse.cn/disclosure/margin/margin/index.html",
                "User-Agent": "Mozilla/5.0 Chrome/132.0.0.0 Safari/537.36",
            }
            try:
                response, route = self._get(
                    "szse-margin-detail",
                    candidate,
                    self.SZSE_REPORT_URL,
                    params=params,
                    headers=headers,
                    expected="xlsx",
                )
                frame = self._xlsx(response).dropna(how="all")
                if frame.empty:
                    errors.append(f"{candidate.isoformat()}: not published")
                    continue
                if frame.shape[1] != 8:
                    raise ExchangeFetchError(
                        f"SZSE margin detail expected 8 fields, received {frame.shape[1]}"
                    )
                frame.columns = [
                    "证券代码",
                    "证券简称",
                    "融资买入额",
                    "融资余额",
                    "融券卖出量",
                    "融券余量",
                    "融券余额",
                    "融资融券余额",
                ]
                frame["证券代码"] = frame["证券代码"].astype(str).str.zfill(6)
                frame["证券简称"] = frame["证券简称"].astype(str).str.replace("&nbsp;", "")
                for column in frame.columns:
                    if column not in {"证券代码", "证券简称"}:
                        frame[column] = pd.to_numeric(
                            frame[column].astype(str).str.replace(",", "", regex=False),
                            errors="coerce",
                        )
                frame = frame.dropna(subset=["证券代码"])
                if frame.empty:
                    errors.append(f"{candidate.isoformat()}: parsed zero rows")
                    continue
                return OfficialFetchResult(
                    frame=frame,
                    actual_date=candidate,
                    error=self._fallback_message(requested, candidate, route),
                    route=route,
                )
            except (ExchangeFetchError, KeyError, TypeError, ValueError) as exc:
                errors.append(f"{candidate.isoformat()}: {type(exc).__name__}: {exc}")
        return OfficialFetchResult(pd.DataFrame(), None, "; ".join(errors) or "no data")
