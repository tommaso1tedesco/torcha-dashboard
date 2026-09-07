"""Entrypoint del worker cron: una singola esecuzione di ingest, poi esce.

Su Railway questo script è il "Start Command" del servizio worker, schedulato
con un Cron Schedule (es. ogni 45 minuti, vedi sources.yaml -> settings.refresh_minutes).
"""
import logging
import sys

from src.clustering import cluster_articles
from src.config import ACTIVE_CATEGORIES, DASHBOARD_WINDOW_HOURS
from src.ingest_interests import run_interest_ingest
from src.ingest_rss import run_ingest
from src.init_db import init_db
from src.queries import get_recent_articles, get_recent_signals
from src.rising import compute_rising_themes
from src.velocity import record_snapshots

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("worker")


def _record_heat_snapshots() -> None:
    """Fase 5: uno scatto per cluster corrente per categoria, per costruire la baseline storica."""
    for category in ACTIVE_CATEGORIES:
        articles = get_recent_articles(category, DASHBOARD_WINDOW_HOURS)
        if not articles:
            continue
        clusters = cluster_articles(articles)
        items = [(c.representative_title, c.article_count, c.heat_score) for c in clusters]
        record_snapshots("heat", items, category=category)


def _record_rising_snapshots() -> None:
    signals = get_recent_signals(DASHBOARD_WINDOW_HOURS)
    if not signals:
        return
    themes = compute_rising_themes(signals)
    items = [(t.keyword, len(t.signals), t.rising_score) for t in themes]
    record_snapshots("rising", items)


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

    logger.info("Registrazione scatti Fase 5 (baseline storica)...")
    _record_heat_snapshots()
    _record_rising_snapshots()
    return 0


if __name__ == "__main__":
    sys.exit(main())
