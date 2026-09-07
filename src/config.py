"""Caricamento configurazione: variabili d'ambiente + sources.yaml."""
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
SOURCES_PATH = BASE_DIR / "sources.yaml"

DATABASE_URL = os.environ["DATABASE_URL"]
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")

ACTIVE_CATEGORIES = [
    c.strip() for c in os.environ.get(
        "ACTIVE_CATEGORIES", "attualita,ultima_ora,economia,politica,tecnologia,curiosita"
    ).split(",") if c.strip()
]
DASHBOARD_WINDOW_HOURS = int(os.environ.get("DASHBOARD_WINDOW_HOURS", "24"))


def load_sources() -> dict:
    with open(SOURCES_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def rss_sources_for_category(category_key: str) -> list[dict]:
    """Fonti con via: rss e rss_url compilato per una categoria."""
    cfg = load_sources()
    cat = cfg["categories"].get(category_key)
    if not cat:
        raise KeyError(f"Categoria '{category_key}' non trovata in sources.yaml")
    return [
        s for s in cat["sources"]
        if s.get("via") == "rss" and s.get("rss_url")
    ]


def all_sources_for_category(category_key: str) -> list[dict]:
    """Tutte le fonti configurate per una categoria, incluse quelle via: apify (per la riga di stato)."""
    cfg = load_sources()
    cat = cfg["categories"].get(category_key)
    if not cat:
        raise KeyError(f"Categoria '{category_key}' non trovata in sources.yaml")
    return cat["sources"]
