"""
Utility condivise da tutti gli scraper:
- connessione al DB SQLite (data/tracker.db)
- caricamento politici.json
- matching robusto del nome di un politico dentro un testo
- inserimento dichiarazioni con deduplica
"""
import sqlite3
import json
import re
import hashlib
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "tracker.db"
POLITICI_PATH = ROOT / "data" / "politici.json"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    is_new = not DB_PATH.exists()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    if is_new:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
    return conn


def load_politici():
    with open(POLITICI_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["politici"]


def sync_politici_table(conn):
    """Inserisce/aggiorna la tabella politici a partire da politici.json."""
    politici = load_politici()
    for p in politici:
        conn.execute(
            """INSERT INTO politici (id, nome, ruolo, partito, partito_sigla, colore)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 nome=excluded.nome, ruolo=excluded.ruolo,
                 partito=excluded.partito, partito_sigla=excluded.partito_sigla,
                 colore=excluded.colore""",
            (p["id"], p["nome"], p["ruolo"], p["partito"], p["partito_sigla"], p["colore"]),
        )
    conn.commit()


def find_politico_in_text(testo, politici=None):
    """
    Ritorna la lista di id dei politici (da politici.json) i cui alias
    compaiono nel testo fornito. Matching case-insensitive su parole intere,
    per evitare falsi positivi su sottostringhe (es. 'Conte' dentro un'altra parola).
    """
    if politici is None:
        politici = load_politici()
    testo_upper = testo.upper()
    trovati = []
    for p in politici:
        for alias in p["alias"]:
            # word-boundary match, tollerante ad apostrofi/accenti già in maiuscolo
            pattern = r"\b" + re.escape(alias.upper()) + r"\b"
            if re.search(pattern, testo_upper):
                trovati.append(p["id"])
                break
    return trovati


def content_hash(testo):
    return hashlib.sha256(testo.encode("utf-8")).hexdigest()[:16]


def insert_dichiarazione(conn, politico_id, data, fonte_tipo, fonte_nome,
                          fonte_url, riassunto, temi, hash_contenuto, testo_grezzo=None):
    """Inserisce una dichiarazione, ignorando silenziosamente i duplicati
    (stesso politico + stessa fonte_url + stesso hash_contenuto)."""
    try:
        conn.execute(
            """INSERT INTO dichiarazioni
               (politico_id, data, fonte_tipo, fonte_nome, fonte_url, riassunto, temi, hash_contenuto, testo_grezzo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (politico_id, data, fonte_tipo, fonte_nome, fonte_url, riassunto,
             temi, hash_contenuto, testo_grezzo),
        )
        conn.commit()
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    except sqlite3.IntegrityError:
        # già presente: va bene, semplicemente saltiamo
        return None


def get_stato_scraping(conn, fonte_tipo):
    row = conn.execute(
        "SELECT ultimo_riferimento FROM stato_scraping WHERE fonte_tipo = ?",
        (fonte_tipo,),
    ).fetchone()
    return row["ultimo_riferimento"] if row else None


def set_stato_scraping(conn, fonte_tipo, valore):
    conn.execute(
        """INSERT INTO stato_scraping (fonte_tipo, ultimo_riferimento, aggiornato_il)
           VALUES (?, ?, datetime('now'))
           ON CONFLICT(fonte_tipo) DO UPDATE SET
             ultimo_riferimento=excluded.ultimo_riferimento,
             aggiornato_il=datetime('now')""",
        (fonte_tipo, valore),
    )
    conn.commit()
