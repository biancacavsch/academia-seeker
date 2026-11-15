"""Regressão: rejeição precisa gravar o estado no item.

Bug histórico: os `return -1000` antecipados não atualizavam
`item.score`/`item.matched_keywords`, então um rescore mantinha o score
antigo do banco e o upsert o persistia (filtro fantasma).
"""

from datetime import datetime, timedelta

from models import AcademicItem, Job
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


def test_remote_reject_persists_state():
    job = Job(title="Museum Curator", company="X", location="São Paulo",
              remote=False, url="https://example.com/y",
              description="museum curator onsite", source="test", score=50.0)
    score_item(job)
    assert job.score == -1000.0, job.score


def test_old_post_does_not_reject_academic():
    # Norma: acadêmicos são regidos pela data de FECHAMENTO, não de postagem.
    # Post antigo + sem deadline passada → segue para quarentena (unknown),
    # nunca é descartado pela idade do post.
    it = _bolsa("Bolsa de mestrado em história")
    it.posted_at = datetime.utcnow() - timedelta(days=400)
    it.score = 80.0
    score_item(it)
    assert it.score != -1000.0 or "older than" not in it.matched_keywords
    assert it.deadline_status == "unknown"


def test_old_age_reject_persists_state_job():
    job = Job(title="Museum Curator", company="X", location="São Paulo",
              remote=True, url="https://example.com/z",
              description="museum curator", source="test", score=80.0)
    job.posted_at = datetime.utcnow() - timedelta(days=400)
    score_item(job)
    assert job.score == -1000.0, job.score


# ---------- novas regras de interesse / área excluída ----------

def test_bolsa_doutorado_nao_rejeitado():
    """Usuária está no mestrado: só programa de MESTRADO é rejeitado;
    doutorado/intercâmbio continua elegível."""
    it = _bolsa("Becas para tesis doctorales en humanidades")
    score_item(it)
    assert it.score != -1000.0
    assert "master's program" not in it.matched_keywords


def test_job_area_excluida_rejeitada():
    job = Job(title="Estágio Jurídico - Direito", company="X",
              location="São Paulo", remote=True, url="https://example.com/a",
              description="estágio em direito e advocacia", source="test",
              score=90.0)
    score_item(job)
    assert job.score == -1000.0
    assert "off-topic" in job.matched_keywords[0]


def test_job_fora_do_interesse_rejeitado():
    job = Job(title="Senior Financial Analyst", company="X",
              location="Remote", remote=True, url="https://example.com/b",
              description="financial planning and analysis", source="test",
              score=90.0)
    score_item(job)
    assert job.score == -1000.0
    assert job.matched_keywords[0] == "filtered: not in interests"


def test_job_presencial_rejeitado_mesmo_com_flag_remote():
    # Título passa o interesse (marketing), mas descrição diz presencial
    job = Job(title="Estágio em Marketing", company="X",
              location="São Paulo", remote=True,
              url="https://example.com/c",
              description="Jornada híbrida: Presencial + Home Office. "
                          "Atividades de mídias sociais.",
              source="test", score=90.0)
    score_item(job)
    assert job.score == -1000.0
    assert job.matched_keywords[0] == "filtered: on-site only"


def test_job_presencial_no_titulo_rejeitado():
    # on-site no título/localização rejeita mesmo sem description
    job = Job(title="Social Media Intern (on-site)", company="X",
              location="New York, NY", remote=True,
              url="https://example.com/e",
              description="remote social media internship",
              source="test", score=90.0)
    score_item(job)
    assert job.score == -1000.0
    assert job.matched_keywords[0] == "filtered: on-site only"


def test_job_remoto_forte_passa_mesmo_com_onsite_na_desc():
    # "home office" no título/localização salva de onsite na descrição
    job = Job(title="Estágio em Marketing (home office)", company="X",
              location="Remote", remote=True,
              url="https://example.com/f",
              description="alguma visita presencial ocasional",
              source="test", score=90.0)
    score_item(job)
    assert job.score != -1000.0
    assert "on-site only" not in job.matched_keywords[0]


def test_job_no_interest_nao_alerta_nao_digest():
    """Vaga fora do escopo não chega nem ao digest (score -1000)."""
    job = Job(title="Truck Driver - Long Haul", company="X",
              location="Remote", remote=True, url="https://example.com/d",
              description="cdl truck driver long haul", source="test",
              score=90.0)
    score_item(job)
    assert job.score < 0


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
