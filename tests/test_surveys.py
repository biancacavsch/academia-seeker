"""Testes dos levantamentos, separação de escopos e limite rígido de 30 termos."""

import copy

import config
import surveys
from models import AcademicItem, Job
from web import survey_forms


def test_limite_de_30_em_todas_as_listas():
    value = config.CONFIG["keywords"]["broad"]
    assert len(value) <= 30
    assert len(config.CONFIG["filters"]["interests"]) <= 30
    assert len(config.CONFIG["keywords"]["estagio"]) <= 30
    assert len(config.CONFIG["keywords"]["negatives"]) <= 30
    for sec in ("academic_search", "estagio_search", "empresas_alvo"):
        for terms in config.CONFIG[sec].get("queries", {}).values():
            assert len(terms) <= 30


def test_limite_aplicado_ao_carregar_config(tmp_path, monkeypatch):
    import yaml
    base = tmp_path / "config.yaml"
    data = {"keywords": {"core": [f"termo {i}" for i in range(40)]},
            "filters": {"min_score_alert": 60}}
    base.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", base)
    monkeypatch.setattr(config, "UI_SETTINGS_PATH", tmp_path / "ui.yaml")
    monkeypatch.setattr(config, "ACTIVE_SURVEYS_PATH", tmp_path / "active.yaml")
    cfg = config.load_config()
    assert len(cfg["keywords"]["core"]) == 30


def test_criar_editar_ativar_e_excluir(tmp_path, monkeypatch):
    monkeypatch.setattr(surveys, "SURVEYS_DIR", tmp_path / "surveys")
    monkeypatch.setattr(surveys, "ACTIVE_PATH", tmp_path / "active.yaml")

    ok, errors = surveys.save_survey(
        "academic", "patrimonio", "Patrimônio e história", "Para minha namorada",
        True, {"keywords": {"glam": ["história", "patrimônio"]}})
    assert ok and not errors
    assert len(surveys.list_surveys("academic")) == 2  # principal + novo

    assert surveys.set_active("academic", "patrimonio")
    assert surveys.active_ids()["academic"] == "patrimonio"

    cfg = surveys.effective_config("academic")
    assert cfg["keywords"]["glam"] == ["história", "patrimônio"]
    # Escopo profissional não é afetado pelo levantamento acadêmico.
    prof = surveys.effective_config("professional")
    assert prof["keywords"]["glam"] == config.CONFIG["keywords"]["glam"]

    ok, msg = surveys.delete_survey("academic", "patrimonio")
    assert ok
    assert surveys.active_ids()["academic"] == "principal"
    ok, msg = surveys.delete_survey("academic", "principal")
    assert not ok


def test_rejeita_mais_de_30_termos_no_survey(tmp_path, monkeypatch):
    monkeypatch.setattr(surveys, "SURVEYS_DIR", tmp_path / "surveys")
    monkeypatch.setattr(surveys, "ACTIVE_PATH", tmp_path / "active.yaml")
    ok, errors = surveys.save_survey(
        "academic", "ruim", "Ruim", "", True,
        {"academic_search": {"queries": {"bolsas_pt": [f"q{i}" for i in range(31)]}}})
    assert not ok
    assert any("30" in e for e in errors)


def test_form_30_termos_e_separacao_de_escopos():
    class Form(dict):
        def getlist(self, key):
            value = self.get(key, "")
            return value if isinstance(value, list) else [value]

    form = Form({
        "action": "save", "survey_id": "principal", "survey_name": "Principal",
        "cfg:keywords.core": "\n".join(f"termo {i}" for i in range(50)),
        "cfg:academic_search.page_budget": "55",
    })
    cfg, errors = survey_forms.form_to_config(form, "academic")
    assert errors == []
    assert len(cfg["keywords"]["core"]) == 30
    assert cfg["academic_search"]["page_budget"] == 55

    # Profissional não aceita chaves exclusivamente acadêmicas.
    prof, _ = survey_forms.form_to_config(form, "professional")
    assert "academic_search" not in prof


def test_itens_sao_marcados_com_survey_id(tmp_path):
    from store import ItemStore
    store = ItemStore(str(tmp_path / "academic.db"))
    item = AcademicItem(title="Chamada X", source="teste", url="https://x.test/cfp",
                        category="cfp")
    item.survey_id = "patrimonio"
    assert store.upsert_item(item)
    rows, total = store.get_items_page(survey_id="patrimonio")
    assert total == 1 and rows[0][0].survey_id == "patrimonio"
    rows, total = store.get_items_page(survey_id="outro")
    assert total == 0
    stats = store.get_stats("patrimonio")
    assert stats["total_items"] == 1


def test_job_tambem_tem_survey_id():
    job = Job(title="Vaga", source="teste", url="https://x.test/job")
    job.survey_id = "profissional-2"
    assert job.survey_id == "profissional-2"
