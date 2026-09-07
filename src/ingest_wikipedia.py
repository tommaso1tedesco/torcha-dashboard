"""Ingest Wikipedia Pageviews API (Parte 2): top articoli del giorno + andamento.

API ufficiale, gratuita, senza token: https://wikimedia.org/api/rest_v1/metrics/pageviews/
Richiede uno User-Agent descrittivo (norma d'uso Wikimedia).
"""
from __future__ import annotations

import logging
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from statistics import mean

from src.config import load_sources
from src.models import Signal

logger = logging.getLogger("ingest_wikipedia")

USER_AGENT = "TorchaDashboard/1.0 (dashboard editoriale IT; contatto: repo GitHub torcha-dashboard)"
TIMEOUT_SECONDS = 15

TOP_N = 20            # quanti articoli top-daily diventano segnale
TREND_N = 10           # per quanti di questi calcoliamo anche l'andamento settimanale
TREND_LOOKBACK_DAYS = 8

# Namespace/pagine non editoriali da escludere dal segnale "top articoli".
_EXCLUDED_PREFIXES = (
    "Speciale:", "Wikipedia:", "File:", "Categoria:", "Aiuto:", "Portale:",
    "Progetto:", "Utente:", "Discussione", "Modulo:", "Template:", "MediaWiki:",
)
_EXCLUDED_TITLES = {"Pagina_principale"}


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        import json
        return json.loads(resp.read())


def _fetch_top_daily(project: str) -> list[tuple[str, int]]:
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    date_path = yesterday.strftime("%Y/%m/%d")
    url = f"https://wikimedia.org/api/rest_v1/metrics/pageviews/top/{project}/all-access/{date_path}"
    data = _get(url)
    articles = data["items"][0]["articles"]
    result = []
    for a in articles:
        title = a["article"]
        if title in _EXCLUDED_TITLES or any(title.startswith(p) for p in _EXCLUDED_PREFIXES):
            continue
        result.append((title, a["views"]))
    return result


def _fetch_article_history(project: str, title: str) -> list[int]:
    end = datetime.now(timezone.utc) - timedelta(days=1)
    start = end - timedelta(days=TREND_LOOKBACK_DAYS - 1)
    url = (
        f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/{project}/all-access/user/"
        f"{title}/daily/{start.strftime('%Y%m%d')}/{end.strftime('%Y%m%d')}"
    )
    data = _get(url)
    return [item["views"] for item in data["items"]]


def run_wikipedia_ingest() -> dict:
    """Ritorna {sources_ok, sources_failed, signals_ingested}, stesso formato delle altre fonti."""
    project = load_sources()["interests"]["wikipedia"]["project"]

    sources_ok, sources_failed, rows = [], [], []
    try:
        top_articles = _fetch_top_daily(project)
    except (urllib.error.URLError, KeyError, ValueError) as e:
        logger.warning("Wikipedia top-daily fallito: %s", e)
        return {"sources_ok": [], "sources_failed": [f"wikipedia_top_daily — {e}"], "signals_ingested": 0}

    now = datetime.now(timezone.utc)
    for title, views in top_articles[:TOP_N]:
        rows.append({
            "signal_source": "wikipedia_top_daily", "keyword": title.replace("_", " "),
            "metric": float(views), "extra": {"project": project}, "fetched_at": now,
        })
    sources_ok.append(f"wikipedia_top_daily ({len(rows)} segnali)")

    trend_count = 0
    for title, _views in top_articles[:TREND_N]:
        try:
            history = _fetch_article_history(project, title)
        except (urllib.error.URLError, KeyError, ValueError) as e:
            logger.warning("Wikipedia trend fallito per '%s': %s", title, e)
            continue
        if len(history) < 2:
            continue
        latest, baseline = history[-1], mean(history[:-1]) or 1.0
        rows.append({
            "signal_source": "wikipedia_trend", "keyword": title.replace("_", " "),
            "metric": round(latest / baseline, 3), "extra": {"history": history, "project": project},
            "fetched_at": now,
        })
        trend_count += 1

    if trend_count:
        sources_ok.append(f"wikipedia_trend ({trend_count} segnali)")
    else:
        sources_failed.append("wikipedia_trend — nessun andamento calcolabile")

    from src.db import SessionLocal
    session = SessionLocal()
    try:
        if rows:
            session.bulk_insert_mappings(Signal, rows)
            session.commit()
    finally:
        session.close()

    return {"sources_ok": sources_ok, "sources_failed": sources_failed, "signals_ingested": len(rows)}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(run_wikipedia_ingest())
