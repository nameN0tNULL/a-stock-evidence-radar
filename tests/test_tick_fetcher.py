from __future__ import annotations

import json
from datetime import date

import pandas as pd
import pytest

from a_stock_radar.tick_fetcher import (
    AkshareTencentTickCollector,
    CapabilityError,
    TickCapability,
    assess_tick_quality,
    classify_tick_capability,
    compute_trade_print_features,
    normalize_security_symbol,
    normalize_tencent_tick_frame,
    require_full_l2,
    write_tick_bundle,
)


def sample_raw_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "成交时间": "09:30:02",
                "成交价格": 10.0,
                "价格变动": 0.01,
                "成交量": 2,
                "成交额": 2000,
                "性质": "买盘",
            },
            {
                "成交时间": "14:58:00",
                "成交价格": 9.9,
                "价格变动": -0.1,
                "成交量": 3,
                "成交额": 2970,
                "性质": "卖盘",
            },
            {
                "成交时间": "15:00:02",
                "成交价格": 9.9,
                "价格变动": 0.0,
                "成交量": 1,
                "成交额": 990,
                "性质": "中性盘",
            },
        ]
    )


def test_normalize_symbol_supports_common_formats() -> None:
    assert normalize_security_symbol("sz000001") == ("000001", "SZ", "000001.SZ")
    assert normalize_security_symbol("600000.XSHG") == ("600000", "SH", "600000.SH")
    assert normalize_security_symbol("430047") == ("430047", "BJ", "430047.BJ")


def test_normalize_tencent_tick_frame_preserves_boundaries() -> None:
    frame = normalize_tencent_tick_frame(sample_raw_frame(), "sz000001", date(2026, 7, 31))

    assert frame["symbol"].eq("000001.SZ").all()
    assert frame["volume_shares"].tolist() == [200, 300, 100]
    assert frame["trade_sign"].tolist() == [1, -1, 0]
    assert frame["capability"].eq("trade_prints").all()
    assert frame["is_official"].eq(False).all()
    assert str(frame["event_time"].dtype) == "datetime64[ns, Asia/Shanghai]"


def test_full_l2_contract_requires_order_fields() -> None:
    trade_prints = normalize_tencent_tick_frame(
        sample_raw_frame(), "sz000001", date(2026, 7, 31)
    )
    assert classify_tick_capability(trade_prints.columns) is TickCapability.TRADE_PRINTS
    with pytest.raises(CapabilityError):
        require_full_l2(trade_prints)

    full_l2 = pd.DataFrame(
        columns=["source_seq", "event_type", "order_id", "price", "size"]
    )
    assert classify_tick_capability(full_l2.columns) is TickCapability.FULL_L2


def test_quality_uses_official_turnover_as_confirmation_gate() -> None:
    frame = normalize_tencent_tick_frame(sample_raw_frame(), "sz000001", date(2026, 7, 31))

    provisional = assess_tick_quality(frame)
    confirmed = assess_tick_quality(frame, official_turnover=5960)
    rejected = assess_tick_quality(frame, official_turnover=10_000, turnover_tolerance=0.03)

    assert provisional.status == "provisional"
    assert "official_turnover_missing" in provisional.reasons
    assert confirmed.status == "confirmed"
    assert confirmed.turnover_difference_ratio == 0
    assert rejected.status == "rejected"
    assert "turnover_mismatch" in rejected.reasons


def test_trade_print_features_do_not_claim_true_order_flow() -> None:
    frame = normalize_tencent_tick_frame(sample_raw_frame(), "sz000001", date(2026, 7, 31))

    features = compute_trade_print_features(frame)

    assert features["total_notional"] == 5960
    assert features["signed_notional_imbalance"] == pytest.approx((2000 - 2970) / 5960)
    assert features["classification_coverage"] == pytest.approx(4970 / 5960)
    assert features["closing_auction_notional_share"] == pytest.approx((2970 + 990) / 5960)
    assert features["supports_true_order_flow_imbalance"] is False
    assert features["supports_cancel_imbalance"] is False


def test_collector_retries_and_records_operator_supplied_date() -> None:
    calls: list[str] = []

    def fetcher(*, symbol: str) -> pd.DataFrame:
        calls.append(symbol)
        if len(calls) == 1:
            raise ConnectionError("temporary")
        return sample_raw_frame()

    collector = AkshareTencentTickCollector(
        fetcher=fetcher,
        retries=2,
        backoff_seconds=0,
        sleep=lambda _: None,
    )
    frame = collector.collect("000001.SZ", date(2026, 7, 31))

    assert calls == ["sz000001", "sz000001"]
    assert frame.attrs["trade_date_is_operator_supplied"] is True


def test_write_tick_bundle_persists_manifest_and_hash(tmp_path) -> None:
    frame = normalize_tencent_tick_frame(sample_raw_frame(), "sz000001", date(2026, 7, 31))
    quality = assess_tick_quality(frame, official_turnover=5960)
    features = compute_trade_print_features(frame)

    paths = write_tick_bundle(tmp_path, frame, quality, features)
    manifest = json.loads(paths.manifest_path.read_text(encoding="utf-8"))

    assert paths.data_path.exists()
    assert manifest["quality"]["status"] == "confirmed"
    assert manifest["source"]["capability"] == "trade_prints"
    assert manifest["limitations"][2] == "not_market_net_inflow"
    assert len(manifest["data_sha256"]) == 64
