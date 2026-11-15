"""Academic web-search collector (ddgs + Marginalia). Academic tracks only.

Fluxo por query: busca → dedup de URLs pelo url_hash no banco (só baixa o
inédito) → fetch (httpx) → extração de texto (trafilatura, fallback bs4) →
classificação em bolsa/publicacao/evento → AcademicItem → score/store/alerta
existentes (com trava de 30 dias e pré-requisito de edital aberto).

Páginas fechadas (ENCERRADO) são descartadas antes de armazenar.
Páginas JS-heavy/PDF são puladas graciosamente.
"""

import logging
import time
from typing import Iterator, Optional
from urllib.parse import urlparse

from collectors import BaseCollector
from models import AcademicItem, url_hash_for
from deadlines import extract_closing_date, is_closed
from config import CONFIG

logger = logging.getLogger(__name__)

TRACK_BY_QUERY_PREFIX = {
    "bolsas": "bolsa",
    "publicacoes": "publicacao",
    "eventos": "evento",
}
REGION_BY_SUFFIX = {"pt": "br-pt", "en": "us-en", "es": "es-es"}

TRACK_MARKERS = {
    "bolsa": (
        "bolsa", "scholarship", "fellowship", "edital", "beca",
        "intercâmbio", "intercambio", "exchange", "sanduíche", "sanduiche",
        "studentship", "stipend", "grant",
    ),
    "publicacao": (
        "call for papers", "chamada de artigos", "chamada de trabalhos",
        "convocatoria", "special issue", "dossiê", "dossie", "chapter",
        "manuscript", "artigos", "articles", "artículos",
    ),
    "evento": (
        "conference", "conferência", "conferencia", "congresso", "congreso",
        "workshop", "symposium", "simpósio", "simposio", "seminar",
        "seminário", "seminario", "summer school", "colloquium", "webinar",
    ),
}

SKIP_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip")

# Caminhos informativos (não são chamada/editais abertos). Mantém /noticias/:
# portais de notícia de universidade/governo anunciam editais de verdade.
SKIP_URL_HINTS = (
    "/artigos", "/silabo", "/insights", "/how-to-", "/dicas", "/guia",
    "/faq", "/perguntas-frequentes", "/o-que-e", "/tutorial",
)

# Títulos de guia/listicle ("como fazer X") — artigo informativo, não oportunidade.
# CUIDADO com "what is "/"o que é ": causam falso positivo em CFPs cujo título
# é a própria pergunta do tema (ex.: UPenn "Call for Papers: What Is the...").
GUIDE_TITLE_MARKERS = (
    "how to", "saiba o que", "confira", "dicas para", "guia", "guía", "guías",
    "guide to", "passo a passo", "step by step",
    "cómo encontrar", "como encontrar", "best ways", "top tips", "explore,",
)

# Notícias/artigos de portal (NÃO são chamada) — bloqueio por PALAVRAS no
# título e no caminho da URL, sem lista de domínios.
# Ex.: g1.globo.com/sp/sao-paulo/noticia/2026/... (notícia sobre a Fapesp)
NEWS_TITLE_MARKERS = (
    "notícia", "noticia", "notícias", "noticias", "reportagem",
    "análise", "analise", "editorial", "opinião", "opiniao",
    "coluna", "veja ", "entenda ", "saiba mais",
    # Verbos de notícia (com espaço para não matar títulos legítimos)
    "após ", "diz ", "dizem ", "afirma ", "anuncia ", "revela ", "explica ",
    "sobre ", "manifesta ", "pronuncia ", "comenta ", "reage ", "defende ",
    "critica ", "aponta ", "destaca ", "ressalta ", "comenta ",
)
NEWS_PATH_HINTS = ("/noticia/",)   # singular: não pega /noticias/ de universidade

# Exceção: se o título É uma chamada explícita, mantém mesmo vindo de notícia
# (ex.: "[Notícia] CHAMADA DE TRABALHOS 2026.2" é um CFP real)
CALL_TITLE_MARKERS = (
    "chamada", "call for", "convocatoria", "convocatória", "edital",
    "cfp", "submissão", "submision", "submission", "deadline", "prazo",
    "inscriç", "inscrip", "chamada de trabalhos", "call for papers",
)


class SearchAcademicCollector(BaseCollector):
    name = "search_academic"

    def __init__(self):
        super().__init__()
        self.cfg = CONFIG.get("academic_search", {})
        self.engines = self.cfg.get("engines", ["ddgs"])
        self.timelimit = self.cfg.get("timelimit", "m")
        self.max_results = self.cfg.get("max_results_per_query", 10)
        self.budget = self.cfg.get("page_budget", 100)
        self.delay = self.cfg.get("request_delay", 2.0)
        self.exclude = tuple(self.cfg.get("exclude_domains", []))
        self.queries = self.cfg.get("queries", {})

    # ---------- engines ----------

    def _search_ddgs(self, query: str, region: str) -> list:
        try:
            from ddgs import DDGS
            from ddgs.exceptions import RatelimitException
        except ImportError:
            logger.warning("ddgs not installed, skipping DDG engine")
            return []
        try:
            with DDGS() as d:
                out = []
                for r in d.text(query, region=region,
                                timelimit=self.timelimit,
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

    def _search_marginalia(self, query: str) -> list:
        import httpx
        try:
            resp = httpx.get(
                "https://api2.marginalia-search.com/search",
                params={"query": query, "count": self.max_results},
                headers={"API-Key": "public",
                         "User-Agent": CONFIG["runtime"]["user_agent"]},
                timeout=CONFIG["runtime"]["timeout"],
            )
            if resp.status_code in (429, 503):
                logger.warning("marginalia rate-limited (public key), skipping")
                return []
            resp.raise_for_status()
            return [{
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("description", ""),
            } for r in resp.json().get("results", [])]
        except Exception as e:
            logger.warning(f"marginalia query failed [{query[:40]}]: {type(e).__name__}: {e}")
            return []

    # ---------- page fetch + extract ----------

    def _fetch_text(self, url: str) -> tuple[str, str]:
        """Retorna (title, text). Levanta exceção se a página não serve."""
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
        return title, text

    # ---------- classify ----------

    def _classify(self, title: str, text: str, expected: str) -> str:
        blob = f"{title} {text[:5000]}".lower()
        scores = {t: sum(1 for m in markers if m in blob)
                  for t, markers in TRACK_MARKERS.items()}
        best = max(scores, key=lambda k: scores[k])
        if scores[best] == 0:
            return expected
        return best

    def _build_item(self, title: str, url: str, text: str,
                    expected_track: str, engine: str) -> Optional[AcademicItem]:
        # Guia/listicle ("como encontrar bolsa") não é oportunidade aberta
        tl = (title or "").lower()
        if any(m in tl for m in GUIDE_TITLE_MARKERS):
            logger.debug(f"skipped guide: {title[:60]}")
            return None
        # Notícia de portal (g1 etc.) — bloqueada por palavras, a menos que
        # o título seja ele mesmo uma chamada explícita
        if any(m in tl for m in NEWS_TITLE_MARKERS) and \
                not any(m in tl for m in CALL_TITLE_MARKERS):
            logger.debug(f"skipped news: {title[:60]}")
            return None
        full = f"{title}\n{text[:8000]}"
        if is_closed(full):
            logger.debug(f"skipped closed: {title[:60]}")
            return None
        track = self._classify(title, text, expected_track)
        closing = extract_closing_date(full)
        event_type = {"bolsa": "bolsa", "publicacao": "cfp",
                      "evento": "evento"}.get(track, "evento")
        return AcademicItem(
            title=title[:300] or url,
            source=f"search/{engine}",
            category=track,
            url=url,
            description=text[:8000],
            posted_at=None,  # sem data confiável → now (filtro de idade mantém)
            deadline_at=closing,
            venue="",
            event_type=event_type,
            submission_deadline=closing,
            track=track,
            tags=[track, engine],
        )

    # ---------- main ----------

    def _iter_queries(self):
        for group, queries in (self.queries or {}).items():
            prefix = group.split("_")[0]
            expected = TRACK_BY_QUERY_PREFIX.get(prefix, "evento")
            suffix = group.split("_")[-1]
            region = REGION_BY_SUFFIX.get(suffix, "wt-wt")
            for q in queries or []:
                yield q, expected, region

    def fetch(self) -> Iterator[AcademicItem]:
        from store import get_academic_store
        store = get_academic_store()  # dedup na coleta lê academic.db
        fetched = 0

        for query, expected, region in self._iter_queries():
            if fetched >= self.budget:
                logger.info(f"page budget reached ({self.budget})")
                return
            results = []
            if "ddgs" in self.engines:
                results += [(r, "ddgs") for r in self._search_ddgs(query, region)]
                time.sleep(1.0)
            if "marginalia" in self.engines:
                results += [(r, "marginalia") for r in self._search_marginalia(query)]
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
                path = urlparse(url).path.lower()
                if any(h in path for h in SKIP_URL_HINTS):
                    continue
                # Notícia de portal (caminho /noticia/) — não é chamada
                if any(h in path for h in NEWS_PATH_HINTS):
                    continue
                if store.get_item(url_hash_for(url)) is not None:
                    continue  # já conhecida — não baixa de novo

                title = (r.get("title") or "").strip()
                try:
                    page_title, text = self._fetch_text(url)
                    fetched += 1
                    item = self._build_item(page_title or title, url, text,
                                            expected, engine)
                    if item is None:
                        continue
                    yield item
                except Exception as e:
                    logger.debug(f"fetch skip {url[:80]}: {type(e).__name__}")
                time.sleep(self.delay)

        self._sleep()
