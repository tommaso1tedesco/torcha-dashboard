"""Dashboard Streamlit: notizie calde per categoria, clusterizzate per Heat score."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st
from sqlalchemy import select

from src.clustering import cluster_articles
from src.config import ACTIVE_CATEGORIES, DASHBOARD_WINDOW_HOURS, load_sources
from src.db import SessionLocal
from src.ingest_rss import run_ingest
from src.init_db import init_db
from src.models import Article, Run

st.set_page_config(page_title="Torcha — Notizie calde", layout="wide")
init_db()

_CATEGORIES_CFG = load_sources()["categories"]
CATEGORY_LABELS = {key: cat["label"] for key, cat in _CATEGORIES_CFG.items()}
VIEW_ONLY_CATEGORIES = {key for key, cat in _CATEGORIES_CFG.items() if cat.get("view_only")}

VELOCITY_FRESH_HOURS = 3.0  # proxy v0 per l'indicatore ^: sostituito dal vero calcolo di velocità in Fase 5


def get_articles(category: str, window_hours: int) -> list[Article]:
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    session = SessionLocal()
    try:
        stmt = (
            select(Article)
            .where(Article.category == category, Article.published_at >= since)
            .order_by(Article.published_at.desc())
        )
        return list(session.execute(stmt).scalars())
    finally:
        session.close()


def get_last_run() -> Run | None:
    session = SessionLocal()
    try:
        stmt = select(Run).order_by(Run.started_at.desc()).limit(1)
        return session.execute(stmt).scalars().first()
    finally:
        session.close()


st.title("🔥 Torcha — Notizie calde")
st.caption("Cosa sta scoppiando adesso, per categoria, ordinato per Heat score.")

col_refresh, col_spacer = st.columns([1, 5])
with col_refresh:
    if st.button("🔄 Aggiorna", type="primary"):
        with st.spinner("Ingest in corso..."):
            summary = run_ingest()
        st.success(
            f"Fatto: {summary['articles_ingested']} nuovi articoli, "
            f"{len(summary['sources_ok'])} fonti OK, {len(summary['sources_failed'])} fonti fallite."
        )

last_run = get_last_run()
with st.expander("Stato fonti (ultimo aggiornamento)", expanded=False):
    if last_run is None:
        st.info("Nessun ingest ancora eseguito. Premi 'Aggiorna' per il primo run.")
    else:
        st.write(f"Ultimo run: {last_run.started_at.strftime('%d/%m/%Y %H:%M UTC')}")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**✅ Fonti OK ({len(last_run.sources_ok)})**")
            for s in last_run.sources_ok:
                st.write(f"- {s}")
        with c2:
            st.markdown(f"**⚠️ Fonti fallite ({len(last_run.sources_failed)})**")
            for s in last_run.sources_failed:
                st.write(f"- {s}")

tabs = st.tabs([CATEGORY_LABELS.get(cat, cat) for cat in ACTIVE_CATEGORIES])

for tab, category in zip(tabs, ACTIVE_CATEGORIES):
    with tab:
        articles = get_articles(category, DASHBOARD_WINDOW_HOURS)
        if not articles:
            st.info("Nessun articolo nelle ultime ore. Premi 'Aggiorna' per raccogliere dati.")
            continue

        if category in VIEW_ONLY_CATEGORIES:
            # "Ultima ora" non è una categoria tematica: vista sulle generaliste ordinata per orario, senza clustering.
            st.caption(f"{len(articles)} articoli, ultime {DASHBOARD_WINDOW_HOURS}h — ordinati per orario")
            for a in articles:
                st.write(f"🕒 {a.published_at.strftime('%d/%m %H:%M UTC')} — [{a.title}]({a.url}) — *{a.source}*")
            continue

        clusters = cluster_articles(articles)
        st.caption(f"{len(articles)} articoli → {len(clusters)} storie, ultime {DASHBOARD_WINDOW_HOURS}h")

        for c in clusters:
            hours_since = (datetime.now(timezone.utc) - c.latest_published_at).total_seconds() / 3600.0
            velocity_flag = " ^" if hours_since <= VELOCITY_FRESH_HOURS else ""

            st.markdown(f"### {c.representative_title}{velocity_flag}")
            meta_cols = st.columns([1, 1, 2])
            meta_cols[0].metric("Heat score", c.heat_score)
            meta_cols[1].metric("Fonti", c.source_count)
            meta_cols[2].write(
                f"🕒 {c.latest_published_at.strftime('%d/%m %H:%M UTC')}  \n"
                f"📰 {', '.join(sorted(set(c.sources)))}"
            )
            with st.expander(f"Articoli nel cluster ({c.article_count})"):
                for a in c.articles:
                    st.write(f"- [{a.title}]({a.url}) — *{a.source}*, {a.published_at.strftime('%d/%m %H:%M UTC')}")
            st.divider()
