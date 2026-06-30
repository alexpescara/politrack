"""
Scraper Resoconti stenografici dell'Assemblea - Senato della Repubblica.

STATO: best-effort, DA TESTARE prima di fidarsi in produzione.

A differenza di documenti.camera.it, durante lo sviluppo www.senato.it ha
risposto con una pagina di "bot detection" ai tentativi di fetch automatico.
Questo NON significa che lo scraping sia vietato (i resoconti sono atti
pubblici, CC BY 3.0 per i dati aperti del Senato), ma significa che la
richiesta va fatta in modo piu' "umano" (header realistici, eventualmente
sessione con cookie) oppure va dirottata su una fonte alternativa.

Possibili strade da verificare quando esegui davvero questo script:
1. Provare comunque la richiesta con gli HEADERS sotto (a volte la protezione
   scatta solo su alcuni path, non su tutti).
2. Usare i dati aperti su https://dati.senato.it (CC BY 3.0) per scoprire
   l'elenco delle sedute recenti (dataset 'dump-sedute-NUM_LEG'), che però
   contengono SOLO metadati e non il testo: per il testo bisognerebbe comunque
   risalire a www.senato.it.
3. In ultima istanza, eseguire questo specifico scraper a mano (o da un
   cron sul proprio PC) invece che da GitHub Actions, se le IP dei runner
   GitHub risultano bloccate in modo persistente.

Pattern del testo (verificato su pagine reali): ogni intervento e' introdotto
da 'COGNOME (GRUPPO).' (es. "GASPARRI (FI-BP-PPE).") oppure, per i membri del
Governo, da 'COGNOME, ruolo.' (es. "GENTILE, sottosegretario di Stato...").
A differenza della Camera qui di solito non c'e' il nome di battesimo, quindi
il matching si appoggia sul COGNOME (con maggiore rischio di falsi positivi
sui cognomi comuni: tienilo a mente).
"""
import re
import sys
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "db"))
from db_utils import (get_connection, sync_politici_table, load_politici,
                       content_hash, insert_dichiarazione,
                       get_stato_scraping, set_stato_scraping)

LISTA_RESOCONTI_URL = "https://www.senato.it/lavori/assemblea/resoconti-elenco-cronologico"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "it-IT,it;q=0.9",
}

# Cognomi dei politici monitorati che sono (o possono essere) senatori.
# Costruito automaticamente da politici.json filtrando per 'senato' in 'camere'.


def cognomi_da_monitorare(politici):
    mapping = {}
    for p in politici:
        if "senato" in p.get("camere", []):
            cognome = p["nome"].split()[-1].upper()
            mapping[cognome] = p["id"]
    return mapping


def estrai_data_da_titolo(titolo):
    mesi = ("gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|"
            "settembre|ottobre|novembre|dicembre")
    m = re.search(r"(\d{1,2})[°\s]*\s*(" + mesi + r")\s+(\d{4})", titolo, re.IGNORECASE)
    if not m:
        return None
    giorno, mese_nome, anno = m.groups()
    mesi_lista = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
                  "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
    mese_num = mesi_lista.index(mese_nome.lower()) + 1
    return f"{anno}-{mese_num:02d}-{int(giorno):02d}"


def estrai_interventi_da_testo(testo_piano, mapping_cognomi):
    """
    Individua nel testo piano gli interventi che iniziano con 'COGNOME (...).'
    o 'COGNOME, ruolo.' per i cognomi che ci interessano, e ne ritorna il
    corpo (fino al prossimo marcatore SPEAKER in maiuscolo).
    """
    pattern_speaker = re.compile(
        r"\b([A-ZÀÈÌÒÙ']{3,})\s*(\([^)]*\)|,\s*[a-zà-ù][^.]*)?\.\s"
    )
    matches = list(pattern_speaker.finditer(testo_piano))
    risultati = []
    for i, m in enumerate(matches):
        cognome = m.group(1)
        if cognome not in mapping_cognomi:
            continue
        inizio_corpo = m.end()
        fine_corpo = matches[i + 1].start() if i + 1 < len(matches) else len(testo_piano)
        corpo = testo_piano[inizio_corpo:fine_corpo].strip()[:4000]
        if len(corpo) < 20:
            continue
        risultati.append({"politico_id": mapping_cognomi[cognome], "testo": corpo})
    return risultati


def processa_pagina_lista(conn, politici):
    mapping = cognomi_da_monitorare(politici)
    if not mapping:
        print("[senato] nessun politico monitorato risulta assegnato al Senato, salto.")
        return 0

    try:
        resp = requests.get(LISTA_RESOCONTI_URL, headers=HEADERS, timeout=20)
    except requests.RequestException as e:
        print(f"[senato] errore di rete: {e}")
        return 0

    if resp.status_code != 200 or "bot" in resp.text.lower()[:300]:
        print("[senato] richiesta bloccata o non riuscita (probabile bot-detection). "
              "Vedi note nel docstring di questo file per le alternative.")
        return 0

    soup = BeautifulSoup(resp.content, "html.parser")
    link_sedute = [a for a in soup.find_all("a", href=True)
                   if "tipodoc=hotresaula" in a["href"] or "tipodoc=Resaula" in a["href"]]

    n_salvati = 0
    ultimo = get_stato_scraping(conn, "senato")
    visti = set(ultimo.split(",")) if ultimo else set()
    nuovi_visti = set()

    for link in link_sedute[:20]:  # tetto di sicurezza
        href = link["href"]
        if href in visti:
            continue
        url_completo = href if href.startswith("http") else f"https://www.senato.it{href}"
        try:
            r2 = requests.get(url_completo, headers=HEADERS, timeout=20)
        except requests.RequestException:
            continue
        if r2.status_code != 200:
            continue
        sub_soup = BeautifulSoup(r2.content, "html.parser")
        testo_piano = sub_soup.get_text("\n", strip=True)
        data_seduta = estrai_data_da_titolo(testo_piano[:300]) or date.today().isoformat()

        interventi = estrai_interventi_da_testo(testo_piano, mapping)
        for interv in interventi:
            h = content_hash(interv["testo"])
            nuovo_id = insert_dichiarazione(
                conn,
                politico_id=interv["politico_id"],
                data=data_seduta,
                fonte_tipo="senato",
                fonte_nome="Resoconto stenografico Senato",
                fonte_url=url_completo,
                riassunto=None,
                temi=None,
                hash_contenuto=h,
                testo_grezzo=interv["testo"],
            )
            if nuovo_id:
                n_salvati += 1
        nuovi_visti.add(href)

    if nuovi_visti:
        set_stato_scraping(conn, "senato", ",".join(visti | nuovi_visti))
    return n_salvati


def main():
    conn = get_connection()
    politici = load_politici()
    sync_politici_table(conn)
    n = processa_pagina_lista(conn, politici)
    print(f"[senato] {n} dichiarazioni candidate salvate")
    conn.close()


if __name__ == "__main__":
    main()
