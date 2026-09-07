"""Rising score v0: raggruppa i Signal (Parte 2) per somiglianza di keyword e calcola un punteggio.

Come l'Heat score v0 (src/clustering.py), questa è la versione semplice prevista
per la Fase 3: stesso clustering per similarità testuale (TF-IDF + cosine, non
match esatto — keyword equivalenti da fonti diverse raramente sono identiche
carattere per carattere), punteggio basato su intensità cross-source + recency.
Il vero calcolo di velocità rispetto a una baseline storica arriva in Fase 5.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.models import Signal
from src.textsim import group_by_similarity

SIMILARITY_THRESHOLD = 0.35
RECENCY_HALF_LIFE_HOURS = 12.0


@dataclass
class Theme:
    keyword: str
    signals: list[Signal] = field(default_factory=list)
    rising_score: float = 0.0

    @property
    def sources(self) -> list[str]:
        return sorted(set(s.signal_source for s in self.signals))

    @property
    def latest_fetched_at(self) -> datetime:
        return max(s.fetched_at for s in self.signals)


def _normalized_metrics(signals: list[Signal]) -> dict[int, float]:
    by_source: dict[str, list[Signal]] = defaultdict(list)
    for s in signals:
        by_source[s.signal_source].append(s)

    normalized: dict[int, float] = {}
    for group in by_source.values():
        values = [s.metric for s in group]
        lo, hi = min(values), max(values)
        span = (hi - lo) or 1.0
        for s in group:
            normalized[s.id] = (s.metric - lo) / span
    return normalized


def compute_rising_themes(signals: list[Signal]) -> list[Theme]:
    if not signals:
        return []

    normalized = _normalized_metrics(signals)
    keywords = [s.keyword for s in signals]
    groups = group_by_similarity(keywords, SIMILARITY_THRESHOLD)

    now = datetime.now(timezone.utc)
    themes = []
    for group_idx in groups:
        group_signals = [signals[i] for i in group_idx]
        source_count = len(set(s.signal_source for s in group_signals))
        intensity = sum(normalized[s.id] for s in group_signals)

        latest = max(s.fetched_at for s in group_signals)
        hours_since = max((now - latest).total_seconds() / 3600.0, 0.0)
        recency_weight = 0.5 ** (hours_since / RECENCY_HALF_LIFE_HOURS)

        score = round((source_count * 2 + intensity) * recency_weight, 3)
        representative = max(group_signals, key=lambda s: len(s.keyword)).keyword
        themes.append(Theme(keyword=representative, signals=group_signals, rising_score=score))

    themes.sort(key=lambda t: t.rising_score, reverse=True)
    return themes
