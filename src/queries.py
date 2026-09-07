"""Query di lettura condivise tra app.py (dashboard) e worker.py (snapshot Fase 5)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.db import SessionLocal
from src.models import Article, Signal


def get_recent_articles(category: str, window_hours: int) -> list[Article]:
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


def get_recent_signals(window_hours: int) -> list[Signal]:
    since = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    session = SessionLocal()
    try:
        stmt = select(Signal).where(Signal.fetched_at >= since)
        return list(session.execute(stmt).scalars())
    finally:
        session.close()
