"""Roteamento de alertas por banco após a separação.

`jobs alert` só pode ver/alertar itens de jobs.db e `academic alert` só os de
academic.db — cada um marca o próprio alerts_sent (nenhuma mensagem real é
enviada: AlertManager é substituído por um dublê).
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


class FakeAlertManager:
    """Dublê: só registra o que seria enviado."""
    sent: list = []

    def send_alerts(self, items, channel="both"):
        FakeAlertManager.sent.extend(items)


@pytest.fixture
def fake_alerts(monkeypatch):
    import main
    FakeAlertManager.sent = []
    monkeypatch.setattr(main, "AlertManager", FakeAlertManager)
    return FakeAlertManager


def _seed(jobs, acad):
    job = Job(title="Estágio remoto em humanidades digitais", source="t",
              url="https://x.org/job/9", remote=True, score=80,
              posted_at=datetime.utcnow(), tags=["estagio", "remote"])
    cfp = AcademicItem(
        title="CFP: chamada aberta", source="t", category="cfp",
        url="https://x.org/cfp/9", score=90,
        submission_deadline=datetime.utcnow() + timedelta(days=20))
    jobs.upsert_item(job)
    acad.upsert_item(cfp)
    return job, cfp


def test_jobs_alert_so_ve_jobs_db(two_dbs, fake_alerts):
    import main
    jobs, acad = two_dbs
    job, cfp = _seed(jobs, acad)

    main.run_alerts(jobs, channel="telegram", category="job")

    assert [i.url for i in fake_alerts.sent] == [job.url]
    assert jobs.is_alerted(job.url_hash) is True
    # academic.db intocado
    assert acad.is_alerted(cfp.url_hash) is False
    assert [i.url for i in acad.get_unalerted_items(min_score=0, kind="academic")] == [cfp.url]


def test_academic_alert_so_ve_academic_db(two_dbs, fake_alerts):
    import main
    jobs, acad = two_dbs
    job, cfp = _seed(jobs, acad)

    main.run_alerts(acad, channel="telegram", kind="academic")

    assert [i.url for i in fake_alerts.sent] == [cfp.url]
    assert acad.is_alerted(cfp.url_hash) is True
    assert jobs.is_alerted(job.url_hash) is False
    # o job segue pendente no jobs.db para um futuro `jobs alert`
    assert [i.url for i in jobs.get_unalerted_items(min_score=0, category="job")] == [job.url]
