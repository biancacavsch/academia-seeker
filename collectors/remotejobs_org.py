"""RemoteJobs.org API collector."""

import logging
from typing import Iterator, Optional

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
                    job = self._parse_job(item)
                    if job:
                        yield job
                except Exception as e:
                    logger.warning(f"Failed to parse RemoteJobs.org job: {e}")

            offset += limit
            if len(jobs_data) < limit:
                break

            self._sleep()

    @staticmethod
    def _text(value, default: str = "") -> str:
        """Converte campos da API (que podem virar None) em texto seguro."""
        if value is None:
            return default
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, (dict, list, bool)):
            return default
        return str(value).strip()

    @staticmethod
    def _int(value) -> Optional[int]:
        """Salário pode chegar como int, float, string ou None."""
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def _parse_job(self, item: dict) -> Optional[Job]:
        title = self._text(item.get("title"))
        url = self._text(item.get("url"))
        if not title or not url:
            # A API devolve itens incompletos; não viram lixo no banco.
            return None

        company = item.get("company")
        company_name = self._text(
            company.get("name") if isinstance(company, dict) else company
        )

        category = item.get("category")
        cat_name = self._text(
            category.get("name") if isinstance(category, dict) else category
        )
        tags = [cat_name] if cat_name else []

        posted_at = None
        raw_date = self._text(item.get("posted_at"))
        if raw_date:
            try:
                from datetime import datetime
                posted_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except Exception:
                pass

        return Job(
            title=title,
            company=company_name,
            location=self._text(item.get("location"), "Remote"),
            remote=True,  # RemoteJobs.org só tem vagas remotas
            url=url,
            description=self._text(item.get("description")),
            source="remotejobs_org",
            tags=tags,
            posted_at=posted_at,
            salary_min=self._int(item.get("salary_min")),
            salary_max=self._int(item.get("salary_max")),
            salary_text=self._text(item.get("salary_text")),
        )