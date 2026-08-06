from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

SHANGHAI = ZoneInfo("Asia/Shanghai")
KAIPANLA_LISTING_URLS = (
    "https://www.kaipanla.com/",
    "https://www.kaipanla.com/featured/1",
    "https://www.kaipanla.com/quick-start/1",
    "https://www.kaipanla.com/latest-news/1",
)
CLS_SUBJECT_URL = "https://www.cls.cn/subject/1105"

_REVIEW_KEYWORDS = (
    "复盘",
    "大盘",
    "盘面",
    "市场",
    "情绪",
    "龙虎榜",
    "热点",
    "题材",
)


@dataclass(frozen=True)
class FetchResult:
    payload: dict[str, Any] | None
    error: str | None = None


class PublicProductClient:
    """Read public product pages without login or private-interface reverse engineering."""

    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        timeout: float = 20,
        retries: int = 3,
        retry_delay: float = 0.8,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout
        self.retries = retries
        self.retry_delay = retry_delay
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "Chrome/126 Safari/537.36 a-stock-evidence-radar/0.6"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
            }
        )

    def _get(self, url: str) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                if not response.encoding or response.encoding.lower() == "iso-8859-1":
                    response.encoding = response.apparent_encoding or "utf-8"
                return response.text
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(self.retry_delay * (attempt + 1))
        assert last_error is not None
        raise last_error

    @staticmethod
    def _article_links(html: str, base_url: str, pattern: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        links: list[str] = []
        seen: set[str] = set()
        for anchor in soup.select("a[href]"):
            url = urljoin(base_url, str(anchor.get("href") or ""))
            if not re.search(pattern, url) or url in seen:
                continue
            seen.add(url)
            links.append(url)
        return links

    @staticmethod
    def _article_date(text: str) -> datetime | None:
        patterns = (
            (
                r"(?:时间\s*[:：]\s*)?(20\d{2})-(\d{2})-(\d{2})\s+"
                r"(\d{2}):(\d{2})(?::(\d{2}))?",
                False,
            ),
            (
                r"(?:发布时间\s*[:：]\s*)?(20\d{2})年(\d{1,2})月(\d{1,2})日\s*"
                r"(\d{1,2}):(\d{2})(?::(\d{2}))?",
                True,
            ),
        )
        for pattern, _ in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            values = [int(value or 0) for value in match.groups()]
            year, month, day, hour, minute, second = values
            try:
                return datetime(
                    year,
                    month,
                    day,
                    hour,
                    minute,
                    second,
                    tzinfo=SHANGHAI,
                )
            except ValueError:
                continue
        return None

    @staticmethod
    def _clean_text(soup: BeautifulSoup) -> str:
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        lines = [
            re.sub(r"\s+", " ", item).strip()
            for item in soup.get_text("\n").splitlines()
        ]
        return "\n".join(item for item in lines if item)

    @staticmethod
    def _kaipanla_facts(text: str) -> dict[str, Any]:
        facts: dict[str, Any] = {}
        patterns = {
            "advance_count": (r"(?:超|约)?\s*(\d{3,4})\s*家(?:个股)?上涨", int),
            "decline_count": (r"(?:超|约)?\s*(\d{3,4})\s*家(?:个股)?下跌", int),
            "limit_up_count": (r"(?:实际)?涨停\s*(\d{1,3})\s*家", int),
            "limit_down_count": (r"(?:实际)?跌停\s*(\d{1,3})\s*家", int),
        }
        for name, (pattern, converter) in patterns.items():
            match = re.search(pattern, text)
            if match:
                facts[name] = converter(match.group(1))
        turnover = re.search(
            r"(?:全天|两市|沪深两市)?成交额[^。；\n]{0,24}?"
            r"(\d+(?:\.\d+)?)\s*(万亿|亿)",
            text,
        )
        if turnover:
            value = float(turnover.group(1))
            facts["turnover_cny"] = value * (
                1e12 if turnover.group(2) == "万亿" else 1e8
            )
        sentiment_terms = [
            term
            for term in (
                "回暖",
                "修复",
                "火热",
                "震荡",
                "分歧",
                "降温",
                "弱势",
                "退潮",
                "恐慌",
            )
            if term in text
        ]
        if sentiment_terms:
            facts["sentiment_terms"] = sentiment_terms
        return facts

    def fetch_kaipanla_review(
        self,
        trade_date: date,
        *,
        maximum_articles: int = 60,
        maximum_age_days: int = 7,
    ) -> FetchResult:
        links: list[str] = []
        errors: list[str] = []
        for listing_url in KAIPANLA_LISTING_URLS:
            try:
                html = self._get(listing_url)
                links.extend(self._article_links(html, listing_url, r"/article/\d+"))
            except Exception as exc:
                errors.append(f"{listing_url}: {type(exc).__name__}: {exc}")
        links = list(dict.fromkeys(links))[:maximum_articles]
        candidates: list[dict[str, Any]] = []
        for url in links:
            try:
                html = self._get(url)
            except Exception as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")
                continue
            soup = BeautifulSoup(html, "html.parser")
            title_node = soup.find("h1") or soup.find("title")
            title = (
                re.sub(r"\s+", " ", title_node.get_text(" ", strip=True))
                if title_node
                else ""
            )
            text = self._clean_text(soup)
            published_at = self._article_date(text)
            if published_at is None:
                continue
            article_date = published_at.date()
            age = (trade_date - article_date).days
            if age < 0 or age > maximum_age_days:
                continue
            score = sum(3 for keyword in _REVIEW_KEYWORDS if keyword in title)
            score += sum(1 for keyword in _REVIEW_KEYWORDS if keyword in text[:1200])
            if article_date == trade_date:
                score += 20
            images = [
                urljoin(url, str(image.get("src") or image.get("data-src") or ""))
                for image in soup.select("img")
                if image.get("src") or image.get("data-src")
            ]
            candidates.append(
                {
                    "title": title,
                    "url": url,
                    "published_at": published_at.isoformat(),
                    "article_date": article_date.isoformat(),
                    "stale_days": age,
                    "score": score,
                    "summary": text[:4000],
                    "images": list(dict.fromkeys(images))[:12],
                    "facts": self._kaipanla_facts(text),
                }
            )
        if not candidates:
            detail = "; ".join(errors[-6:]) if errors else "no public review article found"
            return FetchResult(None, detail)
        selected = max(
            candidates,
            key=lambda item: (item["score"], item["published_at"]),
        )
        selected.update(
            {
                "source_id": "kaipanla_public_review",
                "requested_trade_date": trade_date.isoformat(),
                "retrieved_at": datetime.now(SHANGHAI).isoformat(),
                "access_method": "public_web_page",
                "limitations": [
                    "公开文章只提供复盘叙述和图片，不等同于登录态内完整结构化行情。",
                    "文本中的资金或情绪表述属于产品口径，必须与结构化事实分开。",
                ],
            }
        )
        return FetchResult(selected)

    @staticmethod
    def _cls_article(url: str, html: str) -> dict[str, Any] | None:
        soup = BeautifulSoup(html, "html.parser")
        title_node = soup.find("h1") or soup.find("title")
        title = (
            re.sub(r"\s+", " ", title_node.get_text(" ", strip=True))
            if title_node
            else ""
        )
        text = PublicProductClient._clean_text(soup)
        published_at = PublicProductClient._article_date(text)
        if not published_at or "龙虎榜" not in f"{title}\n{text[:1200]}":
            return None
        codes = re.findall(r"(?<!\d)([0368]\d{5})(?!\d)", f"{title}\n{text}")
        name_match = re.search(
            r"龙虎榜[|｜丨]\s*([^今昨\s]{2,12}?)(?:今日|涨停|跌停|收涨|收跌)",
            title,
        )
        security_name = (
            name_match.group(1).strip("|｜丨：:，,") if name_match else None
        )
        net_match = re.search(
            r"(?:合计|机构专用席位|机构|席位)[^。；\n]{0,35}?净(买入|卖出)\s*"
            r"(\d+(?:\.\d+)?)\s*(亿元|万元|万|亿)",
            text,
        )
        net_amount = None
        if net_match:
            value = float(net_match.group(2))
            scale = 1e8 if net_match.group(3) in {"亿元", "亿"} else 1e4
            net_amount = value * scale * (1 if net_match.group(1) == "买入" else -1)
        label_pattern = r"([\u4e00-\u9fa5A-Za-z0-9（）()·-]{2,32})净{}"
        buyer_labels = re.findall(label_pattern.format("买入"), text)
        seller_labels = re.findall(label_pattern.format("卖出"), text)
        return {
            "security_code": codes[0] if codes else None,
            "security_name": security_name,
            "title": title,
            "body": text[:3000],
            "buyer_labels": "、".join(dict.fromkeys(buyer_labels[:8])),
            "seller_labels": "、".join(dict.fromkeys(seller_labels[:8])),
            "net_amount": net_amount,
            "published_at": published_at.isoformat(),
            "source_url": url,
        }

    def fetch_cls_lhb(
        self,
        trade_date: date,
        *,
        maximum_articles: int = 80,
    ) -> FetchResult:
        try:
            subject_html = self._get(CLS_SUBJECT_URL)
        except Exception as exc:
            return FetchResult(None, f"{type(exc).__name__}: {exc}")
        links = self._article_links(subject_html, CLS_SUBJECT_URL, r"/detail/\d+")
        rows: list[dict[str, Any]] = []
        errors: list[str] = []
        for url in links[:maximum_articles]:
            try:
                article = self._cls_article(url, self._get(url))
            except Exception as exc:
                errors.append(f"{url}: {type(exc).__name__}: {exc}")
                continue
            if article and str(article["published_at"]).startswith(trade_date.isoformat()):
                rows.append(article)
        payload = {
            "source_id": "cls_lhb_public",
            "trade_date": trade_date.isoformat(),
            "retrieved_at": datetime.now(SHANGHAI).isoformat(),
            "access_method": "public_subject_and_article_pages",
            "rows": rows,
            "errors": errors[-10:],
            "limitations": [
                "财联社公开文章是新闻摘要，用于交叉核实，不替代结构化龙虎榜。",
                "文章未暴露证券代码时保留名称和原文，不猜测代码。",
            ],
        }
        error = None if rows else "no same-day public CLS LHB articles found"
        return FetchResult(payload, error)


def download_authorized_artifact(
    url: str,
    output: Path,
    *,
    bearer_token: str | None = None,
    expected_sha256: str | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    headers = {"User-Agent": "a-stock-evidence-radar/0.6"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    digest = hashlib.sha256(response.content).hexdigest()
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        raise ValueError(f"SHA256 mismatch: expected {expected_sha256}, got {digest}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(response.content)
    return {
        "url": url,
        "output": str(output),
        "bytes": len(response.content),
        "sha256": digest,
        "retrieved_at": datetime.now(SHANGHAI).isoformat(),
    }
