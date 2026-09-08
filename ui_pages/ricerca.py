"""Pagina 'Cosa cerca la gente': temi in salita per Rising score (Parte 2)."""
from __future__ import annotations

import streamlit as st

from src.config import DASHBOARD_WINDOW_HOURS
from src.queries import get_recent_signals
from src.rising import compute_rising_themes
from src.ui import render_rising_card, top_stats
from src.velocity import get_velocity_multipliers, lookup_velocity


def render() -> None:
    st.title("📈 Cosa cerca la gente")
    st.caption(
        "Temi in salita nella domanda di ricerca online — Google Trends, ricerche correlate, "
        "TikTok, YouTube e Wikipedia, ordinati per Rising score."
    )

    signals = get_recent_signals(DASHBOARD_WINDOW_HOURS)
    if not signals:
        st.info(
            "Nessun segnale di interesse nelle ultime ore. Premi 'Aggiorna' nella barra laterale "
            "per raccoglierli — Wikipedia e le ricerche correlate sono sempre attive; Google Trends, "
            "TikTok e YouTube girano al più ogni 12h per contenere i costi."
        )
        return

    themes = compute_rising_themes(signals)
    rising_multipliers = get_velocity_multipliers("rising")
    for t in themes:
        mult, is_new = lookup_velocity(rising_multipliers, t.keyword)
        t.rising_score = round(t.rising_score * mult, 3)
        t.is_new = is_new
    themes.sort(key=lambda t: t.rising_score, reverse=True)

    top_stats([
        ("temi", str(len(themes))),
        ("segnali", str(len(signals))),
        ("finestra", f"{DASHBOARD_WINDOW_HOURS}h"),
    ])

    for rank, t in enumerate(themes[:30], start=1):
        render_rising_card(
            rank=rank,
            keyword=t.keyword,
            score=t.rising_score,
            source_keys=[s.signal_source for s in t.signals],
            is_new=t.is_new,
        )
