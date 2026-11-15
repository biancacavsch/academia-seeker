"""Jooble API collector."""

import logging
import os
from typing import Iterator

from collectors import APICollector
from models import Job
from config import CONFIG

logger = logging.getLogger(__name__)


class JoobleCollector(APICollector):
    name = "jooble"

    def __init__(self):
        super().__init__()
        self.api_key = os.getenv("JOOBLE_API_KEY", "")

    def fetch(self) -> Iterator[Job]:
        if not self.api_key:
            logger.warning(f"{self.name}: JOOBLE_API_KEY not configured in .env")
            return

        base_url = "https://jooble.org/api"
        params = self.source_config.get("params", {})
        what = params.get("what", "")
        where = params.get("where", "")
        page = params.get("page", 1)
        max_pages = params.get("max_pages", 3)

        for p in range(page, page + max_pages):
            req_params = {
                "key": self.api_key,
                "page": p,
            }
            if what:
                req_params["what"] = what
            if where:
                req_params["where"] = where

            data = self._post(base_url, req_params)
            jobs_data = data.get("jobs", []) if isinstance(data, dict) else data

            if not jobs_data:
                break

            for item in jobs_data:
                try:
                    yield self._parse_job(item)
                except Exception as e:
                    logger.warning(f"Failed to parse Jooble job: {e}")

            if len(jobs_data) < 20:  # Jooble default page size
                break

            self._sleep()

    def _post(self, url: str, params: dict) -> dict:
        for attempt in range(CONFIG["runtime"]["max_retries"]):
            try:
                resp = self.client.post(url, json=params)
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                logger.warning(f"{self.name} attempt {attempt+1} failed: {e}")
                if attempt == CONFIG["runtime"]["max_retries"] - 1:
                    raise
                time.sleep(2 ** attempt)
        return {}

    def _parse_job(self, item: dict) -> Job:
        location = item.get("location", "")
        remote = "remote" in str(item.get("description", "")).lower() or "home office" in str(item.get("description", "")).lower()

        posted_at = None
        if item.get("updated"):
            try:
                from datetime import datetime
                posted_at = datetime.fromisoformat(item["updated"].replace("Z", "+00:00"))
            except Exception:
                pass

        salary_text = item.get("salary", "")

        return Job(
            title=item.get("title", "").strip(),
            company=item.get("company", "").strip(),
            location=location.strip(),
            remote=remote,
            url=item.get("link", "").strip(),
            description=item.get("description", "").strip(),
            source="jooble",
            tags=[item.get("source", "")] if item.get("source") else [],
            posted_at=posted_at,
            salary_text=salary_text,
        )