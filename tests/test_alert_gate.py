"""Gate de alerta acadêmico + marcação apenas do que foi enviado.

Regressão do caso real: 128 itens com score >= 60 ficavam pendentes para
SEMPRE porque o gate exigia `submission_deadline` futuro e a maioria das
bolsas/CFPs não expõe deadline parseável (NULL). NULL = prazo desconhecido,
não vencido — só prazo vencido deve ser suprimido.
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


def _cfp(url, score, deadline):
    return AcademicItem(
        title="CFP: chamada aberta", source="t", category="cfp",
        url=url, score=score, submission_deadline=deadline)


def _pendentes(store, min_score=60):
    return [i.url for i in
            store.get_unalerted_items(min_score=min_score, kind="academic")]


# ---------- gate de deadline ----------

def test_deadline_null_conta_como_aberto(two_dbs):
    """Bolsa sem deadline parseado (caso mais comum) DEVE alertar."""
    _, acad = two_dbs
    acad.upsert_item(_cfp("https://x.org/bolsa-sem-prazo", 90, None))
    assert _pendentes(acad) == ["https://x.org/bolsa-sem-prazo"]


def test_deadline_futuro_alerta(two_dbs):
    _, acad = two_dbs
    fut = datetime.utcnow() + timedelta(days=30)
    acad.upsert_item(_cfp("https://x.org/aberta", 90, fut))
    assert _pendentes(acad) == ["https://x.org/aberta"]


def test_deadline_vencido_e_suprimido(two_dbs):
    """Edital com prazo já passado NÃO pode alertar."""
    _, acad = two_dbs
    passado = datetime.utcnow() - timedelta(days=3)
    acad.upsert_item(_cfp("https://x.org/vencida", 90, passado))
    assert _pendentes(acad) == []


def test_score_abaixo_do_threshold_nao_alerta(two_dbs):
    _, acad = two_dbs
    acad.upsert_item(_cfp("https://x.org/mediano", 59, None))
    assert _pendentes(acad, min_score=60) == []
    assert _pendentes(acad, min_score=40) == ["https://x.org/mediano"]


def test_backlog_misto_separa_corretamente(two_dbs):
    _, acad = two_dbs
    acad.upsert_item(_cfp("https://x.org/ok1", 80, None))                       # NULL
    acad.upsert_item(_cfp("https://x.org/ok2", 70,
                          datetime.utcnow() + timedelta(days=10)))              # futuro
    acad.upsert_item(_cfp("https://x.org/expirada", 95,
                          datetime.utcnow() - timedelta(days=1)))               # vencido
    acad.upsert_item(_cfp("https://x.org/baixo", 30, None))                     # score
    assert sorted(_pendentes(acad)) == ["https://x.org/ok1", "https://x.org/ok2"]


def test_vaga_antiga_continua_suprimida_por_idade(two_dbs):
    """O gate de idade das vagas não pode ser afetado pela mudança."""
    jobs, _ = two_dbs
    antiga = Job(title="Estágio velho", source="t",
                 url="https://x.org/job/velha", remote=True, score=90,
                 posted_at=datetime.utcnow() - timedelta(days=60))
    recente = Job(title="Estágio novo", source="t",
                  url="https://x.org/job/nova", remote=True, score=90,
                  posted_at=datetime.utcnow())
    jobs.upsert_item(antiga)
    jobs.upsert_item(recente)
    pend = [i.url for i in jobs.get_unalerted_items(min_score=60, kind="job")]
    assert pend == ["https://x.org/job/nova"]


# ---------- marcação apenas do enviado ----------

class FlakyAlertManager:
    """Dublê: reporta um hash como FALHO (como o Telegram faria)."""
    failed: set = set()

    def send_alerts(self, items, channel="both"):
        return FlakyAlertManager.failed


def test_item_com_falha_de_envio_fica_pendente(two_dbs, monkeypatch):
    import main
    _, acad = two_dbs
    item = _cfp("https://x.org/pendente", 90, None)
    acad.upsert_item(item)

    FlakyAlertManager.failed = {item.url_hash}
    monkeypatch.setattr(main, "AlertManager", FlakyAlertManager)

    main.run_alerts(acad, channel="telegram", kind="academic")

    # falhou → NÃO marcado como alertado (reenviado na próxima execução)
    assert acad.is_alerted(item.url_hash) is False
    assert len(_pendentes(acad)) == 1


def test_item_enviado_e_marcado(two_dbs, monkeypatch):
    import main
    _, acad = two_dbs
    item = _cfp("https://x.org/enviado", 90, None)
    acad.upsert_item(item)

    FlakyAlertManager.failed = set()
    monkeypatch.setattr(main, "AlertManager", FlakyAlertManager)

    main.run_alerts(acad, channel="telegram", kind="academic")

    assert acad.is_alerted(item.url_hash) is True
    assert _pendentes(acad) == []
