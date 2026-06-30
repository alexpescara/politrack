-- Schema SQLite per il tracker dichiarazioni politici italiani
-- Compatibile anche con Cloudflare D1 se in futuro si migra (stesso dialetto SQLite)

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS politici (
    id              TEXT PRIMARY KEY,      -- es. 'meloni'
    nome            TEXT NOT NULL,
    ruolo           TEXT,
    partito         TEXT,
    partito_sigla   TEXT,
    colore          TEXT
);

-- Una riga = una dichiarazione/intervento individuato per un politico in una fonte,
-- in una data specifica. NIENTE testo integrale di terzi: solo riassunto/parafrasi
-- generato da noi + link alla fonte originale.
CREATE TABLE IF NOT EXISTS dichiarazioni (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    politico_id     TEXT NOT NULL REFERENCES politici(id),
    data            TEXT NOT NULL,         -- formato YYYY-MM-DD
    fonte_tipo      TEXT NOT NULL,         -- 'camera' | 'senato' | 'governo' | 'youtube' | 'stampa'
    fonte_nome      TEXT,                  -- es. 'Seduta n. 630 Camera' / 'ANSA'
    fonte_url       TEXT NOT NULL,
    riassunto       TEXT,                  -- parafrasi breve generata dall'LLM (no testo originale). NULL finche' non riassunta.
    temi            TEXT,                  -- lista temi separati da virgola (es. 'giustizia,migrazione')
    hash_contenuto  TEXT,                  -- hash del testo grezzo, per evitare duplicati
    testo_grezzo    TEXT,                  -- estratto temporaneo usato SOLO per generare il riassunto;
                                            -- viene azzerato (NULL) da summarize.py una volta creato il riassunto,
                                            -- cosi' non restiamo a conservare testo di terzi piu' del necessario.
    creato_il       TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_dichiarazioni_data ON dichiarazioni(data);
CREATE INDEX IF NOT EXISTS idx_dichiarazioni_politico ON dichiarazioni(politico_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_dichiarazioni_dedup ON dichiarazioni(politico_id, fonte_url, hash_contenuto);

-- Promesse estratte automaticamente (sempre da verificare manualmente: sono "indizi")
CREATE TABLE IF NOT EXISTS promesse (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    politico_id         TEXT NOT NULL REFERENCES politici(id),
    dichiarazione_id    INTEGER NOT NULL REFERENCES dichiarazioni(id),
    testo_promessa      TEXT NOT NULL,
    data_promessa       TEXT NOT NULL,
    stato               TEXT DEFAULT 'da_verificare',  -- da_verificare | mantenuta | non_mantenuta | in_corso
    note_verifica       TEXT,
    aggiornato_il       TEXT DEFAULT (datetime('now'))
);

-- Posizioni nel tempo su un tema, per individuare eventuali cambi di posizione
CREATE TABLE IF NOT EXISTS posizioni_nel_tempo (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    politico_id         TEXT NOT NULL REFERENCES politici(id),
    tema                TEXT NOT NULL,
    dichiarazione_id    INTEGER NOT NULL REFERENCES dichiarazioni(id),
    data                TEXT NOT NULL,
    sintesi_posizione   TEXT NOT NULL    -- 1-2 frasi: "posizione su [tema] in questa data"
);

CREATE INDEX IF NOT EXISTS idx_posizioni_tema ON posizioni_nel_tempo(politico_id, tema);

-- Tiene traccia di cosa e' già stato processato, per non rifare lavoro ad ogni run
CREATE TABLE IF NOT EXISTS stato_scraping (
    fonte_tipo      TEXT PRIMARY KEY,   -- 'camera' | 'senato' | 'governo' | 'youtube' | 'stampa'
    ultimo_riferimento TEXT,            -- es. ultimo numero di seduta processato, o ultima data
    aggiornato_il   TEXT DEFAULT (datetime('now'))
);
