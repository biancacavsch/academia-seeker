"""Regressão: rejeição precisa gravar o estado no item.

Bug histórico: os `return -1000` antecipados não atualizavam
`item.score`/`item.matched_keywords`, então um rescore mantinha o score
antigo do banco e o upsert o persistia (filtro fantasma).
"""

from datetime import datetime, timedelta

from models import AcademicItem
from score import score_item


def _bolsa(title: str, desc: str = "") -> AcademicItem:
    return AcademicItem(
        title=title, source="test", category="bolsa", url="https://example.com/x",
        description=desc, track="bolsa", score=999.0,
        matched_keywords=["stale"],
    )


def test_reject_persists_state():
    # Programa de MESTRADO puro (usuária já está no mestrado → rejeita)
    it = _bolsa("Becas de maestría en humanidades")
    score_item(it)
    assert it.score == -1000.0, it.score
    assert it.matched_keywords == ["filtered: master's program"]


def test_reject_closed_persists_state():
    it = _bolsa("Bolsa de mestrado em história",
                "Inscrições: 01/03/2026 a 28/05/2026. EDITAL ENCERRADO.")
    it.submission_deadline = datetime(2026, 5, 28)
    it.deadline_at = datetime(2026, 5, 28)
    score_item(it)
    assert it.score == -1000.0, (it.score, it.deadline_status)
    assert it.deadline_status == "closed"


def test_old_item_reject_overwrites_stale_score():
    # Programa de mestrado puro: rescore deve sobrescrever score antigo
    it = _bolsa("Becas de maestría en humanidades")
    it.score = 160.0  # simula linha antiga do banco
    score_item(it)
    assert it.score == -1000.0, it.score


def test_bolsa_doutorado_nao_rejeitado():
    """Usuária está no mestrado: só programa de MESTRADO é rejeitado;
    doutorado/intercâmbio continua elegível."""
    it = _bolsa("Becas para tesis doctorales en humanidades")
    score_item(it)
    assert it.score != -1000.0
    assert "master's program" not in it.matched_keywords


# ---------- gate de notícia acadêmica ----------

def test_academic_noticia_rejeitada():
    it = _bolsa("Após Tarcísio dizer que Fapesp irá rever mudanças")
    score_item(it)
    assert it.score == -1000.0
    assert it.matched_keywords[0] == "filtered: news"


def test_academic_chamada_com_noticia_no_titulo_nao_rejeitada():
    it = _bolsa("[Notícia] CHAMADA DE TRABALHOS 2026.2")
    score_item(it)
    assert it.score != -1000.0
    assert "news" not in it.matched_keywords
