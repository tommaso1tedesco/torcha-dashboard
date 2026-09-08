# Torcha Dashboard — Notizie calde + Trend di ricerca

Dashboard editoriale per capire in tempo reale (1) cosa sta scoppiando ora nelle notizie
italiane, divise per categoria e ordinate per **Heat score** (velocità di crescita, non solo
volume), e (2) cosa cerca la gente online (**Rising score**).

## Stato del progetto

**Tutte le 5 fasi del piano originale sono completate**: ingest RSS per le 6 categorie,
clustering TF-IDF, integrazione Apify (Google Trends, Google SERP, TikTok, YouTube, X, Reddit)
+ Google Autocomplete + Wikipedia Pageviews, pannello "Cosa cerca la gente", e infine la vera
velocità: ogni ciclo del worker registra uno scatto (`TopicSnapshot`) per ciascun tema/cluster,
e Heat/Rising score vengono moltiplicati per il rapporto tra l'intensità attuale e la media
storica dello stesso tema (baseline calcolata su Postgres, non più solo recency) — vedi
[prompt-dashboard-claude-code-v2.md](prompt-dashboard-claude-code-v2.md) per lo storico del piano.

## Struttura

```
app.py                  # dashboard Streamlit (servizio "web" su Railway)
worker.py               # un ciclo di ingest completo + registrazione scatti Fase 5 (servizio "worker", schedulato)
sources.yaml            # fonti Parte 1 (rss/apify) e Actor Apify Parte 2, tutti verificati dal vivo
src/
  config.py             # env vars + lettura sources.yaml
  db.py                 # engine/sessione SQLAlchemy
  models.py             # tabelle Article, Run, Signal, InterestRun, TopicSnapshot
  init_db.py            # crea le tabelle se non esistono
  queries.py            # query di lettura condivise tra app.py e worker.py
  ingest_rss.py         # Parte 1: fetch RSS + normalizzazione + upsert, retry e log fonti ok/failed
  clustering.py         # Parte 1: Heat score v0 (usa src/textsim.py per il raggruppamento)
  apify_client_wrapper.py  # chiamata sincrona a un Actor Apify (run + lettura dataset)
  ingest_interests.py   # Parte 2: orchestrazione Apify + Google Autocomplete, degradazione per-fonte
  ingest_wikipedia.py   # Parte 2: Wikipedia Pageviews API (top giornaliero + andamento settimanale)
  rising.py             # Parte 2: Rising score v0 (usa src/textsim.py per il raggruppamento)
  textsim.py            # TF-IDF + cosine similarity condiviso tra clustering.py e rising.py
  velocity.py           # Fase 5: scatti storici (TopicSnapshot) e moltiplicatore di velocità reale
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
   Su Railway: Settings → Cron Schedule, impostato a `*/30 * * * *` (ogni 30 minuti,
   coerente con `settings.refresh_minutes` in `sources.yaml`) — governa solo RSS/Wikipedia/
   Autocomplete (gratuiti); le fonti Apify hanno il proprio limite indipendente di 12h
   (vedi sezione Costi). Più run ci sono, più affidabile diventa la baseline storica
   della Fase 5.

Variabili d'ambiente da impostare su **entrambi** i servizi (web e worker), vedi `.env.example`:
- `DATABASE_URL` — reference alla variabile del servizio Postgres
- `APIFY_TOKEN` — se vuoto, le sole fonti Apify vengono saltate in modo pulito (Wikipedia e
  Autocomplete proseguono comunque, non richiedono token)
- `ACTIVE_CATEGORIES` — le 6 categorie di default
- `DASHBOARD_WINDOW_HOURS` — finestra temporale mostrata in dashboard (default 24)

Al primo deploy, lanciare una volta la creazione schema:
```bash
railway run python3 -m src.init_db
```

## Costi e controllo spesa

RSS, Wikipedia Pageviews e Google Autocomplete sono gratuiti e girano ad ogni ciclo del
worker (`refresh_minutes`, oggi 30 min) senza impatto sui costi. Apify (Google Trends,
SERP, TikTok, YouTube) è a pagamento e, misurato dal vivo a piena potenza e alla stessa
cadenza del worker, costerebbe **oltre $1.000/mese**. Per restare sotto ~€15-17/mese di
spesa Apify (+ ~$5/mese Railway), le fonti Apify seguono un limite indipendente:

- Le fonti Apify girano al più **una volta ogni 12 ore** (`APIFY_MIN_INTERVAL_HOURS`
  in `src/ingest_interests.py`), indipendentemente da quante volte il worker o il
  pulsante "Aggiorna" chiamano `run_interest_ingest()` — RSS/Wikipedia/Autocomplete
  restano invece gratuiti e girano ad ogni ciclo.
- Volumi ridotti per SERP/TikTok/YouTube (`SERP_SEED_COUNT`, `TIKTOK_SEED_COUNT`,
  `YOUTUBE_SEED_COUNT` in `src/ingest_interests.py`; `resultsPerPage`/`maxResults`
  in `sources.yaml`).
- Reddit e X sono escluse dal ciclo automatico (le fonti più costose/meno affidabili
  per il segnale che davano): le funzioni restano nel codice per un uso manuale.

Con questa configurazione la spesa Apify stimata è ~$11-12/mese (2 cicli/giorno).
Per alzarla o abbassarla ulteriormente, agire su `APIFY_MIN_INTERVAL_HOURS` e sui
volumi seed citati sopra.

## Note tecniche

- Le fonti RSS sono verificate dal vivo (vedi commenti in `sources.yaml`): alcune (Fanpage,
  Reuters, AP, AFP, TGCom24, Milano Finanza, Pagella Politica, Il Foglio, Il Giornale, Il Post)
  non hanno un feed RSS pubblico utilizzabile — durante la verifica sono stati trovati anche
  4 feed "morti" (200 OK ma contenuti fermi da mesi/anni: ANSA Tecnologia, Corriere Economia,
  Corriere Politica) poi sostituiti con l'endpoint corretto.
- Gli Actor Apify (Parte 2) sono verificati sullo Store (ID reali) **e testati dal vivo con un
  token reale**: lo schema di output di Google Trends (mode "trending") è risultato diverso da
  quanto documentato (un solo item con dentro `trending_searches[]`, non una lista flat) ed è
  stato corretto di conseguenza; l'Actor Reddit "Lite" non include voti/punteggio (si usa il
  rank di posizione come metrica); l'Actor X (`apidojo/tweet-scraper`) risponde `SUCCEEDED` ma
  ritorna solo `{"noResults": true}` anche per query molto comuni — probabile degradazione del
  servizio esterno, gestita senza crash (0 segnali) ma segnalata in `sources.yaml`.
- Nessuno di TikTok/YouTube/X offre un "trending now" pubblico senza login: sono alimentati con
  query "seed" (le storie più calde di Parte 1) e l'engagement di risposta è letto come segnale
  — un'approssimazione onesta, non un vero feed di trending. Google Trends (mode "trending"),
  Reddit (sort "hot"), Google Autocomplete e Wikipedia sono invece segnali diretti/ufficiali.
- Lo schema DB usa `Base.metadata.create_all` (niente Alembic per ora): le tabelle nuove si
  creano da sole, non serve alterare quelle esistenti. Da introdurre se/quando lo schema in
  produzione dovrà evolvere *modificando* (non solo aggiungendo) tabelle con dati da preservare.
- **Fase 5 (velocità reale)**: `src/velocity.py` confronta l'ultimo `TopicSnapshot` di un tema
  con la media dei precedenti (finestra 7 giorni, richiede almeno 2 scatti più vecchi di 2h per
  avere una baseline) e ne deriva un moltiplicatore (clampato 0.5×-3×) applicato a Heat/Rising
  score. Limite noto: il match nel tempo tra uno scatto e i suoi precedenti è per stringa esatta
  sul titolo/keyword normalizzato, non per similarità come il clustering "live" — una storia che
  cambia titolo tra un run e l'altro perde continuità storica. Un tema senza storico è neutro
  (moltiplicatore 1.0) e marcato "nuovo" (^), non penalizzato.
