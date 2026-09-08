"""Ingest Parte 2: orchestratore di Google Trends/SERP/TikTok/YouTube (via Apify),
Google Autocomplete (pubblico) e Wikipedia (src/ingest_wikipedia.py).

Stessa filosofia di src/ingest_rss.py: ogni fonte è indipendente, se una fallisce
le altre proseguono, e la Run finale riporta chi ha risposto e chi no.

Nota su TikTok/YouTube: nessuno dei due offre un "trending now" pubblico senza
login. Li alimentiamo con query/hashtag "seed" (i temi più caldi da Parte 1, Heat
score) e leggiamo l'engagement di risposta come segnale di interesse — è una
approssimazione onesta, non un vero feed di trending. Google Trends (mode:
trending) è invece un segnale diretto, senza bisogno di seed.

Reddit e X sono escluse dal ciclo automatico per controllo costi/affidabilità
(vedi APIFY_MIN_INTERVAL_HOURS più sotto e i commenti in sources.yaml), ma le
funzioni _ingest_reddit/_ingest_x restano disponibili per un uso manuale.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.apify_client_wrapper import run_actor
from src.config import APIFY_TOKEN, load_sources
from src.db import SessionLocal
from src.clustering import cluster_articles
from src.http import fetch_bytes
from src.models import Article, InterestRun, Signal

logger = logging.getLogger("ingest_interests")

SEED_TOPICS_COUNT = 5
SEED_LOOKBACK_HOURS = 24

# Controllo costi: le fonti RSS/Wikipedia/Autocomplete sono gratuite e girano ad ogni
# ciclo (ogni 45 min, vedi worker.py); le fonti Apify a pagamento no — girano al più
# una volta ogni APIFY_MIN_INTERVAL_HOURS, indipendentemente da quante volte viene
# chiamato run_interest_ingest() (sia da cron che dal pulsante Aggiorna). Con i volumi
# ridotti sotto, tenersi sotto ~€15/mese di spesa Apify richiede questo intervallo.
APIFY_MIN_INTERVAL_HOURS = 12
_APIFY_PAID_SIGNAL_SOURCES = ("google_trends_daily", "google_serp", "tiktok", "youtube")

# Volumi seed per fonte, ridotti rispetto al default per contenere i costi Apify
# (TikTok e YouTube sono le fonti più care per risultato, vedi sources.yaml).
SERP_SEED_COUNT = 3
TIKTOK_SEED_COUNT = 2
YOUTUBE_SEED_COUNT = 2

# Nomi di campo candidati per l'attribuzione keyword->item, in ordine di preferenza.
# Verificati dal vivo sugli Actor reali: "input" (TikTok, YouTube) e "searchHashtag"
# (TikTok) rimandano esattamente al seed usato, quindi vengono prima degli altri.
_QUERY_FIELD_CANDIDATES = ["input", "searchHashtag", "searchQuery", "query", "searchTerm", "inputHashtag", "hashtag"]


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
    """Output reale (verificato dal vivo): un solo item con dentro trending_searches:
    [{rank, term, trend_volume: "500K+", trend_volume_formatted: 500000, related_terms: [...]}]."""
    result = run_actor(cfg["actor_id"], cfg["input_trending"])
    if not result:
        return []
    trends = result[0].get("trending_searches", [])
    rows = []
    now = datetime.now(timezone.utc)
    for t in trends:
        keyword = t.get("term")
        if not keyword:
            continue
        metric = t.get("trend_volume_formatted") or _parse_numeric(t.get("trend_volume")) or 1.0
        rows.append({
            "signal_source": "google_trends_daily", "keyword": str(keyword)[:512],
            "metric": float(metric), "extra": {"related_terms": (t.get("related_terms") or [])[:10]},
            "fetched_at": now,
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
    hashtags = [h for h in hashtags if h]
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
    """Nota (verificato dal vivo): serve .../hot/ nell'URL, non solo la root della subreddit
    (altrimenti l'Actor ritorna i metadati della community, non i post). La variante "Lite"
    di questo Actor non include voti/punteggio nell'output: usiamo il rank di posizione
    (l'ordine "hot" è già per engagement) come metrica v0."""
    subs = cfg.get("subreddits", [])
    start_urls = [{"url": f"https://www.reddit.com/r/{sub}/hot/"} for sub in subs]
    if not start_urls:
        return []
    # maxItems è il tetto complessivo del dataset (default basso se omesso): deve coprire
    # tutte le subreddit, non solo maxPostCount (che è per singolo start URL).
    max_items = cfg["input"].get("maxPostCount", 20) * len(subs)
    input_ = {
        **cfg["input"], "startUrls": start_urls, "maxItems": max_items,
        "searchCommunities": False, "searchComments": False, "searchUsers": False,
    }
    result = run_actor(cfg["actor_id"], input_)
    rows = []
    now = datetime.now(timezone.utc)
    posts = [item for item in result if item.get("dataType") == "post" and item.get("title")]
    n = len(posts)
    for rank, item in enumerate(posts):
        metric = _parse_numeric(item.get("upVotes") or item.get("score") or item.get("numberOfUpvotes")) or float(n - rank)
        rows.append({
            "signal_source": "reddit", "keyword": str(item["title"])[:512], "metric": metric,
            "extra": {"post_url": item.get("url"), "subreddit": item.get("communityName")},
            "fetched_at": now,
        })
    return rows


def _ingest_google_autocomplete(seeds: list[str]) -> list[dict]:
    """Endpoint pubblico Google Suggest: nessun token richiesto."""
    if not seeds:
        return []
    rows = []
    now = datetime.now(timezone.utc)
    for seed in seeds:
        url = "https://www.google.com/complete/search?" + urllib.parse.urlencode({
            "client": "firefox", "q": seed, "hl": "it", "gl": "it",
        })
        raw = fetch_bytes(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        data = json.loads(raw)
        suggestions = data[1] if len(data) > 1 else []
        for rank, suggestion in enumerate(suggestions):
            if suggestion.strip().lower() == seed.strip().lower():
                continue
            rows.append({
                "signal_source": "google_autocomplete", "keyword": suggestion[:512],
                "metric": float(len(suggestions) - rank), "extra": {"seed": seed},
                "fetched_at": now,
            })
    return rows


def _hours_since_last_apify_run() -> float | None:
    """None se non è mai girata; altrimenti ore trascorse dall'ultimo segnale Apify a pagamento."""
    session = SessionLocal()
    try:
        stmt = (
            select(Signal.fetched_at)
            .where(Signal.signal_source.in_(_APIFY_PAID_SIGNAL_SOURCES))
            .order_by(Signal.fetched_at.desc())
            .limit(1)
        )
        last = session.execute(stmt).scalar()
    finally:
        session.close()
    if last is None:
        return None
    return (datetime.now(timezone.utc) - last).total_seconds() / 3600.0


def run_interest_ingest() -> dict:
    """Esegue l'ingest di tutte le fonti di Parte 2 (Apify + Wikipedia).

    Wikipedia/Autocomplete sono gratuite e girano sempre. Le fonti Apify a pagamento
    girano al più ogni APIFY_MIN_INTERVAL_HOURS per contenere i costi (vedi commento
    sulla costante) — indipendentemente da quante volte questa funzione viene chiamata.
    Reddit e X sono escluse dal ciclo automatico (le più costose/meno affidabili per
    il segnale che danno); restano disponibili come funzioni per un uso manuale futuro.
    """
    session = SessionLocal()
    run = InterestRun()
    session.add(run)
    session.commit()

    seeds = _get_seed_keywords()
    tasks = [("google_autocomplete", lambda: _ingest_google_autocomplete(seeds))]

    sources_ok, sources_failed, total = [], [], 0

    if not APIFY_TOKEN:
        sources_failed.append("Apify (tutte le fonti) — APIFY_TOKEN non configurato")
    else:
        hours_since = _hours_since_last_apify_run()
        if hours_since is not None and hours_since < APIFY_MIN_INTERVAL_HOURS:
            logger.info(
                "Fonti Apify saltate per contenere i costi: ultima run %.1fh fa (minimo %dh).",
                hours_since, APIFY_MIN_INTERVAL_HOURS,
            )
            sources_failed.append(
                f"Apify (tutte le fonti) — saltate per controllo costi, prossima tra "
                f"{APIFY_MIN_INTERVAL_HOURS - hours_since:.1f}h"
            )
        else:
            cfg = load_sources()["interests"]["apify"]["actors"]
            tasks += [
                ("google_trends_daily", lambda: _ingest_google_trends_daily(cfg["google_trends"])),
                ("google_serp", lambda: _ingest_google_serp(cfg["google_serp"], seeds[:SERP_SEED_COUNT])),
                ("tiktok", lambda: _ingest_tiktok(cfg["tiktok_trending"], seeds[:TIKTOK_SEED_COUNT])),
                ("youtube", lambda: _ingest_youtube(cfg["youtube_trending"], seeds[:YOUTUBE_SEED_COUNT])),
            ]

    for name, task in tasks:
        logger.info("Avvio fonte interesse '%s'...", name)
        try:
            rows = task()
            _save_signals(rows)
            total += len(rows)
            sources_ok.append(f"{name} ({len(rows)} segnali)")
        except Exception as e:
            logger.warning("Fonte interesse '%s' fallita: %s", name, e)
            sources_failed.append(f"{name} — {e}")

    try:
        from src.ingest_wikipedia import run_wikipedia_ingest
        wiki_summary = run_wikipedia_ingest()
        total += wiki_summary["signals_ingested"]
        sources_ok += wiki_summary["sources_ok"]
        sources_failed += wiki_summary["sources_failed"]
    except Exception as e:
        logger.warning("Fonte interesse 'wikipedia' fallita: %s", e)
        sources_failed.append(f"wikipedia — {e}")

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
