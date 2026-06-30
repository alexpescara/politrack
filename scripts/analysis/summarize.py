"""
Genera, per ogni dichiarazione non ancora riassunta (riassunto IS NULL):
  - una breve parafrasi (riassunto), MAI il testo originale
  - una lista di temi
  - eventuali promesse estratte (testo + tema)
  - un'eventuale sintesi di posizione su un tema (per individuare cambi nel tempo)

Usa l'API Claude (modello economico, output compatto). Richiede la variabile
d'ambiente ANTHROPIC_API_KEY (impostala come secret di GitHub Actions).

IMPORTANTE su costi: con poche decine di dichiarazioni a settimana e prompt
brevi, il costo e' dell'ordine di pochi centesimi al mese. Se preferisci zero
costo assoluto, vedi la funzione `riassunto_fallback_locale` in fondo: una
sintesi estrattiva molto piu' rozza che non chiama nessuna API esterna (da
attivare impostando USE_LOCAL_FALLBACK=1 nell'ambiente).

Importante sul trattamento dell'output: il riassunto generato viene salvato
e SUBITO DOPO il campo testo_grezzo viene azzerato (NULL), per non conservare
il testo originale di terzi più del tempo necessario a riassumerlo.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "db"))
from db_utils import get_connection

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
USE_LOCAL_FALLBACK = os.environ.get("USE_LOCAL_FALLBACK") == "1"
MODEL = "claude-haiku-4-5-20251001"  # modello economico, sufficiente per riassunti brevi

PROMPT_SISTEMA = """Sei un assistente che produce SOLO parafrasi brevi e neutrali di dichiarazioni
politiche italiane, per un archivio personale di consultazione. Non riprodurre mai il testo
originale alla lettera: riformula sempre con parole tue. Rispondi SOLO con JSON valido,
nessun altro testo, nel formato:
{
  "riassunto": "...massimo 60 parole, in italiano, tono neutro...",
  "temi": ["tema1", "tema2"],
  "promesse": [{"testo": "...", "tema": "..."}],
  "posizione": {"tema": "...", "sintesi": "...massimo 30 parole..."}
}
Usa "promesse": [] se non viene espresso alcun impegno concreto e verificabile.
Usa "posizione": null se il testo non esprime una posizione chiara su un tema specifico.
"""


def chiama_claude(testo_grezzo, contesto):
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    messaggio = client.messages.create(
        model=MODEL,
        max_tokens=400,
        system=PROMPT_SISTEMA,
        messages=[{
            "role": "user",
            "content": (
                f"Contesto: {contesto}\n\n"
                f"Testo della dichiarazione (NON riprodurlo, riassumilo solo):\n{testo_grezzo}"
            ),
        }],
    )
    testo_risposta = messaggio.content[0].text
    return json.loads(testo_risposta)


def riassunto_fallback_locale(testo_grezzo):
    """Sintesi estrattiva grezza, zero-costo, zero-API: prende solo le prime ~40 parole
    riformulate al minimo. Qualita' molto inferiore a Claude, ma utile come opzione
    a costo zero assoluto se non si vuole configurare ANTHROPIC_API_KEY."""
    parole = testo_grezzo.split()
    estratto = " ".join(parole[:40])
    return {
        "riassunto": f"(sintesi automatica grezza, da rivedere) {estratto}...",
        "temi": [],
        "promesse": [],
        "posizione": None,
    }


def processa_dichiarazioni_in_attesa(conn, limite=50):
    righe = conn.execute(
        """SELECT id, politico_id, data, fonte_tipo, fonte_nome, testo_grezzo
           FROM dichiarazioni
           WHERE riassunto IS NULL AND testo_grezzo IS NOT NULL
           LIMIT ?""",
        (limite,),
    ).fetchall()

    n_ok = 0
    for riga in righe:
        contesto = f"{riga['fonte_tipo']} - {riga['fonte_nome']} - {riga['data']}"
        try:
            if USE_LOCAL_FALLBACK or not ANTHROPIC_API_KEY:
                risultato = riassunto_fallback_locale(riga["testo_grezzo"])
            else:
                risultato = chiama_claude(riga["testo_grezzo"], contesto)
        except Exception as e:
            print(f"[summarize] errore su dichiarazione {riga['id']}: {e}")
            continue

        temi_str = ",".join(risultato.get("temi", []))
        conn.execute(
            """UPDATE dichiarazioni
               SET riassunto = ?, temi = ?, testo_grezzo = NULL
               WHERE id = ?""",
            (risultato["riassunto"], temi_str, riga["id"]),
        )

        for promessa in risultato.get("promesse", []):
            conn.execute(
                """INSERT INTO promesse (politico_id, dichiarazione_id, testo_promessa, data_promessa)
                   VALUES (?, ?, ?, ?)""",
                (riga["politico_id"], riga["id"], promessa["testo"], riga["data"]),
            )

        posizione = risultato.get("posizione")
        if posizione:
            conn.execute(
                """INSERT INTO posizioni_nel_tempo (politico_id, tema, dichiarazione_id, data, sintesi_posizione)
                   VALUES (?, ?, ?, ?, ?)""",
                (riga["politico_id"], posizione["tema"], riga["id"], riga["data"], posizione["sintesi"]),
            )

        conn.commit()
        n_ok += 1

    return n_ok


def main():
    conn = get_connection()
    n = processa_dichiarazioni_in_attesa(conn)
    print(f"[summarize] {n} dichiarazioni riassunte")
    conn.close()


if __name__ == "__main__":
    main()
