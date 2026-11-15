"""Gate de alerta acadêmico + marcação apenas do que foi enviado.

Regressão do caso real: itens com score >= 60 ficavam pendentes para
SEMPRE porque o gate exigia `submission_deadline` futuro e a maioria das
bolsas/CFPs não expõe deadline parseável (NULL). NULL = prazo desconhecido,
não vencido — só prazo vencido deve ser suprimido.
"""

from datetime import datetime, timedelta

import pytest

import config
from models import AcademicItem
from store import get_academic_store


@pytest.fixture
def acad_db(tmp_path, monkeypatch):
    monkeypatch.setitem(config.CONFIG["storage"], "db_path_academic",
                        str(tmp_path / "academic.db"))
    return get_academic_store()


def _cfp(url, score, deadline, category="cfp", track="publicacao"):
    return AcademicItem(
        title="CFP: chamada aberta", source="t", category=category,
        url=url, score=score, submission_deadline=deadline, track=track)


def _pendentes(store, min_score=60):
    return [i.url for i in
            store.get_unalerted_items(min_score=min_score, kind="academic")]


# ---------- gate de deadline ----------

def test_deadline_null_conta_como_aberto(acad_db):
    """Bolsa sem deadline parseado (caso mais comum) DEVE alertar."""
    acad_db.upsert_item(_cfp("https://x.org/bolsa-sem-prazo", 90, None))
    assert _pendentes(acad_db) == ["https://x.org/bolsa-sem-prazo"]


def test_deadline_futuro_alerta(acad_db):
    fut = datetime.utcnow() + timedelta(days=30)
    acad_db.upsert_item(_cfp("https://x.org/aberta", 90, fut))
    assert _pendentes(acad_db) == ["https://x.org/aberta"]


def test_deadline_vencido_e_suprimido(acad_db):
    """Edital com prazo já passado NÃO pode alertar."""
    passado = datetime.utcnow() - timedelta(days=3)
    acad_db.upsert_item(_cfp("https://x.org/vencida", 90, passado))
    assert _pendentes(acad_db) == []


def test_score_abaixo_do_threshold_nao_alerta(acad_db):
    acad_db.upsert_item(_cfp("https://x.org/mediano", 59, None))
    assert _pendentes(acad_db, min_score=60) == []
    assert _pendentes(acad_db, min_score=40) == ["https://x.org/mediano"]


def test_backlog_misto_separa_corretamente(acad_db):
    acad_db.upsert_item(_cfp("https://x.org/ok1", 80, None))                       # NULL
    acad_db.upsert_item(_cfp("https://x.org/ok2", 70,
                             datetime.utcnow() + timedelta(days=10)))              # futuro
    acad_db.upsert_item(_cfp("https://x.org/expirada", 95,
                             datetime.utcnow() - timedelta(days=1)))               # vencido
    acad_db.upsert_item(_cfp("https://x.org/baixo", 30, None))                     # score
    assert sorted(_pendentes(acad_db)) == ["https://x.org/ok1", "https://x.org/ok2"]


# ---------- marcação apenas do enviado ----------

class FlakyAlertManager:
    """Dublê: reporta um hash como FALHO (como o Telegram faria)."""
    failed: set = set()

    def send_alerts(self, items, channel="both"):
        return FlakyAlertManager.failed


def test_item_com_falha_de_envio_fica_pendente(acad_db, monkeypatch):
    import main
    item = _cfp("https://x.org/pendente", 90, None)
    acad_db.upsert_item(item)

    FlakyAlertManager.failed = {item.url_hash}
    monkeypatch.setattr(main, "AlertManager", FlakyAlertManager)

    main.run_alerts(acad_db, channel="telegram", kind="academic")

    # falhou → NÃO marcado como alertado (reenviado na próxima execução)
    assert acad_db.is_alerted(item.url_hash) is False
    assert len(_pendentes(acad_db)) == 1


def test_item_enviado_e_marcado(acad_db, monkeypatch):
    import main
    item = _cfp("https://x.org/enviado", 90, None)
    acad_db.upsert_item(item)

    FlakyAlertManager.failed = set()
    monkeypatch.setattr(main, "AlertManager", FlakyAlertManager)

    main.run_alerts(acad_db, channel="telegram", kind="academic")

    assert acad_db.is_alerted(item.url_hash) is True
    assert _pendentes(acad_db) == []
