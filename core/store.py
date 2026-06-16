from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from astrbot.api import logger

from .spider import NewsItem


class NewsStore:
    """Persistent store for news cache and seen IDs.

    Data is stored as a JSON file in the AstrBot plugin data directory.
    """

    def __init__(
        self, data_dir: str | Path, filename: str = "star_resonance_news.json"
    ) -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / filename

        # In-memory state
        self.version: int = 1
        self.seen_ids: set[str] = set()
        self.cached_items: list[dict[str, Any]] = []
        self.subscriptions: dict[str, dict[str, Any]] = {}
        self.last_success_at: str = ""
        self.last_error: str = ""

    async def load(self) -> None:
        """Load data from disk. Initializes empty if file doesn't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            await self.save()
            return

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.version = int(raw.get("version", 1))
            raw_seen = raw.get("seen_ids", [])
            self.seen_ids = set(str(s) for s in raw_seen if s)
            self.cached_items = list(raw.get("cache", []))
            raw_subscriptions = raw.get("subscriptions", {})
            self.subscriptions = (
                raw_subscriptions if isinstance(raw_subscriptions, dict) else {}
            )
            self.last_success_at = str(raw.get("last_success_at") or "")
            self.last_error = str(raw.get("last_error") or "")
        except Exception as exc:
            logger.error(f"[星痕共鸣新闻] 读取缓存失败，将使用空数据: {exc}")
            self._reset()

    async def save(self) -> None:
        """Atomically save data to disk."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {
            "version": self.version,
            "seen_ids": sorted(self.seen_ids),
            "cache": self.cached_items[-100:],  # Keep last 100 items
            "subscriptions": self.subscriptions,
            "last_success_at": self.last_success_at,
            "last_error": self.last_error,
        }

        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def _reset(self) -> None:
        self.seen_ids = set()
        self.cached_items = []
        self.subscriptions = {}
        self.last_success_at = ""
        self.last_error = ""

    # --- Seen IDs ---

    def get_seen_ids(self) -> set[str]:
        """Return the set of already-seen news IDs."""
        return self.seen_ids

    def mark_seen(self, ids: list[str]) -> None:
        """Add news IDs to the seen set."""
        self.seen_ids.update(ids)

    def is_seen(self, news_id: str) -> bool:
        """Check if a news ID has already been seen."""
        return news_id in self.seen_ids

    # --- Cache ---

    def get_cached_items(self) -> list[NewsItem]:
        """Return cached items as NewsItem objects."""
        return [NewsItem(**item) for item in self.cached_items]

    def set_cached_items(self, items: list[NewsItem]) -> None:
        """Replace cached items with new data."""
        self.cached_items = [
            {
                "idx": item.idx,
                "title": item.title,
                "url": item.url,
                "published_at": item.published_at,
                "author": item.author,
                "summary": item.summary,
                "tag_ids": item.tag_ids,
            }
            for item in items
        ]

    def initialize_cache(self, items: list[NewsItem]) -> None:
        """Initialize cache from fetched items and mark all as seen.

        Used on first startup to avoid pushing history.
        """
        self.set_cached_items(items)
        self.seen_ids.update(item.idx for item in items if item.idx)

    def update_cache(self, items: list[NewsItem]) -> None:
        """Replace cache and mark new item IDs as seen."""
        self.set_cached_items(items)
        for item in items:
            if item.idx:
                self.seen_ids.add(item.idx)

    # --- Status ---

    def set_last_success(self, at: str | None = None) -> None:
        """Record last successful fetch timestamp."""
        if at is None:
            at = datetime.now(timezone.utc).isoformat()
        self.last_success_at = at
        self.last_error = ""

    def set_last_error(self, error: str) -> None:
        """Record last fetch error message."""
        self.last_error = error

    # --- Subscriptions ---

    def get_enabled_subscription_sessions(self) -> list[str]:
        return [
            session
            for session, data in self.subscriptions.items()
            if isinstance(data, dict) and data.get("enabled", False)
        ]

    def is_subscription_enabled(self, session: str) -> bool:
        data = self.subscriptions.get(session, {})
        return isinstance(data, dict) and bool(data.get("enabled", False))

    def set_subscription(self, session: str, enabled: bool) -> None:
        session = str(session or "").strip()
        if not session:
            return
        data = self.subscriptions.get(session, {})
        if not isinstance(data, dict):
            data = {}
        data["enabled"] = enabled
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.subscriptions[session] = data
