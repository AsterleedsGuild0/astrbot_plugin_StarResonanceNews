from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any

import httpx

from astrbot.api import logger


@dataclass
class NewsItem:
    """Single news entry from the WMP API."""

    idx: str
    title: str = ""
    url: str = ""
    published_at: str = ""
    author: str = ""
    summary: str = ""
    tag_ids: str = ""


class CnSpider:
    """Spider for Tencent WMP news API (StarResonance CN server)."""

    url = "https://apps.game.qq.com/wmp/v3.1/"
    src_name = "国服官网"

    # Tag ID mapping
    TAG_MAP: dict[str, str] = {
        "最新": "136243",
        "公告": "136246",
        "新闻": "136245",
        "活动": "136247",
    }

    DETAIL_URL_TEMPLATE = (
        "https://gm.qq.com/web202503/news-detail.html?newsid={news_id}"
    )

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    async def fetch(
        self,
        category: str = "最新",
        page_size: int = 5,
    ) -> list[NewsItem]:
        """Fetch latest news items from the WMP API.

        Args:
            category: News category name (最新/公告/新闻/活动).
            page_size: Number of items to fetch.

        Returns:
            Parsed list of NewsItem.

        Raises:
            httpx.HTTPError: On HTTP request failure.
            ValueError: On JSON parse or structure error.
        """
        tag_id = self.TAG_MAP.get(category, self.TAG_MAP["最新"])
        params = {
            "p0": 440,
            "p1": "searchNewsKeywordsList",
            "page": 1,
            "pagesize": page_size,
            "order": "sIdxTime",
            "type": "iTag",
            "id": tag_id,
            "source": "web_pc",
        }

        timeout = max(5, int(self._config.get("request_timeout_seconds", 15)))
        verify_ssl = bool(self._config.get("request_verify_ssl", False))
        proxy = str(self._config.get("request_proxy", "") or "").strip()

        async with httpx.AsyncClient(verify=verify_ssl, proxy=proxy or None) as session:
            resp = await session.get(
                self.url,
                params=params,
                timeout=timeout,
            )
        resp.raise_for_status()

        data: dict[str, Any] = resp.json()
        return self._parse_response(data)

    async def fetch_article_text(self, url: str) -> str:
        """Fetch and extract readable text from a news detail page."""
        if not url:
            raise ValueError("新闻详情链接为空")

        news_id = _extract_news_id(url)
        if news_id:
            try:
                text = await self.fetch_article_text_by_id(news_id)
                if text:
                    return text
            except Exception as e:
                logger.warning(
                    f"[星痕共鸣新闻] 详情接口提取失败，回退到 HTML 提取: {type(e).__name__}: {e}"
                )

        timeout = max(5, int(self._config.get("request_timeout_seconds", 15)))
        verify_ssl = bool(self._config.get("request_verify_ssl", False))
        proxy = str(self._config.get("request_proxy", "") or "").strip()

        async with httpx.AsyncClient(verify=verify_ssl, proxy=proxy or None) as session:
            resp = await session.get(url, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = resp.encoding or "utf-8"
        text = _extract_visible_text(resp.text)
        if not text:
            raise ValueError("未能从新闻详情页提取正文")
        return text

    async def fetch_article_text_by_id(self, news_id: str) -> str:
        """Fetch article detail from Tencent WMP detail API by news ID."""
        news_id = str(news_id or "").strip()
        if not news_id:
            raise ValueError("新闻 ID 为空")

        timeout = max(5, int(self._config.get("request_timeout_seconds", 15)))
        verify_ssl = bool(self._config.get("request_verify_ssl", False))
        proxy = str(self._config.get("request_proxy", "") or "").strip()
        params = {
            "p0": 440,
            "source": "web_pc",
            "id": news_id,
        }
        async with httpx.AsyncClient(verify=verify_ssl, proxy=proxy or None) as session:
            resp = await session.get(
                "https://apps.game.qq.com/wmp/v3.1/public/searchNews.php",
                params=params,
                timeout=timeout,
            )
        resp.raise_for_status()
        data = _parse_search_obj(resp.text)
        msg = data.get("msg")
        if not isinstance(msg, dict):
            raise ValueError("详情接口响应缺少 msg 字段")

        title = str(msg.get("sTitle") or "").strip()
        content_html = str(msg.get("sContent") or "")
        desc = str(msg.get("sDesc") or "").strip()
        text = _extract_visible_text(content_html)
        parts = [part for part in [title, desc if desc != title else "", text] if part]
        article_text = "\n".join(parts)
        if not article_text:
            raise ValueError("详情接口未返回正文")
        return article_text

    @classmethod
    def _parse_response(cls, data: dict[str, Any]) -> list[NewsItem]:
        """Parse WMP API response into NewsItem list."""
        msg = data.get("msg")
        if not isinstance(msg, dict):
            raise ValueError("响应缺少 msg 字段")

        result = msg.get("result")
        if not isinstance(result, list):
            raise ValueError("响应 msg.result 不是列表")

        items: list[NewsItem] = []
        for entry in result:
            if not isinstance(entry, dict):
                logger.warning(f"[星痕共鸣新闻] 跳过非字典条目: {type(entry)}")
                continue

            news_id = str(entry.get("iNewsId") or "")
            title = str(entry.get("sTitle") or "无标题新闻")
            published_at = str(entry.get("sIdxTime") or entry.get("sCreated") or "")
            author = str(entry.get("sAuthor") or "星痕共鸣")
            summary = str(entry.get("sDesc") or "")
            tag_ids = str(entry.get("sTagIds") or "")
            url = cls._build_detail_url(news_id)

            items.append(
                NewsItem(
                    idx=news_id,
                    title=title,
                    url=url,
                    published_at=published_at,
                    author=author,
                    summary=summary,
                    tag_ids=tag_ids,
                )
            )

        return items

    @classmethod
    def _build_detail_url(cls, news_id: str) -> str:
        if not news_id:
            return ""
        return cls.DETAIL_URL_TEMPLATE.format(news_id=news_id)

    def format_items(
        self,
        items: list[NewsItem],
        prefix: str = "星痕共鸣国服官网新闻",
        include_time: bool = True,
        include_summary: bool = False,
    ) -> str:
        """Format news items into a display string.

        Args:
            items: News items to format.
            prefix: Header prefix.
            include_time: Whether to include publish time.
            include_summary: Whether to include summary text.

        Returns:
            Formatted string for display.
        """
        if not items:
            return "暂无新闻数据"

        lines: list[str] = [f"> {prefix}"]
        for i, item in enumerate(items, 1):
            line = f"{i}. {item.title}"
            if include_time and item.published_at:
                line += f"\n   {item.published_at}"
            if include_summary and item.summary:
                line += f"\n   {item.summary}"
            if item.url:
                line += f"\n   {item.url}"
            lines.append(line)

        return "\n".join(lines)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg", "canvas"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg", "canvas"}:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        data = data.strip()
        if data:
            self._chunks.append(data)

    def text(self) -> str:
        return "\n".join(self._chunks)


def _extract_visible_text(html: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(html)
    text = unescape(parser.text())
    lines = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if len(line) < 2:
            continue
        # Drop common page chrome and duplicated fragments.
        if line in seen:
            continue
        if line.lower() in {"javascript", "css"}:
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines)


def _extract_news_id(url: str) -> str:
    match = re.search(r"(?:newsid=|/)(\d{5,})(?:\D|$)", url)
    return match.group(1) if match else ""


def _parse_search_obj(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("var searchObj="):
        text = text.removeprefix("var searchObj=")
    if text.endswith(";"):
        text = text[:-1]
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("详情接口响应不是 JSON 对象")
    return data
