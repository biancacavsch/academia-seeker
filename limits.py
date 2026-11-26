"""Limite rígido de 30 termos por lista de palavras-chave/consulta.

Aplicado em TODAS as listas relevantes no carregamento da config, inclusive
em valores que já vinham do config.yaml versionado (ex.: 'broad' com 76 e
'interests' com 142 termos). Nenhuma lista passa de 30 em memória.
"""

from config import BASE_DIR  # noqa: F401  (garante import do pacote)

MAX_TERMS = 30

# Caminhos (config.yaml) que são listas de termos. Caminhos aninhados com '.'
# percorrem dicts; listas de source NÃO são tocadas.
TERM_PATHS = (
    "academic_search.queries.bolsas_pt", "academic_search.queries.bolsas_en",
    "academic_search.queries.bolsas_es", "academic_search.queries.publicacoes_pt",
    "academic_search.queries.publicacoes_en", "academic_search.queries.publicacoes_es",
    "academic_search.queries.eventos_pt", "academic_search.queries.eventos_en",
    "academic_search.queries.eventos_es",
    "estagio_search.queries.pt", "estagio_search.queries.en", "estagio_search.queries.es",
    "empresas_alvo.empresas", "empresas_alvo.queries.pt", "empresas_alvo.queries.en",
    "keywords.core", "keywords.scicomm", "keywords.glam",
    "keywords.philosophy_tech", "keywords.digital_humanities",
    "keywords.cfp_specific", "keywords.education_fit", "keywords.broad",
    "keywords.estagio", "keywords.negatives",
    "filters.interests", "filters.exclude_areas", "filters.onsite_markers",
    "filters.remote_strong_markers",
)

# Blocklists de relevância também são listas de termos.
BLOCKLIST_PATHS = (
    "relevance.blocklists.title", "relevance.blocklists.domain",
    "relevance.blocklists.url_path", "relevance.blocklists.source",
    "relevance.opportunity_gate.relaxed_sources",
)


def _dig(cfg, path):
    cur = cfg
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False, None
        cur = cur[part]
    return True, cur


def _put(cfg, path, value):
    parts = path.split(".")
    cur = cfg
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def enforce_limits(cfg: dict) -> tuple[dict, dict[str, int]]:
    """Trunca listas > 30 em `cfg` (in-place) e devolve contagens de corte."""
    trimmed = {}
    for path in TERM_PATHS + BLOCKLIST_PATHS:
        found, value = _dig(cfg, path)
        if not found or not isinstance(value, list):
            continue
        if len(value) > MAX_TERMS:
            trimmed[path] = len(value)
            unique = []
            seen = set()
            for item in value:
                key = str(item).strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                unique.append(item)
            _put(cfg, path, unique[:MAX_TERMS])
    return cfg, trimmed
