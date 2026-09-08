"""Entry point della dashboard: sidebar condivisa (Aggiorna + stato fonti) + due pagine."""
from __future__ import annotations

import logging

import streamlit as st
from sqlalchemy import select
from streamlit_autorefresh import st_autorefresh

from src.db import SessionLocal
from src.ingest_interests import run_interest_ingest
from src.ingest_rss import run_ingest
from src.init_db import init_db
from src.models import InterestRun, Run
from src.ui import inject_base_css

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(page_title="Torcha", page_icon="🔥", layout="wide")
init_db()
inject_base_css()

# La pagina non si aggiorna da sola: senza questo, chi la lascia aperta vede dati
# vecchi anche se il worker in background ha già ingerito notizie più recenti.
# Rilegge solo il DB (nessuna nuova chiamata RSS/Apify) ogni 5 minuti.
st_autorefresh(interval=5 * 60 * 1000, key="autorefresh")


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


with st.sidebar:
    st.markdown("### 🔥 Torcha")
    if st.button("🔄 Aggiorna", type="primary", use_container_width=True):
        with st.spinner("Notizie in corso..."):
            summary = run_ingest()
        with st.spinner("Segnali di interesse in corso..."):
            interest_summary = run_interest_ingest()
        st.success(
            f"Notizie: +{summary['articles_ingested']} articoli "
            f"({len(summary['sources_ok'])} fonti OK, {len(summary['sources_failed'])} fallite)"
        )
        st.success(
            f"Interesse: +{interest_summary['signals_ingested']} segnali "
            f"({len(interest_summary['sources_ok'])} fonti OK, {len(interest_summary['sources_failed'])} fallite)"
        )

    last_run = get_last_run()
    last_interest_run = get_last_interest_run()

    st.caption(
        "Ultimo aggiornamento notizie: "
        + (last_run.started_at.strftime("%d/%m %H:%M UTC") if last_run else "mai")
    )
    st.caption(
        "Ultimo aggiornamento interesse: "
        + (last_interest_run.started_at.strftime("%d/%m %H:%M UTC") if last_interest_run else "mai")
    )

    with st.expander("Stato fonti"):
        st.markdown("**Notizie**")
        if last_run is None:
            st.caption("Nessun ingest ancora eseguito.")
        else:
            st.caption(f"✅ {len(last_run.sources_ok)} OK · ⚠️ {len(last_run.sources_failed)} fallite")
            for s in last_run.sources_failed:
                st.caption(f"⚠️ {s}")

        st.markdown("**Interesse**")
        if last_interest_run is None:
            st.caption("Nessun ingest ancora eseguito.")
        else:
            st.caption(f"✅ {len(last_interest_run.sources_ok)} OK · ⚠️ {len(last_interest_run.sources_failed)} fallite")
            for s in last_interest_run.sources_failed:
                st.caption(f"⚠️ {s}")


def _notizie_page() -> None:
    from ui_pages.notizie import render
    render()


def _ricerca_page() -> None:
    from ui_pages.ricerca import render
    render()


pages = [
    st.Page(_notizie_page, title="Notizie calde", icon="🔥", default=True),
    st.Page(_ricerca_page, title="Cosa cerca la gente", icon="📈"),
]
st.navigation(pages).run()
