"""Testes da separação de bancos: jobs.db (vagas) × academic.db (bolsas/eventos).

Garante que cada ItemStore aponta para o arquivo do seu grupo e que não há
contaminação cruzada de itens nem de estado de alertas.
"""

from datetime import datetime, timedelta

import pytest

import config
from models import AcademicItem, Job
from store import get_academic_store, get_jobs_store


@pytest.fixture
def two_dbs(tmp_path, monkeypatch):
    monkeypatch.setitem(config.CONFIG["storage"], "db_path_jobs",
                        str(tmp_path / "jobs.db"))
    monkeypatch.setitem(config.CONFIG["storage"], "db_path_academic",
                        str(tmp_path / "academic.db"))
    return get_jobs_store(), get_academic_store()


def _job(url: str = "https://example.com/job/1") -> Job:
    return Job(title="Estágio remoto em redes sociais", source="test",
               url=url, remote=True, tags=["estagio", "remote"])


def _cfp(url: str = "https://example.com/cfp/1") -> AcademicItem:
    return AcademicItem(
        title="CFP: Digital Humanities Conference", source="test",
        category="cfp", url=url,
        submission_deadline=datetime.utcnow() + timedelta(days=20))


# ---------- caminhos ----------

def test_stores_usam_arquivos_distintos(two_dbs):
    jobs, acad = two_dbs
    assert jobs.db_path != acad.db_path
    assert jobs.db_path.endswith("jobs.db")
    assert acad.db_path.endswith("academic.db")


def test_stores_criam_schema(two_dbs):
    jobs, acad = two_dbs
    for store in (jobs, acad):
        with store._conn() as conn:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"items", "alerts_sent"} <= tables


# ---------- isolamento de itens ----------

def test_job_so_vai_para_jobs_db(two_dbs):
    jobs, acad = two_dbs
    job = _job()
    assert jobs.upsert_item(job) is True          # novo
    assert jobs.get_item(job.url_hash) is not None
    assert acad.get_item(job.url_hash) is None     # sem contaminação


def test_academic_so_vai_para_academic_db(two_dbs):
    jobs, acad = two_dbs
    cfp = _cfp()
    assert acad.upsert_item(cfp) is True
    assert acad.get_item(cfp.url_hash) is not None
    assert jobs.get_item(cfp.url_hash) is None


def test_upsert_nao_reinsere_no_outro_banco(two_dbs):
    jobs, acad = two_dbs
    job = _job()
    jobs.upsert_item(job)
    # novo item novo no academic não pode "resgatar" o job
    assert acad.upsert_item(_cfp()) is True
    assert acad.get_item(job.url_hash) is None


# ---------- isolamento de alertas ----------

def test_alertas_isolados_por_banco(two_dbs):
    jobs, acad = two_dbs
    job, cfp = _job(), _cfp()
    jobs.upsert_item(job)
    acad.upsert_item(cfp)

    jobs.mark_alerted(job.url_hash, "telegram")
    assert jobs.is_alerted(job.url_hash) is True
    assert acad.is_alerted(job.url_hash) is False
    assert acad.is_alerted(cfp.url_hash) is False

    # Só o item do academic aparece como não-alertado no academic
    acad_unalerted = acad.get_unalerted_items(min_score=0, kind="academic")
    assert [i.url_hash for i in acad_unalerted] == [cfp.url_hash]
    assert jobs.get_unalerted_items(min_score=0, kind="academic") == []


def test_stats_por_banco(two_dbs):
    jobs, acad = two_dbs
    jobs.upsert_item(_job())
    jobs.upsert_item(_job("https://example.com/job/2"))
    acad.upsert_item(_cfp())

    assert jobs.get_stats()["total_items"] == 2
    assert acad.get_stats()["total_items"] == 1
    assert set(jobs.get_stats()["by_category"]) == {"job"}
    assert "job" not in acad.get_stats()["by_category"]
