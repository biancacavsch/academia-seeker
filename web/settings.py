"""Whitelist, validação e escrita atômica do ui_settings.yaml.

Nada de editor YAML livre: a webview só pode mudar o que está aqui, com
limites pensados para o Raspberry Pi 3B (1 GB RAM).
"""

import os
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import yaml

from config import CONFIG, UI_SETTINGS_PATH, deep_merge, load_config

# Carregador local para que os testes possam trocar UI_SETTINGS_PATH.
def _load_overlay() -> dict:
    if not UI_SETTINGS_PATH.exists():
        return {}
    try:
        data = yaml.safe_load(UI_SETTINGS_PATH.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

# Alias público usado pelos testes e por código externo.
load_ui_settings = _load_overlay

MAX_TERMS = 30
MAX_TERM_LEN = 120
MAX_PAGES = 60          # teto rígido no Pi
MAX_RESULTS = 20

# (rótulo, seção, subseção/chave, chave)
KEYWORD_GROUPS = [
    ("Bolsas (PT)", "academic_search", "queries", "bolsas_pt"),
    ("Bolsas (EN)", "academic_search", "queries", "bolsas_en"),
    ("Bolsas (ES)", "academic_search", "queries", "bolsas_es"),
    ("Publicações (PT)", "academic_search", "queries", "publicacoes_pt"),
    ("Publicações (EN)", "academic_search", "queries", "publicacoes_en"),
    ("Publicações (ES)", "academic_search", "queries", "publicacoes_es"),
    ("Eventos (PT)", "academic_search", "queries", "eventos_pt"),
    ("Eventos (EN)", "academic_search", "queries", "eventos_en"),
    ("Eventos (ES)", "academic_search", "queries", "eventos_es"),
    ("Estágios (PT)", "estagio_search", "queries", "pt"),
    ("Estágios (EN)", "estagio_search", "queries", "en"),
    ("Estágios (ES)", "estagio_search", "queries", "es"),
    ("Empresas-alvo", "empresas_alvo", None, "empresas"),
    ("Termos centrais", "keywords", None, "core"),
    ("Divulgação científica", "keywords", None, "scicomm"),
    ("GLAM / patrimônio", "keywords", None, "glam"),
    ("Humanidades digitais", "keywords", None, "digital_humanities"),
    ("Filosofia da tecnologia", "keywords", None, "philosophy_tech"),
    ("Chamadas (CFP)", "keywords", None, "cfp_specific"),
    ("Fit de formação", "keywords", None, "education_fit"),
    ("Termos amplos", "keywords", None, "broad"),
    ("Estágio", "keywords", None, "estagio"),
    ("Interesses (vagas)", "filters", None, "interests"),
    ("Áreas excluídas", "filters", None, "exclude_areas"),
]

NUMBER_FIELDS = [
    ("Páginas por rodada", "academic_search", "page_budget", 10, MAX_PAGES, 1),
    ("Páginas (estágios)", "estagio_search", "page_budget", 10, MAX_PAGES, 1),
    ("Páginas (empresas)", "empresas_alvo", "page_budget", 10, MAX_PAGES, 1),
    ("Resultados por busca", "academic_search", "max_results_per_query", 1, MAX_RESULTS, 1),
    ("Resultados (estágios)", "estagio_search", "max_results_per_query", 1, MAX_RESULTS, 1),
    ("Pausa entre downloads (s)", "academic_search", "request_delay", 1.0, 10.0, 0.5),
    ("Pausa (estágios, s)", "estagio_search", "request_delay", 1.0, 10.0, 0.5),
    ("Idade máx. da vaga (dias)", "filters", "max_job_age_days", 1, 90, 1),
    ("Score mín. para alerta", "filters", "min_score_alert", 0, 300, 5),
    ("Score mín. para digest", "filters", "min_score_digest", 0, 300, 5),
]

BOOL_FIELDS = [
    ("Só vagas remotas", "filters", "remote_only"),
    ("Coleta acadêmica ligada", "academic_search", "enabled"),
    ("Busca de estágios ligada", "estagio_search", "enabled"),
    ("Empresas-alvo ligadas", "empresas_alvo", "enabled"),
    ("Gate de oportunidade", "relevance.opportunity_gate", "enabled"),
    ("Dedup por título", "relevance.deduplication", "enabled"),
]

SELECT_FIELDS = [
    ("Janela de busca", "academic_search", "timelimit", ["d", "w", "m", "y"]),
    ("Janela (estágios)", "estagio_search", "timelimit", ["d", "w", "m", "y"]),
    ("Motores acadêmicos", "academic_search", "engines", ["ddgs", "marginalia"]),
    ("Motores de estágio", "estagio_search", "engines", ["ddgs"]),
]

PRESETS = {
    "leve": {"academic_search.page_budget": 20,
             "academic_search.request_delay": 3.0,
             "academic_search.max_results_per_query": 5,
             "estagio_search.page_budget": 20,
             "estagio_search.request_delay": 3.0,
             "estagio_search.max_results_per_query": 5},
    "equilibrado": {"academic_search.page_budget": 40,
                    "academic_search.request_delay": 2.0,
                    "academic_search.max_results_per_query": 10,
                    "estagio_search.page_budget": 40,
                    "estagio_search.request_delay": 2.0,
                    "estagio_search.max_results_per_query": 8},
    "profundo": {"academic_search.page_budget": 60,
                 "academic_search.request_delay": 2.0,
                 "academic_search.max_results_per_query": 15,
                 "estagio_search.page_budget": 60,
                 "estagio_search.request_delay": 2.0,
                 "estagio_search.max_results_per_query": 12},
}


def _dig(cfg, path):
    cur = cfg
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _put(target, path, value):
    parts = path.split(".")
    cur = target
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def parse_terms(text: str) -> list[str]:
    out = []
    seen = set()
    for line in (text or "").splitlines():
        term = line.strip()
        if not term or term.startswith("#"):
            continue
        term = term[:MAX_TERM_LEN]
        if term.lower() not in seen:
            seen.add(term.lower())
            out.append(term)
        if len(out) >= MAX_TERMS:
            break
    return out


def _field_scope(section: str, key: str = "") -> str:
    """Classifica um campo para a seção Acadêmica/Profissional/Comum."""
    if section in ("estagio_search", "empresas_alvo"):
        return "professional"
    if section == "academic_search":
        return "academic"
    if key in ("estagio", "interests", "exclude_areas"):
        return "professional"
    return "both"


def editable_view() -> dict:
    """Config efetiva + metadados para montar os formulários."""
    cfg = load_config()
    groups = []
    for label, section, sub, key in KEYWORD_GROUPS:
        value = _dig(cfg, section) or {}
        if sub:
            value = value.get(sub, {})
        terms = value.get(key, []) or []
        groups.append({
            "label": label, "field": f"kw:{section}:{sub or ''}:{key}",
            "scope": _field_scope(section, key),
            "terms": terms, "text": "\n".join(terms),
            "count": len(terms), "max": MAX_TERMS,
        })
    numbers = []
    for label, section, key, lo, hi, step in NUMBER_FIELDS:
        raw = _dig(cfg, f"{section}.{key}")
        numbers.append({
            "label": label, "field": f"num:{section}:{key}",
            "scope": _field_scope(section),
            "value": raw, "min": lo, "max": hi, "step": step,
        })
    bools = []
    for label, section, key in BOOL_FIELDS:
        bools.append({
            "label": label, "field": f"bool:{section}:{key}",
            "scope": _field_scope(section, key),
            "checked": bool(_dig(cfg, f"{section}.{key}")),
        })
    selects = []
    for label, section, key, options in SELECT_FIELDS:
        val = _dig(cfg, f"{section}.{key}") or []
        if not isinstance(val, list):
            val = [val]
        selects.append({
            "label": label, "field": f"sel:{section}:{key}",
            "scope": _field_scope(section),
            "options": options, "selected": val,
        })
    sources = []
    for kind in ("sources", "academic_sources"):
        for src in cfg.get(kind, []) or []:
            if not isinstance(src, dict) or not src.get("name"):
                continue
            sources.append({
                "kind": kind, "name": src["name"],
                "enabled": bool(src.get("enabled")),
                "type": src.get("type", ""),
                "scope": "academic" if kind == "academic_sources" else "professional",
                "field": f"src:{kind}:{src['name']}",
            })
    gate = cfg.get("relevance", {}).get("opportunity_gate", {}) or {}
    blocks = (cfg.get("relevance", {}).get("blocklists", {}) or {})
    return {
        "groups": groups, "numbers": numbers, "bools": bools,
        "selects": selects, "sources": sources,
        "block_title": {"field": "list:relevance.blocklists.title",
                        "text": "\n".join(blocks.get("title", []) or [])},
        "block_domain": {"field": "list:relevance.blocklists.domain",
                         "text": "\n".join(blocks.get("domain", []) or [])},
        "block_path": {"field": "list:relevance.blocklists.url_path",
                       "text": "\n".join(blocks.get("url_path", []) or [])},
        "schedule": cfg.get("schedule", {}) or {},
        "overlay": _load_overlay(),
    }


def overlay_from_form(form) -> tuple[dict, list[str]]:
    """Converts POST into a validated whitelist-only overlay."""
    overlay = {}
    errors = []
    for key, value in form.items():
        try:
            if key.startswith("kw:"):
                _, section, sub, field = key.split(":", 3)
                if sub.lower() in ("", "none", "null"):
                    sub = ""
                path = f"{section}.{sub}.{field}" if sub else f"{section}.{field}"
                terms = parse_terms(value)
                _put(overlay, path, terms)
            elif key.startswith("num:"):
                _, section, field = key.split(":", 2)
                spec = next((s for s in NUMBER_FIELDS
                             if s[1] == section and s[2] == field), None)
                if not spec:
                    continue
                _, _, _, lo, hi, step = spec
                num = float(value)
                if not (lo <= num <= hi):
                    errors.append(f"{spec[0]}: use entre {lo} e {hi}")
                    continue
                if step == 1:
                    num = int(num)
                _put(overlay, f"{section}.{field}", num)
            elif key.startswith("bool:"):
                _, section, field = key.split(":", 2)
                _put(overlay, f"{section}.{field}", value in ("on", "1", "true", "yes"))
            elif key.startswith("sel:"):
                _, section, field = key.split(":", 2)
                spec = next((s for s in SELECT_FIELDS
                             if s[1] == section and s[2] == field), None)
                if not spec:
                    continue
                chosen = form.getlist(key)
                chosen = [c for c in chosen if c in spec[3]]
                _put(overlay, f"{section}.{field}", chosen)
            elif key.startswith("list:"):
                path = key.split(":", 1)[1]
                if path.split(".")[-1] not in ("title", "domain", "url_path"):
                    continue
                _put(overlay, path, parse_terms(value))
            elif key.startswith("src:"):
                _, kind, name = key.split(":", 2)
                if kind not in ("sources", "academic_sources"):
                    continue
                current = _dig(overlay, kind) or _dig(CONFIG, kind) or []
                updated = []
                for src in current:
                    entry = dict(src)
                    if entry.get("name") == name:
                        entry["enabled"] = value in ("on", "1", "true", "yes")
                    updated.append(entry)
                _put(overlay, kind, updated)
            elif key == "schedule_mode":
                if value in ("weekly", "daily", "every_n_days"):
                    _put(overlay, "schedule.mode", value)
            elif key == "schedule_weekday":
                if value in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
                    _put(overlay, "schedule.weekday", value)
            elif key == "schedule_time":
                if isinstance(value, str) and len(value) == 5 and value[2] == ":" \
                        and value[:2].isdigit() and value[3:].isdigit() \
                        and 0 <= int(value[:2]) <= 23 and 0 <= int(value[3:]) <= 59:
                    _put(overlay, "schedule.time", value)
                else:
                    errors.append("Horário inválido (use HH:MM)")
            elif key == "schedule_every_n_days":
                n = int(value)
                if 1 <= n <= 30:
                    _put(overlay, "schedule.every_n_days", n)
                else:
                    errors.append("Intervalo inválido (1–30 dias)")
            elif key == "preset":
                for path, val in PRESETS.get(value, {}).items():
                    _put(overlay, path, val)
        except (ValueError, TypeError) as exc:
            errors.append(f"{key}: valor inválido ({exc})")

    # Checkbox desmarcado não chega no POST: trata a ausência como "desligado",
    # mas só se o formulário enviou ao menos um toggle daquele grupo.
    for kind in ("sources", "academic_sources"):
        sent = {k for k in form if k.startswith(f"src:{kind}:")}
        if not sent:
            continue
        updated = []
        for src in _dig(CONFIG, kind) or []:
            entry = dict(src)
            entry["enabled"] = f"src:{kind}:{entry.get('name')}" in sent
            updated.append(entry)
        _put(overlay, kind, updated)

    return overlay, errors


def save_overlay(overlay: dict) -> None:
    """Escrita atômica com backup e.lock de edição simultânea."""
    UI_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    current = _load_overlay()
    merged = deep_merge(current, overlay)
    backup = None
    if UI_SETTINGS_PATH.exists():
        backup = UI_SETTINGS_PATH.with_suffix(
            f".bak-{datetime.now().strftime('%Y%m%d%H%M%S')}")
        shutil.copy2(UI_SETTINGS_PATH, backup)

    fd, tmp = tempfile.mkstemp(prefix=".ui_settings-", dir=str(UI_SETTINGS_PATH.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(merged, f, allow_unicode=True, sort_keys=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, UI_SETTINGS_PATH)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

    if backup:
        backups = sorted(UI_SETTINGS_PATH.parent.glob("ui_settings.yaml.bak-*"))
        for old in backups[:-5]:
            old.unlink(missing_ok=True)
    CONFIG.clear()
    CONFIG.update(load_config())


def reset_overlay() -> None:
    if UI_SETTINGS_PATH.exists():
        shutil.copy2(UI_SETTINGS_PATH,
                     UI_SETTINGS_PATH.with_suffix(".bak-reset"))
        UI_SETTINGS_PATH.unlink()
    CONFIG.clear()
    CONFIG.update(load_config())


def effective() -> dict:
    return load_config()
