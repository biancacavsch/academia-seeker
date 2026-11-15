"""Filtros anti-ruído: guias/listicles no academic_search e blogs em estágios.

Regressão do caso real: "How to Get Scholarships..." (score 190) e
"Cómo Encontrar una Pasantía..." (155) alertavam como se fossem oportunidades,
enquanto um CFP real da UPenn cujo título é uma pergunta ("What Is the
Relationship between...") NÃO pode ser descartado.
"""

from urllib.parse import urlparse

from collectors.search_academic import (
    GUIDE_TITLE_MARKERS,
    SKIP_URL_HINTS as ACAD_SKIP,
    SearchAcademicCollector,
)

REAL_CFP = ("Call for Papers: What Is the Relationship between Regional "
            "Integration and Digital Sovereignty?")

GUIDE_TITLES = [
    "How to Get Scholarships for Graduate School in the Humanities",
    "Bolsa de mestrado: confira as opções da ESPM",
    "Mestrado sanduíche: saiba o que é e quais são as vantagens",
    "Cómo Encontrar una Pasantía Remota en el Extranjero — Guía",
    "Becas para estudiar en el extranjero 2026: tu guía",
    "Como Passar no Mestrado da USP [Guia com Provas e Dicas 2026]",
]


# ---------- marcadores de título ----------

def test_cfp_real_como_titulo_nao_marcado():
    """CFP cujo título é a pergunta do tema não pode ser tratado como guia."""
    tl = REAL_CFP.lower()
    assert not any(m in tl for m in GUIDE_TITLE_MARKERS)


def test_titulos_de_guia_sao_marcados():
    for t in GUIDE_TITLES:
        assert any(m in t.lower() for m in GUIDE_TITLE_MARKERS), t


# ---------- _build_item ----------

def test_build_item_rejeita_guia():
    c = SearchAcademicCollector()
    for t in GUIDE_TITLES:
        item = c._build_item(t, "https://exemplo.org/artigo",
                             "texto de apoio " * 60, "bolsa", "ddgs")
        assert item is None, t


def test_build_item_aceita_cfp_real():
    c = SearchAcademicCollector()
    text = ("Call for papers. Scholars are invited to submit. "
            "Submission deadline: 15 de dezembro de 2026. ") * 20
    item = c._build_item(REAL_CFP, "https://exemplo.org/cfp/123",
                         text, "publicacao", "ddgs")
    assert item is not None
    assert item.track == "publicacao"


# ---------- filtros de caminho ----------

def _hits(url: str, hints) -> bool:
    path = urlparse(url).path.lower()
    return any(h in path for h in hints)


def test_skip_academico_cobre_guia_mas_preserva_noticias_de_edital():
    # ruído
    assert _hits("https://x.org/es/insights/how-to-find-a-remote-internship.html", ACAD_SKIP)
    assert _hits("https://revistatopicos.com.br/artigos/", ACAD_SKIP)
    assert _hits("https://x.org/silabo_sociologia_2026/temas", ACAD_SKIP)
    # editais anunciados em /noticias/ de universidade/governo são legítimos
    assert not _hits("https://www.gov.br/mec/pt-br/noticias/bolsas-abertas", ACAD_SKIP)
    assert not _hits("https://www.ufpb.br/ppgs/contents/noticias/editais", ACAD_SKIP)
    # anúncio de edital em página de notícia de evento (path comum)
    assert not _hits("https://humanidadesdigitales.net/category/noticias/convocatorias/", ACAD_SKIP)


# ---------- notícia vs chamada (search_academic _build_item) ----------

def test_build_item_rejeita_noticia_portal():
    c = SearchAcademicCollector()
    item = c._build_item(
        "Após Tarcísio dizer que Fapesp iria rever mudanças, fundação se manifesta",
        "https://g1.globo.com/sp/sao-paulo/noticia/2026/09/02/x",
        "texto da notícia " * 50, "bolsa", "ddgs")
    assert item is None


def test_build_item_aceita_chamada_mesmo_com_noticia_no_titulo():
    c = SearchAcademicCollector()
    text = "Submission deadline: 15 de dezembro de 2026. " * 20
    item = c._build_item(
        "[Notícia] CHAMADA DE TRABALHOS 2026.2",
        "https://revistas.usp.br/epigrafe/announcement/view/2173",
        text, "publicacao", "ddgs")
    assert item is not None
    assert item.track == "publicacao"


def test_build_item_rejeita_reportagem_sem_chamada():
    c = SearchAcademicCollector()
    item = c._build_item(
        "Reportagem: como funciona a bolsa Capes no exterior",
        "https://exemplo.com/reportagem/bolsa-capes",
        "texto " * 50, "bolsa", "ddgs")
    assert item is None
