"""Wrapper minimo sopra apify-client: esegue un Actor e ritorna gli item del dataset.

Nota versione: pinnato a apify-client==3.2.0 (richiede Python >= 3.11, coerente con
il runtime usato in produzione). Le versioni 3.x hanno rinominato l'API di `call()`:
`timeout_secs` (int) è diventato `run_timeout` (timedelta, budget di esecuzione
dell'Actor) + `wait_duration` (timedelta, per quanto il client/server aspetta prima
di ritornare comunque) — scoperto dal vivo: con `timeout_secs` la chiamata falliva
all'istante con TypeError per TUTTE le fonti Apify, senza che ce ne accorgessimo nei
test locali perché lì era installata una versione 1.x (compatibile solo fino a
Python 3.10) con la vecchia firma.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from apify_client import ApifyClient

from src.config import APIFY_TOKEN

logger = logging.getLogger("apify_client")

RUN_TIMEOUT_SECONDS = 120       # budget di esecuzione dell'Actor sulla piattaforma Apify
WAIT_DURATION_SECONDS = RUN_TIMEOUT_SECONDS + 15  # quanto aspettiamo la risposta prima di rinunciare


def run_actor(actor_id: str, run_input: dict, max_items: int | None = None) -> list[dict]:
    """Lancia `actor_id` con `run_input`, aspetta il completamento, ritorna gli item del dataset.

    Alza eccezione se APIFY_TOKEN non è configurato, se l'Actor fallisce o va in timeout:
    il chiamante è responsabile di catturarla per la degradazione elegante.
    """
    if not APIFY_TOKEN:
        raise RuntimeError("APIFY_TOKEN non configurato")

    client = ApifyClient(APIFY_TOKEN)
    run = client.actor(actor_id).call(
        run_input=run_input,
        run_timeout=timedelta(seconds=RUN_TIMEOUT_SECONDS),
        wait_duration=timedelta(seconds=WAIT_DURATION_SECONDS),
        max_items=max_items,
    )
    if run is None:
        raise RuntimeError(f"Actor {actor_id}: nessun run restituito (timeout?)")

    # In 3.x .call() ritorna un modello Pydantic (attributi snake_case), non un dict.
    if run.status != "SUCCEEDED":
        raise RuntimeError(f"Actor {actor_id}: run terminato con status {run.status}")

    return list(client.dataset(run.default_dataset_id).iterate_items())
