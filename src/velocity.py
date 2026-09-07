"""Fase 5: velocità reale = intensità attuale di un tema rispetto alla sua baseline storica.

Ogni ciclo del worker registra uno TopicSnapshot per i cluster/temi correnti; qui
confrontiamo l'ultimo scatto con la media dei precedenti per ottenere un moltiplicatore
da applicare all'Heat/Rising score v0 (numero di fonti/intensità + recency).

Un tema senza storico (mai visto prima) è neutro (moltiplicatore 1.0): non lo
premiamo né lo penalizziamo finché non abbiamo almeno un paio di scatti precedenti.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.db import SessionLocal
from src.models import TopicSnapshot

BASELINE_LOOKBACK_DAYS = 7
MIN_SNAPSHOTS_FOR_BASELINE = 2
MIN_AGE_FOR_BASELINE_HOURS = 2.0  # esclude lo scatto "corrente" appena scritto
VELOCITY_MULTIPLIER_MIN = 0.5
VELOCITY_MULTIPLIER_MAX = 3.0


def _normalize_key(text: str) -> str:
    return text.strip().lower()


def record_snapshots(kind: str, items: list[tuple[str, int, float]], category: str | None = None) -> None:
    """Registra uno scatto per ogni (topic_key, count, intensity)."""
    if not items:
        return
    now = datetime.now(timezone.utc)
    rows = [
        {
            "kind": kind, "category": category, "topic_key": _normalize_key(key),
            "count": count, "intensity": intensity, "created_at": now,
        }
        for key, count, intensity in items
    ]
    session = SessionLocal()
    try:
        session.bulk_insert_mappings(TopicSnapshot, rows)
        session.commit()
    finally:
        session.close()


def get_velocity_multipliers(kind: str, category: str | None = None) -> dict[str, float]:
    """Ritorna {topic_key_normalizzato: moltiplicatore} per tutti i temi con baseline sufficiente."""
    since = datetime.now(timezone.utc) - timedelta(days=BASELINE_LOOKBACK_DAYS)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MIN_AGE_FOR_BASELINE_HOURS)

    session = SessionLocal()
    try:
        stmt = select(TopicSnapshot).where(
            TopicSnapshot.kind == kind,
            TopicSnapshot.created_at >= since,
        )
        if category is not None:
            stmt = stmt.where(TopicSnapshot.category == category)
        snapshots = list(session.execute(stmt).scalars())
    finally:
        session.close()

    by_topic: dict[str, list[TopicSnapshot]] = {}
    for s in snapshots:
        by_topic.setdefault(s.topic_key, []).append(s)

    multipliers: dict[str, float] = {}
    for topic_key, snaps in by_topic.items():
        snaps.sort(key=lambda s: s.created_at)
        latest = snaps[-1]
        baseline_snaps = [s for s in snaps[:-1] if s.created_at <= cutoff]
        if len(baseline_snaps) < MIN_SNAPSHOTS_FOR_BASELINE:
            continue
        baseline_avg = sum(s.count for s in baseline_snaps) / len(baseline_snaps)
        if baseline_avg <= 0:
            continue
        ratio = latest.count / baseline_avg
        multipliers[topic_key] = max(VELOCITY_MULTIPLIER_MIN, min(ratio, VELOCITY_MULTIPLIER_MAX))

    return multipliers


def lookup_velocity(multipliers: dict[str, float], topic_key: str) -> tuple[float, bool]:
    """Ritorna (moltiplicatore, ha_storico). Senza storico: neutro (1.0) ma "nuovo" (True)."""
    key = _normalize_key(topic_key)
    if key in multipliers:
        return multipliers[key], False
    return 1.0, True
