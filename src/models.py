"""Modelli ORM: articles (dati raw) e runs (storico ingestion)."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Run(Base):
    """Un'esecuzione dell'ingest (lanciata dal worker cron o dal pulsante Aggiorna)."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sources_ok: Mapped[list] = mapped_column(JSON, default=list)      # nomi fonti che hanno risposto
    sources_failed: Mapped[list] = mapped_column(JSON, default=list)  # nomi fonti fallite
    articles_ingested: Mapped[int] = mapped_column(Integer, default=0)


class InterestRun(Base):
    """Un'esecuzione dell'ingest Apify (Parte 2). Tabella separata da Run per non
    dover alterare lo schema di una tabella già in produzione (niente Alembic)."""

    __tablename__ = "interest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    sources_ok: Mapped[list] = mapped_column(JSON, default=list)
    sources_failed: Mapped[list] = mapped_column(JSON, default=list)
    signals_ingested: Mapped[int] = mapped_column(Integer, default=0)


class Article(Base):
    """Articolo normalizzato: titolo, fonte, categoria, url, timestamp, lingua."""

    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("url", name="uq_articles_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(1024))
    source: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    url: Mapped[str] = mapped_column(String(2048))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lang: Mapped[str] = mapped_column(String(8), default="it")
    first_seen_run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class Signal(Base):
    """Segnale di domanda/interesse (Parte 2): una riga per keyword/topic per fonte.

    `metric` ha significato diverso per fonte (traffic value di Google Trends,
    n° tweet, upvote Reddit, ...): va normalizzato a livello di scoring, non qui.
    """

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_source: Mapped[str] = mapped_column(String(32), index=True)  # google_trends_daily/keyword, google_serp, tiktok, youtube, x, reddit
    keyword: Mapped[str] = mapped_column(String(512), index=True)
    metric: Mapped[float] = mapped_column(default=0.0)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
