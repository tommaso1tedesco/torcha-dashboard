"""Dashboard Streamlit: notizie calde per categoria, clusterizzate per Heat score."""
from __future__ import annotations

import logging

import streamlit as st
from sqlalchemy import select

from src.clustering import cluster_articles
from src.config import ACTIVE_CATEGORIES, DASHBOARD_WINDOW_HOURS, load_sources
from src.db import SessionLocal
from src.ingest_interests import run_interest_ingest
from src.ingest_rss import run_ingest
from src.init_db import init_db
from src.models import InterestRun, Run
from src.queries import get_recent_articles, get_recent_signals
from src.rising import compute_rising_themes
from src.velocity import get_velocity_multipliers, lookup_velocity

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(page_title="Torcha — Notizie calde", layout="wide")
init_db()

_CATEGORIES_CFG = load_sources()["categories"]
CATEGORY_LABELS = {key: cat["label"] for key, cat in _CATEGORIES_CFG.items()}
VIEW_ONLY_CATEGORIES = {key for key, cat in _CATEGORIES_CFG.items() if cat.get("view_only")}


def get_last_run() -> Run | None:
    session = SessionLocal()
    try:
        stmt = select(Run).order_by(Run.started_at.desc()).limit(1)
        return session.execute(stmt).scalars().first()
    finally:
        session.close()


def get_last_interest_run() -> InterestRun | None:
    session = SessionLocal()
    try:
        stmt = select(InterestRun).order_by(InterestRun.started_at.desc()).limit(1)
        return session.execute(stmt).scalars().first()
    finally:
        session.close()


st.title("🔥 Torcha — Notizie calde")
st.caption("Cosa sta scoppiando adesso, per categoria, ordinato per Heat score.")

col_refresh, col_spacer = st.columns([1, 5])
with col_refresh:
    if st.button("🔄 Aggiorna", type="primary"):
        with st.spinner("Ingest notizie (Parte 1) in corso..."):
            summary = run_ingest()
        with st.spinner("Ingest segnali di interesse (Parte 2) in corso..."):
            interest_summary = run_interest_ingest()
        st.success(
            f"Notizie: {summary['articles_ingested']} nuovi articoli, "
            f"{len(summary['sources_ok'])} fonti OK, {len(summary['sources_failed'])} fonti fallite. — "
            f"Interesse: {interest_summary['signals_ingested']} nuovi segnali, "
            f"{len(interest_summary['sources_ok'])} fonti OK, {len(interest_summary['sources_failed'])} fonti fallite."
        )

last_run = get_last_run()
last_interest_run = get_last_interest_run()
with st.expander("Stato fonti (ultimo aggiornamento)", expanded=False):
    st.markdown("#### Notizie (Parte 1)")
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

    st.markdown("#### Interesse / domanda di ricerca (Parte 2)")
    if last_interest_run is None:
        st.info("Nessun ingest ancora eseguito.")
    else:
        st.write(f"Ultimo run: {last_interest_run.started_at.strftime('%d/%m/%Y %H:%M UTC')}")
        c3, c4 = st.columns(2)
        with c3:
            st.markdown(f"**✅ Fonti OK ({len(last_interest_run.sources_ok)})**")
            for s in last_interest_run.sources_ok:
                st.write(f"- {s}")
        with c4:
            st.markdown(f"**⚠️ Fonti fallite ({len(last_interest_run.sources_failed)})**")
            for s in last_interest_run.sources_failed:
                st.write(f"- {s}")

st.divider()
st.header("🔎 Cosa cerca la gente")
st.caption("Temi in salita per Rising score, con la fonte del segnale e le keyword correlate.")
signals = get_recent_signals(DASHBOARD_WINDOW_HOURS)
if not signals:
    st.info("Nessun segnale di interesse nelle ultime ore. Premi 'Aggiorna' per raccoglierli (Wikipedia non richiede token; Google Trends/SERP/social richiedono APIFY_TOKEN).")
else:
    themes = compute_rising_themes(signals)
    rising_multipliers = get_velocity_multipliers("rising")
    for t in themes:
        mult, is_new = lookup_velocity(rising_multipliers, t.keyword)
        t.rising_score = round(t.rising_score * mult, 3)
        t.is_new = is_new
    themes.sort(key=lambda t: t.rising_score, reverse=True)

    for t in themes[:20]:
        cols = st.columns([1, 1, 3])
        cols[0].metric("Rising score", t.rising_score)
        cols[1].write(f"📡 {', '.join(t.sources)}")
        cols[2].markdown(f"**{t.keyword}**{' ^' if t.is_new else ''}")
    st.divider()

tabs = st.tabs([CATEGORY_LABELS.get(cat, cat) for cat in ACTIVE_CATEGORIES])

for tab, category in zip(tabs, ACTIVE_CATEGORIES):
    with tab:
        articles = get_recent_articles(category, DASHBOARD_WINDOW_HOURS)
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
        heat_multipliers = get_velocity_multipliers("heat", category=category)
        for c in clusters:
            mult, is_new = lookup_velocity(heat_multipliers, c.representative_title)
            c.heat_score = round(c.heat_score * mult, 3)
            c.is_new, c.velocity = is_new, mult
        clusters.sort(key=lambda c: c.heat_score, reverse=True)

        st.caption(f"{len(articles)} articoli → {len(clusters)} storie, ultime {DASHBOARD_WINDOW_HOURS}h")

        for c in clusters:
            # "^" = storia nuova (nessuno storico) o in accelerazione reale vs la sua baseline
            velocity_flag = " ^" if (c.is_new or c.velocity > 1.2) else ""

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
