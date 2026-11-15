"""Estágio web-search collector (ddgs) — vagas de estágio remoto/home office.

Busca por termos de estágio (PT/EN) via DuckDuckGo, baixa páginas inéditas
(só novas, dedup pelo url_hash), extrai texto (trafilatura/bs4) e monta Job
remoto com tags de estágio. Cobertura BR + internacional.

É o principal coletor de estágios: dispensa Playwright (indisponível no Pi)
e reaproveita o ddgs que já funciona no projeto.
"""

import logging
import time
from typing import Iterator, Optional
from urllib.parse import urlparse

from collectors import BaseCollector
from collectors.url_utils import (
    resolve_direct_url, extract_direct_links, is_direct_url, is_job_page,
    is_listing_url,
)
from models import Job, url_hash_for
from config import CONFIG

logger = logging.getLogger(__name__)

REGION_BY_SUFFIX = {"pt": "br-pt", "en": "us-en", "es": "es-es"}

SKIP_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")

# URLs de blog/artigos (não são vagas) — ex.: /blog/, /dicas/, /guia/
SKIP_URL_HINTS = (
    "/blog", "/blog-do-emprego", "/sites-de-emprego", "/guia",
    "/educacao", "/carreira/", "/dicas", "/noticias/",
    "/insights", "/how-to-", "/tutorial", "/article", "/artigos",
)

# Termos que indicam que a página É de estágio (valida antes de montar Job)
ESTAGIO_MARKERS = (
    "estágio", "estagio", "estagiário", "estagiaria", "estagiária",
    "estagiarios", "trainee", "aprendiz", "jovem aprendiz", "jovem talento",
    "programa de estágio", "vaga de estágio", "estágio supervisionado",
    "internship", "intern position", "intern role", "summer intern",
)

# Termos de remoto (EN/PT/ES)
REMOTE_MARKERS = (
    "home office", "home-office", "remoto", "remota", "remotamente",
    "remote", "trabalho remoto", "teletrabalho", "work from home", "wfh",
    "trabalho à distância", "trabalho a distancia", "trabajo remoto",
    "teletrabajo", "fully remote", "100% remoto", "online internship",
)

# Termos de presencial (para descartar quando não há sinal de remoto)
PRESENCIAL_MARKERS = (
    "presencial", "on-site", "onsite", "in-person", "in office",
    "no escritório", "na sede", "híbrido presencial",
)


class EstagioSearchCollector(BaseCollector):
    name = "estagio_search"

    def __init__(self):
        super().__init__()
        self.cfg = CONFIG.get("estagio_search", {})
        self.engines = self.cfg.get("engines", ["ddgs"])
        self.timelimit = self.cfg.get("timelimit", "m")
        self.max_results = self.cfg.get("max_results_per_query", 8)
        self.budget = self.cfg.get("page_budget", 40)
        self.delay = self.cfg.get("request_delay", 2.0)
        self.exclude = tuple(self.cfg.get("exclude_domains", []))
        self.queries = self.cfg.get("queries", {})

    # ---------- search ----------

    def _search_ddgs(self, query: str, region: str) -> list:
        try:
            from ddgs import DDGS
        except ImportError:
            logger.warning("ddgs not installed, skipping DDG engine")
            return []
        try:
            with DDGS() as d:
                out = []
                for r in d.text(query, region=region, timelimit=self.timelimit,
                                max_results=self.max_results):
                    out.append({
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    })
                return out
        except Exception as e:
            logger.warning(f"ddgs query failed [{query[:40]}]: {type(e).__name__}: {e}")
            return []

    # ---------- page fetch + extract ----------

    def _fetch_text(self, url: str) -> tuple[str, str, str]:
        """Retorna (title, text, html). Levanta exceção se a página não serve."""
        import httpx
        resp = httpx.get(url, headers={"User-Agent": CONFIG["runtime"]["user_agent"]},
                         timeout=CONFIG["runtime"]["timeout"], follow_redirects=True)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        if "html" not in ctype and "text" not in ctype:
            raise ValueError(f"non-html content: {ctype[:40]}")
        html = resp.text[:2_000_000]

        title, text = "", ""
        try:
            import trafilatura
            text = trafilatura.extract(html, include_comments=False) or ""
            try:
                meta = trafilatura.extract_metadata(html)
                if meta and meta.title:
                    title = meta.title
            except Exception:
                pass
        except ImportError:
            pass
        if not text:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            if not title and soup.title:
                title = soup.title.get_text(strip=True)
            text = soup.get_text(separator=" ", strip=True)[:100000]
        if not text or len(text) < 200:
            raise ValueError("too little text extracted")
        return title, text, html

    # ---------- classify ----------

    def _is_estagio(self, blob: str) -> bool:
        return any(m in blob for m in ESTAGIO_MARKERS)

    def _detect_remote(self, blob: str) -> bool:
        """Remoto se houver sinal de remoto; False só se claramente presencial
        sem sinal de remoto; senão assume remoto (as queries já miram home office)."""
        has_remote = any(m in blob for m in REMOTE_MARKERS)
        has_presencial = any(m in blob for m in PRESENCIAL_MARKERS)
        if has_remote:
            return True
        if has_presencial:
            return False
        return True  # ambíguo → otimista (query já é de estágio remoto)

    def _build_item(self, title: str, url: str, text: str, engine: str,
                    html: str = None) -> Optional[Job]:
        blob = f"{title} {text[:6000]}".lower()
        if not self._is_estagio(blob):
            return None  # não é estágio → descarta
        remote = self._detect_remote(blob)
        tags = ["estagio"]
        if remote:
            tags.append("remote")

        # Link direto: se a página tem link para Gupy/LinkedIn/empresa, usa ele
        final_url = resolve_direct_url(url, html=html)
        if final_url != url:
            tags.append("direct")

        return Job(
            title=title[:300] or url,
            source=f"estagio_search/{engine}",
            url=final_url,
            description=text[:6000],
            company="",
            remote=remote,
            tags=tags,
            posted_at=None,  # sem data confiável → now (filtro de idade mantém)
            location="Remote" if remote else "",
        )

    # ---------- main ----------

    def _iter_queries(self):
        for lang, queries in (self.queries or {}).items():
            region = REGION_BY_SUFFIX.get(lang, "wt-wt")
            for q in queries or []:
                yield q, region

    def fetch(self) -> Iterator[Job]:
        from store import get_jobs_store
        store = get_jobs_store()  # dedup na coleta lê jobs.db
        fetched = 0

        for query, region in self._iter_queries():
            if fetched >= self.budget:
                logger.info(f"estagio page budget reached ({self.budget})")
                return

            results = []
            if "ddgs" in self.engines:
                results = [(r, "ddgs") for r in self._search_ddgs(query, region)]
                time.sleep(1.0)

            for r, engine in results:
                if fetched >= self.budget:
                    return
                url = (r.get("url") or "").strip()
                if not url or not url.startswith("http"):
                    continue
                host = urlparse(url).netloc.lower()
                if self.exclude and host.endswith(self.exclude):
                    continue
                if url.lower().split("?")[0].endswith(SKIP_EXTENSIONS):
                    continue
                # Pula artigos/blog (não são vagas reais)
                path = urlparse(url).path.lower()
                if any(h in path for h in SKIP_URL_HINTS):
                    continue
                # Listagem/homepage de portal (qualquer domínio) nunca é vaga
                if is_listing_url(url):
                    continue
                # Em portal direto (Gupy/LinkedIn/Indeed), só aceita página de
                # vaga específica — rejeita buscas/listagens (ex.: /jobs?q=)
                if is_direct_url(url) and not is_job_page(url):
                    continue
                if store.get_item(url_hash_for(url)) is not None:
                    continue  # já conhecida — não baixa de novo

                title = (r.get("title") or "").strip()
                try:
                    page_title, text, html = self._fetch_text(url)
                    fetched += 1
                    item = self._build_item(page_title or title, url, text, engine, html)
                    if item is None:
                        continue
                    yield item
                except Exception as e:
                    logger.debug(f"estagio fetch skip {url[:80]}: {type(e).__name__}")
                time.sleep(self.delay)

        self._sleep()
