"""Utilitários para extrair links diretos (Gupy/LinkedIn/empresa) de páginas.

Resolve o problema dos agregadores: quando a página baixada contém link para
um destino candidatável (Gupy, LinkedIn, Indeed, site da empresa), retorna
esse link direto em vez da URL intermediária do agregador.
"""

import logging
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)

# Domínios "diretos" — onde a vaga é realmente candidatável
DIRECT_DOMAINS = (
    "gupy.io",
    "linkedin.com",
    "indeed.com",
    "glassdoor.",
    "catho.com.br",
    "infojobs.com.br",
)

# Hosts que indicam link interno do próprio agregador (não vale como direto)
SELF_HOST_HINTS = (
    "99jobs.com",
    "vagas.com.br",
    "trabalhabrasil.com.br",
    "workei.com.br",
    "querohome.com.br",
    "radarhomeoffice.com",
    "buscoemprego",
)

# Subcaminhos que indicam link de VAGA (prioridade alta)
JOB_PATH_HINTS = (
    "/job/", "/jobs/", "/job-", "/vaga", "/position", "/vacancy",
    "/opportunit", "/estagio", "/internship", "/viewjob",
)

# Subcammmhos que NÃO são vaga (perfil de empresa, blog, compartilhar, etc)
NOT_JOB_PATH_HINTS = (
    "/company/", "/companies/", "/about", "/blog", "/profile",
    "/team", "/people", "/careers-page", "/home",
    # LinkedIn share/tracking (não são vaga)
    "/cws/share", "/sharing/", "/sharearticle", "/comm/",
    "/feed/", "/pulse/", "/mynetwork/", "/checkpoint",
    # Buscas/listagens e páginas de salário (não são vaga específica)
    "/job-search", "/salary", "/salaries", "/busca",
)

# Páginas de LISTAGEM (qualquer domínio): índice de vagas, categoria, homepage.
# Ex.: melhoresempregos.com/estagio/vagas-em-br/, querohome/category/estagio/
LISTING_PATH_HINTS = (
    "/category/", "/tag/", "/categorias/", "/categories/",
    "/vagas-de-", "/vagas-em-", "/busca-de-", "/listagem", "/lista-de-",
    "/results", "/search/",
)

# Parâmetros de query que indicam página de BUSCA (não vaga específica)
SEARCH_QUERY_MARKERS = ("q=", "query=", "keywords=", "search=", "term=")


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def is_direct_url(url: str) -> bool:
    """True se a URL aponta para um destino candidatável (Gupy/LinkedIn/etc)."""
    h = _host(url)
    if not h:
        return False
    return any(d in h for d in DIRECT_DOMAINS)


def is_aggregator_host(url: str) -> bool:
    h = _host(url)
    return any(a in h for a in SELF_HOST_HINTS)


def is_listing_url(url: str) -> bool:
    """True se a URL é uma LISTAGEM/homepage de portal (nunca uma vaga específica).

    Vale para QUALQUER domínio — resolve o caso de índices como
    melhoresempregos.com/estagio/vagas-em-br/ ou querohome/category/estagio/
    passarem como se fossem vagas em páginas de domínios não-diretos.
    """
    try:
        p = urlparse(url)
    except Exception:
        return False
    path = p.path.lower()
    if path.strip("/") == "":        # homepage nunca é vaga
        return True
    # Só padrões de listagem — NÃO reusa NOT_JOB_PATH_HINTS intencionalmente:
    # ele contém "/home", que apareceria em vagas legítimas
    # (ex.: /jobs/home-office-intern).
    return any(h in path for h in LISTING_PATH_HINTS)


def is_job_page(url: str) -> bool:
    """True se a URL parece ser a PÁGINA DE UMA VAGA específica (candidatável).

    Rejeita páginas que não são vaga: buscas/listagens (indeed.com/jobs?q=...,
    linkedin slug sem id, gupy job-search), salários (glassdoor /Salary/),
    perfis de empresa e blogs. Evita que o resolvedor troque a URL do
    agregador por uma página genérica de busca.
    """
    try:
        p = urlparse(url)
    except Exception:
        return False
    path = p.path.lower()
    query = p.query.lower()
    host = p.netloc.lower()

    if any(h in path for h in NOT_JOB_PATH_HINTS):
        return False
    if "srch" in path:  # listagens do Glassdoor (...-SRCH_IL...)
        return False

    # LinkedIn: só vaga real — /jobs/view/..., id numérico ou currentJobId
    if "linkedin.com" in host:
        if "/jobs/view" in path:
            return True
        if "currentjobid=" in query:
            return True
        if "/jobs/" in path:
            last = path.rstrip("/").rsplit("/", 1)[-1]
            if last.isdigit() or last.split("-")[-1].isdigit():
                return True
        return False

    # Indeed: só /viewjob?jk=... (não /jobs?q=... nem /cmp/...)
    if "indeed.com" in host:
        return "viewjob" in path or "jk=" in query

    # Página de busca genérica (?q=, ?keywords=, ?term=...) sem id de vaga
    if any(m in query for m in SEARCH_QUERY_MARKERS) and "jk=" not in query:
        return False

    # Precisa parecer página de vaga (allowlist de caminhos)
    return any(h in path for h in JOB_PATH_HINTS)


def extract_direct_links(html: str, base_url: str) -> list:
    """Retorna URLs 'diretas' (Gupy/LinkedIn/etc) presentes no HTML da página.

    Mantém apenas links que parecem ser de VAGA específica (is_job_page):
    descarta perfis de empresa (/company/), blogs, shares do LinkedIn,
    buscas (indeed.com/jobs?q=..., gupy job-search) e páginas de salário.
    """
    from bs4 import BeautifulSoup
    found = []
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return found

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        full = urljoin(base_url, href)
        if not full.startswith("http"):
            continue
        if not is_direct_url(full):
            continue
        if not is_job_page(full):
            continue
        if full not in found:
            found.append(full)
    return found


def resolve_direct_url(page_url: str, html: str = None,
                       fetch_html=None) -> str:
    """Retorna o link direto se existir, senão a própria page_url.

    - Se page_url já é direto E é página de vaga, retorna ela.
    - Se html fornecido, procura links diretos nele.
    - Se fetch_html fornecido (callable), baixa page_url e procura.
    """
    if is_direct_url(page_url) and is_job_page(page_url):
        return page_url

    if html is None and fetch_html is not None:
        try:
            html = fetch_html(page_url)
        except Exception as e:
            logger.debug(f"resolve_direct: fetch fail {page_url[:60]}: {type(e).__name__}")
            html = None

    if html:
        direct = extract_direct_links(html, page_url)
        if direct:
            return direct[0]

    return page_url


def extract_company_site(html: str, base_url: str) -> str:
    """Tenta extrair o site oficial da empresa de links/canônicos no HTML."""
    from bs4 import BeautifulSoup
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return ""

    # canonical / og:site
    for sel in [('link', {'rel': 'canonical'}), ('meta', {'property': 'og:site_name'})]:
        el = soup.find(*sel)
        if el:
            v = el.get("href") or el.get("content") or ""
            if v.startswith("http") and not is_aggregator_host(v):
                return v
    return ""
