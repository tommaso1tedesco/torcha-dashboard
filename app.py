"""Entry point della dashboard: sidebar (Aggiorna + stato fonti) e pagina Notizie."""
from __future__ import annotations

import logging

import streamlit as st
from sqlalchemy import select
from streamlit_autorefresh import st_autorefresh

from src.db import SessionLocal
from src.ingest_rss import run_ingest
from src.init_db import init_db
from src.models import Run
from src.ui import format_local, inject_base_css
from ui_pages.notizie import render

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

st.set_page_config(page_title="Torcha", page_icon="🔥", layout="wide")
init_db()
inject_base_css()

# La pagina non si aggiorna da sola: senza questo, chi la lascia aperta vede dati
# vecchi anche se il worker in background ha già ingerito notizie più recenti.
# Rilegge solo il DB (nessuna nuova chiamata RSS) ogni 5 minuti.
st_autorefresh(interval=5 * 60 * 1000, key="autorefresh")


def get_last_run() -> Run | None:
    session = SessionLocal()
    try:
        stmt = select(Run).order_by(Run.started_at.desc()).limit(1)
        return session.execute(stmt).scalars().first()
    finally:
        session.close()


with st.sidebar:
    st.markdown("### 🔥 Torcha")
    if st.button("🔄 Aggiorna", type="primary", use_container_width=True):
        with st.spinner("Notizie in corso..."):
            summary = run_ingest()
        st.success(
            f"Notizie: +{summary['articles_ingested']} articoli "
            f"({len(summary['sources_ok'])} fonti OK, {len(summary['sources_failed'])} fallite)"
        )

    last_run = get_last_run()
    st.caption("Ultimo aggiornamento: " + (format_local(last_run.started_at) if last_run else "mai"))

    with st.expander("Stato fonti"):
        if last_run is None:
            st.caption("Nessun ingest ancora eseguito.")
        else:
            st.caption(f"✅ {len(last_run.sources_ok)} OK · ⚠️ {len(last_run.sources_failed)} fallite")
            for s in last_run.sources_failed:
                st.caption(f"⚠️ {s}")

render()
