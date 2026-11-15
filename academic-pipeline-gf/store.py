"""SQLite storage for jobs and academic items."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Union, List
from datetime import datetime, timedelta

from models import Job, AcademicItem, BaseItem
from config import CONFIG


SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    url_hash TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    category TEXT NOT NULL,
    url TEXT NOT NULL,
    description TEXT,
    tags TEXT,
    posted_at TEXT,
    deadline_at TEXT,
    location TEXT,
    language TEXT,
    score REAL DEFAULT 0,
    matched_keywords TEXT,
    raw_data TEXT,
    -- Job fields
    company TEXT,
    remote INTEGER,
    salary_min INTEGER,
    salary_max INTEGER,
    salary_text TEXT,
    -- Academic fields
    event_type TEXT,
    venue TEXT,
    submission_deadline TEXT,
    event_start_date TEXT,
    event_end_date TEXT,
    topics TEXT,
    is_virtual INTEGER,
    travel_grant INTEGER,
    track TEXT,
    deadline_status TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts_sent (
    url_hash TEXT PRIMARY KEY,
    alerted_at TEXT NOT NULL,
    channel TEXT NOT NULL,
    FOREIGN KEY (url_hash) REFERENCES items (url_hash)
);

CREATE INDEX IF NOT EXISTS idx_items_posted_at ON items (posted_at);
CREATE INDEX IF NOT EXISTS idx_items_score ON items (score);
CREATE INDEX IF NOT EXISTS idx_items_source ON items (source);
CREATE INDEX IF NOT EXISTS idx_items_category ON items (category);
CREATE INDEX IF NOT EXISTS idx_items_deadline ON items (deadline_at);
CREATE INDEX IF NOT EXISTS idx_items_track ON items (track);
CREATE INDEX IF NOT EXISTS idx_items_deadline_status ON items (deadline_status);
"""


class ItemStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or CONFIG["storage"]["db_path"]
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            stmts = [s.strip() for s in SCHEMA.split(";") if s.strip()]
            # 1. Tabelas (idempotente)
            for s in stmts:
                if s.upper().startswith("CREATE TABLE"):
                    conn.execute(s)
            # 2. Migração de colunas para bancos criados antes de track/deadline_status
            cols = {r[1] for r in conn.execute("PRAGMA table_info(items)").fetchall()}
            if "track" not in cols:
                conn.execute("ALTER TABLE items ADD COLUMN track TEXT")
            if "deadline_status" not in cols:
                conn.execute("ALTER TABLE items ADD COLUMN deadline_status TEXT")
            # 3. Índices (só agora as colunas garantidamente existem)
            for s in stmts:
                if s.upper().startswith("CREATE INDEX"):
                    conn.execute(s)
            conn.commit()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _item_to_row(self, item: BaseItem) -> tuple:
        now = datetime.utcnow().isoformat()
        base = (
            item.url_hash, item.title, item.source, item.category, item.url,
            item.description, ",".join(item.tags) if item.tags else "",
            item.posted_at.isoformat() if item.posted_at else None,
            item.deadline_at.isoformat() if item.deadline_at else None,
            item.location, item.language, item.score,
            ",".join(item.matched_keywords) if item.matched_keywords else "",
            str(item.raw_data) if item.raw_data else "",
        )
        if isinstance(item, Job):
            job_fields = (
                item.company, int(item.remote), item.salary_min, item.salary_max, item.salary_text,
                None, None, None, None, None, None, None, None, None, None,
            )
        else:
            job_fields = (None, None, None, None, None,
                item.event_type if hasattr(item, 'event_type') else None,
                item.venue if hasattr(item, 'venue') else None,
                item.submission_deadline.isoformat() if item.submission_deadline else None,
                item.event_start_date.isoformat() if item.event_start_date else None,
                item.event_end_date.isoformat() if item.event_end_date else None,
                ",".join(item.topics) if item.topics else None,
                int(item.is_virtual) if hasattr(item, 'is_virtual') else 0,
                int(item.travel_grant) if hasattr(item, 'travel_grant') else 0,
                getattr(item, 'track', None) or None,
                getattr(item, 'deadline_status', None) or None,
            )
        return base + job_fields + (now, now)

    def upsert_item(self, item: BaseItem) -> bool:
        """Insere ou atualiza item. Retorna True se é novo (não existia)."""
        with self._conn() as conn:
            cursor = conn.execute("SELECT url_hash FROM items WHERE url_hash = ?", (item.url_hash,))
            exists = cursor.fetchone() is not None

            row = self._item_to_row(item)
            conn.execute("""
                INSERT INTO items (url_hash, title, source, category, url, description,
                                 tags, posted_at, deadline_at, location, language, score,
                                 matched_keywords, raw_data,
                                 company, remote, salary_min, salary_max, salary_text,
                                 event_type, venue, submission_deadline, event_start_date,
                                 event_end_date, topics, is_virtual, travel_grant,
                                 track, deadline_status,
                                 first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url_hash) DO UPDATE SET
                    title = excluded.title,
                    source = excluded.source,
                    category = excluded.category,
                    url = excluded.url,
                    description = excluded.description,
                    tags = excluded.tags,
                    posted_at = excluded.posted_at,
                    deadline_at = excluded.deadline_at,
                    location = excluded.location,
                    language = excluded.language,
                    score = excluded.score,
                    matched_keywords = excluded.matched_keywords,
                    raw_data = excluded.raw_data,
                    company = excluded.company,
                    remote = excluded.remote,
                    salary_min = excluded.salary_min,
                    salary_max = excluded.salary_max,
                    salary_text = excluded.salary_text,
                    event_type = excluded.event_type,
                    venue = excluded.venue,
                    submission_deadline = excluded.submission_deadline,
                    event_start_date = excluded.event_start_date,
                    event_end_date = excluded.event_end_date,
                    topics = excluded.topics,
                    is_virtual = excluded.is_virtual,
                    travel_grant = excluded.travel_grant,
                    track = excluded.track,
                    deadline_status = excluded.deadline_status,
                    last_seen_at = excluded.last_seen_at
            """, row)
            conn.commit()
        return not exists

    def get_item(self, url_hash: str) -> Optional[BaseItem]:
        with self._conn() as conn:
            cursor = conn.execute("SELECT * FROM items WHERE url_hash = ?", (url_hash,))
            row = cursor.fetchone()
            return self._row_to_item(dict(row)) if row else None

    def _row_to_item(self, row: dict) -> BaseItem:
        cat = row.get("category", "job")
        if cat == "job":
            return Job.from_dict(row)
        else:
            return AcademicItem.from_dict(row)

    def is_alerted(self, url_hash: str) -> bool:
        with self._conn() as conn:
            cursor = conn.execute("SELECT 1 FROM alerts_sent WHERE url_hash = ?", (url_hash,))
            return cursor.fetchone() is not None

    def mark_alerted(self, url_hash: str, channel: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO alerts_sent (url_hash, alerted_at, channel) VALUES (?, ?, ?)",
                (url_hash, datetime.utcnow().isoformat(), channel)
            )
            conn.commit()

    def get_unalerted_items(self, min_score: float = 0, category: Optional[str] = None, kind: Optional[str] = None) -> List[BaseItem]:
        from config import CONFIG
        max_age = CONFIG.get("filters", {}).get("max_job_age_days", 30)
        cutoff = (datetime.utcnow() - timedelta(days=max_age)).isoformat()
        with self._conn() as conn:
            # Garantia de edital aberto: itens acadêmicos só alertam com
            # submission_deadline futura OU NÃO INFORMADA (NULL = prazo
            # desconhecido, não vencido — sem isso a maioria das bolsas,
            # que não expõe deadline parseável, nunca alertaria).
            # Só se suprime prazo VENCIDO. Reavaliado "agora", não só na
            # coleta. Vagas passam pela idade do post; acadêmicos, SÓ pela
            # deadline (post antigo com deadline futuro continua válido).
            query = """
                SELECT i.* FROM items i
                LEFT JOIN alerts_sent a ON i.url_hash = a.url_hash
                WHERE a.url_hash IS NULL AND i.score >= ?
                AND ((i.category = 'job'
                      AND (i.posted_at IS NULL OR i.posted_at >= ?))
                     OR (i.category != 'job'
                         AND (i.submission_deadline IS NULL
                              OR date(i.submission_deadline) >= date('now'))))
            """
            params = [min_score, cutoff]
            if category:
                query += " AND i.category = ?"
                params.append(category)
            if kind == "job":
                query += " AND i.category = 'job'"
            elif kind == "academic":
                query += " AND i.category != 'job'"
            query += " ORDER BY i.score DESC, i.posted_at DESC"
            cursor = conn.execute(query, params)
            return [self._row_to_item(dict(row)) for row in cursor.fetchall()]

    def get_recent_items(self, days: int = 7, min_score: float = 0, category: Optional[str] = None, track: Optional[str] = None, posted_age: bool = True) -> List[BaseItem]:
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            query = "SELECT * FROM items WHERE score >= ?"
            params = [min_score]
            if posted_age:
                query += " AND posted_at >= ?"
                params.append(cutoff)
            if category:
                query += " AND category = ?"
                params.append(category)
            if track:
                query += " AND track = ?"
                params.append(track)
            query += " ORDER BY score DESC, posted_at DESC"
            cursor = conn.execute(query, params)
            return [self._row_to_item(dict(row)) for row in cursor.fetchall()]

    def get_upcoming_deadlines(self, days: int = 30, category: Optional[str] = "cfp") -> List[BaseItem]:
        """Items with submission deadline in the next N days.

        category=None → qualquer categoria (a maioria dos CFPs vem como
        'publicacao', não 'cfp'; com filtro fixo o comando saía sempre vazio).
        """
        cutoff = (datetime.utcnow() + timedelta(days=days)).isoformat()
        with self._conn() as conn:
            query = """
                SELECT * FROM items
                WHERE submission_deadline IS NOT NULL
                AND submission_deadline <= ? AND submission_deadline >= ?
            """
            params = [cutoff, datetime.utcnow().isoformat()]
            if category:
                query += " AND category = ?"
                params.append(category)
            query += " ORDER BY submission_deadline ASC"
            cursor = conn.execute(query, params)
            return [self._row_to_item(dict(row)) for row in cursor.fetchall()]

    def get_stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            alerted = conn.execute("SELECT COUNT(*) FROM alerts_sent").fetchone()[0]
            by_source = dict(conn.execute("SELECT source, COUNT(*) FROM items GROUP BY source").fetchall())
            by_category = dict(conn.execute("SELECT category, COUNT(*) FROM items GROUP BY category").fetchall())
            avg_score = conn.execute("SELECT AVG(score) FROM items").fetchone()[0] or 0
            return {
                "total_items": total,
                "alerted": alerted,
                "unalerted": total - alerted,
                "by_source": by_source,
                "by_category": by_category,
                "avg_score": round(avg_score, 1),
            }


def get_academic_store() -> ItemStore:
    """Store do banco acadêmico: bolsas/eventos/chamadas (academic.db)."""
    cfg = CONFIG.get("storage", {})
    return ItemStore(cfg.get("db_path_academic") or cfg.get("db_path"))