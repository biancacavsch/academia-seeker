"""Coletor de vagas via HTML com seletores configuráveis (httpx + bs4).

Dispensa Playwright (indisponível no Pi). Usado para portais de estágio
com HTML estável (ex.: vagas.com.br). Configurado via config.yaml:

  - name: exemplo
    type: html_job
    kind: estagio
    url: "https://..."
    params:
      selector: "li.vaga"
      title_selector: "h2.cargo a"
      link_selector: "h2.cargo a"
      description_selector: ".detalhes p"
      company_selector: ".emprVaga"
      location_selector: ".vaga-local"
      remote: true            # assume remoto se o portal já filtra home office
      max_pages: 2
"""

import logging
from datetime import datetime
from typing import Iterator, Optional
from urllib.parse import urljoin

from collectors import BaseCollector
from collectors.url_utils import resolve_direct_url, is_direct_url
from models import Job
from config import CONFIG

logger = logging.getLogger(__name__)

REMOTE_MARKERS = (
    "home office", "home-office", "remoto", "remota", "remote",
    "trabalho remoto", "teletrabalho", "work from home", "wfh",
    "trabalho à distância", "trabalho a distancia", "trabajo remoto",
    "teletrabajo", "fully remote", "100% remoto",
)
PRESENCIAL_MARKERS = (
    "presencial", "on-site", "onsite", "in-person", "in office",
    "no escritório", "na sede",
)


class JobHTMLCollector(BaseCollector):
    """Coleta vagas de uma listagem HTML usando seletores do config."""

    def fetch(self) -> Iterator[Job]:
        import httpx
        from bs4 import BeautifulSoup

        url = self.source_config.get("url")
        if not url:
            logger.warning(f"{self.name}: no URL configured")
            return

        p = self.source_config.get("params", {})
        selector = p.get("selector", "li.vaga, article, .job, .item")
        title_sel = p.get("title_selector", "h2 a, h3 a, .title a, a")
        link_sel = p.get("link_selector", title_sel)
        desc_sel = p.get("description_selector", ".detalhes p, .desc, .summary, p")
        company_sel = p.get("company_selector", ".emprVaga, .company, .empresa")
        location_sel = p.get("location_selector", ".vaga-local, .local, .location")
        assume_remote = p.get("remote", False)
        max_pages = p.get("max_pages", 1)
        kind = self.source_config.get("kind", "estagio")
        resolve_direct = p.get("resolve_direct", True)

        client = httpx.Client(
            timeout=CONFIG["runtime"]["timeout"],
            headers={"User-Agent": CONFIG["runtime"]["user_agent"]},
            follow_redirects=True,
        )
        try:
            for page in range(1, max_pages + 1):
                page_url = url
                if page > 1:
                    sep = "&" if "?" in url else "?"
                    page_url = f"{url}{sep}page={page}"
                try:
                    resp = client.get(page_url)
                    resp.raise_for_status()
                except Exception as e:
                    logger.warning(f"{self.name}: fetch failed page {page}: {e}")
                    break

                soup = BeautifulSoup(resp.text, "html.parser")
                elements = soup.select(selector)
                if not elements:
                    if page == 1:
                        logger.warning(f"{self.name}: selector '{selector}' matched 0 elements")
                    break

                for el in elements:
                    try:
                        job = self._parse_element(
                            el, url, title_sel, link_sel, desc_sel,
                            company_sel, location_sel, assume_remote, kind)
                        if job:
                            # Link direto: baixa a página da vaga se for interna
                            # e extrai o link para Gupy/empresa (evita agregador)
                            if resolve_direct and not is_direct_url(job.url):
                                try:
                                    r2 = client.get(job.url)
                                    if r2.status_code == 200:
                                        direct = resolve_direct_url(job.url, html=r2.text)
                                        if direct != job.url:
                                            job.url = direct
                                            if "direct" not in job.tags:
                                                job.tags.append("direct")
                                except Exception as e:
                                    logger.debug(f"{self.name}: direct-resolve fail: {type(e).__name__}")
                            yield job
                    except Exception as e:
                        logger.debug(f"{self.name}: parse skip: {type(e).__name__}: {e}")

                self._sleep()
        finally:
            client.close()

    def _detect_remote(self, blob: str, assume_remote: bool) -> bool:
        has_remote = any(m in blob for m in REMOTE_MARKERS)
        has_presencial = any(m in blob for m in PRESENCIAL_MARKERS)
        if has_remote:
            return True
        if has_presencial:
            return False
        return assume_remote

    def _parse_element(self, el, base_url, title_sel, link_sel, desc_sel,
                       company_sel, location_sel, assume_remote, kind) -> Optional[Job]:
        title_el = el.select_one(title_sel)
        if not title_el:
            return None
        title = title_el.get_text(" ", strip=True)
        if not title:
            return None

        link_el = el.select_one(link_sel) or title_el
        href = link_el.get("href", "") if link_el else ""
        # Fallback: o próprio elemento é o link (ex.: <a class="card"> com <h1> dentro)
        if not href and el.name == "a" and el.get("href"):
            href = el.get("href")
        url = urljoin(base_url, href) if href else base_url

        desc_el = el.select_one(desc_sel)
        description = desc_el.get_text(" ", strip=True) if desc_el else ""

        company_el = el.select_one(company_sel)
        company = company_el.get_text(" ", strip=True) if company_el else ""

        location_el = el.select_one(location_sel)
        location = location_el.get_text(" ", strip=True) if location_el else ""

        blob = f"{title} {description} {location}".lower()
        remote = self._detect_remote(blob, assume_remote)

        tags = [kind] if kind else []
        if remote:
            tags.append("remote")

        return Job(
            title=title[:300],
            source=self.name,
            url=url,
            description=description[:6000],
            company=company[:200],
            remote=remote,
            location=location[:200],
            tags=tags,
            posted_at=None,  # vira now() em __post_init__
        )
