"""Adzuna API collector."""

import logging
import os
from typing import Iterator

from collectors import APICollector
from models import Job
from config import CONFIG

logger = logging.getLogger(__name__)


class AdzunaCollector(APICollector):
    name = "adzuna"

    # Sinais de trabalho remoto em EN/PT/ES (remote_only é filtro rígido)
    REMOTE_HINTS = (
        "remote", "remote work", "work from home", "fully remote",
        "home office", "home-office",
        "trabalho remoto", "totalmente remoto", "100% remoto",
        "trabalho à distância", "trabalho a distancia",
        "trabajo remoto", "teletrabajo", "trabajo a distancia",
    )

    def __init__(self):
        super().__init__()
        self.app_id = os.getenv("ADZUNA_APP_ID", "")
        self.app_key = os.getenv("ADZUNA_APP_KEY", "")
        params = self.source_config.get("params", {})
        self.countries = params.get("countries") or [params.get("country", "br")]

    def fetch(self) -> Iterator[Job]:
        if not self.app_id or not self.app_key:
            logger.warning(f"{self.name}: ADZUNA_APP_ID/APP_KEY not configured in .env")
            return

        base_url = self.source_config.get("base_url", "https://api.adzuna.com/v1/api/jobs")
        params = self.source_config.get("params", {})
        max_pages = params.get("max_pages", 2)
        what = params.get("what", "")
        what_or = params.get("what_or", "")
        where = params.get("where", "")
        category = params.get("category", "")
        results_per_page = params.get("results_per_page", 50)

        for country in self.countries:
            for page in range(1, max_pages + 1):
                url = f"{base_url}/{country}/search/{page}"
                req_params = {
                    "app_id": self.app_id,
                    "app_key": self.app_key,
                    "results_per_page": results_per_page,
                }
                if what:
                    req_params["what"] = what
                if what_or:
                    req_params["what_or"] = what_or
                if where:
                    req_params["where"] = where
                if category:
                    req_params["category"] = category

                try:
                    data = self._get(url, req_params)
                except Exception as e:
                    # País/URL com erro (ex.: 404 de país inválido) não pode
                    # derrubar o coletor inteiro — pula para o próximo país
                    logger.warning(
                        f"{self.name}: {country} page {page} falhou "
                        f"({type(e).__name__}) — pulando país")
                    break
                jobs_data = data.get("results", []) if isinstance(data, dict) else data

                if not jobs_data:
                    break

                for item in jobs_data:
                    try:
                        yield self._parse_job(item)
                    except Exception as e:
                        logger.warning(f"Failed to parse Adzuna job: {e}")

                if len(jobs_data) < results_per_page:
                    break

                self._sleep()

    def _parse_job(self, item: dict) -> Job:
        company = item.get("company", {})
        company_name = company.get("display_name", "") if isinstance(company, dict) else str(company)

        location = item.get("location", {})
        loc_name = location.get("display_name", "") if isinstance(location, dict) else str(location)

        category = item.get("category", {})
        cat_name = category.get("label", "") if isinstance(category, dict) else str(category)

        tags = []
        if cat_name:
            tags.append(cat_name)

        # Remote detection (EN/PT/ES) — remote_only é filtro rígido
        remote = False
        desc_lower = str(item.get("description", "")).lower()
        contract_type = str(item.get("contract_type", "")).lower()
        if any(h in desc_lower for h in self.REMOTE_HINTS):
            remote = True
        if any(h in contract_type for h in ("remote", "home office", "home-office")):
            remote = True

        posted_at = None
        if item.get("created"):
            try:
                from datetime import datetime
                posted_at = datetime.fromisoformat(item["created"].replace("Z", "+00:00"))
            except Exception:
                pass

        salary_min = item.get("salary_min")
        salary_max = item.get("salary_max")
        salary_text = ""
        if salary_min and salary_max:
            salary_text = f"{salary_min}-{salary_max} {item.get('salary_currency', 'BRL')}/year"
        elif salary_min:
            salary_text = f"from {salary_min} {item.get('salary_currency', 'BRL')}/year"
        elif salary_max:
            salary_text = f"up to {salary_max} {item.get('salary_currency', 'BRL')}/year"

        return Job(
            title=item.get("title", "").strip(),
            company=company_name.strip(),
            location=loc_name.strip(),
            remote=remote,
            url=item.get("redirect_url", "").strip(),
            description=item.get("description", "").strip(),
            source=self.name,
            tags=tags,
            posted_at=posted_at,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_text=salary_text,
        )


class AdzunaEstagioCollector(AdzunaCollector):
    """Adzuna configurado para termos de estágio (fonte própria em config)."""
    name = "adzuna_estagio"