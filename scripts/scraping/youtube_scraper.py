"""
Scraper YouTube: scopre nuovi video sui canali ufficiali configurati in
config/canali_youtube.json e ne recupera la trascrizione (sottotitoli),
cercando dentro al testo i nomi dei politici monitorati.

Due pezzi distinti, con costi/affidabilita' diversi:

1. SCOPERTA NUOVI VIDEO -> YouTube Data API v3 (ufficiale, gratuita, 10.000
   unita'/giorno). Usiamo playlistItems.list sulla "uploads playlist" del
   canale (channel_id con prefisso UC -> UU), che costa 1 unita' a chiamata:
   molto piu' economico di search.list (100 unita'). Richiede una API key
   gratuita da Google Cloud Console (variabile d'ambiente YOUTUBE_API_KEY).

2. TRASCRIZIONE -> la captions.download ufficiale richiede OAuth e funziona
   solo per video di cui sei proprietario, quindi e' inutilizzabile per
   canali di terzi anche se "ufficiali". Usiamo invece la libreria
   'youtube-transcript-api', che legge i sottotitoli pubblici (manuali o
   automatici) senza consumare quota. E' una libreria di terze parti non
   ufficiale: funziona leggendo dati pubblicamente disponibili sulla pagina
   del video (stessi sottotitoli che un utente vede sul player), ma non e'
   un'interfaccia garantita da Google e potrebbe rompersi in futuro.

Se YOUTUBE_API_KEY non e' impostata, lo script si ferma senza errori
(permette di lasciare disattivata questa fonte finche' non si configura).
"""
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "db"))
from db_utils import (get_connection, sync_politici_table, load_politici,
                       find_politico_in_text, content_hash, insert_dichiarazione,
                       get_stato_scraping, set_stato_scraping)

ROOT = Path(__file__).resolve().parents[2]
CANALI_PATH = ROOT / "config" / "canali_youtube.json"
API_KEY = os.environ.get("YOUTUBE_API_KEY")
MAX_VIDEO_PER_CANALE = 5


def carica_canali():
    import json
    with open(CANALI_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [c for c in data["canali"] if c.get("channel_id") and
            c["channel_id"] != "INSERISCI_CHANNEL_ID"]


def uploads_playlist_id(channel_id):
    # Convenzione YouTube: la "uploads playlist" di un canale UCxxxx è UUxxxx
    if channel_id.startswith("UC"):
        return "UU" + channel_id[2:]
    return None


def video_recenti(channel_id, max_risultati=MAX_VIDEO_PER_CANALE):
    playlist_id = uploads_playlist_id(channel_id)
    if not playlist_id:
        return []
    url = "https://www.googleapis.com/youtube/v3/playlistItems"
    params = {
        "part": "snippet",
        "playlistId": playlist_id,
        "maxResults": max_risultati,
        "key": API_KEY,
    }
    resp = requests.get(url, params=params, timeout=20)
    if resp.status_code != 200:
        print(f"[youtube] errore API ({resp.status_code}): {resp.text[:200]}")
        return []
    items = resp.json().get("items", [])
    risultati = []
    for it in items:
        snippet = it["snippet"]
        risultati.append({
            "video_id": snippet["resourceId"]["videoId"],
            "titolo": snippet["title"],
            "data_pubblicazione": snippet["publishedAt"][:10],
        })
    return risultati


def trascrizione_video(video_id):
    """Ritorna il testo della trascrizione (italiano se disponibile), o None."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        print("[youtube] libreria 'youtube-transcript-api' non installata "
              "(vedi requirements.txt). Salto la trascrizione.")
        return None
    try:
        ytt_api = YouTubeTranscriptApi()
        fetched = ytt_api.fetch(video_id, languages=["it", "it-IT", "en"])
        return " ".join(snippet.text for snippet in fetched)
    except Exception as e:
        print(f"[youtube] nessuna trascrizione disponibile per {video_id}: {e}")
        return None


def main():
    if not API_KEY:
        print("[youtube] variabile YOUTUBE_API_KEY non impostata: fonte disattivata.")
        return

    conn = get_connection()
    politici = load_politici()
    sync_politici_table(conn)

    canali = carica_canali()
    if not canali:
        print("[youtube] nessun canale configurato in config/canali_youtube.json, salto.")
        return

    n_totale = 0
    for canale in canali:
        ultimo = get_stato_scraping(conn, f"youtube_{canale['id']}")
        visti = set(ultimo.split(",")) if ultimo else set()
        nuovi_visti = set()

        for video in video_recenti(canale["channel_id"]):
            if video["video_id"] in visti:
                continue
            nuovi_visti.add(video["video_id"])

            testo = trascrizione_video(video["video_id"])
            if not testo:
                continue

            trovati = find_politico_in_text(testo, politici)
            if not trovati:
                continue

            url_video = f"https://www.youtube.com/watch?v={video['video_id']}"
            corpo = testo[:8000]
            h = content_hash(corpo)
            for politico_id in trovati:
                nuovo_id = insert_dichiarazione(
                    conn,
                    politico_id=politico_id,
                    data=video["data_pubblicazione"],
                    fonte_tipo="youtube",
                    fonte_nome=f"{canale['nome']} - {video['titolo']}",
                    fonte_url=url_video,
                    riassunto=None,
                    temi=None,
                    hash_contenuto=h,
                    testo_grezzo=corpo,
                )
                if nuovo_id:
                    n_totale += 1

        if nuovi_visti:
            set_stato_scraping(conn, f"youtube_{canale['id']}", ",".join(visti | nuovi_visti))

    print(f"[youtube] {n_totale} dichiarazioni candidate salvate")
    conn.close()


if __name__ == "__main__":
    main()
