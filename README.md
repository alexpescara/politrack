# Osservatorio Dichiarazioni — Politici Italiani

Tiene traccia nel tempo di cosa dicono alcuni politici italiani in contesti
pubblici e ufficiali (Aula di Camera/Senato, comunicati del Governo, canali
YouTube ufficiali, articoli di testate giornalistiche selezionate), per poter
poi confrontare promesse fatte e posizioni espresse nel tempo.

**Stato: MVP personale.** Pensato per girare gratis su GitHub (Actions +
Pages), con un solo costo marginale opzionale: le chiamate all'API Claude per
generare i riassunti (pochi centesimi al mese ai volumi previsti).

## Come funziona, in breve

```
GitHub Actions (ogni lunedì)
   │
   ├─ scripts/scraping/camera_scraper.py    → Resoconti Aula Camera
   ├─ scripts/scraping/senato_scraper.py    → Resoconti Aula Senato (*)
   ├─ scripts/scraping/governo_scraper.py   → Comunicati Consiglio dei Ministri
   ├─ scripts/scraping/youtube_scraper.py   → Trascrizioni canali YouTube ufficiali (**)
   ├─ scripts/scraping/stampa_scraper.py    → Solo metadati da feed RSS in whitelist
   │
   ├─ scripts/analysis/summarize.py         → Riassunto + temi + promesse + posizioni (via Claude API)
   └─ scripts/analysis/export_json.py       → Esporta JSON statici per il frontend
   │
   └─ commit automatico dei risultati nel repo (data/tracker.db + frontend/data/*.json)

GitHub Pages (frontend/index.html)
   → Vista calendario: clic su un giorno → popup con le dichiarazioni di quel giorno
```

`(*)` Senato: lo scraper è **da testare**, perché in fase di sviluppo
`www.senato.it` ha mostrato una protezione anti-bot. Vedi i commenti dentro
`senato_scraper.py` per le alternative.

`(**)` YouTube: richiede una `YOUTUBE_API_KEY` gratuita e la configurazione
dei canali in `config/canali_youtube.json` (vedi sotto). Se non configuri
nulla, questa fonte resta semplicemente disattivata: il resto funziona.

## Setup (15-20 minuti)

### 1. Crea il repository
Crea un nuovo repository GitHub (può essere pubblico o privato) e carica
tutto il contenuto di questa cartella.

### 2. Configura i secrets
In **Settings → Secrets and variables → Actions** del repository, aggiungi:

- `ANTHROPIC_API_KEY` — la tua chiave API Claude (necessaria per i riassunti
  di qualità). Se preferisci zero costo assoluto, non impostarla: vedi punto
  "Sintesi a costo zero" più sotto.
- `YOUTUBE_API_KEY` (opzionale) — chiave gratuita da
  [Google Cloud Console](https://console.cloud.google.com/) con "YouTube
  Data API v3" abilitata. Lasciala non impostata se non vuoi (ancora)
  monitorare YouTube.

### 3. Permetti ad Actions di fare commit
In **Settings → Actions → General → Workflow permissions**, seleziona
"Read and write permissions" (necessario perché il workflow fa commit dei
dati aggiornati ogni settimana).

### 4. Attiva GitHub Pages
In **Settings → Pages**, scegli come source "Deploy from a branch", branch
`main`, cartella `/frontend`. Dopo qualche minuto il calendario sarà
visibile su `https://<tuo-utente>.github.io/<nome-repo>/`.

### 5. (Opzionale) Configura i canali YouTube
Apri `config/canali_youtube.json` e sostituisci `INSERISCI_CHANNEL_ID` con
l'ID reale del canale (si trova nella pagina "Informazioni" del canale
YouTube, o tramite l'API `channels.list?forHandle=@nomehandle`).

### 6. Primo avvio manuale
Vai su **Actions → Raccolta settimanale dichiarazioni → Run workflow** per
lanciare subito la prima raccolta, senza aspettare il lunedì.

## Esecuzione locale (per test/debug)

```bash
pip install -r requirements.txt --break-system-packages
export ANTHROPIC_API_KEY=sk-ant-...     # opzionale
export YOUTUBE_API_KEY=...              # opzionale
python scripts/run_weekly.py
```

I dati finiscono in `data/tracker.db` (SQLite) e in `frontend/data/*.json`.
Apri `frontend/index.html` con un server locale (es. `python -m http.server`
dentro `frontend/`) per vederlo: aprendolo come file `file://` il `fetch()`
dei JSON viene bloccato dal browser per via del CORS.

## Sintesi a costo zero (senza API Claude)

Se non vuoi configurare `ANTHROPIC_API_KEY`, imposta la variabile d'ambiente
`USE_LOCAL_FALLBACK=1`: `summarize.py` userà una sintesi estrattiva grezza
(prime ~40 parole) invece di chiamare l'API. Qualità molto inferiore, ma
zero costo assoluto e zero account esterni necessari oltre a GitHub.

## Cosa monitoriamo e perché (limiti onesti)

- **Camera**: i Resoconti stenografici sono testo integrale pubblicato
  dalla Camera stessa — nessun problema di copyright, ed è la fonte più
  solida (verificata su pagine reali durante lo sviluppo).
- **Senato**: stessa natura di atto pubblico, ma lo scraping è più fragile
  per via di una protezione anti-bot riscontrata sul sito — da testare e
  rifinire.
- **Governo**: i comunicati del Consiglio dei Ministri citano spesso i
  singoli Ministri per nome — buona fonte regolare soprattutto per Meloni,
  che presiede quasi ogni riunione.
- **YouTube**: usiamo solo canali ufficiali e solo i sottotitoli pubblici
  (via la libreria `youtube-transcript-api`, non lo scaricamento del video):
  evitiamo sia il download di contenuti protetti sia l'uso scorretto delle
  quote dell'API ufficiale.
- **Stampa**: salviamo *solo* titolo, data, link e una parafrasi breve
  generata da noi — mai il testo dell'articolo. La whitelist delle testate è
  in `config/whitelist_stampa.txt`, modificabile liberamente.
- **Roberto Vannacci** è eurodeputato, non siede in Camera o Senato: per lui
  contano solo stampa, YouTube e comunicati — aspettati molti meno risultati
  rispetto agli altri 7.
- I leader di partito non parlano ogni giorno in Aula personalmente (spesso
  intervengono i loro deputati/senatori): è normale che ci siano periodi con
  poche o nessuna dichiarazione diretta per una persona.
- **Le "promesse" e i "cambi di posizione" estratti dall'LLM sono indizi da
  verificare, non verdetti.** Il modello può sbagliare, perdere contesto o
  interpretare male l'ironia/il sarcasmo. Trattali come spunti per andare a
  controllare la fonte originale, non come fatti accertati.

## Prossimi passi possibili (non ancora fatti)

- Migrare lo storage a Cloudflare D1 + Workers se il volume di dati cresce
  e SQLite-nel-repo iniziasse a diventare scomodo.
- Rendere configurabile la frequenza di scraping (oggi fissa a settimanale,
  vedi `.github/workflows/weekly-scrape.yml`, riga `cron`).
- Aggiungere una vista "per tema" oltre a quella calendario.
- Verificare/irrobustire lo scraper Senato.
