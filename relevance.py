"""Calibração de relevância: gate de oportunidade, blocklists e dedup.

Roda ANTES da pontuação (score.py). A ideia é responder primeiro à pergunta
"isto é uma vaga/bolsa/chamada/evento de verdade?" — e só depois calcular
quantos pontos o assunto tem. Score alto em uma notícia sobre DH continuava
gerando alerta; o gate barra isso na origem.

Todas as listas vêm de CONFIG["relevance"], que pode ser sobrescrito pelo
ui_settings.yaml (editado pela webview).
"""

import re
import unicodedata
from urllib.parse import urlparse

from config import CONFIG
from models import AcademicItem

# Valores padrão — também ficam documentados em config.yaml.
DEFAULT_MARKERS = {
    "bolsa": [
        "edital", "bolsa", "bolsas", "beca", "becas", "scholarship",
        "scholarships", "fellowship", "fellowships", "grant", "grants",
        "financiamento", "auxílio", "auxilio", "financiación", "bourse",
        "studentship", "stipend", "research funding", "call for applications",
        "convocatoria de becas", "inscrições abertas", "inscricoes abertas",
        "bursary", "bursaries", "travel grant", "financial support",
    ],
    "publicacao": [
        "call for papers", "cfp", "chamada", "chamadas", "convocatoria",
        "convocatorias", "submissão", "submissao", "submissions", "submission",
        "deadline", "prazo", "dossiê", "dossie", "special issue", "número temático",
        "numero tematico", "propostas", "papers", "articles", "authors",
        "proposal", "proposals", "call for contributions", "call for chapters",
        "call for", "submeter",
    ],
    "evento": [
        "conference", "congress", "workshop", "symposium", "colloquium",
        "seminar", "summer school", "winter school", "conferência", "conferencia",
        "congresso", "encontro", "jornadas", "simpósio", "simposio", "oficina",
        "evento", "registration", "inscrição", "inscricao", "keynote",
        "call for sessions", "call for panels", "call for presentations",
    ],
    "vaga": [
        "vaga", "vagas", "estágio", "estagio", "estágios", "estagios",
        "internship", "internships", "intern", "hiring", "job", "jobs",
        "position", "positions", "apply", "application", "contratação",
        "contratacao", "trainee", "open role", "career opportunity",
        "remote work", "trabalho remoto", "home office",
    ],
}

DEFAULT_BLOCK_TITLE = [
    "election", "elections", "electoral", "candidate statement",
    "newsletter", "portraits in dh", "new liaison", "new liaisons",
    "newcomers' dinner", "newcomer", "welcome new", "welcoming our new",
    "open letter", "annual general meeting", "annual report",
    "dies aged", "reflecting on", "notes from", "monthly updates",
    "november updates", "december updates", "how to", "guia para",
    "guide to", "dicas para", "best ways", "top tips", "ranking",
    "notícia", "noticia", "notícias", "noticias", "reportagem",
    "podcast", "webinar", "salário", "salario", "salary",
]

DEFAULT_BLOCK_DOMAIN = [
    "wikipedia.org", "youtube.com", "reddit.com", "quora.com",
    "pinterest.com", "glassdoor.com", "medium.com",
]

DEFAULT_BLOCK_PATH = ["/noticia/", "/podcast/", "/opinion/"]

# Fontes curadas: o título costuma ser o nome do artigo, não "Call for Papers".
DEFAULT_RELAXED_SOURCES = [
    "wikicfp", "hnet_announcements", "dhnow_cfps", "dhnow_conferences",
    "philpapers_cfp", "ala_techsource", "dhsi_feed", "euraxess",
]

# Ruído comum em títulos de anúncio repetidos (dedup por prefixo).
DEDUP_NOISE = {
    "vaga", "vagas", "home", "office", "remoto", "remota", "remote",
    "oportunidade", "oportunidades", "oferece", "na", "no", "da", "de",
    "para", "com", "e", "em", "the", "a", "an", "and", "at",
}


_FEEDBACK_BLOCKS = None


def _relevance_cfg() -> dict:
    return CONFIG.get("relevance", {}) or {}


def _feedback_blocks() -> dict:
    """Cache por processo: evita abrir o SQLite para cada item pontuado."""
    global _FEEDBACK_BLOCKS
    if _FEEDBACK_BLOCKS is None:
        try:
            from feedback import get_feedback_store
            _FEEDBACK_BLOCKS = get_feedback_store().blocked()
        except Exception:
            _FEEDBACK_BLOCKS = {"domains": [], "sources": []}
    return _FEEDBACK_BLOCKS


def _compile(words, *, exact_words: bool = True):
    """Compila lista de termos em regex; expressões com espaços são literais."""
    pats = []
    for raw in words or []:
        term = str(raw).strip()
        if not term:
            continue
        escaped = re.escape(term).replace(r"\ ", r"\s+")
        if exact_words and not any(c in term for c in " /-"):
            escaped = rf"\b{escaped}\b"
        pats.append(re.compile(escaped, re.IGNORECASE))
    return pats


def strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text or "")
        if not unicodedata.combining(c)
    )


def normalize_title(title: str) -> str:
    """Título normalizado para dedup (sem acento, pontuação e ruído comum)."""
    clean = strip_accents(title or "").lower()
    clean = re.sub(r"[^a-z0-9]+", " ", clean)
    return re.sub(r"\s+", " ", clean).strip()


def dedup_key(title: str, prefix_tokens: int = 3) -> str:
    """Chave curta: primeiros tokens significativos do título.

    'Estágio em Mídias Sociais – Remoto', 'Estágio em Mídias Sociais | Elifegroup'
    e 'ESTÁGIO EM MÍDIAS SOCIAIS: ...' viram a mesma chave.
    """
    tokens = [t for t in normalize_title(title).split() if t not in DEDUP_NOISE]
    return " ".join(tokens[:prefix_tokens]) if tokens else ""


def domain_of(url: str) -> str:
    try:
        return (urlparse(url or "").hostname or "").lower()
    except Exception:
        return ""


def _source_of(item) -> str:
    return (getattr(item, "source", "") or "").lower()


def _track_of(item) -> str:
    track = (getattr(item, "track", "") or "").lower()
    if track:
        return track
    return (getattr(item, "category", "") or "").lower()


def check_opportunity(item, settings: dict = None) -> tuple[bool, str]:
    """Retorna (elegível, motivo). Motivo é gravado em matched_keywords."""
    cfg = settings if settings is not None else _relevance_cfg()
    if not cfg.get("enabled", True):
        return True, ""

    gate = cfg.get("opportunity_gate", {}) or {}
    blocks = cfg.get("blocklists", {}) or {}

    title = getattr(item, "title", "") or ""
    desc = getattr(item, "description", "") or ""
    url = getattr(item, "url", "") or ""

    # Sinais de oportunidade no título são calculados antes das blocklists:
    # "[Notícia] CHAMADA DE TRABALHOS" é chamada legítima, não notícia.
    markers = gate.get("markers", {}) or {}
    all_markers = []
    for group in ("bolsa", "publicacao", "evento", "vaga"):
        all_markers.extend(markers.get(group) or DEFAULT_MARKERS.get(group, []))
    signal_pats = _compile(list(dict.fromkeys(all_markers)))
    title_has_signal = any(p.search(title) for p in signal_pats)

    # 1) Blocklists explícitas
    for raw in blocks.get("title", []) or []:
        term = strip_accents(str(raw)).strip().lower()
        if term and term in strip_accents(title).lower() and not title_has_signal:
            return False, f"filtered: blocked title ({term})"

    domain = domain_of(url)
    domain_list = list(blocks.get("domain", []) or [])
    source_list = list(blocks.get("source", []) or [])
    if cfg.get("use_feedback", True):
        fb = _feedback_blocks()
        domain_list.extend(fb.get("domains") or [])
        source_list.extend(fb.get("sources") or [])
    if _source_of(item) in {s.lower() for s in source_list}:
        return False, "filtered: blocked source (feedback)"
    for raw in domain_list:
        blocked = str(raw).strip().lower().lstrip(".")
        if blocked and (domain == blocked or domain.endswith("." + blocked)):
            return False, f"filtered: blocked domain ({blocked})"

    for raw in blocks.get("url_path", []) or []:
        hint = str(raw).strip().lower()
        if hint and hint in (urlparse(url).path or "").lower():
            return False, f"filtered: blocked url path ({hint})"

    for raw in blocks.get("regex", []) or []:
        try:
            if re.search(str(raw), f"{title} {desc}", re.IGNORECASE):
                return False, "filtered: blocked regex"
        except re.error:
            continue

    # 2) Gate de oportunidade — só para itens acadêmicos.
    # Vagas já vêm de fontes de vagas e passam pelos gates de interesse/remoto
    # no score.py; exigir "vaga/job/internship" no título mataria anúncios
    # legítimos como "Research Data Steward".
    if not gate.get("enabled", True) or not isinstance(item, AcademicItem):
        return True, ""

    # Determina o conjunto de termos esperado pelo trilho do item
    track = _track_of(item)
    if "bolsa" in track or "fellow" in track or "scholarship" in track:
        expected = markers.get("bolsa") or DEFAULT_MARKERS["bolsa"]
    elif "public" in track or "cfp" in track or "paper" in track:
        expected = markers.get("publicacao") or DEFAULT_MARKERS["publicacao"]
    elif "event" in track or "conference" in track or "workshop" in track:
        expected = markers.get("evento") or DEFAULT_MARKERS["evento"]
    elif track == "job":
        expected = markers.get("vaga") or DEFAULT_MARKERS["vaga"]
    else:
        expected = all_markers

    # Uma chamada de bolsa também é oportunidade se disser "call for papers"
    # etc. — por isso sempre inclui os marcadores gerais.
    pats = _compile(list(dict.fromkeys(expected + all_markers)))
    if not any(p.search(title) for p in pats):
        relaxed = _source_of(item) in {
            str(s).lower() for s in (gate.get("relaxed_sources") or DEFAULT_RELAXED_SOURCES)
        }
        hay = f"{title} {desc[:800]}" if relaxed else title
        if not any(p.search(hay) for p in pats):
            return False, "filtered: not an opportunity"
    return True, ""


def deduplicate(items, settings: dict = None):
    """Remove duplicados por título normalizado/prefixo, mantendo a ordem.

    Só deduplica dentro da mesma fonte para não perder o mesmo CFP republicado
    por dois agregadores diferentes.
    """
    cfg = settings if settings is not None else _relevance_cfg()
    dcfg = cfg.get("deduplication", {}) or {}
    if not dcfg.get("enabled", True):
        return list(items)

    prefix = int(dcfg.get("prefix_tokens", 3))
    seen = set()
    out = []
    for item in items:
        key = dedup_key(getattr(item, "title", ""), prefix)
        if not key:
            out.append(item)
            continue
        signature = (_source_of(item), key)
        if signature in seen:
            continue
        seen.add(signature)
        out.append(item)
    return out
