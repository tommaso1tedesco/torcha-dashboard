"""Modelli ORM: articles (dati raw), runs (storico ingestion) e topic_snapshots (baseline velocità)."""
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


class Article(Base):
    """Articolo normalizzato: titolo, fonte, categoria, url, timestamp, lingua.

    Univoco per (url, category) e non per url da sola: lo stesso articolo può
    comparire sia nella sua categoria tematica (es. Sky TG24 in "attualita") sia
    nella vista "ultima_ora" quando quest'ultima riusa lo stesso feed — altrimenti
    la seconda riga viene scartata in silenzio come falso duplicato (bug reale,
    scoperto dal vivo aggiungendo Sky TG24/Rai News a "Ultima ora").
    """

    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("url", "category", name="uq_articles_url_category"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(1024))
    source: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)
    url: Mapped[str] = mapped_column(String(2048))
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lang: Mapped[str] = mapped_column(String(8), default="it")
    first_seen_run_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class TopicSnapshot(Base):
    """Fase 5: uno scatto per tema/cluster ad ogni ciclo di ingest, usato come baseline
    storica per calcolare la vera velocità (tasso attuale vs media dei giorni precedenti).

    `topic_key` è il titolo rappresentativo del cluster (Heat, kind="heat"), normalizzato
    (lowercase, strip).
    Nota v0: il match nel tempo è per stringa esatta su `topic_key`, non per similarità
    come il clustering "live" — una stessa storia che cambia titolo tra un run e l'altro
    perde continuità storica. Limite noto, da eventualmente affinare in una fase successiva.
    """

    __tablename__ = "topic_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), index=True)              # "heat"
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)  # categoria del cluster
    topic_key: Mapped[str] = mapped_column(String(512), index=True)
    count: Mapped[int] = mapped_column(Integer, default=0)      # n. articoli/segnali nel cluster
    intensity: Mapped[float] = mapped_column(default=0.0)       # heat score v0 al momento dello scatto
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
