from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any

import requests

from a_stock_radar.exchange_fetcher import OfficialExchangeFetcher


class FakeResponse:
    def __init__(self, payload: Any, *, url: str = "https://example.test") -> None:
        self._payload = payload
        self.url = url
        self.status_code = 200
        self.headers = {"content-type": "application/json"}
        self.content = b"{}"
        self.text = "{}"

    def json(self) -> Any:
        return self._payload


class FailingSession:
    def get(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        raise requests.HTTPError("403 Forbidden")


class FakeBrowserSession:
    page = None

    def fetch_json(self, url, params):  # noqa: ANN001, ANN202
        return {"result": [{"SEC_CODE": "510050"}]}


class FakeBrowserFetcher:
    config = type("Config", (), {"proxy_server": "socks5://127.0.0.1:7891"})()

    @contextmanager
    def session(self):
        yield FakeBrowserSession()


def _fetcher(tmp_path: Path, monkeypatch) -> OfficialExchangeFetcher:  # noqa: ANN001
    monkeypatch.setenv("RADAR_DIAGNOSTICS_DIR", str(tmp_path))
    monkeypatch.setenv("RADAR_EXCHANGE_LOOKBACK_DAYS", "3")
    return OfficialExchangeFetcher()


def test_sse_etf_empty_current_date_falls_back(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    fetcher = _fetcher(tmp_path, monkeypatch)
    payloads = iter(
        [
            {"result": []},
            {
                "result": [
                    {
                        "NUM": "1",
                        "SEC_CODE": "510050",
                        "SEC_NAME": "50ETF",
                        "ETF_TYPE": "单市",
                        "STAT_DATE": "2026-07-28",
                        "TOT_VOL": "553.25",
                    }
                ]
            },
        ]
    )

    def fake_get(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        return FakeResponse(next(payloads)), "direct"

    monkeypatch.setattr(fetcher, "_get", fake_get)
    result = fetcher.fetch_sse_etf_shares(date(2026, 7, 29))

    assert result.actual_date == date(2026, 7, 28)
    assert result.frame.loc[0, "基金份额"] == 5_532_500
    assert "using 2026-07-28" in (result.error or "")


def test_sse_margin_empty_result_does_not_assign_columns(
    tmp_path: Path, monkeypatch
) -> None:  # noqa: ANN001
    fetcher = _fetcher(tmp_path, monkeypatch)
    row = [0] * 13
    row[1] = "2026-07-28"
    payloads = iter([{"result": []}, {"result": [row]}])

    def fake_get(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        return FakeResponse(next(payloads)), "direct"

    monkeypatch.setattr(fetcher, "_get", fake_get)
    result = fetcher.fetch_sse_margin_summary(date(2026, 7, 29))

    assert result.actual_date == date(2026, 7, 28)
    assert len(result.frame) == 1
    assert list(result.frame.columns) == [
        "信用交易日期",
        "融资余额",
        "融资买入额",
        "融券余量",
        "融券余量金额",
        "融券卖出量",
        "融资融券余额",
    ]


def test_szse_margin_empty_result_does_not_assign_columns(
    tmp_path: Path, monkeypatch
) -> None:  # noqa: ANN001
    fetcher = _fetcher(tmp_path, monkeypatch)
    payloads = iter([[{"data": []}], [{"data": [["1", "2", "3", "4", "5", "6"]]}]])

    def fake_get(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        return FakeResponse(next(payloads)), "direct"

    monkeypatch.setattr(fetcher, "_get", fake_get)
    result = fetcher.fetch_szse_margin_summary(date(2026, 7, 29))

    assert result.actual_date == date(2026, 7, 28)
    assert result.frame.loc[0, "融资融券余额"] == 600_000_000


def test_sse_json_uses_browser_after_request_routes_fail(
    tmp_path: Path, monkeypatch
) -> None:  # noqa: ANN001
    fetcher = _fetcher(tmp_path, monkeypatch)
    fetcher.direct_session = FailingSession()
    fetcher.proxy_session = FailingSession()
    fetcher.browser_fetcher = FakeBrowserFetcher()

    response, route = fetcher._get(
        "sse-etf-shares",
        date(2026, 7, 29),
        fetcher.SSE_QUERY_URL,
        params={"STAT_DATE": "2026-07-29"},
        headers={"Referer": "https://www.sse.com.cn/"},
        expected="json",
    )

    assert route == "browser-proxy"
    assert response.json()["result"][0]["SEC_CODE"] == "510050"
