"""Base collector classes."""

from abc import ABC, abstractmethod
from typing import Iterator
import time
import logging

from models import Job, AcademicItem, BaseItem
from config import CONFIG

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    name: str = "base"
    rate_limit: float = 1.0

    def __init__(self):
        self.config = CONFIG["sources"]
        self.source_config = next((s for s in self.config if s["name"] == self.name), {})
        self.rate_limit = self.source_config.get("rate_limit", 1.0)

    @abstractmethod
    def fetch(self) -> Iterator[BaseItem]:
        """Yield BaseItem objects (Job or AcademicItem)."""
        pass

    def _sleep(self):
        time.sleep(self.rate_limit)


class APICollector(BaseCollector):
    """Base para coletores de API REST."""

    def __init__(self):
        super().__init__()
        import httpx
        self.client = httpx.Client(
            timeout=CONFIG["runtime"]["timeout"],
            headers={"User-Agent": CONFIG["runtime"]["user_agent"]},
            follow_redirects=True,
        )

    def _get(self, url: str, params: dict = None) -> dict:
        for attempt in range(CONFIG["runtime"]["max_retries"]):
            try:
                resp = self.client.get(url, params=params)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                logger.warning(f"{self.name} attempt {attempt+1} failed: {e}")
                if attempt == CONFIG["runtime"]["max_retries"] - 1:
                    raise
                time.sleep(2 ** attempt)
        return {}

    def close(self):
        self.client.close()


class RSSCollector(BaseCollector):
    """Base para coletores de feed RSS/Atom."""

    def __init__(self):
        super().__init__()
        import feedparser
        self.feedparser = feedparser

    def _parse_feed(self, url: str):
        return self.feedparser.parse(url)


# Re-export academic base classes for registry
from collectors.academic_base import AcademicRSSCollector, AcademicHTMLCollector