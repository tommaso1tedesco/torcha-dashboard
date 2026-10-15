# Torcha Dashboard — Notizie calde

Dashboard editoriale per capire in tempo reale cosa sta scoppiando ora nelle notizie
italiane, divise per categoria e ordinate per **Heat score** (quante fonti ne parlano,
quanto è recente, quanto sta accelerando rispetto al solito).

Tutto è gratuito lato dati: le sole fonti sono feed RSS pubblici. Non ci sono API a
pagamento né servizi esterni a consumo.

## Come funziona

- `worker.py` gira ogni 30 minuti (cron): scarica i feed RSS di `sources.yaml`, salva gli
  articoli su Postgres, registra uno scatto per ogni cluster (`TopicSnapshot`) e cancella
  gli scatti più vecchi di 8 giorni.
- `app.py` (Streamlit) legge da Postgres, raggruppa gli articoli per somiglianza
  (TF-IDF + cosine, `src/textsim.py`) e calcola l'Heat score, moltiplicato per la velocità
  rispetto alla baseline degli ultimi 7 giorni (`src/velocity.py`).
- Gli orari a schermo sono in fuso italiano; i dati sono salvati in UTC.

## Struttura

```
app.py                  # dashboard Streamlit (servizio "web")
worker.py               # ingest schedulato (servizio "worker", cron)
sources.yaml            # fonti per categoria, tutte verificate dal vivo
src/
  config.py             # variabili d'ambiente + sources.yaml
  db.py, models.py      # SQLAlchemy: articles, runs, topic_snapshots
  ingest_rss.py         # fetch + normalizzazione + upsert
  http.py               # fetch con timeout rigido (urllib non copre il DNS)
  clustering.py         # clustering articoli e Heat score
  textsim.py            # TF-IDF + cosine similarity
  velocity.py           # baseline storica, moltiplicatore, pulizia scatti vecchi
  queries.py, ui.py     # letture condivise e componenti grafici
ui_pages/notizie.py     # pagina Notizie (una scheda per categoria)
```

## Sviluppo locale

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql://utente:password@host:5432/db
python3 -m src.init_db     # crea le tabelle
python3 worker.py          # un ingest manuale (la dashboard ha anche il pulsante Aggiorna)
streamlit run app.py
```

## Deploy su Railway

Tre servizi nello stesso progetto, collegati allo stesso repo GitHub:

1. **Postgres** — fornisce `DATABASE_URL`.
2. **web** — Start Command: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0`
3. **worker** — Start Command: `python3 worker.py`, Cron Schedule `*/30 * * * *`.

Variabili d'ambiente (su web e worker): `DATABASE_URL`; opzionali `ACTIVE_CATEGORIES`
(default: le 6 categorie) e `DASHBOARD_WINDOW_HOURS` (default 24).

Per il deploy via API usare `serviceInstanceDeploy` con `latestCommit: true`: senza, Railway
rifa il deploy del commit precedente.

## Note tecniche

- `requirements.txt` pinna `SQLAlchemy<2.1` e `src/db.py` specifica `postgresql+psycopg2://`:
  SQLAlchemy 2.1 ha cambiato il driver di default a psycopg v3 e rompeva il worker.
- Gli articoli con data di pubblicazione nel futuro vengono scartati (alcuni feed includono
  eventi programmati).
- Il volume Postgres è piccolo: `topic_snapshots` va ripulita (lo fa il worker) o riempie
  il disco.
- Limite noto: il clustering non unisce notizie sulla stessa storia in lingue diverse né tra
  categorie diverse.
