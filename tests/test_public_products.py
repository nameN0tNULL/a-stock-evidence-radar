from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pandas as pd

from a_stock_radar.hosted_product_provider import HostedProductSourceProvider
from a_stock_radar.public_products import (
    CLS_SUBJECT_URL,
    KAIPANLA_LISTING_URLS,
    PublicProductClient,
    download_authorized_artifact,
)


class FakeResponse:
    def __init__(self, text: str = "", content: bytes | None = None) -> None:
        self.text = text
        self.content = content if content is not None else text.encode()
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self) -> None:
        return None


class FakeSession:
    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.headers: dict[str, str] = {}

    def get(self, url: str, timeout: float) -> FakeResponse:
        assert timeout > 0
        if url not in self.pages:
            raise RuntimeError(f"unexpected URL: {url}")
        return FakeResponse(self.pages[url])


class FakeAkshare:
    @staticmethod
    def stock_zh_a_spot_em() -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "代码": "000001",
                    "名称": "平安银行",
                    "最新价": "12.30",
                    "涨跌幅": "2.5",
                    "成交额": "1250000000",
                    "流通市值": "220000000000",
                    "换手率": "1.2",
                }
            ]
        )

    @staticmethod
    def stock_lhb_detail_em(**_: object) -> pd.DataFrame:
        return pd.DataFrame()

    @staticmethod
    def stock_lhb_jgmmtj_em(**_: object) -> pd.DataFrame:
        return pd.DataFrame()

    @staticmethod
    def stock_lhb_hyyyb_em(**_: object) -> pd.DataFrame:
        return pd.DataFrame()

    @staticmethod
    def stock_lhb_yybph_em(**_: object) -> pd.DataFrame:
        return pd.DataFrame()

    @staticmethod
    def stock_lhb_traderstatistic_em(**_: object) -> pd.DataFrame:
        return pd.DataFrame()


def test_kaipanla_public_review_extracts_same_day_facts() -> None:
    article_url = "https://www.kaipanla.com/article/100"
    listing = f'<a href="{article_url}">复盘</a>'
    article = """
    <html><head><title>8月6日一图复盘：市场修复</title></head>
    <body>
      <h1>8月6日一图复盘：市场修复</h1>
      <p>时间：2026-08-06 17:20:00</p>
      <p>3500家上涨，1800家下跌，实际涨停88家，跌停2家。</p>
      <p>两市成交额1.25万亿，市场情绪回暖但仍有分歧。</p>
      <img src="/uploads/review.png" />
    </body></html>
    """
    pages = {url: listing for url in KAIPANLA_LISTING_URLS}
    pages[article_url] = article
    client = PublicProductClient(FakeSession(pages), retries=1)

    result = client.fetch_kaipanla_review(date(2026, 8, 6))

    assert result.error is None
    assert result.payload is not None
    assert result.payload["article_date"] == "2026-08-06"
    assert result.payload["facts"]["advance_count"] == 3500
    assert result.payload["facts"]["limit_up_count"] == 88
    assert result.payload["facts"]["turnover_cny"] == 1.25e12
    assert result.payload["images"] == [
        "https://www.kaipanla.com/uploads/review.png"
    ]


def test_cls_public_article_supports_chinese_timestamp() -> None:
    article_url = "https://www.cls.cn/detail/1234567"
    subject = f'<a href="{article_url}">龙虎榜</a>'
    article = """
    <html><head><title>龙虎榜丨平安银行今日收涨</title></head>
    <body>
      <h1>龙虎榜丨平安银行今日收涨</h1>
      <p>2026年08月06日 17:16:52</p>
      <p>000001机构专用席位合计净买入1.2亿元，深股通专用净卖出5000万元。</p>
    </body></html>
    """
    client = PublicProductClient(
        FakeSession({CLS_SUBJECT_URL: subject, article_url: article}),
        retries=1,
    )

    result = client.fetch_cls_lhb(date(2026, 8, 6))

    assert result.payload is not None
    rows = result.payload["rows"]
    assert len(rows) == 1
    assert rows[0]["security_code"] == "000001"
    assert rows[0]["security_name"] == "平安银行"
    assert rows[0]["net_amount"] == 120_000_000
    assert rows[0]["published_at"].startswith("2026-08-06T17:16:52")


def test_authorized_artifact_checks_sha256(tmp_path, monkeypatch) -> None:
    payload = b"code,dde_net_amount,amount\n000001,100,1000\n"
    digest = hashlib.sha256(payload).hexdigest()
    captured: dict[str, object] = {}

    def fake_get(url: str, headers: dict[str, str], timeout: float) -> FakeResponse:
        captured.update({"url": url, "headers": headers, "timeout": timeout})
        return FakeResponse(content=payload)

    monkeypatch.setattr("a_stock_radar.public_products.requests.get", fake_get)
    output = tmp_path / "dazhihui.csv"

    result = download_authorized_artifact(
        "https://licensed.example/dde.csv",
        output,
        bearer_token="secret-token",
        expected_sha256=digest,
    )

    assert output.read_bytes() == payload
    assert result["sha256"] == digest
    assert captured["headers"] == {
        "User-Agent": "a-stock-evidence-radar/0.6",
        "Authorization": "Bearer secret-token",
    }


def test_hosted_provider_uses_eastmoney_snapshot_and_public_kaipanla(tmp_path) -> None:
    trade_date = date(2026, 8, 6)
    public_dir = tmp_path / "imports" / "kaipanla_public"
    public_dir.mkdir(parents=True)
    (public_dir / "2026-08-06.json").write_text(
        json.dumps(
            {
                "title": "一图复盘",
                "article_date": "2026-08-06",
                "limitations": ["公开文章"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    bundle = HostedProductSourceProvider(
        tmp_path,
        {},
        ak_module=FakeAkshare(),
    ).fetch(trade_date)

    assert bundle.data_mode == "curated"
    assert bundle.market.iloc[0]["security_code"] == "000001"
    quality = {item.source_id: item for item in bundle.qualities}
    assert quality["market_eastmoney_snapshot"].available
    assert quality["kaipanla_public_review"].available
    artifact_dir = tmp_path / "data" / "raw" / "product_sources" / "date=20260806"
    assert (artifact_dir / "eastmoney_market_snapshot.csv").exists()
    assert (artifact_dir / "kaipanla_public_review.json").exists()
