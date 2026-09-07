# Torcha Dashboard — Notizie calde + Trend di ricerca

Dashboard editoriale per capire in tempo reale (1) cosa sta scoppiando ora nelle notizie
italiane, divise per categoria e ordinate per **Heat score** (velocità di crescita, non solo
volume), e (2) cosa cerca la gente online (**Rising score** — Fase 4+).

## Stato del progetto

**Fase 1 (in corso)**: ingest RSS per le categorie *Attualità* e *Tecnologia*, clustering
TF-IDF sulla stessa storia, Heat score v0 (fonti × recency), dashboard Streamlit con
pulsante "Aggiorna" e riga di stato fonti. Le altre 4 categorie e l'integrazione Apify
(Trends/SERP/social/Wikipedia) arrivano nelle fasi successive — vedi
[prompt-dashboard-claude-code-v2.md](prompt-dashboard-claude-code-v2.md) per il piano completo.

## Struttura

```
app.py              # dashboard Streamlit (servizio "web" su Railway)
worker.py           # singola esecuzione di ingest (servizio "worker" su Railway, schedulato)
sources.yaml         # fonti per categoria: via rss/apify, URL feed verificati
src/
  config.py          # env vars + lettura sources.yaml
  db.py               # engine/sessione SQLAlchemy
  models.py           # tabelle Article, Run
  init_db.py          # crea le tabelle se non esistono
  ingest_rss.py        # fetch + normalizzazione + upsert, con retry e log fonti ok/failed
  clustering.py         # TF-IDF + cosine similarity, Heat score v0
```

## Locale

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # poi imposta DATABASE_URL su un Postgres raggiungibile
python3 -m src.init_db          # crea le tabelle
python3 worker.py               # un ingest manuale (facoltativo, la dashboard ha il bottone Aggiorna)
streamlit run app.py
```

## Deploy su Railway

Tre servizi nello stesso progetto Railway, tutti collegati allo stesso repo GitHub:

1. **Postgres** — plugin/database Railway, fornisce `DATABASE_URL` (Railway la inietta
   automaticamente nei servizi collegati come reference variable).
2. **web** (dashboard) — Start Command:
   ```
   streamlit run app.py --server.port $PORT --server.address 0.0.0.0
   ```
3. **worker** (ingest schedulato) — stesso repo, Start Command:
   ```
   python3 worker.py
   ```
   Su Railway: Settings → Cron Schedule, impostato a `*/45 * * * *` (ogni 45 minuti,
   coerente con `settings.refresh_minutes` in `sources.yaml`).

Variabili d'ambiente da impostare su **entrambi** i servizi (web e worker), vedi `.env.example`:
- `DATABASE_URL` — reference alla variabile del servizio Postgres
- `APIFY_TOKEN` — necessario dalla Fase 3, può restare vuoto per ora
- `ACTIVE_CATEGORIES` — `attualita,tecnologia` in Fase 1
- `DASHBOARD_WINDOW_HOURS` — finestra temporale mostrata in dashboard (default 24)

Al primo deploy, lanciare una volta la creazione schema:
```bash
railway run python3 -m src.init_db
```

## Note tecniche

- Le fonti RSS sono verificate dal vivo (vedi commenti in `sources.yaml`): Fanpage, Reuters,
  AP e AFP non hanno un feed RSS pubblico utilizzabile e sono marcate `via: apify` — verranno
  attivate in Fase 3 tramite Apify.
- Lo schema DB usa `Base.metadata.create_all` (niente Alembic per ora): con solo 2 tabelle
  in Fase 1 le migrazioni versionate sono overhead prematuro. Da introdurre se/quando lo
  schema in produzione dovrà evolvere preservando dati.
- L'indicatore di velocità "^" in dashboard è un proxy v0 (articolo più recente del cluster
  entro 3h); il vero calcolo di velocità rispetto alla baseline storica arriva in Fase 5.
