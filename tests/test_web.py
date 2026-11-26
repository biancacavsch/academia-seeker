"""Testes da webview e da whitelist de ajustes (sem systemd, sem rede)."""

import pytest

import config
from web import settings


def _form(**kwargs):
    return kwargs


def test_keywords_sao_limitados_e_dedup():
    terms = "\n".join([f"termo {i}" for i in range(40)] + ["termo 0", "  ", "# comentário"])
    overlay, errors = settings.overlay_from_form(
        _form(**{"kw:keywords:None:core": terms}))
    assert errors == []
    core = overlay["keywords"]["core"]
    assert len(core) == settings.MAX_TERMS
    assert core[0] == "termo 0"
    assert all(len(t) <= settings.MAX_TERM_LEN for t in core)


def test_page_budget_teto_60():
    overlay, errors = settings.overlay_from_form(
        _form(**{"num:academic_search:page_budget": "999"}))
    assert errors
    assert "page_budget" not in overlay.get("academic_search", {})

    overlay, errors = settings.overlay_from_form(
        _form(**{"num:academic_search:page_budget": "55"}))
    assert errors == []
    assert overlay["academic_search"]["page_budget"] == 55


def test_request_delay_minimo():
    overlay, errors = settings.overlay_from_form(
        _form(**{"num:academic_search:request_delay": "0.2"}))
    assert errors
    assert not overlay

    overlay, errors = settings.overlay_from_form(
        _form(**{"num:academic_search:request_delay": "2.5"}))
    assert errors == []
    assert overlay["academic_search"]["request_delay"] == 2.5


def test_fontes_desmarcadas_sao_desligadas():
    overlay, errors = settings.overlay_from_form(_form(**{
        "src:academic_sources:ach_rss": "on",
    }))
    assert errors == []
    academic = {s["name"]: s["enabled"] for s in overlay["academic_sources"]}
    assert academic["ach_rss"] is True
    assert academic["wikicfp"] is False


def test_agenda_validada():
    overlay, errors = settings.overlay_from_form(_form(**{
        "schedule_mode": "daily", "schedule_time": "07:30",
        "schedule_weekday": "sat", "schedule_every_n_days": "3",
    }))
    assert errors == []
    assert overlay["schedule"]["mode"] == "daily"
    assert overlay["schedule"]["time"] == "07:30"

    _, errors = settings.overlay_from_form(_form(**{"schedule_time": "99:99"}))
    assert errors


def test_save_overlay_atomico_e_merge(tmp_path, monkeypatch):
    path = tmp_path / "ui_settings.yaml"
    monkeypatch.setattr(settings, "UI_SETTINGS_PATH", path)
    original = config.load_config()
    settings.save_overlay({"filters": {"min_score_alert": 75}})
    settings.save_overlay({"academic_search": {"page_budget": 25}})
    saved = settings.load_ui_settings()
    assert saved["filters"]["min_score_alert"] == 75
    assert saved["academic_search"]["page_budget"] == 25
    config.CONFIG.clear()
    config.CONFIG.update(original)


def test_overlay_nao_derruba_config_com_yaml_invalido(tmp_path, monkeypatch):
    path = tmp_path / "ui_settings.yaml"
    path.write_text("::: nao yaml: [", encoding="utf-8")
    monkeypatch.setattr(settings, "UI_SETTINGS_PATH", path)
    assert settings.load_ui_settings() == {}


def test_schedule_expression():
    from web.services import schedule_expression
    cfg = config.CONFIG.setdefault("schedule", {})
    old = dict(cfg)
    try:
        cfg.update({"mode": "weekly", "weekday": "sun", "time": "03:17"})
        assert schedule_expression() == "Sun 03:17:00"
        cfg.update({"mode": "daily"})
        assert schedule_expression() == "*-*-* 03:17:00"
        cfg.update({"mode": "every_n_days", "every_n_days": 7})
        assert schedule_expression() == "*-*-7/7 03:17:00"
    finally:
        cfg.clear()
        cfg.update(old)


def test_rotas_com_test_client(tmp_path, monkeypatch):
    from web.app import create_app

    monkeypatch.setitem(config.CONFIG["storage"], "db_path_jobs", str(tmp_path / "j.db"))
    monkeypatch.setitem(config.CONFIG["storage"], "db_path_academic", str(tmp_path / "a.db"))
    monkeypatch.setitem(config.CONFIG["storage"], "db_path_feedback", str(tmp_path / "f.db"))
    monkeypatch.setenv("WEB_PASSWORD", "senha-teste")
    monkeypatch.delenv("WEB_PASSWORD_HASH", raising=False)

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    assert client.get("/").status_code == 302
    page = client.get("/login")
    assert page.status_code == 200 and b"academia-seeker" in page.data

    csrf = client.get("/login").data.decode().split('name="csrf" value="')[1].split('"')[0]
    res = client.post("/login", data={"password": "senha-teste", "csrf": csrf})
    assert res.status_code == 302

    for url in ("/", "/itens", "/ajustes", "/sistema", "/revisao"):
        assert client.get(url).status_code == 200, url

    # CSRF obrigatório em POST
    assert client.post("/ajustes", data={}).status_code == 400
