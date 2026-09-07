"""Entrypoint del worker cron: una singola esecuzione di ingest, poi esce.

Su Railway questo script è il "Start Command" del servizio worker, schedulato
con un Cron Schedule (es. ogni 45 minuti, vedi sources.yaml -> settings.refresh_minutes).
"""
import logging
import sys

from src.ingest_interests import run_interest_ingest
from src.ingest_rss import run_ingest
from src.init_db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("worker")


def main() -> int:
    init_db()  # idempotente: se il worker parte prima della dashboard, crea comunque lo schema

    logger.info("Avvio ingest RSS (Parte 1)...")
    summary = run_ingest()
    logger.info("Fonti OK (%d): %s", len(summary["sources_ok"]), summary["sources_ok"])
    if summary["sources_failed"]:
        logger.warning("Fonti fallite (%d): %s", len(summary["sources_failed"]), summary["sources_failed"])
    logger.info("Articoli nuovi ingeriti: %d", summary["articles_ingested"])

    logger.info("Avvio ingest interesse — Apify + Wikipedia (Parte 2)...")
    interest_summary = run_interest_ingest()
    logger.info("Fonti interesse OK (%d): %s", len(interest_summary["sources_ok"]), interest_summary["sources_ok"])
    if interest_summary["sources_failed"]:
        logger.warning("Fonti interesse fallite (%d): %s", len(interest_summary["sources_failed"]), interest_summary["sources_failed"])
    logger.info("Segnali nuovi ingeriti: %d", interest_summary["signals_ingested"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
