"""Clustering TF-IDF + cosine similarity degli articoli sulla stessa storia, e Heat score v0.

Nota: questa è la versione "semplice" prevista per la Fase 1. Il vero calcolo di
velocità (tasso di crescita rispetto alla baseline storica in Postgres) arriva in Fase 5:
qui l'heat score è un proxy basato su numero di fonti, numero di articoli e recency.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.models import Article
from src.textsim import group_by_similarity

SIMILARITY_THRESHOLD = 0.35
RECENCY_HALF_LIFE_HOURS = 12.0


@dataclass
class Cluster:
    representative_title: str
    articles: list[Article]
    sources: list[str] = field(default_factory=list)
    latest_published_at: datetime | None = None
    heat_score: float = 0.0
    is_new: bool = False       # nessuno storico Fase 5 ancora disponibile per questo cluster
    velocity: float = 1.0      # moltiplicatore Fase 5 già applicato a heat_score (1.0 = neutro/nuovo)

    @property
    def article_count(self) -> int:
        return len(self.articles)

    @property
    def source_count(self) -> int:
        return len(set(self.sources))


def _heat_score(cluster_articles: list[Article]) -> float:
    now = datetime.now(timezone.utc)
    source_count = len(set(a.source for a in cluster_articles))
    article_count = len(cluster_articles)

    latest = max(a.published_at for a in cluster_articles)
    hours_since = max((now - latest).total_seconds() / 3600.0, 0.0)
    recency_weight = 0.5 ** (hours_since / RECENCY_HALF_LIFE_HOURS)

    # presenza cross-source pesa più del semplice conteggio articoli
    return round((source_count * 2 + article_count) * recency_weight, 3)


def cluster_articles(articles: list[Article]) -> list[Cluster]:
    """Raggruppa articoli sulla stessa storia (per titolo) e calcola l'Heat score v0."""
    if not articles:
        return []
    if len(articles) == 1:
        a = articles[0]
        return [Cluster(
            representative_title=a.title,
            articles=[a],
            sources=[a.source],
            latest_published_at=a.published_at,
            heat_score=_heat_score([a]),
        )]

    titles = [a.title for a in articles]
    groups = group_by_similarity(titles, SIMILARITY_THRESHOLD)

    clusters = []
    for group_idx in groups:
        group_articles = [articles[i] for i in group_idx]
        group_articles.sort(key=lambda a: a.published_at, reverse=True)
        representative = group_articles[0].title
        clusters.append(Cluster(
            representative_title=representative,
            articles=group_articles,
            sources=[a.source for a in group_articles],
            latest_published_at=group_articles[0].published_at,
            heat_score=_heat_score(group_articles),
        ))

    clusters.sort(key=lambda c: c.heat_score, reverse=True)
    return clusters
