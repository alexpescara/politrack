"""
Orchestratore eseguito settimanalmente da GitHub Actions (vedi
.github/workflows/weekly-scrape.yml). Esegue in sequenza tutti gli scraper,
poi la sintesi via LLM, poi l'export dei JSON per il frontend.

Ogni scraper e' isolato in un try/except: se una fonte fallisce (es. sito
che blocca le richieste), le altre vanno comunque avanti.
"""
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scraping"))
sys.path.insert(0, str(ROOT / "analysis"))
sys.path.insert(0, str(ROOT / "db"))


def esegui(nome, funzione):
    print(f"\n=== {nome} ===")
    try:
        funzione()
    except Exception:
        print(f"[run_weekly] ERRORE in {nome}, continuo con il resto:")
        traceback.print_exc()


def main():
    import camera_scraper
    import senato_scraper
    import governo_scraper
    import youtube_scraper
    import stampa_scraper
    import summarize
    import export_json

    esegui("Camera", camera_scraper.main)
    esegui("Senato", senato_scraper.main)
    esegui("Governo", governo_scraper.main)
    esegui("YouTube", youtube_scraper.main)
    esegui("Stampa", stampa_scraper.main)
    esegui("Sintesi (riassunti/promesse/posizioni)", summarize.main)
    esegui("Export JSON per il frontend", export_json.main)


if __name__ == "__main__":
    main()
