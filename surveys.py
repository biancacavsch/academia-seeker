"""Levantamentos (perfis) com interesses e escopos independentes.

Um levantamento é um arquivo YAML em `surveys/` com:
  - escopo: `academic` (bolsas/CFPs/eventos) ou `professional` (vagas/estágios)
  - `config`: sobrescritas permitidas das seções do config.yaml
  - `enabled`, `schedule`: quando e se roda

O levantamento ativo de cada escopo fica em `active_surveys.yaml` e pode ser
trocado pela webview sem editar arquivos versionados. O perfil "principal"
é o padrão e herda o config.yaml original; ele nunca é excluível.
"""

from __future__ import annotations

import copy
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from config import BASE_DIR, CONFIG, deep_merge

SURVEYS_DIR = BASE_DIR / "surveys"
ACTIVE_PATH = BASE_DIR / "active_surveys.yaml"
MAX_TERMS = 30
MAX_SURVEYS = 12
SCOPES = ("academic", "professional")
DEFAULT_IDS = {"academic": "principal", "professional": "principal"}
TERM_PATHS = {
    "academic": (
        "academic_search.queries.bolsas_pt", "academic_search.queries.bolsas_en",
        "academic_search.queries.bolsas_es", "academic_search.queries.publicacoes_pt",
        "academic_search.queries.publicacoes_en", "academic_search.queries.publicacoes_es",
        "academic_search.queries.eventos_pt", "academic_search.queries.eventos_en",
        "academic_search.queries.eventos_es", "keywords.core", "keywords.scicomm",
        "keywords.glam", "keywords.digital_humanities", "keywords.philosophy_tech",
        "keywords.cfp_specific", "keywords.education_fit", "keywords.broad",
        "filters.interests", "filters.exclude_areas",
    ),
    "professional": (
        "estagio_search.queries.pt", "estagio_search.queries.en",
        "estagio_search.queries.es", "empresas_alvo.empresas",
        "empresas_alvo.queries.pt", "empresas_alvo.queries.en",
        "keywords.estagio", "keywords.core", "keywords.broad",
        "filters.interests", "filters.exclude_areas",
    ),
}

# Chaves que um levantamento pode sobrescrever (whitelist por seção).
EDITABLE_SECTIONS = ("academic_search", "estagio_search", "empresas_alvo",
                    "filters", "keywords", "relevance")


def _safe_id(raw: str) -> str:
    value = re.sub(r"[^a-z0-9_-]+", "-", str(raw or "").strip().lower()).strip("-")
    return value[:48]


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_yaml(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}-", dir=str(path.parent))
    try:
        with __import__("os").fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
            f.flush()
            __import__("os").fsync(f.fileno())
        backup = None
        if path.exists():
            backup = path.with_suffix(path.suffix + ".bak")
            shutil.copy2(path, backup)
        __import__("os").chmod(tmp, 0o644)
        __import__("os").replace(tmp, path)
        if backup and backup.exists():
            backup.unlink()
    finally:
        if Path(tmp).exists():
            Path(tmp).unlink()


def defaults() -> dict[str, dict]:
    """Perfil inicial de cada escopo (herda todo o config.yaml)."""
    return {
        "academic": {
            "id": "principal",
            "name": "Meu levantamento acadêmico",
            "scope": "academic",
            "description": "Humanidades digitais, divulgação científica e filosofia da tecnologia.",
            "enabled": True,
            "config": {},
        },
        "professional": {
            "id": "principal",
            "name": "Meu levantamento profissional",
            "scope": "professional",
            "description": "Vagas e estágios remotos na minha área.",
            "enabled": True,
            "config": {},
        },
    }


def active_ids() -> dict[str, str]:
    data = _read_yaml(ACTIVE_PATH)
    out = dict(DEFAULT_IDS)
    for scope in SCOPES:
        sid = _safe_id(data.get(scope))
        if sid:
            out[scope] = sid
    return out


def set_active(scope: str, survey_id: str) -> bool:
    if scope not in SCOPES:
        return False
    sid = _safe_id(survey_id)
    if not sid or not get_survey(scope, sid):
        return False
    data = _read_yaml(ACTIVE_PATH)
    data[scope] = sid
    _write_yaml(ACTIVE_PATH, data)
    return True


def _survey_path(scope: str, sid: str) -> Path:
    return SURVEYS_DIR / f"{scope}__{_safe_id(sid)}.yaml"


def list_surveys(scope: str) -> list[dict]:
    if scope not in SCOPES:
        return []
    active = active_ids().get(scope)
    out = []
    for path in sorted(SURVEYS_DIR.glob(f"{scope}__*.yaml")):
        data = _read_yaml(path)
        sid = _safe_id(data.get("id") or path.stem.split("__", 1)[-1])
        if data.get("scope", scope) != scope:
            continue
        out.append({
            "id": sid,
            "name": str(data.get("name") or sid)[:80],
            "description": str(data.get("description") or "")[:240],
            "scope": scope,
            "enabled": bool(data.get("enabled", True)),
            "active": sid == active,
            "deletable": sid != "principal",
            "config": data.get("config") or {},
        })
    if not any(s["id"] == "principal" for s in out):
        out.insert(0, dict(defaults()[scope], deletable=False, active=active == "principal"))
    return out


def get_survey(scope: str, sid: str, *, with_config: bool = False) -> dict | None:
    if scope not in SCOPES:
        return None
    sid = _safe_id(sid)
    if not sid:
        return None
    path = _survey_path(scope, sid)
    if not path.exists():
        if sid == "principal":
            result = dict(defaults()[scope], deletable=False,
                          active=active_ids().get(scope) == sid)
            return result if with_config else {k: v for k, v in result.items() if k != "config"}
        return None
    data = _read_yaml(path)
    result = {
        "id": sid,
        "name": str(data.get("name") or sid)[:80],
        "description": str(data.get("description") or "")[:240],
        "scope": scope,
        "enabled": bool(data.get("enabled", True)),
        "active": active_ids().get(scope) == sid,
        "deletable": sid != "principal",
        "config": data.get("config") or {},
    }
    return result if with_config else {k: v for k, v in result.items() if k != "config"}


def count_terms(cfg: dict, scope: str) -> dict[str, int]:
    """Conta termos por caminho, limitado a MAX_TERMS por lista."""
    out = {}
    from web.settings import _dig  # import local evita ciclo
    for path in TERM_PATHS.get(scope, ()):
        value = _dig(cfg, path)
        out[path] = len(value) if isinstance(value, list) else 0
    return out


def validate_config(config: dict, scope: str) -> tuple[dict, list[str]]:
    """Apenas seções da whitelist e listas com no máximo 30 termos."""
    errors: list[str] = []
    clean = {}
    if not isinstance(config, dict):
        return clean, ["config inválido"]
    for section, payload in config.items():
        if section not in EDITABLE_SECTIONS or not isinstance(payload, dict):
            errors.append(f"seção não permitida: {section}")
            continue
        clean[section] = copy.deepcopy(payload)

    # Conta cada lista de termos (inclusive as que o config.yaml já traz).
    base = CONFIG
    from web.settings import _dig
    for path in TERM_PATHS.get(scope, ()):
        current = _dig(clean, path)
        if current is None:
            fallback = _dig(base, path)
            current = copy.deepcopy(fallback) if isinstance(fallback, list) else []
        if not isinstance(current, list):
            errors.append(f"{path}: esperada lista de termos")
            continue
        if len(current) > MAX_TERMS:
            errors.append(f"{path}: {len(current)} termos (máximo {MAX_TERMS})")
            continue
        parts = path.split(".")
        cur = clean
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = current
    return clean, errors


def save_survey(scope: str, sid: str, name: str, description: str,
                enabled: bool, config: dict) -> tuple[dict | None, list[str]]:
    """Cria ou atualiza um levantamento. Retorna (perfil salvo, erros)."""
    if scope not in SCOPES:
        return None, ["escopo inválido"]
    sid = _safe_id(sid)
    if not sid:
        return None, ["identificador inválido"]
    clean, errors = validate_config(config, scope)
    if errors:
        return None, errors
    data = _read_yaml(_survey_path(scope, sid))
    if sid == "principal" and not data:
        data = dict(defaults()[scope])
    data.update({
        "id": sid, "scope": scope,
        "name": str(name or sid).strip()[:80] or sid,
        "description": str(description or "").strip()[:240],
        "enabled": bool(enabled), "config": clean,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    if not list_surveys(scope) and sid == "principal":
        set_active(scope, sid)
    _write_yaml(_survey_path(scope, sid), data)
    return get_survey(scope, sid), []


def delete_survey(scope: str, sid: str) -> tuple[bool, str]:
    if scope not in SCOPES:
        return False, "escopo inválido"
    sid = _safe_id(sid)
    if sid == "principal":
        return False, "o levantamento principal não pode ser excluído"
    path = _survey_path(scope, sid)
    if not path.exists():
        return False, "levantamento não encontrado"
    path.unlink()
    if active_ids().get(scope) == sid:
        data = _read_yaml(ACTIVE_PATH)
        data[scope] = "principal"
        _write_yaml(ACTIVE_PATH, data)
    return True, "levantamento excluído"


def effective_config(scope: str | None = None, *, sid: str | None = None) -> dict:
    """Config efetiva de um levantamento (config.yaml + overlay + perfil)."""
    cfg = copy.deepcopy(CONFIG)
    if scope is None:
        return cfg
    target = _safe_id(sid) if sid else active_ids().get(scope)
    survey = get_survey(scope, target or "", with_config=True)
    if not survey or not survey.get("enabled", True):
        return cfg
    for section, payload in (survey.get("config") or {}).items():
        if section in EDITABLE_SECTIONS and isinstance(payload, dict):
            cfg[section] = deep_merge(cfg.get(section, {}) or {}, payload)
    return cfg
