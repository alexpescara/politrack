"""
Scraper comunicati stampa del Governo (Palazzo Chigi / Consiglio dei Ministri).

Fonte: https://www.governo.it/it/tipologie-contenuto/comunicati-stampa
Sono atti pubblici istituzionali: nessun problema di copyright.

Il sito elenca i comunicati in ordine cronologico inverso. Ogni comunicato ha
una pagina propria (es. .../articolo/comunicato-stampa-del-consiglio-dei-ministri-n-179/32157)
con il testo completo, che spesso cita i singoli Ministri per nome e cognome
(es. "su proposta del Ministro Matteo Salvini...", "Il Consiglio dei Ministri,
su proposta del Presidente Giorgia Meloni..."). Per Meloni, che presiede quasi
ogni riunione, e' la fonte istituzionale piu' regolare.
"""
import re
import sys
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "db"))
from db_utils import (get_connection, sync_politici_table, load_politici,
                       find_politico_in_text, content_hash, insert_dichiarazione,
                       get_stato_scraping, set_stato_scraping)

LISTA_URL = "https://www.governo.it/it/tipologie-contenuto/comunicati-stampa"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PoliticiTrackerBot/0.1; uso personale non commerciale)"
}
MAX_ARTICOLI_PER_RUN = 15


def estrai_data(testo):
    mesi = ("gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|"
            "settembre|ottobre|novembre|dicembre")
    m = re.search(r"(\d{1,2})\s+(" + mesi + r")\s+(\d{4})", testo, re.IGNORECASE)
    if not m:
        return None
    giorno, mese_nome, anno = m.groups()
    mesi_lista = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
                  "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
    mese_num = mesi_lista.index(mese_nome.lower()) + 1
    return f"{anno}-{mese_num:02d}-{int(giorno):02d}"


def trova_nuovi_link_articoli(conn):
    try:
        resp = requests.get(LISTA_URL, headers=HEADERS, timeout=20)
    except requests.RequestException as e:
        print(f"[governo] errore di rete: {e}")
        return []
    if resp.status_code != 200:
        print(f"[governo] status code {resp.status_code}, salto.")
        return []

    soup = BeautifulSoup(resp.content, "html.parser")
    link = [a["href"] for a in soup.find_all("a", href=True) if "/articolo/" in a["href"]]
    link = list(dict.fromkeys(link))  # dedup mantenendo ordine

    ultimo = get_stato_scraping(conn, "governo")
    visti = set(ultimo.split("||")) if ultimo else set()
    nuovi = [l for l in link if l not in visti]
    return nuovi[:MAX_ARTICOLI_PER_RUN], visti


def processa_articolo(conn, politici, href):
    url = href if href.startswith("http") else f"https://www.governo.it{href}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
    except requests.RequestException:
        return 0
    if resp.status_code != 200:
        return 0

    soup = BeautifulSoup(resp.content, "html.parser")
    testo = soup.get_text("\n", strip=True)
    data_comunicato = estrai_data(testo[:1000]) or date.today().isoformat()

    trovati = find_politico_in_text(testo, politici)
    if not trovati:
        return 0

    corpo = testo[:6000]
    h = content_hash(corpo)
    n_salvati = 0
    for politico_id in trovati:
        nuovo_id = insert_dichiarazione(
            conn,
            politico_id=politico_id,
            data=data_comunicato,
            fonte_tipo="governo",
            fonte_nome="Comunicato stampa - Consiglio dei Ministri",
            fonte_url=url,
            riassunto=None,
            temi=None,
            hash_contenuto=h,
            testo_grezzo=corpo,
        )
        if nuovo_id:
            n_salvati += 1
    return n_salvati


def main():
    conn = get_connection()
    politici = load_politici()
    sync_politici_table(conn)

    nuovi_link, visti = trova_nuovi_link_articoli(conn)
    n_totale = 0
    for href in nuovi_link:
        n_totale += processa_articolo(conn, politici, href)
        visti.add(href)

    if nuovi_link:
        set_stato_scraping(conn, "governo", "||".join(visti))
    print(f"[governo] {n_totale} dichiarazioni candidate salvate da {len(nuovi_link)} comunicati")
    conn.close()


if __name__ == "__main__":
    main()
