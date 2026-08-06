from __future__ import annotations

from datetime import date

from a_stock_radar.config import Settings
from a_stock_radar.pipeline import curated_market_export_available


def settings(root) -> Settings:
    return Settings(
        root=root,
        app={},
        thresholds={},
        taxonomy={},
        sources={
            "products": {
                "kaipanla": {
                    "import_dir": "imports/kaipanla",
                    "env_path": "RADAR_KAIPANLA_EXPORT",
                }
            }
        },
    )


def test_auto_mode_requires_requested_date_kaipanla_export(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("RADAR_KAIPANLA_EXPORT", raising=False)
    trade_date = date(2026, 8, 6)
    configured = settings(tmp_path)

    assert not curated_market_export_available(configured, trade_date)

    directory = tmp_path / "imports" / "kaipanla"
    directory.mkdir(parents=True)
    (directory / "2026-08-06.csv").write_text(
        "代码,名称,最新价,涨跌幅,成交额\n000001,平安银行,12.3,1.2,1000000\n",
        encoding="utf-8",
    )

    assert curated_market_export_available(configured, trade_date)
    assert not curated_market_export_available(configured, date(2026, 8, 5))
