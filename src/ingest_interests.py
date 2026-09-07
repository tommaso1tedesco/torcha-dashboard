"""Ingest Parte 2 (Apify): Google Trends, Google SERP, TikTok, YouTube, X, Reddit.

Stessa filosofia di src/ingest_rss.py: ogni fonte è indipendente, se una fallisce
le altre proseguono, e la Run finale riporta chi ha risposto e chi no.

Nota su TikTok/YouTube/X: nessuno di questi offre un "trending now" pubblico senza
login. Li alimentiamo con query/hashtag "seed" (i temi più caldi da Parte 1, Heat
score) e leggiamo l'engagement di risposta come segnale di interesse — è una
approssimazione onesta, non un vero feed di trending. Google Trends (mode:
trending) e Reddit (sort: hot sulle subreddit configurate) sono invece segnali
diretti, senza bisogno di seed.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.apify_client_wrapper import run_actor
from src.config import APIFY_TOKEN, load_sources
from src.db import SessionLocal
from src.clustering import cluster_articles
from src.models import Article, InterestRun, Signal

logger = logging.getLogger("ingest_interests")

SEED_TOPICS_COUNT = 5
SEED_LOOKBACK_HOURS = 24

# Nomi di campo candidati per l'attribuzione keyword->item, in ordine di preferenza.
_QUERY_FIELD_CANDIDATES = ["searchQuery", "query", "searchTerm", "inputHashtag", "hashtag"]


def _shorten_to_query(title: str, max_words: int = 4) -> str:
    first_clause = re.split(r"[,:;—-]", title)[0]
    words = first_clause.split()
    return " ".join(words[:max_words]).strip()


def _get_seed_keywords(limit: int = SEED_TOPICS_COUNT) -> list[str]:
    """Query brevi (2-4 parole) dalle storie più calde di Parte 1, da usare come seed."""
    since = datetime.now(timezone.utc) - timedelta(hours=SEED_LOOKBACK_HOURS)
    session = SessionLocal()
    try:
        stmt = select(Article).where(Article.published_at >= since)
        articles = list(session.execute(stmt).scalars())
    finally:
        session.close()
    if not articles:
        return []
    clusters = cluster_articles(articles)
    seeds = [_shorten_to_query(c.representative_title) for c in clusters[:limit]]
    return [s for s in seeds if s]


def _attribute_keyword(item: dict, seeds: list[str], fallback_text_fields: list[str]) -> str | None:
    """Trova a quale seed appartiene un item: prima via campo esplicito, poi via overlap di parole."""
    for field in _QUERY_FIELD_CANDIDATES:
        val = item.get(field)
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, dict) and val.get("name"):
            return str(val["name"]).strip()

    text = " ".join(str(item.get(f, "")) for f in fallback_text_fields).lower()
    if not text.strip():
        return None
    best_seed, best_overlap = None, 0
    for seed in seeds:
        overlap = sum(1 for w in seed.lower().split() if len(w) > 3 and w in text)
        if overlap > best_overlap:
            best_seed, best_overlap = seed, overlap
    return best_seed


def _parse_numeric(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        m = re.match(r"([\d.,]+)\s*([KMB]?)", value.strip(), re.IGNORECASE)
        if m:
            num = float(m.group(1).replace(",", ""))
            mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(m.group(2).upper(), 1)
            return num * mult
    return 0.0


def _save_signals(rows: list[dict]) -> None:
    if not rows:
        return
    session = SessionLocal()
    try:
        session.bulk_insert_mappings(Signal, rows)
        session.commit()
    finally:
        session.close()


def _ingest_google_trends_daily(cfg: dict) -> list[dict]:
    result = run_actor(cfg["actor_id"], cfg["input_trending"])
    rows = []
    for item in result:
        keyword = item.get("query") or item.get("title") or item.get("keyword") or item.get("searchTerm")
        if not keyword:
            continue
        metric = _parse_numeric(
            item.get("trafficValue") or item.get("traffic") or item.get("searchVolume") or item.get("formattedTraffic")
        ) or 1.0
        rows.append({
            "signal_source": "google_trends_daily", "keyword": str(keyword)[:512],
            "metric": metric, "extra": {"raw_keys": list(item.keys())}, "fetched_at": datetime.now(timezone.utc),
        })
    return rows


def _ingest_google_serp(cfg: dict, seeds: list[str]) -> list[dict]:
    if not seeds:
        return []
    result = run_actor(cfg["actor_id"], {**cfg["input"], "queries": "\n".join(seeds)})
    rows = []
    for item in result:
        keyword = item.get("searchQuery", {}).get("term") if isinstance(item.get("searchQuery"), dict) else item.get("searchQuery")
        keyword = keyword or (seeds[0] if len(seeds) == 1 else None)
        if not keyword:
            continue
        paa = item.get("peopleAlsoAsk") or []
        related = item.get("relatedQueries") or item.get("relatedSearches") or []
        has_ai_overview = bool(item.get("aiOverview"))
        metric = float(len(paa) + len(related) + (3 if has_ai_overview else 0))
        rows.append({
            "signal_source": "google_serp", "keyword": str(keyword)[:512],
            "metric": metric,
            "extra": {"people_also_ask": [p.get("question") for p in paa if isinstance(p, dict)][:10], "has_ai_overview": has_ai_overview},
            "fetched_at": datetime.now(timezone.utc),
        })
    return rows


def _ingest_tiktok(cfg: dict, seeds: list[str]) -> list[dict]:
    if not seeds:
        return []
    hashtags = [re.sub(r"[^a-zA-Z0-9]", "", s.split()[0]) for s in seeds if s.split()]
    hashtags = [h for h in hashtags if h][:SEED_TOPICS_COUNT]
    if not hashtags:
        return []
    result = run_actor(cfg["actor_id"], {**cfg["input"], "hashtags": hashtags})
    rows = []
    for item in result:
        keyword = _attribute_keyword(item, seeds, ["text", "desc"])
        if not keyword:
            continue
        metric = _parse_numeric(item.get("diggCount") or item.get("playCount") or 0)
        rows.append({
            "signal_source": "tiktok", "keyword": str(keyword)[:512], "metric": metric,
            "extra": {"video_url": item.get("webVideoUrl") or item.get("videoUrl")},
            "fetched_at": datetime.now(timezone.utc),
        })
    return rows


def _ingest_youtube(cfg: dict, seeds: list[str]) -> list[dict]:
    if not seeds:
        return []
    result = run_actor(cfg["actor_id"], {**cfg["input"], "searchQueries": seeds})
    rows = []
    for item in result:
        keyword = _attribute_keyword(item, seeds, ["title"])
        if not keyword:
            continue
        metric = _parse_numeric(item.get("viewCount") or item.get("viewCountInt") or 0)
        rows.append({
            "signal_source": "youtube", "keyword": str(keyword)[:512], "metric": metric,
            "extra": {"video_url": item.get("url")},
            "fetched_at": datetime.now(timezone.utc),
        })
    return rows


def _ingest_x(cfg: dict, seeds: list[str]) -> list[dict]:
    if not seeds:
        return []
    result = run_actor(cfg["actor_id"], {**cfg["input"], "searchTerms": seeds})
    rows = []
    for item in result:
        keyword = _attribute_keyword(item, seeds, ["text", "fullText"])
        if not keyword:
            continue
        metric = _parse_numeric(item.get("likeCount") or item.get("retweetCount") or 0) + 1
        rows.append({
            "signal_source": "x", "keyword": str(keyword)[:512], "metric": metric,
            "extra": {"tweet_url": item.get("url") or item.get("twitterUrl")},
            "fetched_at": datetime.now(timezone.utc),
        })
    return rows


def _ingest_reddit(cfg: dict) -> list[dict]:
    start_urls = [{"url": f"https://www.reddit.com/r/{sub}/"} for sub in cfg.get("subreddits", [])]
    if not start_urls:
        return []
    result = run_actor(cfg["actor_id"], {**cfg["input"], "startUrls": start_urls})
    rows = []
    for item in result:
        title = item.get("title")
        if not title:
            continue
        metric = _parse_numeric(item.get("upVotes") or item.get("score") or item.get("numberOfUpvotes") or 0)
        rows.append({
            "signal_source": "reddit", "keyword": str(title)[:512], "metric": metric,
            "extra": {"post_url": item.get("url") or item.get("permalink"), "subreddit": item.get("communityName")},
            "fetched_at": datetime.now(timezone.utc),
        })
    return rows


def run_interest_ingest() -> dict:
    """Esegue l'ingest di tutte le fonti Apify configurate. Ritorna {sources_ok, sources_failed, signals_ingested}."""
    if not APIFY_TOKEN:
        logger.info("APIFY_TOKEN non configurato: salto l'ingest Parte 2 (Apify).")
        return {"sources_ok": [], "sources_failed": ["Apify (tutte le fonti) — APIFY_TOKEN non configurato"], "signals_ingested": 0}

    session = SessionLocal()
    run = InterestRun()
    session.add(run)
    session.commit()

    cfg = load_sources()["interests"]["apify"]["actors"]
    seeds = _get_seed_keywords()

    tasks = [
        ("google_trends_daily", lambda: _ingest_google_trends_daily(cfg["google_trends"])),
        ("google_serp", lambda: _ingest_google_serp(cfg["google_serp"], seeds)),
        ("tiktok", lambda: _ingest_tiktok(cfg["tiktok_trending"], seeds)),
        ("youtube", lambda: _ingest_youtube(cfg["youtube_trending"], seeds)),
        ("x", lambda: _ingest_x(cfg["x_trending"], seeds)),
        ("reddit", lambda: _ingest_reddit(cfg["reddit_rising"])),
    ]

    sources_ok, sources_failed, total = [], [], 0
    for name, task in tasks:
        try:
            rows = task()
            _save_signals(rows)
            total += len(rows)
            sources_ok.append(f"{name} ({len(rows)} segnali)")
        except Exception as e:
            logger.warning("Fonte interesse '%s' fallita: %s", name, e)
            sources_failed.append(f"{name} — {e}")

    run.finished_at = datetime.now(timezone.utc)
    run.sources_ok = sources_ok
    run.sources_failed = sources_failed
    run.signals_ingested = total
    session.commit()
    session.close()

    return {"sources_ok": sources_ok, "sources_failed": sources_failed, "signals_ingested": total}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(run_interest_ingest())
