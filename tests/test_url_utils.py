"""Testes do resolvedor de links diretos (collectors/url_utils.py).

Garante que o extrator só aceite páginas de VAGA específica (Gupy/LinkedIn/
Indeed reais) e rejeite buscas, salários, perfis e shares — o problema dos
"links diretos" que apontavam para páginas genéricas de agregadores.
"""

from collectors.url_utils import (
    extract_direct_links,
    is_direct_url,
    is_job_page,
    is_listing_url,
    resolve_direct_url,
)

GUPY_JOB = "https://elife.gupy.io/jobs/12814560"
AGGREGATOR = "https://workei.com.br/1125-estagio-midias-sociais-elifegroup"


# ---------- domínios ----------

def test_is_direct_domain():
    assert is_direct_url(GUPY_JOB)
    assert is_direct_url("https://www.linkedin.com/jobs/view/x-123")
    assert is_direct_url("https://www.indeed.com/viewjob?jk=abc")
    assert not is_direct_url("https://workei.com.br/1125-estagio")
    assert not is_direct_url("")


# ---------- is_job_page: páginas de vaga real ----------

def test_job_pages_accepted():
    assert is_job_page(GUPY_JOB)
    assert is_job_page("https://empregos.gupy.io/job/12814560")
    assert is_job_page("https://www.indeed.com/viewjob?jk=abc123")
    assert is_job_page("https://br.linkedin.com/jobs/view/estagio-x-4066573218")
    assert is_job_page("https://www.linkedin.com/jobs/search/?currentJobId=99")
    assert is_job_page("https://www.glassdoor.com/job-listing/j?pos=1&vjs=3")


def test_search_and_junk_pages_rejected():
    # buscas/listagens
    assert not is_job_page("https://www.indeed.com/jobs?q=remote")
    assert not is_job_page("https://portal.gupy.io/job-search/term=est%C3%A1gio")
    assert not is_job_page("https://br.linkedin.com/jobs/est%C3%A1gio-home-office-vagas")
    # salário (caso real que vazou como "direct")
    assert not is_job_page(
        "https://www.glassdoor.com/Salary/Imagine-Learning-Teacher-"
        "Salaries-E393172_D_KO17,24.htm"
    )
    # listagem de busca do Glassdoor (SRCH)
    assert not is_job_page(
        "https://www.glassdoor.com.br/Vaga/brasil-estagio-remoto-vagas-SRCH_IL.0,13.htm"
    )
    # perfis / compartilhamentos
    assert not is_job_page("https://www.linkedin.com/company/vagascom")
    assert not is_job_page("https://www.linkedin.com/cws/share?url=x")
    # blog
    assert not is_job_page("https://www.gupy.io/blog-do-emprego/estagio")


# ---------- extract_direct_links ----------

def test_extract_keeps_gupy_drops_junk():
    html = f"""
    <html><body>
      <a href="{GUPY_JOB}">Candidatar-se</a>
      <a href="https://www.linkedin.com/cws/share?url=x">Share</a>
      <a href="https://www.indeed.com/jobs?q=remote">Indeed busca</a>
      <a href="https://www.glassdoor.com/Salary/x-Salary-E1_KO1.htm">Salário</a>
      <a href="https://portal.gupy.io/job-search/term=estagio">Busca Gupy</a>
      <a href="https://workei.com.br/interno">agregador interno</a>
    </body></html>
    """
    assert extract_direct_links(html, AGGREGATOR) == [GUPY_JOB]


def test_extract_empty_when_only_junk():
    html = '<a href="https://www.indeed.com/jobs?q=remote">busca</a>'
    assert extract_direct_links(html, AGGREGATOR) == []


# ---------- resolve_direct_url ----------

def test_resolve_returns_gupy_link():
    html = f'<a href="{GUPY_JOB}">Inscrever-se</a>'
    assert resolve_direct_url(AGGREGATOR, html=html) == GUPY_JOB


def test_resolve_falls_back_to_original_when_only_junk():
    html = '<a href="https://www.indeed.com/jobs?q=remote">busca</a>'
    assert resolve_direct_url(AGGREGATOR, html=html) == AGGREGATOR


def test_resolve_keeps_direct_job_page_as_is():
    assert resolve_direct_url(GUPY_JOB) == GUPY_JOB


def test_resolve_search_page_tries_html_for_better_link():
    # page_url é busca (não é vaga) → extrai link de vaga do html se houver
    page = "https://www.indeed.com/jobs?q=internship"
    html = f'<a href="{GUPY_JOB}">ver vaga</a>'
    assert resolve_direct_url(page, html=html) == GUPY_JOB


# ---------- is_listing_url: listagens/homepages em QUALQUER domínio ----------

def test_listings_rejected_any_domain():
    # casos reais que passavam como "vaga" (score 115-140)
    assert is_listing_url("https://www.melhoresempregos.com/estagio/vagas-em-br/")
    assert is_listing_url("https://www.melhoresempregos.com/remoto/vagas-de-marketing/")
    assert is_listing_url("https://www.querohome.com.br/category/estagio/")
    assert is_listing_url("https://slis-jobline.simmons.edu/category/internships/")
    assert is_listing_url("https://direitoremoto.com.br/")          # homepage
    assert is_listing_url("https://portal.example.com/search/?q=vaga")


def test_real_job_pages_never_listing():
    assert not is_listing_url("https://www.catho.com.br/vagas/estagio-em-redes/39160984")
    assert not is_listing_url(GUPY_JOB)
    assert not is_listing_url(
        "https://radarhomeoffice.com/vaga/elifegroup-estagio-em-midias-sociais-monitoramento-remoto")
    assert not is_listing_url(
        "https://www.querohome.com.br/estagio-em-midias-sociais-monitoramento/")
    # vaga legítima com /home no caminho NÃO pode ser descartada
    assert not is_listing_url("https://example.com/jobs/home-office-intern-123")
