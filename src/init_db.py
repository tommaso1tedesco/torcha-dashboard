"""Crea le tabelle se non esistono (idempotente).

Fase 1: schema semplice, create_all basta. Se in fasi successive lo schema
inizia a evolvere in produzione con dati da preservare, introdurremo Alembic
per le migrazioni versionate.
"""
from src.db import engine
from src.models import Base


def init_db() -> None:
    Base.metadata.create_all(engine)


if __name__ == "__main__":
    init_db()
    print("Schema DB creato/verificato.")
