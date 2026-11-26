"""Regressão: gate de oportunidade calibrável (ruído real da 1ª rodada)."""

from models import AcademicItem, Job
from relevance import (
    check_opportunity, deduplicate, dedup_key, domain_of, normalize_title,
)
from config import deep_merge


def _acad(title, source="ach_rss", desc="", category="event"):
    return AcademicItem(
        title=title, source=source, category=category,
        url="https://example.org/post/1", description=desc,
    )


# ---------- blocklists ----------

def test_eleicoes_do_ach_sao_bloqueadas():
    ok, reason = check_opportunity(_acad("ACH 2026 Elections"))
    assert not ok
    assert "blocked title" in reason


def test_portraits_e_newsletter_sao_bloqueados():
    for title in (
        "Portraits in DH: Marisa Parham and AADHum",
        "November Updates from the ACH",
        "Welcoming Our New Co-Deputy Editors",
        "Open Letter on Net Neutrality",
    ):
        ok, reason = check_opportunity(_acad(title))
        assert not ok, (title, reason)


def test_dominio_bloqueado():
    item = AcademicItem(
        title="Call for Papers: DH 2027", source="search/ddgs", category="cfp",
        url="https://en.wikipedia.org/wiki/Digital_humanities",
    )
    ok, reason = check_opportunity(item)
    assert not ok
    assert "blocked domain" in reason


def test_url_noticia_bloqueada():
    item = AcademicItem(
        title="Bolsa em humanidades digitais", source="search/ddgs",
        category="bolsa", url="https://g1.globo.com/sp/noticia/2026/11/bolsa.html",
    )
    ok, _ = check_opportunity(item)
    assert not ok


# ---------- gate de oportunidade ----------

def test_chamada_valida_passa():
    for title in (
        "Call for Papers: Digital Humanities 2027",
        "Edital de bolsa mestrado em humanidades digitais",
        "CFP: chamada aberta",
        "Conferência Internacional de Humanidades Digitais — inscrições abertas",
        "Bolsa de mestrado em história",
    ):
        ok, reason = check_opportunity(_acad(title))
        assert ok, (title, reason)


def test_post_institucional_sem_sinal_e_rejeitado():
    ok, reason = check_opportunity(_acad("ACH-Supported Student Experiences at DH 2018"))
    assert not ok
    assert reason == "filtered: not an opportunity"


def test_fonte_curada_aceita_sinal_na_descricao():
    title = "Viral Texts as Signals of Inherited Reading Practices"
    desc = "We invite submissions for a special issue. Deadline 30/01/2027."
    ok, _ = check_opportunity(_acad(title, source="wikicfp", desc=desc))
    assert ok
    # Mesmo título em fonte não curada continua barrado (título sem sinal).
    ok2, _ = check_opportunity(_acad(title, source="ach_rss", desc=desc))
    assert not ok2


def test_gate_pode_ser_desligado():
    settings = {"enabled": True, "opportunity_gate": {"enabled": False}}
    # Sem blocklists no overlay, o título institucional passa.
    assert check_opportunity(_acad("Palestra sobre DH"), settings)[0]
    # Blocklists são independentes do gate: com a config real, continuam ativas.
    assert not check_opportunity(_acad("ACH 2026 Elections"))[0]


def test_gate_nao_se_aplica_a_vagas():
    job = Job(
        title="Research Data Steward", company="X", location="Remote",
        remote=True, url="https://remotejobs.org/jobs/1", source="remotejobs_org",
    )
    ok, _ = check_opportunity(job)
    assert ok


# ---------- dedup ----------

def test_variantes_de_estagio_colapsam():
    titulos = [
        "Estagiario de Marketing home office na Oportunidades",
        "Estágio em Mídias Sociais – Monitoramento – Remoto",
        "Estágio em Mídias Sociais — Vaga Home Office | Elifegroup",
        "ESTÁGIO EM MÍDIAS SOCIAIS: Elifegroup Oferece Vaga 100% Home Office",
    ]
    keys = [dedup_key(t) for t in titulos]
    assert keys[1] == keys[2] == keys[3] == "estagio midias sociais"
    assert keys[0] != keys[1]


def test_deduplicate_mantem_ordem_e_nao_mistura_fontes():
    jobs = [
        Job(title="Estágio em Mídias Sociais – Remoto", company="A", location="Remote",
            remote=True, url=f"https://x/{i}", source="estagio_search/ddgs")
        for i in range(3)
    ]
    jobs.append(Job(title="Estágio em Mídias Sociais – Remoto", company="B",
                    location="Remote", remote=True, url="https://y/1",
                    source="catho_estagio"))
    result = deduplicate(jobs)
    assert len(result) == 2
    assert result[0].url == "https://x/0"
    assert result[1].source == "catho_estagio"


def test_normalizacao_e_dominio():
    assert normalize_title("Édagos—MÍDIAS  sociais!") == "edagos midias sociais"
    assert domain_of("https://WWW.Example.org:8080/a") == "www.example.org"


def test_deep_merge_nao_muta_original():
    base = {"a": {"b": 1, "c": 2}, "d": 3}
    merged = deep_merge(base, {"a": {"b": 9}, "d": 4})
    assert merged == {"a": {"b": 9, "c": 2}, "d": 4}
    assert base == {"a": {"b": 1, "c": 2}, "d": 3}
