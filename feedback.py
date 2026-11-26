"""Feedback e auditoria das decisões de relevância.

Toda decisão (alertado / rejeitado) é registrada em feedback.db. A webview
usa esses dados para mostrar precisão por fonte e para transformar o botão
"Irrelevante" em regras aplicadas na próxima coleta.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from config import CONFIG

SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url_hash TEXT NOT NULL,
    title TEXT,
    source TEXT,
    domain TEXT,
    score REAL,
    decision TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decisions_source ON decisions(source);
CREATE INDEX IF NOT EXISTS idx_decisions_created ON decisions(created_at);

CREATE TABLE IF NOT EXISTS feedback (
    url_hash TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    reason TEXT,
    title TEXT,
    source TEXT,
    domain TEXT,
    created_at TEXT NOT NULL
);
"""


class FeedbackStore:
    def __init__(self, db_path=None):
        self.db_path = db_path or CONFIG["storage"].get("db_path_feedback", "feedback.db")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            conn.execute("PRAGMA journal_mode=WAL")

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def record(self, item, decision: str, reason: str = ""):
        from relevance import domain_of
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO decisions
                   (url_hash, title, source, domain, score, decision, reason, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (getattr(item, "url_hash", ""), getattr(item, "title", ""),
                 getattr(item, "source", ""), domain_of(getattr(item, "url", "")),
                 getattr(item, "score", 0), decision, reason,
                 datetime.utcnow().isoformat()),
            )

    def mark(self, item, label: str, reason: str = ""):
        """label: relevant | irrelevant | block_domain | block_source."""
        from relevance import domain_of
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO feedback
                   (url_hash, label, reason, title, source, domain, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(url_hash) DO UPDATE SET
                     label=excluded.label, reason=excluded.reason,
                     created_at=excluded.created_at""",
                (getattr(item, "url_hash", ""), label, reason,
                 getattr(item, "title", ""), getattr(item, "source", ""),
                 domain_of(getattr(item, "url", "")),
                 datetime.utcnow().isoformat()),
            )

    def labels(self) -> dict[str, str]:
        with self._conn() as conn:
            return {r["url_hash"]: r["label"] for r in conn.execute(
                "SELECT url_hash, label FROM feedback")}

    def blocked(self) -> dict:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT label, source, domain FROM feedback "
                "WHERE label IN ('block_domain', 'block_source')").fetchall()
        return {
            "domains": sorted({r["domain"] for r in rows if r["label"] == "block_domain" and r["domain"]}),
            "sources": sorted({r["source"] for r in rows if r["label"] == "block_source" and r["source"]}),
        }

    def precision_by_source(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT source,
                          SUM(CASE WHEN decision='alerted' THEN 1 ELSE 0 END) AS alerted,
                          COUNT(*) AS total
                   FROM decisions GROUP BY source ORDER BY total DESC""").fetchall()
        with self._conn() as conn:
            fb = {(r["source"], r["label"]): r["c"] for r in conn.execute(
                "SELECT source, label, COUNT(*) AS c FROM feedback GROUP BY source, label")}
        out = []
        for r in rows:
            src = r["source"]
            relevant = fb.get((src, "relevant"), 0)
            irrelevant = fb.get((src, "irrelevant"), 0)
            out.append({
                "source": src, "total": r["total"],
                "alerted": r["alerted"] or 0,
                "relevant": relevant, "irrelevant": irrelevant,
                "precision": round(100 * relevant / (relevant + irrelevant), 1)
                if (relevant + irrelevant) else None,
            })
        return out

    def recent_decisions(self, limit: int = 20) -> list[dict]:
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM decisions ORDER BY id DESC LIMIT ?", (limit,))]


def get_feedback_store() -> FeedbackStore:
    return FeedbackStore()
