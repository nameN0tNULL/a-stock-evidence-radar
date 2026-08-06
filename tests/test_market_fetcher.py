from __future__ import annotations

import pandas as pd

from a_stock_radar.market_fetcher import (
    FreeMarketAggregator,
    TencentMarketAdapter,
    compare_market_frames,
    merge_market_frames,
    normalize_sina_market_frame,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.headers = {}
        self.offsets = []

    def get(self, url, params, timeout):
        offset = int(params["offset"])
        self.offsets.append(offset)
        return FakeResponse(self.pages[offset])


def test_tencent_adapter_fetches_all_pages_and_normalizes_units() -> None:
    pages = {
        0: {
            "code": 0,
            "data": {
                "total": 3,
                "rank_list": [
                    {
                        "code": "sh600000",
                        "name": "浦发银行",
                        "zxj": "10",
                        "zdf": "1",
                        "turnover": "2",
                        "ltsz": "3",
                        "hsl": "4",
                    },
                    {
                        "code": "sz000001",
                        "name": "平安银行",
                        "zxj": "11",
                        "zdf": "2",
                        "turnover": "5",
                        "ltsz": "6",
                        "hsl": "7",
                    },
                ],
            },
        },
        2: {
            "code": 0,
            "data": {
                "total": 3,
                "rank_list": [
                    {
                        "code": "bj430047",
                        "name": "诺思兰德",
                        "zxj": "12",
                        "zdf": "3",
                        "turnover": "8",
                        "ltsz": "9",
                        "hsl": "10",
                    },
                ],
            },
        },
    }
    session = FakeSession(pages)
    adapter = TencentMarketAdapter(session=session, page_size=2, retries=1)

    frame = adapter.fetch_market_spot()

    assert session.offsets == [0, 2]
    assert frame["代码"].tolist() == ["600000", "000001", "430047"]
    assert frame.loc[0, "成交额"] == 20_000
    assert frame.loc[0, "流通市值"] == 30_000
    assert frame.attrs["expected_rows"] == 3


def test_normalize_sina_market_frame_supports_current_chinese_schema() -> None:
    frame = pd.DataFrame(
        [
            {
                "代码": "sh600000",
                "名称": "浦发银行",
                "最新价": "10.10",
                "涨跌幅": "1.20",
                "成交额": "123456",
            },
            {
                "代码": "bj430047",
                "名称": "诺思兰德",
                "最新价": "12.30",
                "涨跌幅": "2.10",
                "成交额": "654321",
            },
        ]
    )

    normalized = normalize_sina_market_frame(frame)

    assert normalized["代码"].tolist() == ["600000", "430047"]
    assert normalized.loc[0, "最新价"] == 10.10
    assert normalized.loc[0, "成交额"] == 123456
    assert normalized["source_id"].eq("market_sina").all()


def test_normalize_sina_market_frame_supports_legacy_english_schema() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "sz000001",
                "name": "平安银行",
                "trade": "11.20",
                "changepercent": "0.80",
                "amount": "999",
                "nmc": "1234",
                "turnoverratio": "2.5",
            }
        ]
    )

    normalized = normalize_sina_market_frame(frame)

    assert normalized.loc[0, "代码"] == "000001"
    assert normalized.loc[0, "流通市值"] == 1234
    assert normalized.loc[0, "换手率"] == 2.5


def test_merge_market_frames_fills_gaps_without_overwriting_primary() -> None:
    primary = pd.DataFrame(
        [
            {
                "代码": "600000",
                "名称": "浦发银行",
                "最新价": 10.0,
                "涨跌幅": 1.0,
                "成交额": None,
                "source_id": "market_tencent",
            },
        ]
    )
    secondary = pd.DataFrame(
        [
            {
                "代码": "600000",
                "名称": "浦发银行",
                "最新价": 10.1,
                "涨跌幅": 1.1,
                "成交额": 123.0,
                "source_id": "market_sina",
            },
            {
                "代码": "000001",
                "名称": "平安银行",
                "最新价": 11.0,
                "涨跌幅": 2.0,
                "成交额": 456.0,
                "source_id": "market_sina",
            },
        ]
    )

    merged = merge_market_frames([primary, secondary]).set_index("代码")

    assert merged.loc["600000", "最新价"] == 10.0
    assert merged.loc["600000", "成交额"] == 123.0
    assert merged.loc["600000", "source_count"] == 2
    assert merged.loc["000001", "source_id"] == "market_sina"


def test_compare_market_frames_allows_small_timing_differences() -> None:
    primary = pd.DataFrame(
        [
            {"代码": "600000", "最新价": 10.00, "涨跌幅": 1.00},
            {"代码": "000001", "最新价": 11.00, "涨跌幅": 2.00},
        ]
    )
    secondary = pd.DataFrame(
        [
            {"代码": "600000", "最新价": 10.01, "涨跌幅": 1.05},
            {"代码": "000001", "最新价": 11.10, "涨跌幅": 2.30},
        ]
    )

    agreement = compare_market_frames(primary, secondary)

    assert agreement.overlap_rows == 2
    assert agreement.close_mismatch_rows == 1
    assert agreement.pct_mismatch_rows == 1
    assert agreement.mismatch_ratio == 0.5


def test_aggregator_skips_slower_sources_when_tencent_is_complete() -> None:
    calls = []
    tencent = pd.DataFrame(
        [
            {
                "代码": f"{index:06d}",
                "名称": "x",
                "最新价": 1,
                "涨跌幅": 0,
                "成交额": 1,
            }
            for index in range(5)
        ]
    )
    tencent.attrs["expected_rows"] = 5

    def forbidden(name):
        def fetch():
            calls.append(name)
            raise AssertionError(name)

        return fetch

    result = FreeMarketAggregator(minimum_rows=5).fetch(
        lambda: tencent,
        forbidden("eastmoney"),
        forbidden("browser"),
        forbidden("sina"),
    )

    assert len(result.frame) == 5
    assert calls == []
    assert [attempt.source_id for attempt in result.attempts] == ["market_tencent"]


def test_aggregator_uses_sina_before_eastmoney_for_incomplete_tencent() -> None:
    calls = []
    tencent = pd.DataFrame(
        [
            {
                "代码": "600000",
                "名称": "浦发银行",
                "最新价": 10,
                "涨跌幅": 1,
                "成交额": 1,
            }
        ]
    )
    tencent.attrs["expected_rows"] = 3
    sina = pd.DataFrame(
        [
            {
                "代码": "sh600000",
                "名称": "浦发银行",
                "最新价": 10,
                "涨跌幅": 1,
                "成交额": 1,
            },
            {
                "代码": "sz000001",
                "名称": "平安银行",
                "最新价": 11,
                "涨跌幅": 2,
                "成交额": 2,
            },
            {
                "代码": "bj430047",
                "名称": "诺思兰德",
                "最新价": 12,
                "涨跌幅": 3,
                "成交额": 3,
            },
        ]
    )

    def eastmoney():
        calls.append("eastmoney")
        raise AssertionError("Eastmoney should not be called")

    result = FreeMarketAggregator(minimum_rows=3).fetch(
        lambda: tencent,
        eastmoney,
        None,
        lambda: sina,
    )

    assert set(result.frame["代码"]) == {"600000", "000001", "430047"}
    assert calls == []
    assert [attempt.source_id for attempt in result.attempts] == [
        "market_tencent",
        "market_sina",
    ]


def test_aggregator_can_verify_complete_tencent_with_sina() -> None:
    tencent = pd.DataFrame(
        [
            {
                "代码": "600000",
                "名称": "浦发银行",
                "最新价": 10.0,
                "涨跌幅": 1.0,
                "成交额": 1,
            }
        ]
    )
    tencent.attrs["expected_rows"] = 1
    sina = pd.DataFrame(
        [
            {
                "代码": "sh600000",
                "名称": "浦发银行",
                "最新价": 10.1,
                "涨跌幅": 1.2,
                "成交额": 2,
            }
        ]
    )

    result = FreeMarketAggregator(
        minimum_rows=1,
        verify_secondary=True,
    ).fetch(
        lambda: tencent,
        lambda: pd.DataFrame(),
        None,
        lambda: sina,
    )

    assert result.frame.loc[0, "最新价"] == 10.0
    assert result.frame.loc[0, "source_count"] == 2
    assert result.agreement.overlap_rows == 1
    assert result.agreement.close_mismatch_rows == 1
    assert [attempt.source_id for attempt in result.attempts] == [
        "market_tencent",
        "market_sina",
    ]
