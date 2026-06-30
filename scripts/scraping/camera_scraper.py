"""
Scraper Resoconti stenografici dell'Assemblea - Camera dei Deputati.

Fonte: documenti.camera.it (sottodominio che, a differenza di www.camera.it,
non ha mostrato protezioni anti-bot nei test). Gli atti parlamentari sono
atti pubblici della Camera: nessun problema di copyright a leggerli ed
elaborarli.

Struttura reale della pagina (verificata su esempi reali, es. seduta 630):
ogni intervento e' introdotto da un link al profilo del parlamentare, es.
    <a href=".../schedaDeputato?...idPersona=302080...">ANGELO BONELLI</a> (AVS). <testo>
oppure per Presidente/Ministri:
    <a ...>PRESIDENTE</a>. <testo>
    <a ...>LUIGI D'ERAMO</a>, *Sottosegretario di Stato...*. <testo>

NOTA IMPORTANTE: questo scraper individua le sedute più recenti tentando
una sequenza di numeri di seduta a partire dall'ultimo processato. Il numero
seduta NON corrisponde 1:1 al numero di giorni: la Camera non siede tutti i
giorni. Il modo più robusto per ottenere l'elenco aggiornato delle sedute
sarebbe leggere https://www.camera.it/leg19/207 (pagina indice), ma quella
pagina ha protezione anti-bot al momento dei test: se risulta accessibile
quando esegui davvero lo script, conviene sostituire la logica di scoperta
sedute con il parsing di quella pagina (più robusto del "tentativo numerico").
"""
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "db"))
from db_utils import (get_connection, sync_politici_table, load_politici,
                       find_politico_in_text, content_hash, insert_dichiarazione,
                       get_stato_scraping, set_stato_scraping)

BASE_URL = "https://documenti.camera.it/leg19/resoconti/assemblea/html/sed{seduta:04d}/stenografico.htm"
LEGISLATURA = 19
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PoliticiTrackerBot/0.1; uso personale non commerciale)"
}
MAX_TENTATIVI_VUOTI_CONSECUTIVI = 5  # quante sedute "non trovate" di fila prima di fermarsi
MAX_SEDUTE_PER_RUN = 30  # tetto di sicurezza per non fare troppe richieste in un run


def estrai_data_seduta(soup):
    """Cerca nel testo qualcosa come 'martedì 10 marzo 2026'."""
    testo = soup.get_text(" ", strip=True)[:500]
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


def estrai_interventi(soup):
    """
    Ritorna una lista di dict {speaker_label, testo} ricostruendo gli interventi
    a partire dai link ai parlamentari (idPersona) o dalle etichette PRESIDENTE/
    nomi+ruolo, che nel sorgente HTML compaiono come <a> seguiti da '(GRUPPO).'
    o ', Ruolo.' e poi dal testo dell'intervento, fino al prossimo marcatore.
    """
    # Sostituiamo ogni <a> con un marcatore univoco per poterlo isolare col testo
    for a in soup.find_all("a"):
        a.replace_with(f"\n@@SPEAKER@@{a.get_text(strip=True)}@@/SPEAKER@@\n")

    testo_completo = soup.get_text("\n", strip=False)
    # Split sui marcatori
    parti = re.split(r"@@SPEAKER@@(.*?)@@/SPEAKER@@", testo_completo)
    # parti = [testo_prima, speaker1, testo_dopo_speaker1, speaker2, testo_dopo_speaker2, ...]
    interventi = []
    for i in range(1, len(parti), 2):
        speaker = parti[i].strip()
        corpo = parti[i + 1] if i + 1 < len(parti) else ""
        # Il corpo inizia tipicamente con "(GRUPPO). testo" o ", Ruolo. testo" o ". testo"
        corpo = corpo.strip()
        if not corpo:
            continue
        # Tronchiamo il corpo al primo "doppio newline + maiuscole lunghe" già gestito dallo split
        interventi.append({"speaker": speaker, "testo": corpo})
    return interventi


def processa_seduta(conn, politici, numero_seduta):
    url = BASE_URL.format(seduta=numero_seduta)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
    except requests.RequestException:
        return None
    if resp.status_code != 200 or len(resp.content) < 500:
        return None

    soup = BeautifulSoup(resp.content, "html.parser")
    data_seduta = estrai_data_seduta(soup) or date.today().isoformat()
    interventi = estrai_interventi(soup)

    n_salvati = 0
    for interv in interventi:
        speaker = interv["speaker"]
        # Scartiamo subito 'PRESIDENTE' e simili: non sono i politici che monitoriamo
        # (a meno che il loro nome completo compaia comunque nel testo dell'intervento,
        # caso gestito comunque dal matching sul corpo).
        trovati = set(find_politico_in_text(speaker, politici))
        # Cerchiamo anche dentro il corpo (citazioni, "il Ministro X ha detto...")
        # ma contiamo come "dichiarazione" solo se e' lo SPEAKER stesso a coincidere,
        # per evitare di attribuire a un politico parole di un altro che lo cita.
        if not trovati:
            continue

        corpo = interv["testo"][:4000]  # limite di sicurezza per singolo intervento
        h = content_hash(corpo)
        for politico_id in trovati:
            nuovo_id = insert_dichiarazione(
                conn,
                politico_id=politico_id,
                data=data_seduta,
                fonte_tipo="camera",
                fonte_nome=f"Resoconto stenografico Camera - seduta n. {numero_seduta}",
                fonte_url=url,
                riassunto=None,  # verra' generato dopo da scripts/analysis/summarize.py
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

    ultimo = get_stato_scraping(conn, "camera")
    numero_iniziale = int(ultimo) + 1 if ultimo else 1
    numero = numero_iniziale
    vuoti_consecutivi = 0
    processate = 0
    ultimo_trovato = ultimo

    while processate < MAX_SEDUTE_PER_RUN and vuoti_consecutivi < MAX_TENTATIVI_VUOTI_CONSECUTIVI:
        risultato = processa_seduta(conn, politici, numero)
        if risultato is None:
            vuoti_consecutivi += 1
        else:
            vuoti_consecutivi = 0
            ultimo_trovato = str(numero)
            processate += 1
            print(f"[camera] seduta {numero}: {risultato} dichiarazioni candidate salvate")
        numero += 1
        time.sleep(1.5)  # cortesia verso il server

    if ultimo_trovato and ultimo_trovato != ultimo:
        set_stato_scraping(conn, "camera", ultimo_trovato)
    conn.close()


if __name__ == "__main__":
    main()
