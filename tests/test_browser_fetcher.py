from __future__ import annotations

from contextlib import contextmanager

from a_stock_radar.browser_fetcher import (
    EastmoneyBrowserAdapter,
    _decode_json_or_jsonp,
    _diff_records,
)


def test_decode_json_and_jsonp() -> None:
    assert _decode_json_or_jsonp('{"data": {"total": 1}}')["data"]["total"] == 1
    assert _decode_json_or_jsonp('callback({"data": {"total": 2}});')["data"]["total"] == 2


def test_diff_records_accepts_dict_and_list() -> None:
    records, total = _diff_records({"data": {"total": 2, "diff": {"0": {"f12": "1"}}}})
    assert records == [{"f12": "1"}]
    assert total == 2

    records, total = _diff_records({"data": {"diff": [{"f12": "2"}]}})
    assert records == [{"f12": "2"}]
    assert total == 1


class FakeSession:
    def fetch_json(self, url, params):  # noqa: ANN001
        if "push2delay" in url:
            return {
                "data": {
                    "total": 1,
                    "diff": [
                        {
                            "f12": "510300",
                            "f14": "沪深300ETF",
                            "f2": 4.1,
                            "f3": 1.2,
                            "f6": 123456,
                            "f38": 1000000,
                            "f402": -0.1,
                            "f441": 4.09,
                        }
                    ],
                }
            }
        return {
            "data": {
                "total": 1,
                "diff": [
                    {
                        "f12": "600000",
                        "f14": "浦发银行",
                        "f2": 10.0,
                        "f3": 0.5,
                        "f6": 10000,
                        "f8": 1.1,
                        "f21": 100000000,
                    }
                ],
            }
        }


class FakeFetcher:
    @contextmanager
    def session(self):
        yield FakeSession()


def test_eastmoney_browser_adapter_normalizes_expected_columns() -> None:
    adapter = EastmoneyBrowserAdapter(fetcher=FakeFetcher())
    market = adapter.fetch_market_spot()
    etf = adapter.fetch_etf_spot()

    assert market.loc[0, "代码"] == "600000"
    assert market.loc[0, "涨跌幅"] == 0.5
    assert etf.loc[0, "代码"] == "510300"
    assert etf.loc[0, "最新份额"] == 1000000
