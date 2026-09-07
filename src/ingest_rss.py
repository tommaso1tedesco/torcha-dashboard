"""Ingest via RSS: fetch, normalizzazione, upsert su Postgres, log fonti ok/failed."""
from __future__ import annotations

import logging
import time
import urllib.error
from calendar import timegm
from datetime import datetime, timezone

import feedparser
from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.config import ACTIVE_CATEGORIES, all_sources_for_category
from src.db import SessionLocal
from src.http import fetch_bytes
from src.models import Article, Run

logger = logging.getLogger("ingest_rss")

USER_AGENT = "Mozilla/5.0 (compatible; TorchaDashboardBot/1.0; +https://github.com/)"
TIMEOUT_SECONDS = 15
MAX_RETRIES = 2


def _fetch_feed(url: str) -> feedparser.FeedParserDict | None:
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            raw = fetch_bytes(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS)
            parsed = feedparser.parse(raw)
            if parsed.bozo and not parsed.entries:
                raise ValueError(f"feed non parsabile: {parsed.bozo_exception}")
            return parsed
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            last_error = e
            logger.warning("Tentativo %d/%d fallito per %s: %s", attempt, MAX_RETRIES, url, e)
            time.sleep(1.5 * attempt)
    logger.error("Fonte non raggiungibile dopo %d tentativi: %s (%s)", MAX_RETRIES, url, last_error)
    return None


def _entry_published_at(entry) -> datetime:
    for field in ("published_parsed", "updated_parsed"):
        struct = getattr(entry, field, None)
        if struct:
            return datetime.fromtimestamp(timegm(struct), tz=timezone.utc)
    return datetime.now(timezone.utc)


def _normalize_entries(parsed: feedparser.FeedParserDict, source_name: str, category: str) -> list[dict]:
    rows = []
    for entry in parsed.entries:
        url = getattr(entry, "link", None)
        title = getattr(entry, "title", None)
        if not url or not title:
            continue
        rows.append({
            "title": title.strip(),
            "source": source_name,
            "category": category,
            "url": url.strip(),
            "published_at": _entry_published_at(entry),
            "lang": "it",
        })
    return rows


def run_ingest(categories: list[str] | None = None) -> dict:
    """Esegue l'ingest RSS per le categorie indicate (default: ACTIVE_CATEGORIES).

    Ritorna un riepilogo {sources_ok, sources_failed, articles_ingested}.
    """
    categories = categories or ACTIVE_CATEGORIES
    session = SessionLocal()
    run = Run()
    session.add(run)
    session.flush()  # per avere run.id

    sources_ok: list[str] = []
    sources_failed: list[str] = []
    total_new = 0

    try:
        for category in categories:
            sources = all_sources_for_category(category)
            for src in sources:
                label = f"{src['name']} ({category})"
                if src.get("via") != "rss" or not src.get("rss_url"):
                    sources_failed.append(f"{label} — non disponibile via RSS (via={src.get('via')})")
                    continue

                parsed = _fetch_feed(src["rss_url"])
                if parsed is None:
                    sources_failed.append(f"{label} — fetch/parse fallito")
                    continue

                rows = _normalize_entries(parsed, src["name"], category)
                if not rows:
                    sources_failed.append(f"{label} — feed raggiunto ma 0 articoli estratti")
                    continue

                for row in rows:
                    row["first_seen_run_id"] = run.id
                stmt = pg_insert(Article).values(rows).on_conflict_do_nothing(index_elements=["url"])
                result = session.execute(stmt)
                total_new += result.rowcount or 0
                sources_ok.append(label)

        run.finished_at = datetime.now(timezone.utc)
        run.sources_ok = sources_ok
        run.sources_failed = sources_failed
        run.articles_ingested = total_new
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    logger.info(
        "Run completata: %d nuovi articoli, %d fonti ok, %d fonti fallite",
        total_new, len(sources_ok), len(sources_failed),
    )
    return {
        "sources_ok": sources_ok,
        "sources_failed": sources_failed,
        "articles_ingested": total_new,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    summary = run_ingest()
    print(summary)
