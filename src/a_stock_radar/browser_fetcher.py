from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping
from urllib.parse import urlencode

import pandas as pd


@dataclass(frozen=True)
class BrowserFetchConfig:
    proxy_server: str | None
    timeout_ms: int = 45_000
    headless: bool = True
    diagnostics_dir: Path = Path("diagnostics/browser")

    @classmethod
    def from_env(cls) -> "BrowserFetchConfig":
        return cls(
            proxy_server=os.getenv("RADAR_BROWSER_PROXY") or None,
            timeout_ms=int(os.getenv("RADAR_BROWSER_TIMEOUT_MS", "45000")),
            headless=os.getenv("RADAR_BROWSER_HEADLESS", "true").lower() not in {"0", "false", "no"},
            diagnostics_dir=Path(os.getenv("RADAR_DIAGNOSTICS_DIR", "diagnostics/browser")),
        )


class BrowserJsonSession:
    def __init__(self, page: Any, timeout_ms: int, diagnostics_dir: Path):
        self.page = page
        self.timeout_ms = timeout_ms
        self.diagnostics_dir = diagnostics_dir
        self.counter = 0

    def fetch_json(self, url: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        query = urlencode({key: value for key, value in (params or {}).items() if value is not None})
        target = f"{url}?{query}" if query else url
        self.counter += 1
        try:
            response = self.page.goto(
                target,
                wait_until="domcontentloaded",
                timeout=self.timeout_ms,
            )
            if response is None:
                raise RuntimeError("browser navigation returned no response")
            if response.status >= 400:
                raise RuntimeError(f"HTTP_{response.status}: {response.status_text}")

            body = self.page.locator("body").inner_text(timeout=min(self.timeout_ms, 10_000)).strip()
            if not body:
                body = self.page.content().strip()
            return _decode_json_or_jsonp(body)
        except Exception:
            self._save_diagnostics(target)
            raise

    def _save_diagnostics(self, target: str) -> None:
        self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", target)[:100]
        prefix = self.diagnostics_dir / f"{self.counter:03d}_{slug}"
        try:
            self.page.screenshot(path=str(prefix.with_suffix(".png")), full_page=True)
        except Exception:
            pass
        try:
            prefix.with_suffix(".html").write_text(self.page.content(), encoding="utf-8")
        except Exception:
            pass


class BrowserJsonFetcher:
    """Standard Playwright JSON fetcher using a fixed local HTTP/SOCKS proxy."""

    def __init__(self, config: BrowserFetchConfig | None = None):
        self.config = config or BrowserFetchConfig.from_env()

    @contextmanager
    def session(self) -> Iterator[BrowserJsonSession]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - environment issue
            raise RuntimeError("Playwright browser extra is not installed") from exc

        with sync_playwright() as playwright:
            launch_options: dict[str, Any] = {"headless": self.config.headless}
            if self.config.proxy_server:
                launch_options["proxy"] = {"server": self.config.proxy_server}
            browser = playwright.chromium.launch(**launch_options)
            try:
                context = browser.new_context(
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    viewport={"width": 1365, "height": 768},
                    java_script_enabled=True,
                )
                page = context.new_page()
                page.set_default_timeout(self.config.timeout_ms)
                yield BrowserJsonSession(
                    page=page,
                    timeout_ms=self.config.timeout_ms,
                    diagnostics_dir=self.config.diagnostics_dir,
                )
            finally:
                browser.close()


def _decode_json_or_jsonp(body: str) -> dict[str, Any]:
    text = body.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"^[^(]+\((.*)\)\s*;?\s*$", text, flags=re.DOTALL)
        if not match:
            preview = text[:300].replace("\n", " ")
            raise RuntimeError(f"expected JSON response, received: {preview}")
        parsed = json.loads(match.group(1))
    if not isinstance(parsed, dict):
        raise RuntimeError(f"expected a JSON object, received {type(parsed).__name__}")
    return parsed


def _diff_records(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    data = payload.get("data")
    if not isinstance(data, dict):
        return [], 0
    diff = data.get("diff") or []
    if isinstance(diff, dict):
        records = [value for value in diff.values() if isinstance(value, dict)]
    elif isinstance(diff, list):
        records = [value for value in diff if isinstance(value, dict)]
    else:
        records = []
    try:
        total = int(data.get("total") or len(records))
    except (TypeError, ValueError):
        total = len(records)
    return records, total


class EastmoneyBrowserAdapter:
    """Browser fallback for the two Eastmoney sources used by M1."""

    MARKET_URL = "https://82.push2.eastmoney.com/api/qt/clist/get"
    ETF_URL = "https://push2delay.eastmoney.com/api/qt/clist/get"

    def __init__(self, fetcher: BrowserJsonFetcher | None = None):
        self.fetcher = fetcher or BrowserJsonFetcher()

    @classmethod
    def enabled_from_env(cls) -> bool:
        return os.getenv("RADAR_BROWSER_FALLBACK", "false").lower() in {"1", "true", "yes"}

    def fetch_market_spot(self) -> pd.DataFrame:
        params: dict[str, Any] = {
            "pn": 1,
            "pz": 100,
            "po": 1,
            "np": 2,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2,
            "invt": 2,
            "fid": "f3",
            "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
            "fields": (
                "f2,f3,f6,f8,f12,f14,f20,f21"
            ),
        }
        records = self._fetch_all(self.MARKET_URL, params)
        if not records:
            return pd.DataFrame()
        return pd.DataFrame(
            {
                "代码": [item.get("f12") for item in records],
                "名称": [item.get("f14") for item in records],
                "最新价": [item.get("f2") for item in records],
                "涨跌幅": [item.get("f3") for item in records],
                "成交额": [item.get("f6") for item in records],
                "流通市值": [item.get("f21") for item in records],
                "换手率": [item.get("f8") for item in records],
            }
        )

    def fetch_etf_spot(self) -> pd.DataFrame:
        params: dict[str, Any] = {
            "pn": 1,
            "pz": 100,
            "po": 1,
            "np": 1,
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": 2,
            "invt": 2,
            "wbp2u": "|0|0|0|web",
            "fid": "f12",
            "fs": "b:MK0021,b:MK0022,b:MK0023,b:MK0024,b:MK0827",
            "fields": "f2,f3,f6,f12,f14,f38,f402,f441",
        }
        records = self._fetch_all(self.ETF_URL, params)
        if not records:
            return pd.DataFrame()
        return pd.DataFrame(
            {
                "代码": [item.get("f12") for item in records],
                "名称": [item.get("f14") for item in records],
                "最新价": [item.get("f2") for item in records],
                "涨跌幅": [item.get("f3") for item in records],
                "成交额": [item.get("f6") for item in records],
                "最新份额": [item.get("f38") for item in records],
                "基金折价率": [item.get("f402") for item in records],
                "IOPV实时估值": [item.get("f441") for item in records],
            }
        )

    def _fetch_all(self, url: str, base_params: dict[str, Any]) -> list[dict[str, Any]]:
        page_size = int(base_params.get("pz", 100))
        records: list[dict[str, Any]] = []
        with self.fetcher.session() as session:
            page_number = 1
            total = page_size
            while len(records) < total:
                params = dict(base_params)
                params["pn"] = page_number
                payload = session.fetch_json(url, params)
                page_records, total = _diff_records(payload)
                if not page_records:
                    break
                records.extend(page_records)
                if len(page_records) < page_size:
                    break
                page_number += 1
                if page_number > 100:
                    raise RuntimeError("pagination exceeded 100 pages")
        return records
