"""Digital Humanities Now RSS collector."""

import logging
import re
from typing import Iterator
from datetime import datetime

from collectors import RSSCollector
from models import Job

logger = logging.getLogger(__name__)


class DHNowCollector(RSSCollector):
    name = "dhnow_jobs"

    def fetch(self) -> Iterator[Job]:
        url = self.source_config.get("url", "https://digitalhumanitiesnow.org/category/news/job/feed/")
        feed = self._parse_feed(url)

        for entry in feed.entries:
            try:
                yield self._parse_entry(entry)
            except Exception as e:
                logger.warning(f"Failed to parse DHNow entry: {e}")

        self._sleep()

    def _parse_entry(self, entry) -> Job:
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        description = entry.get("summary", entry.get("description", "")).strip()
        published = entry.get("published_parsed") or entry.get("updated_parsed")

        posted_at = None
        if published:
            posted_at = datetime(*published[:6])

        # Extrai tags do conteúdo se houver categorias
        tags = []
        for tag in entry.get("tags", []):
            if isinstance(tag, dict):
                tags.append(tag.get("term", ""))
            else:
                tags.append(str(tag))

        # Tenta extrair empresa/instituição do título ou descrição
        company = self._extract_company(title, description)

        return Job(
            title=title,
            company=company,
            location="Remote / Various",
            remote=True,  # DHNow posts são geralmente acadêmicos, muitos remote
            url=link,
            description=description,
            source="dhnow_jobs",
            tags=tags,
            posted_at=posted_at,
        )

    def _extract_company(self, title: str, desc: str) -> str:
        # Padrões comuns: "Job: Title at Institution" ou "Institution: Title"
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
        return "Academic Institution"