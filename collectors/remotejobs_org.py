"""RemoteJobs.org API collector."""

import logging
from typing import Iterator

from collectors import APICollector
from models import Job

logger = logging.getLogger(__name__)


class RemoteJobsOrgCollector(APICollector):
    name = "remotejobs_org"

    def fetch(self) -> Iterator[Job]:
        base_url = self.source_config.get("base_url", "https://remotejobs.org/api/v1/jobs")
        params = self.source_config.get("params", {})
        limit = params.get("limit", 50)
        max_pages = params.get("max_pages", 3)

        offset = 0
        for page in range(max_pages):
            req_params = {"limit": limit, "offset": offset}
            if params.get("category"):
                req_params["category"] = params["category"]
            if params.get("keyword"):
                req_params["search"] = params["keyword"]

            data = self._get(base_url, req_params)
            jobs_data = data.get("data", []) if isinstance(data, dict) else data

            if not jobs_data:
                break

            for item in jobs_data:
                try:
                    yield self._parse_job(item)
                except Exception as e:
                    logger.warning(f"Failed to parse RemoteJobs.org job: {e}")

            offset += limit
            if len(jobs_data) < limit:
                break

            self._sleep()

    def _parse_job(self, item: dict) -> Job:
        company = item.get("company", {})
        company_name = company.get("name", "") if isinstance(company, dict) else str(company)

        category = item.get("category", {})
        cat_name = category.get("name", "") if isinstance(category, dict) else str(category)
        tags = [cat_name] if cat_name else []

        job_type = item.get("type", "")
        remote = True  # RemoteJobs.org só tem vagas remotas

        posted_at = None
        if item.get("posted_at"):
            try:
                from datetime import datetime
                posted_at = datetime.fromisoformat(item["posted_at"].replace("Z", "+00:00"))
            except Exception:
                pass

        salary_min = item.get("salary_min")
        salary_max = item.get("salary_max")
        salary_text = item.get("salary_text", "")

        return Job(
            title=item.get("title", "").strip(),
            company=company_name.strip(),
            location=item.get("location", "Remote").strip(),
            remote=remote,
            url=item.get("url", "").strip(),
            description=item.get("description", "").strip(),
            source="remotejobs_org",
            tags=tags,
            posted_at=posted_at,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_text=salary_text,
        )