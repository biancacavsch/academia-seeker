"""UPenn Call for Papers collector (category pages, structured deadlines).

Site: call-for-papers.sas.upenn.edu (Drupal 7, server-rendered — plain HTTP).
Per entry: h2.node-title > a (title+link), .field-name-field-cfp-updated
(posted), .field-name-field-cfp-contact-name (venue/org),
.field-name-field-cfp-due-date (submission deadline),
.field-name-field-cfp-content (description).
Category slugs configured in config.yaml (add more as needed).
"""

import logging
from datetime import datetime
from typing import Iterator, Optional
from urllib.parse import urljoin

from collectors import APICollector
from models import AcademicItem

logger = logging.getLogger(__name__)

BASE = "https://call-for-papers.sas.upenn.edu"


class UpennCfpCollector(APICollector):
    name = "upenn_cfp"

    def __init__(self):
        super().__init__()
        params = self.source_config.get("params", {})
        self.categories = params.get("categories", [
            "humanities-computing-and-the-internet",
            "science-and-culture",
        ])
        self.max_pages = params.get("max_pages", 3)

    def fetch(self) -> Iterator[AcademicItem]:
        for cat in self.categories:
            yield from self._fetch_category(cat)
            self._sleep()

    def _fetch_category(self, cat: str) -> Iterator[AcademicItem]:
        for page in range(self.max_pages):
            url = f"{BASE}/category/{cat}"
            params = {"page": page} if page > 0 else None
            try:
                resp = self.client.get(url, params=params)
                if resp.status_code == 404:
                    logger.warning(f"{self.name}: unknown category '{cat}', skipping")
                    return
                resp.raise_for_status()
            except Exception as e:
                logger.warning(f"{self.name} [{cat}] p{page} failed: {e}")
                return

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "html.parser")
            articles = soup.select("article.node-cfp")
            if not articles:
                return

            for art in articles:
                try:
                    item = self._parse_article(art, cat)
                    if item:
                        yield item
                except Exception as e:
                    logger.debug(f"Failed to parse UPenn article: {e}")

    def _parse_article(self, art, cat: str) -> Optional[AcademicItem]:
        a = art.select_one("h2.node-title a")
        if not a:
            return None
        title = a.get_text(strip=True)
        link = urljoin(BASE, a.get("href", ""))

        def field(cls: str) -> str:
            el = art.select_one(f".{cls} .field-item")
            return el.get_text(" ", strip=True) if el else ""

        updated = field("field-name-field-cfp-updated")
        venue = field("field-name-field-cfp-contact-name")
        due = field("field-name-field-cfp-due-date")
        content = field("field-name-field-cfp-content")

        posted_at = self._parse_due(updated)
        deadline = self._parse_due(due)

        return AcademicItem(
            title=title,
            source=self.name,
            category="publicacao",
            url=link,
            description=content[:8000] or title,
            tags=["upenn", "cfp", cat],
            posted_at=posted_at,
            deadline_at=deadline,
            venue=venue,
            event_type="cfp",
            submission_deadline=deadline,
            track="publicacao",
        )

    @staticmethod
    def _parse_due(text: str) -> Optional[datetime]:
        """'Sunday, September 20, 2026' (opcionalmente com ' - 12:30pm')."""
        text = (text or "").split("-")[0].strip()
        for fmt in ("%A, %B %d, %Y", "%A, %b %d, %Y", "%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                pass
        return None
