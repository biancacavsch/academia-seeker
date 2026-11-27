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


def _isolated_surveys(tmp_path, monkeypatch):
    monkeypatch.setattr(surveys, "SURVEYS_DIR", tmp_path / "surveys")
    monkeypatch.setattr(surveys, "ACTIVE_PATH", tmp_path / "active.yaml")


class _Form(dict):
    def getlist(self, key):
        value = self.get(key, "")
        return value if isinstance(value, list) else [value]


def test_editar_levantamento_nao_ativo_mostra_os_termos_dele(tmp_path, monkeypatch):
    _isolated_surveys(tmp_path, monkeypatch)
    surveys.save_survey("academic", "principal", "Principal", "", True,
                        {"keywords": {"core": ["do-principal"]}})
    surveys.save_survey("academic", "segundo", "Segundo", "", True,
                        {"keywords": {"core": ["do-segundo"]}})
    surveys.set_active("academic", "principal")

    view = survey_forms.editable_paths("academic", sid="segundo")
    core = next(t for t in view["terms"] if t["path"] == "keywords.core")
    assert "do-segundo" in core["text"]
    assert "do-principal" not in core["text"]


def test_salvar_sem_id_edita_o_levantamento_ativo(tmp_path, monkeypatch):
    _isolated_surveys(tmp_path, monkeypatch)
    surveys.save_survey("academic", "principal", "Antigo", "", True, {})
    surveys.set_active("academic", "principal")
    form = _Form({
        "action": "save", "survey_id": "", "survey_name": "Novo nome",
        "survey_enabled": "on", "cfg:keywords.core": "termo unico",
    })
    ok, errors = survey_forms.apply_form(form, "academic")
    assert ok and not errors
    assert surveys.get_survey("academic", "principal")["name"] == "Novo nome"


def test_email_por_levantamento(tmp_path, monkeypatch):
    _isolated_surveys(tmp_path, monkeypatch)
    assert surveys.normalize_email("namorada@example.com") == "namorada@example.com"
    assert surveys.normalize_email("a@x.com; b@y.com") == "a@x.com,b@y.com"
    assert surveys.normalize_email("invalido") is None

    ok, errors = surveys.save_survey(
        "academic", "namorada", "Patrimônio", "", True, {},
        email="namorada@example.com")
    assert ok and not errors
    assert surveys.survey_email("academic", "namorada") == "namorada@example.com"
    assert surveys.survey_email("academic", "principal") == ""
    assert surveys.get_survey("academic", "namorada")["email"] == "namorada@example.com"

    ok, errors = surveys.save_survey(
        "academic", "namorada", "Patrimônio", "", True, {}, email="errado")
    assert not ok and any("E-mail" in e for e in errors)


def test_todos_os_levantamentos_ligados_rodam(tmp_path, monkeypatch):
    _isolated_surveys(tmp_path, monkeypatch)
    surveys.save_survey("academic", "principal", "Principal", "", True, {})
    surveys.save_survey("academic", "namorada", "Namorada", "", True, {})
    surveys.save_survey("academic", "antigo", "Antigo", "", False, {})
    ids = [s["id"] for s in surveys.enabled_surveys("academic")]
    assert ids == ["namorada", "principal"]


def test_email_do_levantamento_sobrescreve_destinatario(monkeypatch):
    from alerts import AlertManager
    from models import Job

    captured = {}

    class FakeSMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            pass

        def login(self, *args):
            pass

        def send_message(self, msg):
            captured["to"] = msg["To"]

    monkeypatch.setattr("alerts.smtplib.SMTP", FakeSMTP)
    mgr = AlertManager()
    monkeypatch.setattr(mgr, "email_cfg", {
        "enabled": True, "smtp_host": "smtp.test", "smtp_port": 587,
        "smtp_user": "user@test", "smtp_pass": "x",
        "from_email": "user@test", "to_email": "dono@test",
    })
    job = Job(title="Vaga", source="teste", url="https://x.test/job")
    mgr._send_email([job], to_email="namorada@example.com")
    assert captured["to"] == "namorada@example.com"
    mgr._send_email([job])
    assert captured["to"] == "dono@test"


def test_configuracoes_separadas_por_escopo():
    from web import settings
    view = settings.editable_view()
    assert any(f["scope"] == "academic" for f in view["numbers"])
    assert any(f["scope"] == "professional" for f in view["numbers"])
    assert any(s["scope"] == "academic" for s in view["sources"])
    assert any(s["scope"] == "professional" for s in view["sources"])
    assert any(g["scope"] == "professional" for g in view["groups"])
