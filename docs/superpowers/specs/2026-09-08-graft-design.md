# Graft — Design Spec (v1)

- **Data**: 2026-09-08
- **Stato**: Draft per review
- **Autore**: Stefano Paradisi (+ Claude)

## 1. Sintesi

Graft è un **framework open-source self-hosted** che permette di aggiungere un
**chatbot LLM con RAG** a un sito web **già esistente**, senza modificarne il
backend e con **una sola riga HTML** nel frontend.

Il cliente fa girare un servizio Docker (`graft-server`) accanto al proprio sito.
Nel sito incolla uno `<script>` che inietta un widget di chat isolato in Shadow
DOM. Il widget parla direttamente al `graft-server`, che fa retrieval sui
documenti caricati dal cliente e genera risposte **strettamente ancorate** a quei
documenti, citando le fonti.

### Principio guida

> Aggancio **solo frontend, 1 riga**. Backend del sito ospite = **zero modifiche**.
> Tutta la logica vive nel `graft-server` self-hosted.

## 2. Obiettivi e non-obiettivi

### Obiettivi (v1)

- Agganciarsi a **qualsiasi stack** di sito ospite (Angular, React, Spring,
  Node, WordPress, HTML statico) senza toccarne il backend.
- **Multi-bot**: una istanza gestisce N bot, ognuno con knowledge base, config
  provider, tema e widget-key propri.
- **RAG strict grounded**: risponde solo dai chunk recuperati, cita le fonti,
  altrimenti dichiara "non ho informazioni".
- **Multi-provider LLM/embeddings**, chiave/modello portati dal cliente.
- **Multi-utente** con ruoli (owner / editor / viewer).
- Ingestion via **upload documenti** (PDF, Markdown, TXT).
- Deploy **`docker compose up`**.

### Non-obiettivi (rimandati)

- Auto-crawl del sito / re-index schedulato.
- Ingestion API push (contenuti dinamici da DB del cliente).
- Identità end-user autenticata (JWT firmato dal backend ospite).
- Modalità SaaS hosted multi-tenant.
- Analytics avanzate, feedback 👍👎, handoff umano, RBAC per-bot fine.
- SDK client per linguaggio.

## 3. Architettura

Monolite modulare: un solo backend FastAPI serve API pubblica (chat), Admin API,
SPA admin e bundle del widget. Scartato: microservizi separati (overkill per MVP
self-hosted).

```
   Sito ospite (stack qualsiasi, backend INVARIATO)
   ┌───────────────────────────────────────────┐
   │  <html> ... prodotto dal backend cliente   │
   │  <script src=".../graft.js"                 │
   │          data-graft-bot="WIDGET_KEY"></script>
   └───────────────┬───────────────────────────┘
                   │  graft.js crea host + Shadow DOM
                   ▼
        ┌─────────────────────┐  HTTP/SSE (CORS: allowed_origins)
        │  Widget (Shadow DOM) │ ───────────────────────────────┐
        └─────────────────────┘                                 │
                                                                 ▼
                              ┌──────────────────────────────────────────┐
                              │            graft-server (FastAPI)          │
                              │  ┌──────────────┐   ┌───────────────────┐  │
                              │  │ Chat API      │   │ Admin API + SPA    │  │
                              │  │ (public)      │   │ (Refine, auth JWT) │  │
                              │  └──────┬───────┘   └─────────┬─────────┘  │
                              │         ▼                     ▼            │
                              │  ┌──────────────┐   ┌───────────────────┐  │
                              │  │ RAG engine    │   │ Ingestion pipeline │  │
                              │  └──────┬───────┘   └─────────┬─────────┘  │
                              │         └──────────┬──────────┘            │
                              │            Provider adapters                │
                              │   (OpenAI-compat | Anthropic | Google |     │
                              │    Mistral)  →  LLM + Embeddings            │
                              └───────────────────────┬────────────────────┘
                                                      ▼
                                        Postgres + pgvector
```

### Deliverable

`docker-compose.yml` con due servizi:

- `app` — immagine `graft-server` (FastAPI + widget build + admin SPA build).
- `db` — Postgres con estensione `pgvector`.

## 4. Componenti

### 4.1 `graft-widget` (frontend embeddabile)

- Bundle **TypeScript vanilla** (niente framework) compilato in singolo
  `graft.js`, per tenerlo piccolo e senza dipendenze runtime.
- All'avvio: crea un elemento host nel DOM del sito, `attachShadow({mode:'open'})`,
  monta launcher flottante + pannello chat **dentro lo Shadow DOM**.
- **Isolamento**: CSS del sito non entra, CSS del widget non esce → nessun
  conflitto con lo stack ospite.
- Config via `data-*` attributes: `data-graft-bot` (widget-key), override
  opzionali (posizione, colore) — ma il tema di default arriva dalla config del
  bot lato server.
- Funzioni v1: apertura/chiusura, invio messaggio, **risposte in streaming**
  (SSE), rendering markdown base, **citazioni fonti**, stato "sto scrivendo",
  responsive mobile.
- Fuori v1: draggable, persistenza cronologia lato client oltre la sessione.

Esempio di aggancio nel sito ospite:

```html
<script src="https://graft.example.com/widget/graft.js"
        data-graft-bot="wk_live_xxx" defer></script>
```

### 4.2 `graft-server` — Chat API (pubblica)

Endpoint consumato dal widget. Non richiede login (utenti anonimi del sito).

- `POST /api/v1/chat` — corpo: `{ bot_key, session_id, message, history? }`.
  Risposta **SSE stream** di token + blocco finale con citazioni.
- Validazioni per ogni richiesta:
  1. `bot_key` valido → risolve il bot.
  2. Header `Origin` ∈ `allowed_origins` del bot (blocca embedding non
     autorizzato su altri domini).
  3. **Rate limit** per `(bot, IP/session)`.
- Flusso: vedi §6 (RAG engine).

### 4.3 `graft-server` — Admin API + SPA

- **Admin API** REST protetta da JWT (FastAPI Users). CRUD su bot, documenti,
  utenti, lettura conversazioni; upload file; test config provider.
- **Admin SPA**: Refine + Ant Design, servita staticamente a `/admin`, parla con
  l'Admin API via `dataProvider` REST.

### 4.4 Ingestion pipeline

Upload documento → **parse** → **chunking** (dimensione + overlap configurabili,
default sensato) → **embed**
di ogni chunk col provider embeddings del bot → **persist** chunk + vettore +
metadata (documento, posizione) su Postgres/pgvector. Stato documento:
`pending → processing → ready | failed`.

**Parser selezionabile**: default `pypdf` (leggero); `unstructured` (robusto)
attivabile via config di ingestion. `unstructured` ha dipendenze pesanti → resta
un **extra opzionale** (dependency group / variante immagine), non nell'immagine
base. Il processing gira in background (coda su Redis) per non bloccare l'upload.

### 4.5 RAG engine

Vedi §6.

### 4.6 Provider adapters

Vedi §7.

## 5. Modello dati (Postgres + pgvector)

Tutte le tabelle con `id UUID PK`, `created_at`, `updated_at`.

- **users** (FastAPI Users): `email`, `hashed_password`, `is_active`,
  `is_superuser`, **`role`** ∈ {owner, editor, viewer}.
- **bots**: `name`, `widget_key` (unica, pubblica), `allowed_origins TEXT[]`,
  `llm_config JSONB` (provider + modello + endpoint), `embedding_config JSONB`,
  `system_prompt TEXT`, `theme JSONB`, `retrieval_config JSONB` (top_k, soglia).
  Le **API key provider sono cifrate at rest**.
- **bot_members** (v1): `user_id`, `bot_id` — assegna bot agli editor. Il ruolo
  `owner` vede tutto; `editor` opera solo sui bot in `bot_members`.
- **documents**: `bot_id FK`, `filename`, `mime_type`, `status`, `error?`,
  `chunk_count`.
- **chunks** (tabella **partizionata LIST per `embedding_dim`**):
  `document_id FK`, `bot_id FK` (denormalizzato per filtro veloce),
  `content TEXT`, `embedding_dim INT`, `embedding vector(N)`, `metadata JSONB`,
  `position INT`. Partizioni figlie per dimensione (768, 1024, 1536, 3072…),
  ognuna con `vector(N)` tipizzato + **indice HNSW** proprio + indice su
  `bot_id`. La query, nota la dimensione del bot, colpisce **una sola
  partizione** → ricerca ANN indicizzata anche con provider misti tra bot.
- **conversations**: `bot_id FK`, `visitor_session`, `started_at`.
- **messages**: `conversation_id FK`, `role` ∈ {user, assistant}, `content`,
  `citations JSONB`.

> **Dimensione vettore risolta** (§13.1): partizione per dimensione. Ogni bot ha
> un unico modello embeddings → dimensione fissa per bot; il retrieval è sempre
> per-bot, quindi confronta solo vettori dello stesso spazio. Nuove dimensioni =
> nuova partizione, senza toccare le altre.

## 6. Pipeline RAG (strict grounded)

**Query (runtime chat):**

1. Riceve messaggio + eventuale history breve.
2. **Embed** della query col provider embeddings del bot.
3. **Similarity search** su `chunks` filtrata per `bot_id`, top-k con soglia di
   similarità minima (da `retrieval_config`).
4. Se nessun chunk supera la soglia → risposta di fallback "non ho informazioni
   su questo" (comportamento strict), senza chiamare l'LLM per inventare.
5. Altrimenti costruisce il **prompt grounded**:
   - system prompt del bot + istruzione hard: "Rispondi **solo** usando il
     CONTESTO. Se il contesto non basta, dillo. Cita le fonti."
   - blocco CONTESTO = chunk recuperati con id sorgente.
6. **Stream** dal provider LLM del bot → token al widget via SSE.
7. Allega **citazioni** (documento + posizione) al messaggio finale; persiste
   conversazione e messaggi.

## 7. Provider abstraction

Due interfacce Python:

- `LLMProvider.stream_chat(messages, model, **opts) -> AsyncIterator[str]`
- `EmbeddingProvider.embed(texts, model) -> list[vector]`

Adapter concreti:

- **OpenAI-compatible** — copre **OpenAI, Ollama, LM Studio** (stesso schema
  API, cambia solo `base_url`/`api_key`). Chat + embeddings.
- **Anthropic** — chat. **Nessun embeddings proprio** → il bot deve configurare
  un embedding provider separato (validato in fase di config).
- **Google** (Gemini) — chat + embeddings.
- **Mistral** — chat + embeddings.

Config **per-bot**: quale provider per LLM, quale per embeddings (possono
differire), modello, endpoint/base_url, api_key (cifrata). Endpoint admin per
**test connessione** prima di salvare.

## 8. Sicurezza

- **widget_key pubblica** → difesa con `allowed_origins`: check header `Origin`
  in ingresso + stesso elenco come **whitelist CORS**. Un dominio non
  autorizzato non può usare il bot né passare la CORS.
- **Rate limiting** per `(bot, IP/session)` sulla Chat API (protezione costi
  LLM e abuso), **backed da Redis** (contatori con TTL, coerenti tra worker).
- **API key provider cifrate at rest** (chiave di cifratura da env del deploy).
- **Admin auth**: JWT (FastAPI Users), password hashed (argon2/bcrypt).
- **RBAC**: enforcement backend (dependency FastAPI per ruolo) **e** UI
  (`accessControlProvider` di Refine nasconde azioni non permesse). L'UI non è
  l'unica barriera: il backend valida sempre.
- Nessun dato sensibile in URL/query string.

### Ruoli

| Ruolo  | Utenti | Bot (tutti) | Documenti/config bot | Conversazioni | Settings |
|--------|--------|-------------|----------------------|---------------|----------|
| owner  | CRUD   | CRUD        | CRUD                 | read          | manage   |
| editor | –      | read assegnati | CRUD assegnati    | read          | –        |
| viewer | –      | read        | read                 | read          | –        |

("assegnati" = bot in `bot_members` per quell'editor; attivo in v1.)

## 9. Superficie API (bozza)

**Pubblica**

- `POST /api/v1/chat` (SSE) — chat widget.
- `GET  /widget/graft.js` — bundle widget.

**Admin (JWT)**

- `POST /auth/jwt/login`, `POST /auth/jwt/logout` (FastAPI Users).
- `GET/POST/PATCH/DELETE /admin/bots`
- `GET/POST/DELETE /admin/bots/{id}/documents` (+ upload multipart)
- `POST /admin/bots/{id}/provider/test`
- `GET /admin/bots/{id}/conversations`, `GET .../conversations/{cid}`
- `GET/POST/PATCH/DELETE /admin/users` (solo owner)

Convenzione REST compatibile col `dataProvider` di Refine (`simple-rest` o
provider custom sottile).

## 10. Deployment

```
graft/
  docker-compose.yml        # app + db(pgvector) + redis
  server/                   # FastAPI (Python)
  widget/                   # TS vanilla → graft.js
  admin/                    # Refine + Ant Design SPA
```

- Tre servizi: `app` (FastAPI + build widget/admin), `db` (Postgres+pgvector),
  `redis` (rate limit + coda ingestion). Worker ingestion: task in background
  che consuma la coda Redis.
- Immagine base **snella** (`pypdf`); variante/extra con `unstructured` per chi
  serve parsing pesante.
- `docker compose up` avvia tutto; migrazioni DB al boot (Alembic), incluse le
  partizioni `chunks` per dimensione.
- Config via env: chiave cifratura, secret JWT, connessione DB, URL Redis, CORS
  di base.
- Provider key e config bot si impostano dalla dashboard, non da env.

## 11. Testing

- **Backend (pytest)**:
  - unit: chunking, costruzione prompt grounded, adapter provider (HTTP
    mockato), logica rate-limit/origin-check.
  - integrazione: ingestion + retrieval end-to-end su **pgvector di test**.
  - fallback strict: query senza match → risposta "non ho info", LLM non
    chiamato.
- **Widget**: test leggeri su isolamento Shadow DOM + parsing SSE; smoke manuale
  su una pagina demo.
- **Admin**: smoke su login + un flusso CRUD.

## 12. Scope MVP — riepilogo

**Dentro**: multi-bot; upload PDF/MD/TXT (parser selezionabile, ingestion in
background su coda Redis); RAG strict grounded + citazioni; 4 adapter provider
(6 backend LLM); Postgres/pgvector con `chunks` partizionati per dimensione;
widget Shadow DOM streaming; admin SPA Refine; multi-utente + RBAC
(owner/editor/viewer) con `bot_members`; log conversazioni; allowed_origins +
rate limit Redis; `docker compose up`.

**Fuori**: auto-crawl, re-index schedulato, ingestion push API, identità
end-user, SaaS hosted, analytics avanzate, RBAC per-bot fine, SDK client.

## 13. Decisioni risolte

1. **Dimensione vettore multi-modello** → tabella `chunks` **partizionata LIST
   per `embedding_dim`**, ogni partizione `vector(N)` + HNSW proprio. Retrieval
   per-bot colpisce una sola partizione. Supporta provider misti tra bot.
2. **Parsing PDF** → **entrambi, selezionabili**: `pypdf` di default (immagine
   base snella), `unstructured` come extra opzionale attivabile via config.
3. **Rate limit** → **Redis** (contatori TTL). Aggiunge il servizio `redis` in
   compose; riusato anche come coda per l'ingestion in background.
4. **`bot_members`** → **in v1**. RBAC editor legato ai bot assegnati fin da
   subito.
5. **Refine data provider** → **custom**, per allineare paginazione/filtri/sort
   della forma di risposta FastAPI a Refine.
