"""Coletor de vagas por empresa-alvo (Gupy/LinkedIn/Indeed via ddgs site:).

Para cada empresa da lista em `empresas_alvo.empresas`, monta queries
`site:gupy.io <empresa> estágio remoto` (etc), busca via ddgs e extrai os
links diretos (Gupy/LinkedIn/empresa) — dispensa API da Gupy e Playwright.

Config (config.yaml):

  empresas_alvo:
    enabled: true
    empresas:
      - "Nubank"
      - "iFood"
    queries:
      pt:
        - "site:gupy.io {empresa} estágio remoto"
        - "site:gupy.io {empresa} estágio home office"
      en:
        - "site:linkedin.com/jobs {empresa} remote internship"
"""

import logging
import time
from typing import Iterator, Optional
from urllib.parse import urlparse

from collectors import BaseCollector
from collectors.url_utils import resolve_direct_url, is_direct_url, is_job_page, is_listing_url
from models import Job, url_hash_for
from config import CONFIG

logger = logging.getLogger(__name__)

REGION_BY_SUFFIX = {"pt": "br-pt", "en": "us-en", "es": "es-es"}
SKIP_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")

# URLs de blog/artigos (não são vagas) — ex.: gupy.io/blog-do-emprego/...
SKIP_URL_HINTS = (
    "/blog", "/blog-do-emprego", "/sites-de-emprego", "/guia",
    "/educacao", "/carreira/", "/dicas", "/noticias/",
    "/insights", "/how-to-", "/tutorial", "/article", "/artigos",
)

ESTAGIO_MARKERS = (
    "estágio", "estagio", "estagiário", "estagiaria", "estagiária",
    "trainee", "aprendiz", "jovem aprendiz", "jovem talento",
    "internship", "intern position", "intern role",
)
REMOTE_MARKERS = (
    "home office", "home-office", "remoto", "remota", "remote",
    "trabalho remoto", "work from home", "wfh", "fully remote",
)


class EmpresasAlvoCollector(BaseCollector):
    name = "empresas_alvo"

    def __init__(self):
        super().__init__()
        self.cfg = CONFIG.get("empresas_alvo", {})
        self.engines = self.cfg.get("engines", ["ddgs"])
        self.timelimit = self.cfg.get("timelimit", "m")
        self.max_results = self.cfg.get("max_results_per_query", 5)
        self.budget = self.cfg.get("page_budget", 30)
        self.delay = self.cfg.get("request_delay", 2.0)
        self.exclude = tuple(self.cfg.get("exclude_domains", []))
        self.empresas = self.cfg.get("empresas", [])
        self.queries = self.cfg.get("queries", {})

    def _search_ddgs(self, query: str, region: str) -> list:
        try:
            from ddgs import DDGS
        except ImportError:
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
            logger.warning(f"empresas_alvo ddgs failed [{query[:50]}]: {type(e).__name__}")
            return []

    def _fetch_text(self, url: str) -> tuple[str, str, str]:
        import httpx
        resp = httpx.get(url, headers={"User-Agent": CONFIG["runtime"]["user_agent"]},
                         timeout=CONFIG["runtime"]["timeout"], follow_redirects=True)
        resp.raise_for_status()
        ctype = resp.headers.get("content-type", "")
        if "html" not in ctype and "text" not in ctype:
            raise ValueError(f"non-html: {ctype[:40]}")
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
        if not text or len(text) < 150:
            raise ValueError("too little text")
        return title, text, html

    def _is_estagio(self, blob: str) -> bool:
        return any(m in blob for m in ESTAGIO_MARKERS)

    def _is_remote(self, blob: str) -> bool:
        return any(m in blob for m in REMOTE_MARKERS)

    def _build_item(self, title: str, page_url: str, text: str,
                    empresa: str, html: str) -> Optional[Job]:
        blob = f"{title} {text[:5000]}".lower()
        if not self._is_estagio(blob):
            return None
        remote = self._is_remote(blob)
        tags = ["estagio", empresa.lower()]
        if remote:
            tags.append("remote")
        # Link direto (Gupy/LinkedIn/empresa)
        final_url = resolve_direct_url(page_url, html=html)
        if final_url != page_url:
            tags.append("direct")
        return Job(
            title=title[:300] or page_url,
            source=f"empresas_alvo/{empresa}",
            url=final_url,
            description=text[:5000],
            company=empresa,
            remote=remote,
            tags=tags,
            posted_at=None,
            location="Remote" if remote else "",
        )

    def _iter_queries(self):
        for empresa in self.empresas:
            for lang, templates in (self.queries or {}).items():
                region = REGION_BY_SUFFIX.get(lang, "wt-wt")
                for tpl in templates or []:
                    yield tpl.format(empresa=empresa), region, empresa

    def fetch(self) -> Iterator[Job]:
        from store import get_jobs_store
        store = get_jobs_store()  # dedup na coleta lê jobs.db
        fetched = 0

        for query, region, empresa in self._iter_queries():
            if fetched >= self.budget:
                logger.info(f"empresas_alvo budget reached ({self.budget})")
                return

            results = []
            if "ddgs" in self.engines:
                results = [(r, "ddgs") for r in self._search_ddgs(query, region)]
                time.sleep(self.delay)  # pausa entre buscas (evita rate-limit)

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
                    continue

                title = (r.get("title") or "").strip()
                try:
                    page_title, text, html = self._fetch_text(url)
                    fetched += 1
                    item = self._build_item(page_title or title, url, text, empresa, html)
                    if item is None:
                        continue
                    yield item
                except Exception as e:
                    logger.debug(f"empresas_alvo skip {url[:70]}: {type(e).__name__}")
                time.sleep(self.delay)

        self._sleep()
