"""Remotive API collector."""

import logging
from typing import Iterator

from collectors import APICollector
from models import Job

logger = logging.getLogger(__name__)


class RemotiveCollector(APICollector):
    name = "remotive"

    def fetch(self) -> Iterator[Job]:
        base_url = self.source_config.get("base_url", "https://remotive.com/api/remote-jobs")
        params = self.source_config.get("params", {})
        category = params.get("category", "")
        max_pages = params.get("max_pages", 5)

        # Remotive API não tem paginação nativa, retorna tudo
        # Filtramos localmente por categoria se necessário
        data = self._get(base_url)
        jobs_data = data.get("jobs", []) if isinstance(data, dict) else data

        categories_filter = set(c.strip().lower() for c in category.split(",")) if category else set()

        for item in jobs_data:
            try:
                job = self._parse_job(item)
                if categories_filter and job.tags:
                    job_cats = {t.lower() for t in job.tags}
                    if not job_cats & categories_filter:
                        continue
                yield job
            except Exception as e:
                logger.warning(f"Failed to parse Remotive job: {e}")

        self._sleep()

    def _parse_job(self, item: dict) -> Job:
        tags = item.get("tags", [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]

        # Categoria do Remotive
        category = item.get("category", "")
        if category:
            tags.append(category)

        remote = item.get("job_type", "").lower() == "remote" or True  # Remotive é só remote

        posted_at = None
        if item.get("publication_date"):
            try:
                from datetime import datetime
                posted_at = datetime.fromisoformat(item["publication_date"].replace("Z", "+00:00"))
            except Exception:
                pass

        return Job(
            title=item.get("title", "").strip(),
            company=item.get("company_name", "").strip(),
            location=item.get("candidate_required_location", "Remote").strip(),
            remote=remote,
            url=item.get("url", "").strip(),
            description=item.get("description", "").strip(),
            source="remotive",
            tags=tags,
            posted_at=posted_at,
            salary_text=f"{item.get('salary', '')}".strip(),
        )