"""Arbeitnow API collector."""

import logging
from typing import Iterator
from urllib.parse import urljoin

from collectors import APICollector
from models import Job
from config import CONFIG

logger = logging.getLogger(__name__)


class ArbeitnowCollector(APICollector):
    name = "arbeitnow"

    def fetch(self) -> Iterator[Job]:
        base_url = self.source_config.get("base_url", "https://www.arbeitnow.com/api/job-board-api")
        max_pages = self.source_config.get("params", {}).get("max_pages", 3)

        for page in range(max_pages):
            params = {"page": page} if page > 0 else {}
            data = self._get(base_url, params)

            # API retorna {"data": [...]} ou lista direta
            jobs_data = data.get("data", data) if isinstance(data, dict) else data

            if not jobs_data:
                break

            for item in jobs_data:
                try:
                    yield self._parse_job(item)
                except Exception as e:
                    logger.warning(f"Failed to parse Arbeitnow job: {e}")

            self._sleep()

    def _parse_job(self, item: dict) -> Job:
        # Normaliza campos
        remote = item.get("remote", False)
        if isinstance(remote, str):
            remote = remote.lower() in ("true", "yes", "1", "remote")

        tags = item.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        # Data
        posted_at = None
        for date_field in ("created_at", "date", "published_at", "posted_at"):
            if item.get(date_field):
                try:
                    from datetime import datetime
                    posted_at = datetime.fromisoformat(item[date_field].replace("Z", "+00:00"))
                    break
                except Exception:
                    pass

        return Job(
            title=item.get("title", "").strip(),
            company=item.get("company_name", "").strip(),
            location=item.get("location", "").strip(),
            remote=remote,
            url=item.get("url", "").strip(),
            description=item.get("description", "").strip(),
            source="arbeitnow",
            tags=tags,
            posted_at=posted_at,
            salary_text=item.get("salary", ""),
        )