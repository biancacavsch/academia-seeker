"""Roteamento de alertas por banco (academic only).

`academic alert` só vê/alerta itens de academic.db — cada um marca o próprio
alerts_sent (nenhuma mensagem real é enviada: AlertManager é substituído por
um dublê).
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


class FakeAlertManager:
    """Dublê: só registra o que seria enviado."""
    sent: list = []

    def send_alerts(self, items, channel="both"):
        FakeAlertManager.sent.extend(items)
        return set()


@pytest.fixture
def fake_alerts(monkeypatch):
    import main
    FakeAlertManager.sent = []
    monkeypatch.setattr(main, "AlertManager", FakeAlertManager)
    return FakeAlertManager


def _cfp(url, score, deadline, track="publicacao"):
    return AcademicItem(
        title="CFP: chamada aberta", source="t", category="cfp",
        url=url, score=score, submission_deadline=deadline, track=track)


def test_academic_alert_so_ve_academic_db(acad_db, fake_alerts):
    import main
    cfp = _cfp("https://x.org/cfp/9", 90,
               datetime.utcnow() + timedelta(days=20))
    acad_db.upsert_item(cfp)

    main.run_alerts(acad_db, channel="telegram", kind="academic")

    assert [i.url for i in fake_alerts.sent] == ["https://x.org/cfp/9"]
    assert acad_db.is_alerted(cfp.url_hash) is True
