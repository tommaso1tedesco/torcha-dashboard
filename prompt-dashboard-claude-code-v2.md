# Prompt per Claude Code — Dashboard "Notizie calde + Trend di ricerca" (v2)

> Incolla tutto il testo qui sotto in Claude Code, in una cartella di progetto vuota.

---

Voglio costruire una **dashboard editoriale sempre online** per una pagina italiana di informazione sui social. Obiettivo strategico: **arrivare primi sulle notizie**. La dashboard deve rispondere a due domande in ogni momento:

1. **Cosa sta scoppiando ADESSO** — notizie calde, divise per categoria e ordinate per "quanto stanno salendo" (non solo per volume).
2. **Cosa cercano le persone** online in questo momento — domanda di ricerca / interesse emergente.

Prima di scrivere codice, propommi un **piano a fasi** e conferma con me lo stack. Poi procedi in modo **incrementale**: prima una versione funzionante con poche fonti, poi il resto.

## Deploy e infrastruttura (importante)

- Il progetto deve stare su **GitHub** e girare **sempre online su Railway**.
- Architettura su Railway in tre pezzi:
  1. **Servizio web** = la dashboard.
  2. **Database Postgres** = storico dei run (indispensabile: senza storico non posso calcolare la *velocità* dei temi).
  3. **Worker schedulato (cron)** = ogni N minuti lancia la raccolta dati, ingerisce i risultati e aggiorna il DB.
- Tutte le chiavi (token Apify, API keys, credenziali) devono stare in **variabili d'ambiente**, mai nel codice. Prepara un `.env.example`.

## Come raccogliamo i dati: Apify come layer di scraping

Non voglio scraping "fatto in casa" di Google e social: gli IP da datacenter di Railway verrebbero bloccati subito. Usiamo **Apify**, che gestisce proxy e anti-bot, e dal codice su Railway ci limitiamo a **orchestrare** (chiamare gli Actor via API, ricevere dati puliti, salvarli).

- Il token Apify va in env var (`APIFY_TOKEN`).
- Gli **ID degli Actor** vanno in `sources.yaml`, così posso cambiarli senza toccare il codice. Actor da usare (verifica sullo Store gli ID esatti e lo schema di input di ognuno):
  - Google Trends (trending searches + interest over time + related queries)
  - Google SERP (organico, People Also Ask, ricerche correlate, AI Overviews)
  - Trending di TikTok, YouTube, X/Twitter, Reddit
- Gestisci **retry, rate limit e degradazione elegante**: se un Actor fallisce, il resto della dashboard continua a funzionare, con log chiaro di cosa non ha risposto.

## PARTE 1 — Notizie calde, divise per categoria

Le notizie vanno raccolte via **RSS dove disponibile** (più stabile e gratis) e classificate in queste **6 categorie**. **Ti fornisco già un file `sources.yaml` compilato** con categorie, fonti, domini e flag (`via: rss`/`via: apify`, `paywall`); usalo come configurazione di partenza. In quel file i campi `rss_url` sono volutamente vuoti: **verifica tu dal vivo gli URL RSS reali di ogni testata e compilali** (non inventarli — se un feed non esiste o è morto, segnalamelo e imposta quella fonte su `via: apify`). La lista qui sotto è la stessa del file, per riferimento.

- **Attualità** — generaliste principali: ANSA, Sky TG24, TGCom24, Rai News, Adnkronos, Fanpage, Open. Intl: Reuters, AP, AFP.
- **Ultima ora** — non è una categoria tematica ma una *vista*: le news più recenti da tutte le generaliste, ordinate per orario (usa i feed "Ultima Ora" di ANSA e Adnkronos dove ci sono).
- **Economia** — Il Sole 24 Ore, Milano Finanza/MF; sezioni economia di ANSA, Repubblica, Corriere. Intl: The Economist, Financial Times, Bloomberg, Reuters Business.
- **Politica** — Pagella Politica, YouTrend; sezioni politica di ANSA, Repubblica, Corriere; quotidiani di **orientamenti diversi** (Domani, Il Foglio, Il Fatto Quotidiano, Il Giornale) per un quadro equilibrato. Intl: Politico Europe.
- **Tecnologia** — HDblog, DDay.it, Wired Italia, Punto Informatico; sezione tech di ANSA. Intl: The Verge, Ars Technica, TechCrunch.
- **Curiosità / Approfondimento** — Il Post, Internazionale. Intl: Vox, The Atlantic, BBC Future.

Requisiti:
- Ogni articolo va normalizzato in uno schema comune: `titolo, fonte, categoria, url, timestamp, lingua`.
- Una fonte può alimentare più categorie (es. ANSA compare in quasi tutte tramite le sue sezioni): gestisci il mapping fonte->categoria nel config.
- Nella categoria "Ultima ora" non duplicare fonti: è un filtro/ordinamento sulle generaliste.

## PARTE 2 — Cosa cercano le persone

Raccogli i segnali di domanda **solo dove sono pubblici**. NON tentare di ricavare "cosa chiede la gente agli LLM" (ChatGPT/Gemini/ecc.): quelle query sono private, non esistono come dato pubblico, non c'è niente da raccogliere. Fonti da usare:

- **Google** (via Apify): Trends (temi in salita), Autocomplete, People Also Ask, ricerche correlate — geo Italia.
- **Social** (via Apify): trending topic/hashtag di TikTok, YouTube, X; thread in salita su Reddit.
- **Wikipedia Pageviews API** (ufficiale, gratuita): top articoli del giorno su it.wikipedia + andamento per pagina. Ottimo segnale anticipatore.

## Logica di "calore" e trend (il cuore del progetto)

Non voglio un aggregatore, ma uno **scoring** che privilegia ciò che *sta salendo*:

- **Velocità**: tasso di nuovi articoli/menzioni su un tema nelle ultime N ore rispetto alla baseline storica (da Postgres).
- **Presenza cross-source**: un tema presente insieme su più fonti/segnali pesa di più.
- **Decadimento temporale**: le cose recenti pesano di più.
- **Clustering per categoria**: raggruppa gli articoli sulla *stessa* storia (prima versione: TF-IDF + coseno; se serve qualità, embedding tipo `sentence-transformers`), così non vedo 15 righe per lo stesso evento.

Calcola e mostra due punteggi distinti: **Heat score** (notizie) e **Rising score** (domanda di ricerca).

## Output — la dashboard

- Stack: **Python** per la pipeline dati + **Streamlit** per la dashboard.
- Struttura a **schede per categoria** (Attualità, Ultima ora, Economia, Politica, Tecnologia, Curiosità), ognuna con la lista clusterizzata ordinata per Heat score: titolo rappresentativo, n° fonti, elenco testate, orario, indicatore di velocità (^).
- Un pannello **"Cosa cerca la gente"**: temi in salita per Rising score, con la fonte del segnale (Trends / social / Wikipedia) e le keyword correlate.
- **Pulsante "Aggiorna"** on-demand + aggiornamento periodico via il worker cron.
- Una riga di **stato fonti** (chi ha risposto, chi no).

## Come voglio che tu proceda

1. Presentami piano a fasi + stack, aspetta il mio ok.
2. **Fase 1**: setup repo + Railway + Postgres + ingest RSS di 2-3 categorie + clustering semplice + dashboard base con le schede. Falla girare davvero, anche online.
3. Dopo la mia conferma: aggiungi le altre categorie, poi l'integrazione Apify (Trends/SERP/social), poi Wikipedia, poi lo scoring di velocità.
4. Ad ogni fase: gestione errori, log leggibili, `.env.example`, e un README con i comandi per girare in locale e per il deploy su Railway.

Comincia proponendomi il piano.
