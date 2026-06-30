"""
Scraper "stampa": legge i feed RSS delle testate in config/whitelist_stampa.txt
e salva SOLO metadati (titolo, data, link) per gli articoli che, dal
titolo/sommario disponibile nel feed RSS, sembrano riguardare uno dei
politici monitorati. NON scarica e NON salva mai il testo integrale
dell'articolo: rispetta il copyright editoriale.

Il riassunto vero e proprio (parafrasi) verra' generato da
scripts/analysis/summarize.py basandosi SOLO su titolo+sommario del feed
(che gia' l'editore pubblica liberamente per la sindacazione), non sul
corpo dell'articolo.
"""
import re
import sys
from datetime import datetime
from pathlib import Path

import feedparser

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "db"))
from db_utils import (get_connection, sync_politici_table, load_politici,
                       find_politico_in_text, content_hash, insert_dichiarazione,
                       get_stato_scraping, set_stato_scraping)

ROOT = Path(__file__).resolve().parents[2]
WHITELIST_PATH = ROOT / "config" / "whitelist_stampa.txt"


def carica_whitelist():
    fonti = []
    with open(WHITELIST_PATH, "r", encoding="utf-8") as f:
        for riga in f:
            riga = riga.strip()
            if not riga or riga.startswith("#"):
                continue
            parti = [p.strip() for p in riga.split("|")]
            if len(parti) < 3 or not parti[2]:
                continue  # nessun feed RSS configurato per questa fonte
            fonti.append({"dominio": parti[0], "nome": parti[1], "rss": parti[2]})
    return fonti


def normalizza_data(entry):
    for campo in ("published_parsed", "updated_parsed"):
        val = getattr(entry, campo, None)
        if val:
            return datetime(*val[:6]).date().isoformat()
    return datetime.today().date().isoformat()


def main():
    conn = get_connection()
    politici = load_politici()
    sync_politici_table(conn)

    fonti = carica_whitelist()
    n_totale = 0

    for fonte in fonti:
        ultimo = get_stato_scraping(conn, f"stampa_{fonte['dominio']}")
        visti = set(ultimo.split("||")) if ultimo else set()
        nuovi_visti = set()

        try:
            feed = feedparser.parse(fonte["rss"])
        except Exception as e:
            print(f"[stampa] errore nel feed {fonte['nome']}: {e}")
            continue

        for entry in feed.entries[:40]:
            link = entry.get("link")
            if not link or link in visti:
                continue
            nuovi_visti.add(link)

            titolo = entry.get("title", "")
            sommario = entry.get("summary", "")
            testo_breve = f"{titolo}. {sommario}"

            trovati = find_politico_in_text(testo_breve, politici)
            if not trovati:
                continue

            data_pub = normalizza_data(entry)
            h = content_hash(testo_breve)
            for politico_id in trovati:
                nuovo_id = insert_dichiarazione(
                    conn,
                    politico_id=politico_id,
                    data=data_pub,
                    fonte_tipo="stampa",
                    fonte_nome=fonte["nome"],
                    fonte_url=link,
                    riassunto=None,
                    temi=None,
                    hash_contenuto=h,
                    # qui usiamo SOLO titolo+sommario, mai il corpo dell'articolo
                    testo_grezzo=testo_breve[:1500],
                )
                if nuovo_id:
                    n_totale += 1

        if nuovi_visti:
            set_stato_scraping(conn, f"stampa_{fonte['dominio']}", "||".join(visti | nuovi_visti))

    print(f"[stampa] {n_totale} dichiarazioni candidate salvate")
    conn.close()


if __name__ == "__main__":
    main()
