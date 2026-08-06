from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from .models import SourceQuality
from .product_io import normalize_kaipanla, write_frame, write_json
from .product_provider import ProductSourceProvider
from .sources import SourceBundle


class HostedProductSourceProvider:
    """Product-source provider that can run on a GitHub-hosted Linux runner.

    Public pages are synchronized before this provider runs. Proprietary DDE/ACE
    data is accepted only through an authorized artifact URL or a checked-in
    export supplied by the user.
    """

    def __init__(
        self,
        root: Path,
        source_config: dict[str, Any] | None = None,
        *,
        ak_module: Any | None = None,
    ) -> None:
        self.root = root
        self.base = ProductSourceProvider(
            root,
            source_config,
            ak_module=ak_module,
        )
        self.ak = self.base.ak

    @staticmethod
    def _quality(
        source_id: str,
        display_name: str,
        trade_date: date,
        frame: pd.DataFrame,
        *,
        evidence_level: str = "L2",
        actual_date: date | None = None,
        error: str | None = None,
    ) -> SourceQuality:
        available = not frame.empty
        return SourceQuality(
            source_id=source_id,
            display_name=display_name,
            trade_date=trade_date,
            available=available,
            expected_date=trade_date,
            actual_date=actual_date if available else None,
            freshness_ok=available and (actual_date in {None, trade_date}),
            schema_ok=available,
            row_count=len(frame),
            official=False,
            evidence_level=evidence_level,  # type: ignore[arg-type]
            error_message=error,
        )

    def _eastmoney_market(self, trade_date: date) -> tuple[pd.DataFrame, str | None]:
        function = getattr(self.ak, "stock_zh_a_spot_em", None)
        if function is None:
            return pd.DataFrame(), "AKShare does not expose stock_zh_a_spot_em"
        try:
            raw = function()
            if not isinstance(raw, pd.DataFrame) or raw.empty:
                return pd.DataFrame(), "Eastmoney market snapshot returned no rows"
            normalized = normalize_kaipanla(raw, trade_date)
            if normalized.empty:
                return pd.DataFrame(), "Eastmoney market snapshot schema was not recognized"
            normalized["source_id"] = "eastmoney_market_snapshot"
            return normalized, None
        except Exception as exc:
            return pd.DataFrame(), f"{type(exc).__name__}: {exc}"

    def _load_public_kaipanla(
        self,
        trade_date: date,
        directory: Path,
    ) -> SourceQuality:
        path = self.root / "imports" / "kaipanla_public" / f"{trade_date.isoformat()}.json"
        if not path.exists():
            return self._quality(
                "kaipanla_public_review",
                "开盘啦公开复盘文章",
                trade_date,
                pd.DataFrame(),
                evidence_level="L3",
                error="public Kaipanla review artifact was not found",
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            article_date = date.fromisoformat(str(payload.get("article_date")))
            frame = pd.DataFrame([payload])
            write_json(directory / "kaipanla_public_review.json", payload)
            return self._quality(
                "kaipanla_public_review",
                "开盘啦公开复盘文章",
                trade_date,
                frame,
                evidence_level="L3",
                actual_date=article_date,
                error=(
                    None
                    if article_date == trade_date
                    else f"latest public review is {article_date}; requested {trade_date}"
                ),
            )
        except Exception as exc:
            return self._quality(
                "kaipanla_public_review",
                "开盘啦公开复盘文章",
                trade_date,
                pd.DataFrame(),
                evidence_level="L3",
                error=f"{type(exc).__name__}: {exc}",
            )

    def _mark_public_cls(self, trade_date: date, directory: Path, bundle: SourceBundle) -> None:
        path = self.root / "imports" / "cls" / f"{trade_date.isoformat()}.csv"
        if not path.exists():
            return
        try:
            frame = pd.read_csv(path, dtype=str)
        except Exception:
            return
        if "source_url" not in frame.columns:
            return
        for quality in bundle.qualities:
            if quality.source_id == "cls_lhb_authorized":
                quality.source_id = "cls_lhb_public"
                quality.display_name = "财联社公开龙虎榜文章"
                quality.error_message = None if quality.available else quality.error_message
        facts_path = directory / "seat_facts.json"
        try:
            facts = json.loads(facts_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        changed = False
        for fact in facts:
            if fact.get("source_id") == "cls_lhb_authorized":
                fact["source_id"] = "cls_lhb_public"
                fact["limitations"] = [
                    "财联社公开龙虎榜文章用于交叉核实，不替代交易所或东方财富结构化明细。",
                    "文章未披露证券代码时不会猜测或补造代码。",
                ]
                changed = True
        if changed:
            write_json(facts_path, facts)

    def fetch(self, trade_date: date) -> SourceBundle:
        bundle = self.base.fetch(trade_date)
        directory = (
            self.root
            / "data"
            / "raw"
            / "product_sources"
            / f"date={trade_date.strftime('%Y%m%d')}"
        )
        directory.mkdir(parents=True, exist_ok=True)

        market, market_error = self._eastmoney_market(trade_date)
        if not market.empty:
            write_frame(directory / "eastmoney_market_snapshot.csv", market)
            if bundle.market.empty:
                bundle.market = market
        bundle.qualities.append(
            self._quality(
                "eastmoney_market_snapshot",
                "东方财富A股全市场快照",
                trade_date,
                market,
                evidence_level="L2",
                actual_date=trade_date if not market.empty else None,
                error=market_error,
            )
        )
        bundle.qualities.append(self._load_public_kaipanla(trade_date, directory))
        self._mark_public_cls(trade_date, directory, bundle)
        bundle.data_mode = "curated"
        return bundle
