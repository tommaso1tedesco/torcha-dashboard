"""GET con timeout "hard" lato client, condiviso da tutti i moduli che fanno urllib diretto.

Il parametro `timeout` di `urllib.request.urlopen` NON copre in modo affidabile un DNS
lookup che si blocca (limite noto di socket/urllib su alcune piattaforme): la richiesta
gira in un thread con un `.result(timeout=...)` che la abbandona comunque, anche se il
thread di sfondo resta bloccato. Scoperto dal vivo: un ingest RSS è rimasto bloccato per
~10 minuti nonostante `timeout=15` su ogni singola `urlopen`.
"""
from __future__ import annotations

import urllib.request
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

DEFAULT_TIMEOUT_SECONDS = 15


def fetch_bytes(url: str, headers: dict | None = None, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> bytes:
    """Alza TimeoutError se non risponde entro `timeout` secondi, DNS incluso."""
    def _do_request() -> bytes:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(_do_request).result(timeout=timeout + 5)
    except FutureTimeoutError as e:
        raise TimeoutError(f"timeout dopo {timeout + 5}s: {url}") from e
    finally:
        pool.shutdown(wait=False)
