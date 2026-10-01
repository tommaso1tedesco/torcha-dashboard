"""Engine e sessione SQLAlchemy."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config import DATABASE_URL

# Railway a volte espone l'URL come postgres:// (schema legacy non supportato da SQLAlchemy 2.x)
_url = DATABASE_URL
if _url.startswith("postgres://"):
    _url = _url.replace("postgres://", "postgresql://", 1)

# Driver esplicito: un "postgresql://" nudo lascia a SQLAlchemy la scelta del driver di
# default, e SQLAlchemy 2.1 l'ha cambiato da psycopg2 (quello installato, vedi
# requirements.txt) a psycopg v3 (non installato) — scoperto dal vivo quando questo ha
# mandato in crash il worker in produzione. Specificandolo qui non dipendiamo più dal
# default, qualunque esso sia in futuro.
if _url.startswith("postgresql://"):
    _url = _url.replace("postgresql://", "postgresql+psycopg2://", 1)

engine = create_engine(_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
