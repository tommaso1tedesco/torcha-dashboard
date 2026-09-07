"""Wrapper minimo sopra apify-client: esegue un Actor e ritorna gli item del dataset.

Ogni chiamata è sincrona (run-and-wait) con timeout: se un Actor è lento o fallisce,
il chiamante deve gestire l'eccezione e continuare con gli altri (degradazione elegante,
stesso pattern di src/ingest_rss.py). `timeout_secs` limita solo il tempo di esecuzione
dell'Actor sulla piattaforma Apify, non il tempo di attesa lato client: per non rischiare
che una singola fonte blocchi l'intero ingest (vedi src/http.py per un caso analogo
capitato dal vivo con l'RSS), l'intera chiamata gira con un timeout "hard" lato client.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

from apify_client import ApifyClient

from src.config import APIFY_TOKEN

logger = logging.getLogger("apify_client")

RUN_TIMEOUT_SECONDS = 120
CLIENT_HARD_TIMEOUT_SECONDS = RUN_TIMEOUT_SECONDS + 30


def _call_actor(actor_id: str, run_input: dict, max_items: int | None) -> list[dict]:
    client = ApifyClient(APIFY_TOKEN)
    run = client.actor(actor_id).call(run_input=run_input, timeout_secs=RUN_TIMEOUT_SECONDS)
    if run is None:
        raise RuntimeError(f"Actor {actor_id}: nessun run restituito (timeout?)")

    status = run.get("status")
    if status != "SUCCEEDED":
        raise RuntimeError(f"Actor {actor_id}: run terminato con status {status}")

    dataset_id = run["defaultDatasetId"]
    kwargs = {}
    if max_items is not None:
        kwargs["limit"] = max_items
    return list(client.dataset(dataset_id).iterate_items(**kwargs))


def run_actor(actor_id: str, run_input: dict, max_items: int | None = None) -> list[dict]:
    """Lancia `actor_id` con `run_input`, aspetta il completamento, ritorna gli item del dataset.

    Alza eccezione se APIFY_TOKEN non è configurato, se l'Actor fallisce o va in timeout
    (lato piattaforma o lato client): il chiamante è responsabile di catturarla per la
    degradazione elegante.
    """
    if not APIFY_TOKEN:
        raise RuntimeError("APIFY_TOKEN non configurato")

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(_call_actor, actor_id, run_input, max_items).result(timeout=CLIENT_HARD_TIMEOUT_SECONDS)
    except FutureTimeoutError as e:
        raise TimeoutError(f"Actor {actor_id}: timeout lato client dopo {CLIENT_HARD_TIMEOUT_SECONDS}s") from e
    finally:
        pool.shutdown(wait=False)
