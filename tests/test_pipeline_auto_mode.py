from __future__ import annotations

from a_stock_radar import pipeline
from a_stock_radar.config import Settings


def settings(root) -> Settings:
    return Settings(
        root=root,
        app={},
        thresholds={},
        taxonomy={},
        sources={"products": {}},
    )


def test_auto_mode_uses_hosted_product_provider(tmp_path, monkeypatch) -> None:
    marker = object()
    monkeypatch.setattr(
        pipeline,
        "HostedProductSourceProvider",
        lambda root, sources: marker,
    )

    result = pipeline._select_provider(
        "auto",
        object(),
        settings(tmp_path),
    )

    assert result is marker


def test_legacy_mode_remains_explicit(tmp_path, monkeypatch) -> None:
    marker = object()
    monkeypatch.setattr(pipeline, "AkshareProvider", lambda mapper: marker)

    result = pipeline._select_provider(
        "legacy",
        object(),
        settings(tmp_path),
    )

    assert result is marker
