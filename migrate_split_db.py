"""Migra o items.db legado para os dois bancos separados (idempotente).

Uso:
    .venv/bin/python migrate_split_db.py

- Faz backup items.db → items.db.pre-separacao (se ainda não existir)
- category = 'job'  → jobs.db      (vagas/estágios)
- category != 'job' → academic.db  (bolsas/eventos/chamadas)
- Copia também as linhas de alerts_sent correspondentes (evita re-alertar)
- Rodar APENAS com o pipeline parado (nenhum `collect` em andamento)

Re-execuções são seguras: itens já existentes são ignorados (OR IGNORE).
"""

import shutil
import sqlite3
import sys
from pathlib import Path

from config import CONFIG
from store import ItemStore, get_jobs_store, get_academic_store

BASE = Path(__file__).parent


def _table_cols(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _copy_rows(src_conn: sqlite3.Connection, dest: ItemStore, table: str,
               where: str, params: tuple) -> tuple[int, int]:
    """Copia linhas de src → dest (INSERT OR IGNORE). Retorna (lidas, inseridas)."""
    src_cols = _table_cols(src_conn, table)
    with dest._conn() as dconn:
        dest_cols = set(_table_cols(dconn, table))
        cols = [c for c in src_cols if c in dest_cols]
        if not cols:
            return 0, 0
        col_sql = ", ".join(cols)
        ph = ", ".join("?" * len(cols))
        pk = "url_hash" if "url_hash" in cols else cols[0]
        read = inserted = 0
        for row in src_conn.execute(f"SELECT * FROM {table} WHERE {where}", params):
            read += 1
            exists = dconn.execute(
                f"SELECT 1 FROM {table} WHERE {pk} = ?", (row[pk],)).fetchone()
            if exists:
                continue
            dconn.execute(f"INSERT INTO {table} ({col_sql}) VALUES ({ph})",
                          [row[c] for c in cols])
            inserted += 1
        dconn.commit()
        return read, inserted


def main() -> int:
    legacy = BASE / CONFIG["storage"].get("db_path", "items.db")
    if not legacy.exists():
        print(f"Nada a migrar: {legacy.name} não existe.")
        return 0

    # 1. Backup único
    backup = BASE / "items.db.pre-separacao"
    if not backup.exists():
        shutil.copy2(legacy, backup)
        print(f"✓ Backup criado: {backup.name}")

    # 2. Instancia os dois bancos novos (cria schema)
    jobs_store = get_jobs_store()
    acad_store = get_academic_store()
    if Path(jobs_store.db_path).resolve() == Path(acad_store.db_path).resolve():
        print("ERRO: jobs e academic apontam para o mesmo arquivo.")
        return 1

    src = sqlite3.connect(legacy)
    src.row_factory = sqlite3.Row

    # 3. Itens
    j_read, j_new = _copy_rows(src, jobs_store, "items", "category = ?", ("job",))
    a_read, a_new = _copy_rows(src, acad_store, "items", "category != 'job'", ())
    src.close()

    # 4. Alertas já enviados (só para itens que existem no destino)
    src = sqlite3.connect(legacy)
    src.row_factory = sqlite3.Row
    for store in (jobs_store, acad_store):
        with store._conn() as dconn:
            dest_hashes = {r[0] for r in dconn.execute("SELECT url_hash FROM items")}
        alerts = src.execute("SELECT * FROM alerts_sent").fetchall()
        with store._conn() as dconn:
            copied = 0
            for row in alerts:
                if row["url_hash"] not in dest_hashes:
                    continue
                if dconn.execute("SELECT 1 FROM alerts_sent WHERE url_hash = ?",
                                 (row["url_hash"],)).fetchone():
                    continue
                dconn.execute(
                    "INSERT INTO alerts_sent (url_hash, alerted_at, channel) VALUES (?, ?, ?)",
                    (row["url_hash"], row["alerted_at"], row["channel"]))
                copied += 1
            dconn.commit()
        print(f"✓ {Path(store.db_path).name}: +{copied} alertas copiados")
    src.close()

    # 5. Verificação (Definition of Done)
    print(f"\nLeitura de {legacy.name}: {j_read} vagas + {a_read} acadêmicos")
    print(f"Inseridos: jobs.db +{j_new} | academic.db +{a_new}")
    ok = True
    for store, label, expect_job in ((jobs_store, "jobs.db", True),
                                     (acad_store, "academic.db", False)):
        with store._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            cats = sorted(r[0] for r in conn.execute(
                "SELECT DISTINCT category FROM items").fetchall())
            alerted = conn.execute("SELECT COUNT(*) FROM alerts_sent").fetchone()[0]
        bad = (expect_job and cats != ["job"]) or (not expect_job and "job" in cats)
        ok = ok and not bad
        status = "✗" if bad else "✓"
        print(f"{status} {label}: {total} itens | {alerted} alertas | categorias: {cats}")

    if not ok:
        print("\nVERIFICAÇÃO FALHOU — verifique os bancos antes de prosseguir.")
        return 1
    print("\n✓ Migração concluída e verificada. items.db preservado como legado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
