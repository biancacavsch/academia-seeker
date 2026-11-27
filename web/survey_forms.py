"""Formulários e validação dos levantamentos (acadêmico/profissional)."""

from surveys import (MAX_TERMS, SCOPES, TERM_PATHS, active_ids, delete_survey,
                     effective_config, get_survey, list_surveys, save_survey,
                     set_active)
from web.settings import _dig, _put, parse_terms

# Rótulos PT-BR para cada caminho editável de termos.
TERM_LABELS = {
    "academic_search.queries.bolsas_pt": "Bolsas (PT)",
    "academic_search.queries.bolsas_en": "Bolsas (EN)",
    "academic_search.queries.bolsas_es": "Bolsas (ES)",
    "academic_search.queries.publicacoes_pt": "Publicações (PT)",
    "academic_search.queries.publicacoes_en": "Publicações (EN)",
    "academic_search.queries.publicacoes_es": "Publicações (ES)",
    "academic_search.queries.eventos_pt": "Eventos (PT)",
    "academic_search.queries.eventos_en": "Eventos (EN)",
    "academic_search.queries.eventos_es": "Eventos (ES)",
    "estagio_search.queries.pt": "Estágios (PT)",
    "estagio_search.queries.en": "Estágios (EN)",
    "estagio_search.queries.es": "Estágios (ES)",
    "empresas_alvo.empresas": "Empresas-alvo",
    "empresas_alvo.queries.pt": "Consultas empresas (PT)",
    "empresas_alvo.queries.en": "Consultas empresas (EN)",
    "keywords.core": "Termos centrais",
    "keywords.scicomm": "Divulgação científica",
    "keywords.glam": "Patrimônio / GLAM",
    "keywords.digital_humanities": "Humanidades digitais",
    "keywords.philosophy_tech": "Filosofia da tecnologia",
    "keywords.cfp_specific": "Chamadas (CFP)",
    "keywords.education_fit": "Fit de formação",
    "keywords.broad": "Termos amplos",
    "keywords.estagio": "Estágio",
    "filters.interests": "Interesses",
    "filters.exclude_areas": "Áreas excluídas",
}

NUMBER_LABELS = {
    "academic_search.page_budget": ("Páginas por rodada", 10, 60),
    "academic_search.max_results_per_query": ("Resultados por busca", 1, 20),
    "academic_search.request_delay": ("Pausa entre downloads (s)", 1.0, 10.0),
    "estagio_search.page_budget": ("Páginas (estágios)", 10, 60),
    "estagio_search.max_results_per_query": ("Resultados (estágios)", 1, 20),
    "estagio_search.request_delay": ("Pausa (estágios, s)", 1.0, 10.0),
    "empresas_alvo.page_budget": ("Páginas (empresas)", 10, 60),
    "filters.max_job_age_days": ("Idade máx. da vaga (dias)", 1, 90),
    "filters.min_score_alert": ("Score mín. para alerta", 0, 300),
    "filters.min_score_digest": ("Score mín. para digest", 0, 300),
}

BOOL_LABELS = {
    "academic_search.enabled": "Coleta acadêmica ligada",
    "estagio_search.enabled": "Busca de estágios ligada",
    "empresas_alvo.enabled": "Empresas-alvo ligadas",
    "filters.remote_only": "Só vagas remotas",
    "relevance.opportunity_gate.enabled": "Gate de oportunidade",
    "relevance.deduplication.enabled": "Dedup por título",
}

SELECT_LABELS = {
    "academic_search.timelimit": ("Janela de busca", ["d", "w", "m", "y"]),
    "academic_search.engines": ("Motores acadêmicos", ["ddgs", "marginalia"]),
    "estagio_search.timelimit": ("Janela (estágios)", ["d", "w", "m", "y"]),
    "estagio_search.engines": ("Motores de estágio", ["ddgs"]),
    "empresas_alvo.engines": ("Motores (empresas)", ["ddgs"]),
}

# Caminhos editáveis por escopo (interseção com as seções permitidas).
def _paths(scope: str) -> list[str]:
    return list(TERM_PATHS.get(scope, ()))


def editable_paths(scope: str, sid: str = "") -> dict:
    """Campos editáveis de um levantamento, com valores efetivos.

    `sid` deve ser o levantamento being edited; quando vazio usa o ativo.
    """
    sid = sid or active_ids().get(scope)
    cfg = effective_config(scope, sid=sid)
    terms = []
    for path in _paths(scope):
        values = _dig(cfg, path)
        values = values if isinstance(values, list) else []
        terms.append({
            "path": path,
            "label": TERM_LABELS.get(path, path),
            "text": "\n".join(str(v) for v in values),
            "count": len(values),
            "max": MAX_TERMS,
        })
    numbers = []
    for path, (label, lo, hi) in NUMBER_LABELS.items():
        if path.startswith("academic_search") and scope != "academic":
            continue
        if (path.startswith("estagio_search") or path.startswith("empresas_alvo")) \
                and scope != "professional":
            continue
        value = _dig(cfg, path)
        step = 0.5 if path.endswith("request_delay") else 1
        numbers.append({
            "path": path, "label": label, "value": value,
            "min": lo, "max": hi, "step": step,
        })
    bools = []
    for path, label in BOOL_LABELS.items():
        if path.startswith("academic_search") and scope != "academic":
            continue
        if (path.startswith("estagio_search") or path.startswith("empresas_alvo")) \
                and scope != "professional":
            continue
        bools.append({"path": path, "label": label,
                      "checked": bool(_dig(cfg, path))})
    selects = []
    for path, (label, options) in SELECT_LABELS.items():
        if path.startswith("academic_search") and scope != "academic":
            continue
        if (path.startswith("estagio_search") or path.startswith("empresas_alvo")) \
                and scope != "professional":
            continue
        val = _dig(cfg, path) or []
        if not isinstance(val, list):
            val = [val]
        selects.append({"path": path, "label": label,
                        "options": options, "selected": val})
    sources = []
    kind = "academic_sources" if scope == "academic" else "sources"
    for src in cfg.get(kind, []) or []:
        if not isinstance(src, dict) or not src.get("name"):
            continue
        if scope == "professional" and src.get("kind") == "estagio" and \
                src.get("name") not in ("estagio_search", "adzuna_estagio"):
            # estágios também são escopo profissional; mantém todos
            pass
        sources.append({
            "kind": kind, "name": src["name"],
            "enabled": bool(src.get("enabled")),
            "type": src.get("type", ""),
        })
    blocks = (_dig(cfg, "relevance.blocklists") or {})
    return {
        "terms": terms, "numbers": numbers, "bools": bools,
        "selects": selects, "sources": sources,
        "block_title": "\n".join(blocks.get("title", []) or []),
        "block_domain": "\n".join(blocks.get("domain", []) or []),
        "block_path": "\n".join(blocks.get("url_path", []) or []),
        "survey": get_survey(scope, sid or "") or {},
        "surveys": list_surveys(scope),
    }


def form_to_config(form, scope: str) -> tuple[dict, list[str]]:
    """Converts a survey form POST into a per-survey config overlay."""
    config = {}
    errors = []
    allowed = set(_paths(scope))
    allowed.update(NUMBER_LABELS)
    allowed.update(BOOL_LABELS)
    allowed.update(SELECT_LABELS)
    for key, value in form.items():
        if not key.startswith("cfg:"):
            continue
        path = key[4:]
        if path not in allowed and not path.startswith("relevance.blocklists."):
            continue
        # Escopo rígido: chaves acadêmicas nunca entram no levantamento
        # profissional e vice-versa.
        if path.startswith("academic_search.") and scope != "academic":
            continue
        if (path.startswith("estagio_search.") or path.startswith("empresas_alvo.")) \
                and scope != "professional":
            continue
        if path in allowed and path in TERM_PATHS.get(scope, ()):
            terms = parse_terms(value)
            if len(terms) > MAX_TERMS:  # defesa dupla (parse_terms já limita)
                errors.append(f"{TERM_LABELS.get(path, path)}: máximo {MAX_TERMS} termos")
                continue
            _put(config, path, terms)
        elif path in NUMBER_LABELS:
            label, lo, hi = NUMBER_LABELS[path]
            try:
                num = float(value)
            except (TypeError, ValueError):
                errors.append(f"{label}: número inválido")
                continue
            if not lo <= num <= hi:
                errors.append(f"{label}: use entre {lo} e {hi}")
                continue
            if isinstance(lo, int) and isinstance(hi, int) and num.is_integer():
                num = int(num)
            _put(config, path, num)
        elif path in BOOL_LABELS:
            _put(config, path, value in ("on", "1", "true", "yes"))
        elif path in SELECT_LABELS:
            options = SELECT_LABELS[path][1]
            chosen = [c for c in form.getlist(key) if c in options]
            _put(config, path, chosen)
        elif path.startswith("relevance.blocklists."):
            leaf = path.rsplit(".", 1)[-1]
            if leaf in ("title", "domain", "url_path"):
                _put(config, path, parse_terms(value))

    # Checkboxes desmarcados não chegam no POST.
    for path in BOOL_LABELS:
        if (path.startswith("academic_search") and scope != "academic") or \
           ((path.startswith("estagio_search") or path.startswith("empresas_alvo"))
                and scope != "professional"):
            continue
        if f"cfg:{path}" in form:
            continue
        # Só marca como desligado se o formulário trouxe ao menos um toggle
        # da mesma seção (evita apagar configs em POSTs parciais de teste).
        section = path.split(".", 1)[0]
        if any(k.startswith(f"cfg:{section}") for k in form):
            _put(config, path, False)
    return config, errors


def apply_form(form, scope: str) -> tuple[bool, list[str]]:
    """Aplica criar/editar/excluir/ativar a partir de um POST."""
    action = form.get("action", "save")
    sid_raw = form.get("survey_id", "")
    sid = sid_raw.strip().lower().replace(" ", "-")[:48]
    if action == "save" and not sid:
        # POSTs sem ID (ex.: abrir a página sem ?editar) editam o ativo.
        sid = active_ids().get(scope, "principal")
    if action == "delete":
        ok, msg = delete_survey(scope, sid)
        return ok, [msg]
    if action == "activate":
        ok = set_active(scope, sid)
        return ok, [] if ok else ["Não foi possível ativar o levantamento"]
    if action == "create":
        sid = sid or "novo-" + datetime_now()
        if get_survey(scope, sid):
            return False, ["Já existe um levantamento com esse identificador"]
    config, errors = form_to_config(form, scope)
    if errors:
        return False, errors
    ok, errs = save_survey(
        scope, sid,
        form.get("survey_name", sid),
        form.get("survey_description", ""),
        form.get("survey_enabled", "on") == "on",
        config,
        form.get("survey_email", ""),
    )
    if not ok:
        return False, errs
    if action == "create":
        set_active(scope, sid)
    return True, []


def datetime_now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%d%m%y-%H%M%S")
