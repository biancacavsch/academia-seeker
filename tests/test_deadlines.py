"""Testes unitários: extração de fechamento e status (PT/EN/ES)."""

from datetime import datetime

from deadlines import (
    extract_closing_date,
    compute_deadline_status,
    is_closed,
)

REF = datetime(2026, 9, 24)


def test_range_br_end():
    d = extract_closing_date("Inscrições: 29/04/2026 a 28/05/2026", REF)
    assert d == datetime(2026, 5, 28), d


def test_range_de_a():
    d = extract_closing_date("Período de 01 de março a 15 de maio de 2026", REF)
    assert d == datetime(2026, 5, 15), d


def test_ate_data_por_extenso():
    d = extract_closing_date("Propostas até 29 de maio de 2026", REF)
    assert d == datetime(2026, 5, 29), d


def test_ate_sem_ano_futuro_ou_rolagem():
    d = extract_closing_date("Submissões até 29 de maio", REF)
    # 29/05/2026 já passou em 24/09/2026 → rola para 2027
    assert d == datetime(2027, 5, 29), d


def test_prazo_explicito():
    d = extract_closing_date("Prazo final: 15/10/2026", REF)
    assert d == datetime(2026, 10, 15), d


def test_en_deadline():
    d = extract_closing_date("Submission deadline: October 15, 2026", REF)
    assert d == datetime(2026, 10, 15), d


def test_en_applications_close():
    d = extract_closing_date("Applications close September 30, 2026", REF)
    assert d == datetime(2026, 9, 30), d


def test_es_plazo():
    d = extract_closing_date("Plazo de envío: 30/11/2026", REF)
    assert d == datetime(2026, 11, 30), d


def test_es_hasta():
    d = extract_closing_date("Recepción de trabajos hasta el 12 de diciembre de 2026", REF)
    assert d == datetime(2026, 12, 12), d


def test_data_avulsa_nao_vale():
    assert extract_closing_date("O evento será em 18 de julho de 2026 em São Paulo", REF) is None


def test_sem_data():
    assert extract_closing_date("Chamada aberta para trabalhos", REF) is None


def test_encerrado_pt():
    assert is_closed("EDITAL ENCERRADO — inscrições encerradas em 28/05/2026")
    assert is_closed("Chamada encerrada. Prazo foi 28/05/2026")
    assert not is_closed("Edital aberto para bolsas de mestrado")
    # "Não há editais abertos" é estado da página-listagem, não do item → não marca
    assert not is_closed("Não há editais abertos no momento")


def test_encerrado_en_es():
    assert is_closed("Applications are now closed")
    assert is_closed("Convocatoria cerrada")
    assert not is_closed("Call for papers now open")


def test_status_open():
    assert compute_deadline_status(datetime(2026, 10, 15), "", REF) == "open"


def test_status_closing_soon():
    assert compute_deadline_status(datetime(2026, 9, 30), "", REF) == "closing_soon"


def test_status_deadline_hoje_aberto():
    assert compute_deadline_status(datetime(2026, 9, 24), "", REF) == "closing_soon"


def test_status_closed_data_passada():
    assert compute_deadline_status(datetime(2026, 5, 28), "", REF) == "closed"


def test_status_closed_marcador_sobrepoe_data_futura():
    assert compute_deadline_status(datetime(2026, 12, 1), "ENCERRADO", REF) == "closed"


def test_status_unknown():
    assert compute_deadline_status(None, "edital aberto", REF) == "unknown"
