"""
Esporta dal database SQLite alcuni file JSON statici che il frontend
(pagina HTML in /frontend) legge direttamente, senza bisogno di un backend
sempre attivo. Questo e' il pezzo che rende possibile ospitare tutto
gratuitamente su GitHub Pages.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "db"))
from db_utils import get_connection

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "docs" / "data"


def esporta_dichiarazioni(conn):
    righe = conn.execute(
        """SELECT d.id, d.politico_id, d.data, d.fonte_tipo, d.fonte_nome,
                  d.fonte_url, d.riassunto, d.temi
           FROM dichiarazioni d
           WHERE d.riassunto IS NOT NULL
           ORDER BY d.data DESC"""
    ).fetchall()

    per_giorno = defaultdict(list)
    for r in righe:
        per_giorno[r["data"]].append({
            "id": r["id"],
            "politico_id": r["politico_id"],
            "fonte_tipo": r["fonte_tipo"],
            "fonte_nome": r["fonte_nome"],
            "fonte_url": r["fonte_url"],
            "riassunto": r["riassunto"],
            "temi": (r["temi"] or "").split(",") if r["temi"] else [],
        })
    return per_giorno


def esporta_politici(conn):
    righe = conn.execute("SELECT * FROM politici").fetchall()
    return {r["id"]: dict(r) for r in righe}


def esporta_promesse(conn):
    righe = conn.execute(
        """SELECT p.*, d.fonte_url, d.fonte_nome
           FROM promesse p JOIN dichiarazioni d ON d.id = p.dichiarazione_id
           ORDER BY p.data_promessa DESC"""
    ).fetchall()
    return [dict(r) for r in righe]


def esporta_posizioni(conn):
    righe = conn.execute(
        """SELECT pos.*, d.fonte_url
           FROM posizioni_nel_tempo pos JOIN dichiarazioni d ON d.id = pos.dichiarazione_id
           ORDER BY pos.politico_id, pos.tema, pos.data"""
    ).fetchall()
    raggruppate = defaultdict(list)
    for r in righe:
        raggruppate[f"{r['politico_id']}::{r['tema']}"].append(dict(r))
    return raggruppate


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_connection()

    with open(OUT_DIR / "dichiarazioni_per_giorno.json", "w", encoding="utf-8") as f:
        json.dump(esporta_dichiarazioni(conn), f, ensure_ascii=False, indent=2)

    with open(OUT_DIR / "politici.json", "w", encoding="utf-8") as f:
        json.dump(esporta_politici(conn), f, ensure_ascii=False, indent=2)

    with open(OUT_DIR / "promesse.json", "w", encoding="utf-8") as f:
        json.dump(esporta_promesse(conn), f, ensure_ascii=False, indent=2)

    with open(OUT_DIR / "posizioni.json", "w", encoding="utf-8") as f:
        json.dump(esporta_posizioni(conn), f, ensure_ascii=False, indent=2)

    conn.close()
    print(f"[export] file JSON scritti in {OUT_DIR}")


if __name__ == "__main__":
    main()
