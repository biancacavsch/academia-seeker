"""H-Net announcements collector."""

import logging
from typing import Iterator, Optional
from datetime import datetime

from collectors.academic_base import AcademicRSSCollector
from models import AcademicItem

logger = logging.getLogger(__name__)


class HNetCollector(AcademicRSSCollector):
    name = "hnet_announcements"

    def __init__(self):
        super().__init__()
        self.keywords = self.source_config.get("params", {}).get("keywords", [
            "digital humanities", "philosophy of technology", "science communication",
            "public humanities", "digital scholarship", "cultural heritage",
            "history of technology", "media studies", "critical theory",
            "philosophy", "humanities", "technology", "communication"
        ])

    def fetch(self) -> Iterator[AcademicItem]:
        url = self.source_config.get("url", "https://networks.h-net.org/rss/announcements")
        feed = self._parse_feed(url)

        for entry in feed.entries:
            try:
                item = self._parse_hnet_entry(entry)
                if item:
                    yield item
            except Exception as e:
                logger.warning(f"Failed to parse H-Net entry: {e}")

        self._sleep()

    def _parse_hnet_entry(self, entry) -> Optional[AcademicItem]:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        description = entry.get("summary", entry.get("description", "")).strip()
        published = entry.get("published_parsed") or entry.get("updated_parsed")

        posted_at = None
        if published:
            posted_at = datetime(*published[:6])

        # H-Net categories in tags
        tags = []
        for tag in entry.get("tags", []):
            if isinstance(tag, dict):
                tags.append(tag.get("term", "").lower())
            else:
                tags.append(str(tag).lower())

        # Match against our keywords
        matched_kw = self._match_keywords(title, description, tags)
        if not matched_kw:
            return None  # Skip non-relevant announcements

        deadline_at = self._extract_deadline(description)
        event_type = self._detect_event_type(title, description)
        is_virtual = self._detect_virtual(title, description)

        item = AcademicItem(
            title=title,
            source=self.name,
            category="event",
            url=link,
            description=description,
            tags=tags + matched_kw,
            posted_at=posted_at,
            deadline_at=deadline_at,
            event_type=event_type,
            is_virtual=is_virtual,
            matched_keywords=matched_kw,
        )
        return item

    def _match_keywords(self, title: str, desc: str, tags: list[str]) -> list[str]:
        text = f"{title} {desc} {' '.join(tags)}".lower()
        matched = []
        for kw in self.keywords:
            if kw.lower() in text:
                matched.append(kw)
        return matched