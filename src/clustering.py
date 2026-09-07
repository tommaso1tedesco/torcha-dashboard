"""Clustering TF-IDF + cosine similarity degli articoli sulla stessa storia, e Heat score v0.

Nota: questa è la versione "semplice" prevista per la Fase 1. Il vero calcolo di
velocità (tasso di crescita rispetto alla baseline storica in Postgres) arriva in Fase 5:
qui l'heat score è un proxy basato su numero di fonti, numero di articoli e recency.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from src.models import Article

# Stopword italiane essenziali: evitiamo una dipendenza extra (nltk) per una lista
# ridotta usata solo a supporto del TF-IDF sui titoli.
ITALIAN_STOPWORDS = [
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "a", "da", "in", "con",
    "su", "per", "tra", "fra", "e", "è", "che", "chi", "cui", "non", "si", "come", "più",
    "anche", "ma", "o", "se", "al", "allo", "alla", "ai", "agli", "alle", "del", "dello",
    "della", "dei", "degli", "delle", "nel", "nello", "nella", "nei", "negli", "nelle",
    "sul", "sullo", "sulla", "sui", "sugli", "sulle", "questo", "questa", "questi", "queste",
    "quello", "quella", "quelli", "quelle", "suo", "sua", "suoi", "sue", "loro",
]

SIMILARITY_THRESHOLD = 0.35
RECENCY_HALF_LIFE_HOURS = 12.0


@dataclass
class Cluster:
    representative_title: str
    articles: list[Article]
    sources: list[str] = field(default_factory=list)
    latest_published_at: datetime | None = None
    heat_score: float = 0.0

    @property
    def article_count(self) -> int:
        return len(self.articles)

    @property
    def source_count(self) -> int:
        return len(set(self.sources))


def _connected_components(similarity: np.ndarray, threshold: float) -> list[list[int]]:
    n = similarity.shape[0]
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if similarity[i, j] >= threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for idx in range(n):
        root = find(idx)
        groups.setdefault(root, []).append(idx)
    return list(groups.values())


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
    vectorizer = TfidfVectorizer(stop_words=ITALIAN_STOPWORDS, min_df=1)
    tfidf = vectorizer.fit_transform(titles)
    similarity = cosine_similarity(tfidf)

    groups = _connected_components(similarity, SIMILARITY_THRESHOLD)

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
