"""EURAXESS RSS collector (European research jobs & fellowships)."""

import logging
import re
from typing import Iterator
from datetime import datetime

from collectors import RSSCollector
from models import Job

logger = logging.getLogger(__name__)

REMOTE_HINTS = (
    "remote", "remote work", "work from home", "fully remote",
    "home office", "home-office", "telework", "teleworking",
    "travail à distance", "teletrabajo", "trabalho remoto",
)


class EuraxessCollector(RSSCollector):
    name = "euraxess"

    def fetch(self) -> Iterator[Job]:
        url = self.source_config.get("url", "https://euraxess.ec.europa.eu/job-feed")
        feed = self._parse_feed(url)

        for entry in feed.entries:
            try:
                yield self._parse_entry(entry)
            except Exception as e:
                logger.warning(f"Failed to parse EURAXESS entry: {e}")

        self._sleep()

    def _parse_entry(self, entry) -> Job:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        description = entry.get("summary", entry.get("description", "")).strip()
        published = entry.get("published_parsed") or entry.get("updated_parsed")

        posted_at = None
        if published:
            posted_at = datetime(*published[:6])

        text = f"{title} {description}".lower()
        remote = any(h in text for h in REMOTE_HINTS)

        company = self._extract_org(title, description)
        location = self._extract_location(description)

        return Job(
            title=title,
            company=company,
            location=location or "Europe (see posting)",
            remote=remote,
            url=link,
            description=description,
            source="euraxess",
            tags=["euraxess", "research"],
            posted_at=posted_at,
        )

    def _extract_org(self, title: str, desc: str) -> str:
        patterns = [
            r"at\s+([A-Z][A-Za-z\s&.,'\-()]+?)(?:\s*[|,]|$)",
            r"([A-Z][A-Za-z\s&.,'\-()]*?(?:University|Institute|Centre|Center|Laboratory|College|School|Museum|Library|Foundation|Agency))",
        ]
        for pat in patterns:
            m = re.search(pat, f"{title} {desc}")
            if m:
                return m.group(1).strip()
        return "Research Institution (EURAXESS)"

    def _extract_location(self, desc: str) -> str:
        m = re.search(
            r"\b(Portugal|Spain|France|Germany|Italy|Netherlands|Belgium|Sweden|Norway|"
            r"Denmark|Finland|Ireland|Poland|Austria|Greece|Czechia|Romania|Hungary|"
            r"Croatia|Estonia|Latvia|Lithuania|Slovakia|Slovenia|United Kingdom|UK|"
            r"Brazil|Brasil|USA|Canada)\b",
            desc,
        )
        return m.group(1) if m else ""
