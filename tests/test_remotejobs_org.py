"""Regressão: API RemoteJobs.org devolve None em location/salary/company.

Antes do fix, `item.get("location", "Remote").strip()` estourava
AttributeError quando o campo existia com valor None, descartando vagas
válidas. Também havia risco em `title`, `url`, `description`, `company.name`
e `salary_text`.
"""

from collectors.remotejobs_org import RemoteJobsOrgCollector


def _item(**overrides):
    item = {
        "id": "10007016-f761-40ff-b0eb-a6f30b80fb1a",
        "title": "Research Data Steward",
        "url": "https://remotejobs.org/jobs/10007016",
        "company": {"name": "Example Org", "website": None, "logo_url": None},
        "category": {"name": "Science"},
        "location": None,
        "description": "  Trabalho remoto com dados  ",
        "posted_at": "2026-11-20T12:00:00Z",
        "salary_min": None,
        "salary_max": None,
        "salary_text": None,
    }
    item.update(overrides)
    return item


def test_location_nulo_vira_remote():
    job = RemoteJobsOrgCollector()._parse_job(_item())
    assert job.location == "Remote"
    assert job.remote is True


def test_salarios_nulos_nao_quebram():
    job = RemoteJobsOrgCollector()._parse_job(_item())
    assert job.salary_min is None
    assert job.salary_max is None
    assert job.salary_text == ""


def test_salarios_como_string_sao_numeros():
    job = RemoteJobsOrgCollector()._parse_job(
        _item(salary_min="50000", salary_max="80000.9", salary_text="  USD 50k ")
    )
    assert job.salary_min == 50000
    assert job.salary_max == 80000
    assert job.salary_text == "USD 50k"


def test_company_e_category_nulos():
    job = RemoteJobsOrgCollector()._parse_job(
        _item(company=None, category=None, description=None)
    )
    assert job.company == ""
    assert job.tags == []
    assert job.description == ""


def test_company_com_nome_nulo():
    job = RemoteJobsOrgCollector()._parse_job(_item(company={"name": None}))
    assert job.company == ""


def test_titulo_ou_url_vazios_sao_descartados():
    c = RemoteJobsOrgCollector()
    assert c._parse_job(_item(title=None)) is None
    assert c._parse_job(_item(url="   ")) is None
    assert c._parse_job({}) is None


def test_data_invalida_nao_quebra():
    job = RemoteJobsOrgCollector()._parse_job(_item(posted_at="não é data"))
    # BaseItem.__post_init__ preenche utcnow() quando posted_at fica None.
    assert job.posted_at is not None


def test_data_valida_e_parseada():
    job = RemoteJobsOrgCollector()._parse_job(_item())
    assert job.posted_at is not None
    assert job.posted_at.year == 2026


def test_fetch_nao_perde_vagas_por_campos_nulos(monkeypatch):
    """Cenário real: 1 vaga com location None no meio de outras 2 válidas."""
    c = RemoteJobsOrgCollector()
    monkeypatch.setattr(
        c, "_get", lambda url, params: {"data": [_item(), _item(location="Berlim"), _item(title=None)]}
    )
    jobs = list(c.fetch())
    assert len(jobs) == 2
    assert jobs[0].location == "Remote"
    assert jobs[1].location == "Berlim"
