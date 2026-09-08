"""Componenti UI condivisi tra le pagine: CSS e helper per renderizzare le card.

Streamlit da solo (st.metric, st.columns) rende poco leggibile una lista di
"storie in classifica": qui costruiamo card HTML (via st.markdown unsafe) con
badge colorati per intensità e per fonte, ispirate a prodotti come Google
Trends / Product Hunt / Hacker News (rank numerato + badge + meta compatta).
"""
from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

# Tutti i timestamp sono salvati in UTC (best practice per il DB); a schermo si
# mostrano sempre convertiti al fuso italiano, con il cambio ora legale/solare
# gestito automaticamente da zoneinfo (nessuna dipendenza esterna).
ITALY_TZ = ZoneInfo("Europe/Rome")


def format_local(dt: datetime, fmt: str = "%d/%m %H:%M") -> str:
    return dt.astimezone(ITALY_TZ).strftime(fmt)


# Etichette leggibili per le fonti di Parte 2: i nomi tecnici (es. "google_trends_daily")
# non devono mai arrivare a schermo così come sono.
SOURCE_LABELS: dict[str, tuple[str, str]] = {
    "google_trends_daily": ("🔍", "Google Trends"),
    "google_serp": ("🔎", "Ricerche Google"),
    "tiktok": ("🎵", "TikTok"),
    "youtube": ("▶️", "YouTube"),
    "x": ("🐦", "X"),
    "reddit": ("👽", "Reddit"),
    "wikipedia_top_daily": ("📖", "Wikipedia"),
    "wikipedia_trend": ("📖", "Wikipedia"),
    "google_autocomplete": ("💬", "Ricerche correlate"),
}


def inject_base_css() -> None:
    st.markdown(
        """
        <style>
        .tc-toprow { display: flex; gap: 10px; flex-wrap: wrap; margin: 4px 0 22px; }
        .tc-stat {
            background: var(--tc-surface, #f8fafc); border: 1px solid var(--tc-border, #e5e7eb);
            border-radius: 10px; padding: 8px 14px; font-size: 13px; color: var(--tc-muted, #475569);
        }
        .tc-stat b { color: var(--tc-text, #0f172a); font-size: 14px; }

        .tc-card {
            display: flex; gap: 14px; align-items: flex-start;
            background: var(--tc-surface, #ffffff); border: 1px solid var(--tc-border, #e5e7eb);
            border-radius: 12px; padding: 14px 18px; margin-bottom: 10px;
        }
        .tc-rank { font-size: 20px; font-weight: 800; min-width: 30px; color: var(--tc-rank, #cbd5e1); line-height: 1.4; }
        .tc-rank.t1 { color: #ef4444; }
        .tc-rank.t2 { color: #f97316; }
        .tc-body { flex: 1; min-width: 0; }
        .tc-title { font-size: 16px; font-weight: 700; color: var(--tc-text, #0f172a); margin: 0 0 8px; line-height: 1.35; }
        .tc-title a { color: inherit; text-decoration: none; }
        .tc-title a:hover { text-decoration: underline; }
        .tc-meta { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; font-size: 12.5px; color: var(--tc-muted, #64748b); }

        .tc-badge { display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 12px; font-weight: 700; white-space: nowrap; }
        .tc-badge.hot { background: #fee2e2; color: #b91c1c; }
        .tc-badge.warm { background: #ffedd5; color: #c2410c; }
        .tc-badge.mild { background: #f1f5f9; color: #475569; }
        .tc-badge.rising { background: #dcfce7; color: #15803d; }
        .tc-src { background: var(--tc-chip, #f1f5f9); color: var(--tc-chip-text, #334155); padding: 2px 8px; border-radius: 6px; font-size: 12px; }
        .tc-time { color: var(--tc-muted, #94a3b8); }

        @media (prefers-color-scheme: dark) {
            .tc-card, .tc-stat { background: #1e293b; border-color: #334155; }
            .tc-title, .tc-stat b { color: #f1f5f9; }
            .tc-meta, .tc-stat, .tc-time { color: #94a3b8; }
            .tc-src { background: #334155; color: #cbd5e1; }
            .tc-badge.mild { background: #334155; color: #cbd5e1; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def top_stats(stats: list[tuple[str, str]]) -> None:
    """Riga di chip di orientamento in cima alla pagina, es. [("Storie", "42"), ...]."""
    chips = "".join(f'<div class="tc-stat"><b>{value}</b> {label}</div>' for label, value in stats)
    st.markdown(f'<div class="tc-toprow">{chips}</div>', unsafe_allow_html=True)


def _score_tier(rank: int) -> str:
    if rank <= 3:
        return "hot"
    if rank <= 10:
        return "warm"
    return "mild"


def source_badges_html(source_keys: list[str]) -> str:
    seen: dict[str, str] = {}
    for key in source_keys:
        icon, label = SOURCE_LABELS.get(key, ("📡", key))
        seen[html.escape(label)] = icon
    return "".join(f'<span class="tc-src">{icon} {label}</span>' for label, icon in seen.items())


def render_heat_card(rank: int, title: str, url: str | None, score: float, source_count: int,
                      sources: list[str], time_label: str, is_rising: bool) -> None:
    # HTML costruito su una riga sola e senza indentazione: st.markdown fa prima passare il
    # contenuto per un parser Markdown, che tratta le righe rientrate come blocchi di codice
    # e le mostra come testo grezzo invece di renderizzarle (scoperto dal vivo).
    tier = _score_tier(rank)
    rank_class = "t1" if rank <= 3 else ("t2" if rank <= 10 else "")
    title_safe = html.escape(title)
    title_html = f'<a href="{html.escape(url)}" target="_blank">{title_safe}</a>' if url else title_safe
    rising_badge = ' <span class="tc-badge rising">🔺 in crescita</span>' if is_rising else ""
    src_html = "".join(f'<span class="tc-src">📰 {html.escape(s)}</span>' for s in sorted(set(sources))[:6])

    parts = [
        '<div class="tc-card">',
        f'<div class="tc-rank {rank_class}">{rank}</div>',
        '<div class="tc-body">',
        f'<p class="tc-title">{title_html}</p>',
        '<div class="tc-meta">',
        f'<span class="tc-badge {tier}">🔥 {score:g}</span>',
        f'<span class="tc-src">📡 {source_count} font{"e" if source_count == 1 else "i"}</span>',
        f'<span class="tc-time">🕒 {time_label}</span>',
        rising_badge,
        '</div>',
        f'<div class="tc-meta" style="margin-top:6px">{src_html}</div>',
        '</div>',
        '</div>',
    ]
    st.markdown("".join(parts), unsafe_allow_html=True)


def render_rising_card(rank: int, keyword: str, score: float, source_keys: list[str], is_new: bool) -> None:
    tier = _score_tier(rank)
    rank_class = "t1" if rank <= 3 else ("t2" if rank <= 10 else "")
    new_badge = ' <span class="tc-badge rising">🔺 nuovo</span>' if is_new else ""
    src_html = source_badges_html(source_keys)

    parts = [
        '<div class="tc-card">',
        f'<div class="tc-rank {rank_class}">{rank}</div>',
        '<div class="tc-body">',
        f'<p class="tc-title">{html.escape(keyword)}</p>',
        '<div class="tc-meta">',
        f'<span class="tc-badge {tier}">📈 {score:g}</span>',
        new_badge,
        '</div>',
        f'<div class="tc-meta" style="margin-top:6px">{src_html}</div>',
        '</div>',
        '</div>',
    ]
    st.markdown("".join(parts), unsafe_allow_html=True)


def render_timeline_row(time_label: str, title: str, url: str, source: str) -> None:
    parts = [
        '<div class="tc-card" style="padding:10px 16px;">',
        '<div class="tc-body" style="display:flex; align-items:center; gap:10px; flex-wrap:wrap;">',
        f'<span class="tc-time">🕒 {time_label}</span>',
        f'<a href="{html.escape(url)}" target="_blank" style="font-weight:600; color:var(--tc-text,#0f172a); text-decoration:none;">{html.escape(title)}</a>',
        f'<span class="tc-src">📰 {html.escape(source)}</span>',
        '</div>',
        '</div>',
    ]
    st.markdown("".join(parts), unsafe_allow_html=True)
