"""Archives Gig RSS collector (tag digital-humanities)."""

import logging
from typing import Iterator
from datetime import datetime

from collectors import RSSCollector
from models import Job

logger = logging.getLogger(__name__)


class ArchivesGigDHCollector(RSSCollector):
    name = "archives_gig_dh"

    def fetch(self) -> Iterator[Job]:
        url = self.source_config.get("url", "https://archivesgig.com/tag/digital-humanities/feed/")
        feed = self._parse_feed(url)

        for entry in feed.entries:
            try:
                yield self._parse_entry(entry)
            except Exception as e:
                logger.warning(f"Failed to parse Archives Gig entry: {e}")

        self._sleep()

    def _parse_entry(self, entry) -> Job:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        description = entry.get("summary", entry.get("description", "")).strip()
        published = entry.get("published_parsed") or entry.get("updated_parsed")

        posted_at = None
        if published:
            posted_at = datetime(*published[:6])

        tags = []
        for tag in entry.get("tags", []):
            if isinstance(tag, dict):
                tags.append(tag.get("term", ""))
            else:
                tags.append(str(tag))

        company = self._extract_company(title, description)

        return Job(
            title=title,
            company=company,
            location="Remote / Various",
            remote=True,
            url=link,
            description=description,
            source="archives_gig_dh",
            tags=tags,
            posted_at=posted_at,
        )

    def _extract_company(self, title: str, desc: str) -> str:
        import re
        patterns = [
            r"at\s+([A-Z][A-Za-z\s&.,'-]+)(?:\s*[|,]|$)",
            r"@\s*([A-Z][A-Za-z\s&.,'-]+)",
            r"^([A-Z][A-Za-z\s&.,'-]+):\s",
            r"\(([A-Z][A-Za-z\s&.,'-]+)\)",
        ]
        text = f"{title} {desc}"
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return m.group(1).strip()
        return "Archives/Museum Institution"