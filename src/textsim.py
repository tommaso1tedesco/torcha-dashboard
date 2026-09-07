"""Raggruppamento di testi brevi per similarità (TF-IDF + cosine), condiviso da
clustering.py (Parte 1, titoli di articoli) e rising.py (Parte 2, keyword/topic)."""
from __future__ import annotations

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Stopword italiane essenziali: evitiamo una dipendenza extra (nltk) per una lista
# ridotta usata solo a supporto del TF-IDF.
ITALIAN_STOPWORDS = [
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "a", "da", "in", "con",
    "su", "per", "tra", "fra", "e", "è", "che", "chi", "cui", "non", "si", "come", "più",
    "anche", "ma", "o", "se", "al", "allo", "alla", "ai", "agli", "alle", "del", "dello",
    "della", "dei", "degli", "delle", "nel", "nello", "nella", "nei", "negli", "nelle",
    "sul", "sullo", "sulla", "sui", "sugli", "sulle", "questo", "questa", "questi", "queste",
    "quello", "quella", "quelli", "quelle", "suo", "sua", "suoi", "sue", "loro",
]


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


def group_by_similarity(texts: list[str], threshold: float) -> list[list[int]]:
    """Ritorna gruppi di indici di `texts` che si somigliano (cosine similarity >= threshold)."""
    n = len(texts)
    if n == 0:
        return []
    if n == 1:
        return [[0]]

    vectorizer = TfidfVectorizer(stop_words=ITALIAN_STOPWORDS, min_df=1)
    tfidf = vectorizer.fit_transform(texts)
    similarity = cosine_similarity(tfidf)
    return _connected_components(similarity, threshold)
