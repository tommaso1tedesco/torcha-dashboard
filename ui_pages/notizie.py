"""Pagina 'Notizie': una scheda per categoria, classifica per Heat score."""
from __future__ import annotations

import streamlit as st

from src.clustering import cluster_articles
from src.config import ACTIVE_CATEGORIES, DASHBOARD_WINDOW_HOURS, load_sources
from src.queries import get_recent_articles
from src.ui import format_local, render_heat_card, render_timeline_row, top_stats
from src.velocity import get_velocity_multipliers, lookup_velocity

_CATEGORIES_CFG = load_sources()["categories"]
CATEGORY_LABELS = {key: cat["label"] for key, cat in _CATEGORIES_CFG.items()}
VIEW_ONLY_CATEGORIES = {key for key, cat in _CATEGORIES_CFG.items() if cat.get("view_only")}

# Senza un tetto, categorie con fonti molto prolifiche (es. Bloomberg, ~75 notizie/giorno
# di nicchia finanziaria in inglese, quasi tutte a fonte singola) affogano le storie
# davvero cross-fonte in centinaia di card a bassa Heat score. Il tetto non nasconde
# dati (restano tutti in "Tutti gli articoli"/DB), solo la lista mostrata in pagina —
# coerente con il tetto già usato in "Interessi".
MAX_STORIES_SHOWN = 40


def render() -> None:
    st.title("🔥 Notizie")
    st.caption(
        "Cosa sta scoppiando adesso, per categoria — ordinato per Heat score "
        "(quante fonti ne parlano, quanto è recente, quanto sta accelerando rispetto al solito)."
    )

    tabs = st.tabs([CATEGORY_LABELS.get(cat, cat) for cat in ACTIVE_CATEGORIES])

    for tab, category in zip(tabs, ACTIVE_CATEGORIES):
        with tab:
            _render_category(category)


def _render_category(category: str) -> None:
    articles = get_recent_articles(category, DASHBOARD_WINDOW_HOURS)
    if not articles:
        st.info("Nessun articolo nelle ultime ore. Premi 'Aggiorna' nella barra laterale per raccogliere dati.")
        return

    if category in VIEW_ONLY_CATEGORIES:
        top_stats([("articoli", str(len(articles))), ("finestra", f"{DASHBOARD_WINDOW_HOURS}h")])
        for a in articles[:MAX_STORIES_SHOWN]:
            render_timeline_row(format_local(a.published_at), a.title, a.url, a.source)
        if len(articles) > MAX_STORIES_SHOWN:
            st.caption(f"Mostrati i {MAX_STORIES_SHOWN} più recenti su {len(articles)}.")
        return

    clusters = cluster_articles(articles)
    heat_multipliers = get_velocity_multipliers("heat", category=category)
    for c in clusters:
        mult, is_new = lookup_velocity(heat_multipliers, c.representative_title)
        c.heat_score = round(c.heat_score * mult, 3)
        c.is_new, c.velocity = is_new, mult
    clusters.sort(key=lambda c: c.heat_score, reverse=True)

    top_stats([
        ("storie", str(len(clusters))),
        ("articoli", str(len(articles))),
        ("finestra", f"{DASHBOARD_WINDOW_HOURS}h"),
    ])
    if len(clusters) > MAX_STORIES_SHOWN:
        st.caption(
            f"Mostrate le {MAX_STORIES_SHOWN} storie più calde su {len(clusters)} — "
            "le altre hanno una sola fonte e Heat score basso."
        )

    for rank, c in enumerate(clusters[:MAX_STORIES_SHOWN], start=1):
        is_rising = c.is_new or c.velocity > 1.2
        top_article = c.articles[0]
        render_heat_card(
            rank=rank,
            title=c.representative_title,
            url=top_article.url,
            score=c.heat_score,
            source_count=c.source_count,
            sources=c.sources,
            time_label=format_local(c.latest_published_at),
            is_rising=is_rising,
        )
        if c.article_count > 1:
            with st.expander(f"Tutti gli articoli di questa storia ({c.article_count})"):
                for a in c.articles:
                    st.write(f"- [{a.title}]({a.url}) — *{a.source}*, {format_local(a.published_at)}")
