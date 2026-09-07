# Torcha Dashboard — Notizie calde + Trend di ricerca

Dashboard editoriale per capire in tempo reale (1) cosa sta scoppiando ora nelle notizie
italiane, divise per categoria e ordinate per **Heat score** (velocità di crescita, non solo
volume), e (2) cosa cerca la gente online (**Rising score**).

## Stato del progetto

**Fase 1-3 completate**: ingest RSS per tutte le 6 categorie, clustering TF-IDF sulla stessa
storia, Heat score v0, dashboard Streamlit con pulsante "Aggiorna" e riga di stato fonti;
integrazione Apify (Google Trends, Google SERP, TikTok, YouTube, X, Reddit) con Rising score
v0 e pannello "Cosa cerca la gente". Wikipedia Pageviews (Fase 4) e lo scoring di velocità
definitivo su baseline storica (Fase 5) sono i prossimi passi — vedi
[prompt-dashboard-claude-code-v2.md](prompt-dashboard-claude-code-v2.md) per il piano completo.

## Struttura

```
app.py                  # dashboard Streamlit (servizio "web" su Railway)
worker.py               # singola esecuzione di ingest, Parte 1 + Parte 2 (servizio "worker", schedulato)
sources.yaml            # fonti Parte 1 (rss/apify) e Actor Apify Parte 2, tutti verificati dal vivo
src/
  config.py             # env vars + lettura sources.yaml
  db.py                 # engine/sessione SQLAlchemy
  models.py             # tabelle Article, Run, Signal, InterestRun
  init_db.py            # crea le tabelle se non esistono
  ingest_rss.py         # Parte 1: fetch RSS + normalizzazione + upsert, retry e log fonti ok/failed
  clustering.py         # Parte 1: Heat score v0 (usa src/textsim.py per il raggruppamento)
  apify_client_wrapper.py  # chiamata sincrona a un Actor Apify (run + lettura dataset)
  ingest_interests.py   # Parte 2: orchestrazione dei 6 Actor Apify, degradazione per-fonte
  rising.py             # Parte 2: Rising score v0 (usa src/textsim.py per il raggruppamento)
  textsim.py            # TF-IDF + cosine similarity condiviso tra clustering.py e rising.py
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
- `APIFY_TOKEN` — se vuoto, l'ingest Parte 2 (Apify) viene saltato in modo pulito
- `ACTIVE_CATEGORIES` — le 6 categorie di default
- `DASHBOARD_WINDOW_HOURS` — finestra temporale mostrata in dashboard (default 24)

Al primo deploy, lanciare una volta la creazione schema:
```bash
railway run python3 -m src.init_db
```

## Note tecniche

- Le fonti RSS sono verificate dal vivo (vedi commenti in `sources.yaml`): alcune (Fanpage,
  Reuters, AP, AFP, TGCom24, Milano Finanza, Pagella Politica, Il Foglio, Il Giornale, Il Post)
  non hanno un feed RSS pubblico utilizzabile — durante la verifica sono stati trovati anche
  4 feed "morti" (200 OK ma contenuti fermi da mesi/anni: ANSA Tecnologia, Corriere Economia,
  Corriere Politica) poi sostituiti con l'endpoint corretto.
- Gli Actor Apify (Parte 2) sono verificati sullo Store (ID reali, schema di input reale — non
  inventato). Nessuno di TikTok/YouTube/X offre un "trending now" pubblico senza login: sono
  alimentati con query "seed" (le storie più calde di Parte 1) e l'engagement di risposta è
  letto come segnale — un'approssimazione onesta, non un vero feed di trending. Google Trends
  (mode "trending") e Reddit (sort "hot" sulle subreddit configurate) sono invece segnali diretti.
- Lo schema DB usa `Base.metadata.create_all` (niente Alembic per ora): le tabelle nuove si
  creano da sole, non serve alterare quelle esistenti. Da introdurre se/quando lo schema in
  produzione dovrà evolvere *modificando* (non solo aggiungendo) tabelle con dati da preservare.
- L'indicatore di velocità "^" e il Rising/Heat score sono v0: raggruppamento per similarità
  testuale + intensità cross-source + recency, non ancora la vera velocità rispetto alla
  baseline storica in Postgres (Fase 5).
