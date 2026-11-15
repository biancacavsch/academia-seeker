"""Deadline extraction and open/closed status for academic opportunities.

Norma (bem definida):
- Toda oportunidade acadêmica tem `deadline_status` em {open, closing_soon, closed, unknown}.
- Só `open` (e sua subdivisão visual `closing_soon`, ≤15 dias) pode alertar e
  aparecer nas seções ①②③ do digest.
- `closed`: data de fechamento < hoje OU marcador de encerramento no texto.
- `unknown`: nenhuma data de fechamento extraível → quarentena rotulada, nunca alerta.
- Data de referência: momento do scraping (`first_seen_at`); reavaliada contra
  "agora" no momento do alerta.
- Qual data vale (prioridade): (a) fim explícito de intervalo;
  (b) data ligada a marcador explícito; (c) data avulsa NÃO vale.
- Comparação por data (UTC); o dia do vencimento conta como aberto.
"""

import re
from datetime import datetime
from typing import Optional

# Marcadores de encerramento (PT/EN/ES)
CLOSED_PATTERNS = [
    r"\bencerrad[oa]s?\b",
    r"\binscri[çc][õo]es?\s+encerradas?\b",
    r"\bchamada\s+encerrada\b",
    r"\bprazo\s+encerrad[oa]s?\b",
    r"\bfinalizad[oa]s?\b",
    r"\bclosed\b",
    r"\bapplications?\s+closed\b",
    r"\bcall\s+closed\b",
    r"\bdeadline\s+passed\b",
    r"\bno\s+longer\s+accepting\b",
    r"\bcerrad[oa]s?\b",
    r"\bconvocatoria\s+cerrada\b",
    r"\bplazo\s+finalizado\b",
]
CLOSED_RE = re.compile("|".join(f"(?:{p})" for p in CLOSED_PATTERNS), re.IGNORECASE)

MONTHS_PT = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}
MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5,
    "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9,
    "octubre": 10, "noviembre": 11, "diciembre": 12,
}
MONTHS_EN = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
ALL_MONTHS = {**MONTHS_PT, **MONTHS_ES, **MONTHS_EN}

# Marcadores explícitos de prazo (PT/EN/ES)
DEADLINE_MARKERS = (
    r"deadline|data\s+limite|prazo(?:\s+final|\s+de\s+(?:inscri[çc][ãa]o|submiss[ãa]o))?|"
    r"submiss[ãa]o(?:es)?\s+at[ée]|inscri[çc][õo]es?\s+at[ée]|\bat[ée]\b|"
    r"application\s+deadline|applications?\s+(?:close|due|open\s+until)|"
    r"\bcloses?\b|\bclosing\s+date\b|\bdue\s+(?:date|by)?|"
    r"cierre|fecha\s+l[íi]mite|plazo(?:\s+de\s+(?:inscripci[óo]n|env[íi]o))?|"
    r"env[íi]o\s+hasta|hasta\s+el"
)

DATE_NUM = r"(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2,4})"
DATE_ISO = r"(\d{4})-(\d{1,2})-(\d{1,2})"
MONTH_NAMES = "|".join(sorted(ALL_MONTHS, key=len, reverse=True))
DATE_TEXT = rf"(\d{{1,2}})\s+de\s+({MONTH_NAMES})(?:\s+de\s+(\d{{4}}))?"
DATE_TEXT_EN = rf"({MONTH_NAMES})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})"


def is_closed(text: str) -> bool:
    """True se o texto indica oportunidade encerrada."""
    return bool(CLOSED_RE.search(text or ""))


def _parse_num(d: str, m: str, y: str) -> Optional[datetime]:
    day, mon, year = int(d), int(m), int(y)
    if year < 100:
        year += 2000
    # Assume formato BR DD/MM; se mês > 12, tenta MM/DD
    if mon > 12 and day <= 12:
        day, mon = mon, day
    try:
        return datetime(year, mon, day)
    except ValueError:
        return None


def _parse_text_date(day: str, month_name: str, year: Optional[str],
                     ref: datetime) -> Optional[datetime]:
    mon = ALL_MONTHS.get(month_name.lower())
    if not mon:
        return None
    y = int(year) if year else ref.year
    try:
        dt = datetime(y, mon, int(day))
    except ValueError:
        return None
    # Sem ano explícito e data já passada → assume próximo ano
    if not year and dt.date() < ref.date():
        try:
            dt = datetime(y + 1, mon, int(day))
        except ValueError:
            return None
    return dt


def _parse_text_date_en(month_name: str, day: str, year: str) -> Optional[datetime]:
    mon = ALL_MONTHS.get(month_name.lower())
    if not mon:
        return None
    try:
        return datetime(int(year), mon, int(day))
    except ValueError:
        return None


def _find_dates(text: str, ref: datetime) -> list:
    """Todas as datas encontradas com sua posição no texto."""
    out = []
    for m in re.finditer(DATE_NUM, text):
        dt = _parse_num(*m.groups())
        if dt:
            out.append((m.start(), dt))
    for m in re.finditer(DATE_ISO, text):
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            out.append((m.start(), dt))
        except ValueError:
            pass
    for m in re.finditer(DATE_TEXT, text, re.IGNORECASE):
        dt = _parse_text_date(m.group(1), m.group(2), m.group(3), ref)
        if dt:
            out.append((m.start(), dt))
    for m in re.finditer(DATE_TEXT_EN, text, re.IGNORECASE):
        dt = _parse_text_date_en(m.group(1), m.group(2), m.group(3))
        if dt:
            out.append((m.start(), dt))
    return sorted(out)


def _parse_range_end(groups, ref: datetime) -> Optional[datetime]:
    half = len(groups) // 2
    tail = groups[half:]
    if len(tail) < 2 or not tail[0] or not tail[1]:
        return None
    if tail[1].isdigit() and len(tail) >= 3 and tail[2] and tail[2].isdigit():
        return _parse_num(tail[0], tail[1], tail[2])
    return _parse_text_date(tail[0], tail[1], tail[2] if len(tail) > 2 else None, ref)


def extract_closing_date(text: str, ref: Optional[datetime] = None) -> Optional[datetime]:
    """Extrai a data de fechamento. Retorna None se indeterminável.

    Prioridade: (a) fim de intervalo explícito; (b) data após marcador
    explícito; (c) data avulsa NÃO vale → None.
    """
    ref = ref or datetime.utcnow()
    text = text or ""

    # (a) Intervalos: "29/04/2026 a 28/05/2026", "de X a Y", "X - Y", "X to Y"
    range_pats = [
        rf"{DATE_NUM}\s*(?:a|at[ée]|-|–|to)\s*{DATE_NUM}",
        rf"{DATE_TEXT}\s*(?:a|at[ée]|-|–|to)\s*{DATE_TEXT}",
    ]
    for pat in range_pats:
        for m in re.finditer(pat, text, re.IGNORECASE):
            end = _parse_range_end(m.groups(), ref)
            if end:
                return end

    # (b) Data após marcador explícito (janela de 80 chars após o marcador)
    for m in re.finditer(DEADLINE_MARKERS, text, re.IGNORECASE):
        window = text[m.end():m.end() + 80]
        dates = _find_dates(window, ref)
        if dates:
            return dates[0][1]

    # (c) Data avulsa não vale
    return None


def compute_deadline_status(closing: Optional[datetime],
                            text: str = "",
                            ref: Optional[datetime] = None,
                            soon_days: int = 15) -> str:
    """open | closing_soon | closed | unknown (comparação por data, UTC)."""
    ref = ref or datetime.utcnow()
    today = ref.date()
    if is_closed(text):
        return "closed"
    if closing is None:
        return "unknown"
    day = closing.date() if isinstance(closing, datetime) else closing
    if day < today:
        return "closed"
    if (day - today).days <= soon_days:
        return "closing_soon"
    return "open"
