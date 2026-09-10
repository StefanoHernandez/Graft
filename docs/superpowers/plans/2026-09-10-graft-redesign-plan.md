# Graft Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Il destinatario è il collega: questo documento non avvia implementazioni o agenti.

**Goal:** Consegnare un chatbot documentale installabile su un sito reale, con ingestione recuperabile, fonti verificabili e amministrazione minima.

**Architecture:** Conservare monolite FastAPI, modelli, adapter e Postgres/pgvector. Aggiungere worker Redis nella stessa immagine, poi chat e widget prima della dashboard completa. Ridurre la prima release a un owner, conservando multi-bot e predisposizione multiutente.

**Tech Stack:** Python >=3.12, FastAPI, SQLAlchemy async, Alembic, pgvector, Redis/arq, FastAPI Users, pypdf, TypeScript vanilla.

**Spec:** [2026-09-10-graft-redesign.md](../specs/2026-09-10-graft-redesign.md), da leggere interamente prima del primo task.

## Global Constraints

- Baseline ispezionata: `c16dbae`; prima di lavorare verificare branch e modifiche sopraggiunte.
- Python >=3.12. Dipendenze bloccate nei lockfile; build frozen.
- Nessuna riscrittura, nessun nuovo database, nessun framework RAG aggiuntivo.
- Prima release: un amministratore attivo, più bot, un percorso provider verificato dal vivo, PDF testuali/MD/TXT, widget essenziale, amministrazione essenziale.
- Limiti iniziali: 10 MiB/file, 200 pagine PDF, 1 milione di caratteri estratti, 2.000 chunk/documento.
- Chunk: tetto 1.000 caratteri, overlap massimo 200; batch embeddings massimo 32.
- Job: lease 120 secondi, heartbeat 30 secondi, timeout 10 minuti, tre tentativi complessivi.
- Chat: input 2.000 caratteri, history 6 messaggi/8.000 caratteri, contesto 6.000 caratteri, output 512 token.
- Origin e rate limit sono obbligatori prima di esporre chat; auth obbligatoria prima di qualsiasi API admin.
- Codice e verifiche eseguiti dal collega. In questo passaggio sono stati scritti solo documenti: non considerare test o milestone già superati.

## Uso del piano e ordine di consegna

Tre incrementi, ciascuno con un gate. Ogni task è una PR piccola, non un unico merge finale.

| Incremento | Task | Risultato | Dipendenza |
|---|---|---|---|
| A — documenti affidabili | 0–6 | Upload autenticato, worker, retry, originali persistenti | Baseline |
| B — valore sul sito | 7–11 | RAG, chat protetta, fonti, widget, valutazione live | A |
| C — prima release operabile | 12–14 | Admin minimo, build, backup/restore, manuale | B |
| D — estensione originaria | 15–16 | RBAC completo e Refine, altri provider | C, utilizzo validato |

Priorità: terminare A, poi B. Non costruire Refine, HNSW, OCR o crawler durante A/B.
I task D sono specificati come estensioni separate: non impediscono la prima release.

### Procedura comune per ciascun task

- [ ] Leggere file indicati e test correnti; verificare contratti dei task precedenti.
- [ ] Scrivere i casi elencati, eseguirli e confermare il fallimento atteso.
- [ ] Implementare il comportamento minimo descritto; gli snippet fissano contratti,
      non sono sostituti del codice completo e dei controlli elencati.
- [ ] Eseguire test mirati, poi suite del relativo incremento e lint.
- [ ] Aggiornare wiki engineering interessata, annotare comandi/esiti nella PR.
- [ ] Fare commit del solo task e review del diff prima del task dipendente.

Non inventare successi se Docker, provider o rete sono indisponibili: distinguere
test falliti da verifiche non eseguite. Nessuna chiave reale nelle fixture.

## Task 0 — Riprodurre baseline e liberare unit test da Docker

**File:** modificare `server/tests/conftest.py`, `server/pyproject.toml`;
spostare test puri in `server/tests/unit/`, test DB in `server/tests/integration/`;
creare `server/tests/integration/conftest.py`.

**Interfacce:** fixture `client` disponibile senza DB; fixture `pg`, `migrated`,
`db_engine`, `db_session`, `ready_client` solo nel ramo integration.
Separare i due test di `test_health.py`: liveness unit, readiness integration.

- [ ] Da `server/`: `uv sync --locked`, `uv run pytest -q`, `uv run ruff check .`.
      Annotare risultato reale; wiki dichiara 46 test, ma non costituisce prova attuale.
- [ ] Spostare provider, crypto, chunking e parsing fra unitari; conservare nomi test.
- [ ] Rendere fixture di migrazione autouse soltanto sotto integration. Registrare
      marker `integration` e `live`; live escluso dal comando predefinito.
- [ ] Provare unitari con `DOCKER_HOST=unix:///nonexistent-graft.sock uv run pytest tests/unit -q`.
- [ ] Eseguire integrazione e controllare che schema derivi ancora da Alembic.

**Gate:** unitari passano senza Docker; integrazione usa DB reale. Nessun test perso
nel trasloco; se numero cambia, spiegare split/parametrizzazioni.

## Task 1 — Errori provider e configurazione sicura

**File:** modificare `server/graft/providers/{base,config,factory,openai_compatible,anthropic_llm}.py`,
`server/graft/config.py`; test `server/tests/unit/test_provider_errors.py`,
`server/tests/unit/test_settings.py`.

**Interfaccia prodotta:** `ProviderError(code: str, retryable: bool)` con messaggio
pubblico fisso. Codici: `provider_auth`, `provider_rate_limit`, `provider_timeout`,
`provider_unavailable`, `provider_invalid_response`, `provider_config`.
Conservare `ProviderConnectionError` come sottoclasse compatibile per i test esistenti.
Factory accetta opzioni timeout/retry tramite argomenti keyword con default documentati.

```python
class ProviderError(Exception):
    def __init__(self, code: str, *, retryable: bool = False):
        self.code = code
        self.retryable = retryable
        super().__init__(code)
```

- [ ] Testare auth, 429, timeout, 5xx e errore durante iterazione stream.
- [ ] Inserire un falso segreto nell'eccezione SDK; verificare assenza da messaggio
      normalizzato e log catturati. Non loggare traceback SDK contenenti request.
- [ ] Normalizzare `embed`, `stream_chat`, `test_connection`; cancellazione deve
      propagarsi senza diventare errore provider. Chiudere client in lifespan/worker.
- [ ] Validare vettori: quantità, dimensione uniforme >0, valori finiti e norma >0.
- [ ] Config prod rifiuta JWT placeholder e Fernet invalida. Dev resta avviabile
      per health; operazioni con chiavi richiedono comunque Fernet valida.

**Verifica:** `uv run pytest tests/unit -q`; `uv run ruff check .`.
**Commit:** `fix: normalize provider failures and validate runtime config`.

## Task 2 — Schema additivo, storage e identità embeddings

**File:** modificare `server/graft/models/{document,conversation}.py`,
`server/graft/config.py`; creare `server/migrations/versions/0003_document_lifecycle.py`,
`server/graft/ingestion/storage.py`, `server/graft/providers/fingerprint.py`,
`server/tests/unit/test_storage.py`, `server/tests/unit/test_fingerprint.py`,
`server/tests/integration/test_document_lifecycle_schema.py`.

**Interfacce:** `save_source(root: Path, bot_id: UUID, document_id: UUID, data: bytes) -> str`,
`read_source(root: Path, storage_key: str) -> bytes`,
`delete_source(root: Path, storage_key: str) -> None`,
`embedding_fingerprint(config: EmbeddingConfig) -> str`.
Lo storage controlla containment anche quando legge una chiave dal DB.

```python
def test_key_rotation_keeps_fingerprint():
    first = EmbeddingConfig(provider="openai_compatible", model="m", api_key="a")
    second = first.model_copy(update={"api_key": "b"})
    assert embedding_fingerprint(first) == embedding_fingerprint(second)
    assert embedding_fingerprint(first.model_copy(update={"model": "other"})) != embedding_fingerprint(first)
```

- [ ] Aggiungere campi documento definiti nella spec; `attempt_count` non nullable
      default 0. Per Message aggiungere `request_id` UUID nullable e `status`
      default `completed`, limitato a completed/failed/cancelled.
- [ ] La riga user porta esito del tentativo; assistant viene inserito soltanto
      su completamento. Durante esecuzione non è necessario nuovo stato nel DB:
      user nasce cancelled e viene aggiornato completed/failed al termine.
- [ ] Testare upgrade da 0002 con bot/documento/chunk già presenti, poi downgrade
      su DB temporaneo. Legacy conserva contenuti, fingerprint/storage null.
- [ ] Testare traversal, nome originale con slash, scrittura atomica, doppia delete,
      path esterno e due documenti con stesso filename.
- [ ] Riutilizzare endpoint predefiniti della factory nella normalizzazione;
      non duplicare mappe provider divergenti. Nessuna API key nel fingerprint.

**Gate:** migrazione non distruttiva; originali leggibili dopo nuova istanza storage.
**Verifica:** `uv run pytest tests/unit/test_storage.py tests/unit/test_fingerprint.py tests/integration/test_document_lifecycle_schema.py -q`.

## Task 3 — Parsing con provenienza e chunking per paragrafi

**File:** modificare `server/graft/ingestion/{parsing,chunking}.py`;
creare `server/graft/ingestion/types.py`, `server/graft/ingestion/parse_worker.py`;
aggiornare test unitari parsing/chunking; creare fixture reali in
`server/tests/fixtures/documents/` e `server/tests/unit/test_parse_process.py`.

**Interfacce prodotte:**

```python
@dataclass(frozen=True)
class ParsedSection:
    text: str
    page: int | None = None
    heading: str | None = None

@dataclass(frozen=True)
class ChunkDraft:
    content: str
    metadata: dict

def parse_document(filename: str, mime_type: str, data: bytes) -> list[ParsedSection]: ...
def chunk_sections(sections: list[ParsedSection], *, size: int = 1000,
                   overlap: int = 200) -> list[ChunkDraft]: ...
```

Le firme sono contratti da implementare, non stubs da lasciare nel repository.

- [ ] Testare PDF testuale vero a due pagine, PDF senza testo, PDF corrotto, MD con
      heading, UTF-8 e testo vuoto. Non limitarsi al mock PdfReader esistente.
- [ ] Per ciascuna sezione accumulare paragrafi fino al tetto; emettere chunk e
      portare al successivo coda di massimo overlap caratteri. Per singolo paragrafo
      lungo usare finestre. Nessuna perdita di parole, nessun ciclo senza avanzamento.
- [ ] Verificare pagina mantenuta, confini rispettati e heading disponibile;
      testare size/overlap invalidi e limite numero chunk prima di embed.
- [ ] `parse_worker` legge file locale, emette JSON limitato su stdout. Parent usa
      subprocess asincrono, impone timeout e termina/attende child su timeout/cancel.
      Non scambiare timeout di un thread per arresto effettivo del parser.
- [ ] Limitare pagine prima dell'estrazione e caratteri durante l'accumulo.

**Verifica:** `uv run pytest tests/unit/test_ingestion_parsing.py tests/unit/test_ingestion_chunking.py tests/unit/test_parse_process.py -q`.
**Gate:** provenienza PDF dimostrata con fixture reale; timeout non lascia subprocess.

## Task 4 — Pipeline con transazioni brevi e fencing

**File:** modificare `server/graft/ingestion/{pipeline,store}.py`;
creare `server/graft/ingestion/jobs.py`; aggiornare
`server/tests/integration/test_ingestion_pipeline.py` e creare
`server/tests/integration/test_ingestion_concurrency.py`.

**Interfacce:** `claim_document(session, document_id: UUID, now: datetime) -> UUID | None`,
`heartbeat_document(session, document_id: UUID, run_id: UUID, now: datetime) -> bool`,
`finish_document(session, document_id: UUID, run_id: UUID, fingerprint: str, chunks: list[Chunk]) -> bool`.
Queste funzioni possiedono una transazione breve ciascuna; provider fuori transazione.
Pipeline riceve sessionmaker, document_id ed embedder; non un ORM object affidato
per tutta la durata. Aggiornare tutti i chiamanti/test del vecchio contratto.

```sql
UPDATE documents
SET status = 'processing', ingestion_run_id = :run_id,
    lease_expires_at = :lease_end, attempt_count = attempt_count + 1
WHERE id = :id AND
  (status = 'pending' OR (status = 'processing' AND lease_expires_at < :now))
RETURNING id;
```

- [ ] Test fallisce→retry riesce: status ready e error null. Cambiare test vuoto
      perché ora failed/no_extractable_text è comportamento deliberato.
- [ ] Testare due claim concorrenti: un solo vincitore. Commit vecchio run dopo
      nuova lease: nessuna modifica ai chunk. Delete durante embed: nessuna resurrezione.
- [ ] Fare parsing ed embedding in batch fuori transazione; controllare dimensioni
      fra batch, quantità vettori e fingerprint prima di pubblicare risultato.
- [ ] Commit finale: SELECT FOR UPDATE documento; verificare token e config;
      delete+insert chunk+ready atomici. Se row manca o token differisce, scartare.
- [ ] Failure aggiorna solo il run ancora proprietario. Salva codice sanificato;
      mantiene vecchi chunk ma li esclude tramite status. Heartbeat in task cancellabile.

**Verifica:** `uv run pytest tests/integration/test_ingestion_pipeline.py tests/integration/test_ingestion_concurrency.py -q`.
**Gate:** crash/errore non espone dataset parziale e lavoro obsoleto non sovrascrive dati.

## Task 5 — Login owner e API minime documenti/bot

**File:** creare `server/graft/security/auth.py`, `server/graft/cli.py`,
`server/graft/api/admin.py`, `server/graft/api/schemas.py`;
modificare `server/graft/main.py`, `server/pyproject.toml`, `server/uv.lock`;
test `server/tests/integration/test_admin_api.py`.

**Consuma:** storage task 2, config provider task 1. **Produce:** endpoint spec §6,
inizialmente upload pending; dispatcher task 6 completerà l'elaborazione.
Riutilizzare FastAPI Users già dipendenza. Aggiungere multipart solo quando richiesto
dalla route upload. Verificare API della versione risolta, senza copiare codice obsoleto.

- [ ] Test anonimo 401, viewer/editor 403 in questa release, owner attivo ammesso,
      owner disattivato respinto. Nessuna route di registrazione pubblica.
- [ ] CLI crea primo owner con password nascosta; due esecuzioni concorrenti non
      creano due owner: lock transazionale DB sull'operazione bootstrap.
- [ ] Schema bot separa input/output; widget key generata con `secrets.token_urlsafe(32)`.
      API key cifrata prima del DB, response ha soltanto has_api_key.
- [ ] PATCH embeddings prende lock riga bot, controlla documenti e restituisce 409
      se fingerprint cambia. Upload prende lo stesso lock: test race upload/PATCH.
- [ ] Upload legge a blocchi fino al limite, salva originale e DB; filename non guida
      storage. Errori 413 dimensione, 415 formato, 404 bot, 409 retry stato incompatibile.
- [ ] Retry porta failed→pending, azzera tentativi/error, invalida vecchio run.
      Delete DB prima del file; cleanup fallito genera codice operativo, non rollback
      di dati già revocati. Provider test usa chiamate minime reali, non solo models.list.

**Verifica:** `uv run pytest tests/integration/test_admin_api.py -q`.
**Gate:** nessuna operazione admin anonima; chiavi assenti da JSON/log; race config risolta.

## Task 6 — Worker Redis, dispatcher e recupero

**File:** creare `server/graft/ingestion/{queue,worker}.py`;
modificare `server/pyproject.toml`, `server/uv.lock`, `docker-compose.yml`,
`server/entrypoint.sh`; test `server/tests/integration/test_ingestion_worker.py`.

**Interfacce:** `enqueue_document(redis, document_id: UUID) -> None`;
arq job `ingest_job(ctx, document_id: str)`; periodic `dispatch_pending(ctx)`;
CLI worker `uv run arq graft.ingestion.worker.WorkerSettings`.

```python
await redis.enqueue_job("ingest_job", str(document_id),
                        _job_id=f"ingest:{document_id}")
```

- [ ] Bloccare versione arq compatibile nel lockfile; `max_jobs=1`, `keep_result=0`,
      timeout 600s. Configurare Redis AOF con volume. No file bytes/segreti nei job.
- [ ] Dispatcher ogni 60s interroga DB pending o lease scaduta; enqueue duplicato
      è innocuo. Redis offline dopo commit upload non perde il documento.
- [ ] Worker claim→pipeline; auth/invalid document failed immediato; transient retry
      10s/30s, massimo tre claim. Esaurimento claim porta failed anche su crash ripetuti.
- [ ] Testare crash prima di enqueue, durante embed, dopo commit prima ack, Redis
      riavviato, job duplicato, documento eliminato. Usare DB e Redis reali con fake embedder.
- [ ] Avvio Compose: app migra, app healthcheck HTTP dopo avvio, worker dipende da
      app healthy e DB healthy. Worker entrypoint non esegue Alembic. Per upgrade,
      fermare worker prima di migrare e riavviarlo dopo readiness.

**Verifica:** `uv run pytest tests/integration/test_ingestion_worker.py -q`.
**Gate A:** upload autenticato → ready; worker terminato e riavviato completa senza
chunk duplicati. Registrare tempi e stati osservati. Non iniziare B con job persi.

## Task 7 — Retrieval corretto e corpus di valutazione

**File:** creare `server/graft/rag/{__init__,retrieval}.py`,
`server/tests/integration/test_retrieval.py`,
`server/tests/fixtures/rag/cases.json`, `server/tests/fixtures/rag/documents/`.

**Interfaccia:** `retrieve(session, bot_id: UUID, fingerprint: str, query_vector: list[float], *, top_k: int = 5, min_score: float = 0.5) -> list[RetrievedChunk]`.
`RetrievedChunk`: dataclass con chunk_id, document_id, content, score, filename,
page, heading. Ordine score desc, chunk_id come tie-break.

```sql
WITH eligible AS MATERIALIZED (
  SELECT c.* FROM chunks c JOIN documents d ON d.id = c.document_id
  WHERE c.bot_id = :bot_id AND d.bot_id = :bot_id AND d.status = 'ready'
    AND d.embedding_fingerprint = :fingerprint
    AND c.embedding_dim = :dim AND vector_dims(c.embedding) = :dim
)
SELECT *, 1 - (embedding <=> :query_vector) AS score
FROM eligible
WHERE 1 - (embedding <=> :query_vector) >= :min_score
ORDER BY embedding <=> :query_vector, id LIMIT :top_k;
```

- [ ] Usare bind vector tipizzato pgvector, mai interpolare SQL. Join filename e
      metadata alla query effettiva per produrre RetrievedChunk.
- [ ] Testare bot A/B con dimensioni diverse, stessa dimensione ma fingerprint diverso,
      failed e legacy esclusi, soglia, ordinamento e zero vettori respinti.
- [ ] Creare almeno 20 domande: 8 rispondibili, 6 assenti, 3 parziali, 3 discordanti;
      ogni caso ha id, domanda, documenti attesi, fatti attesi, deve_astenersi.
- [ ] Fixture includono istruzioni malevole nel documento; non devono diventare
      istruzioni di sistema. Test DB con vettori noti, valutazione live separata.

**Verifica:** `uv run pytest tests/integration/test_retrieval.py -q`.
**Gate:** nessun confronto cross-bot/dimensione e nessun dato legacy usato per errore.

## Task 8 — Orchestrazione RAG, prompt, errori e citazioni

**File:** creare `server/graft/rag/{prompt,service}.py`,
`server/tests/unit/test_rag_prompt.py`, `server/tests/integration/test_rag_service.py`.

**Interfacce:** `build_messages(question, history, sources, system_prompt) -> list[ChatMessage]`;
`answer_question(...) -> AsyncIterator[dict]` emette gli eventi delta/done/error
definiti dalla spec. Consuma retrieve e provider esistenti, non introduce agent framework.

- [ ] Test nessun contesto con fake LLM che solleva se chiamato: ritorna fallback
      e zero chiamate. Test contesto presente con `[S1]` valido e `[S99]` invalido.
- [ ] Taglia contesto entro budget prima della chiamata; assegna etichette solo ai
      chunk inclusi. History arriva dal DB, mai dal payload del visitatore.
- [ ] Prompt esplicita limite documentale, astensione, fonti, contenuto non fidato;
      system_prompt del bot non può rimuovere istruzione di grounding del prodotto.
- [ ] Validatore controlla esistenza citazioni, non pretende di dimostrare entailment.
      Risposta con contesto ma senza alcuna citazione valida termina invalid_citation.
- [ ] Errori/cancel liberano stream/client; nessun retry dopo prima delta. Non
      salvare assistant incompleto come risposta valida.

**Verifica:** `uv run pytest tests/unit/test_rag_prompt.py tests/integration/test_rag_service.py -q`.

## Task 9 — Chat pubblica, SSE, CORS e limiti

**File:** creare `server/graft/api/chat.py`, `server/graft/security/origins.py`,
`server/graft/security/rate_limit.py`; modificare main e modelli se richiesto dai
vincoli; test `server/tests/integration/test_chat_api.py`,
`server/tests/integration/test_rate_limit.py`, `server/tests/unit/test_origins.py`.

**Interfaccia:** POST/frames spec §7. Error JSON pre-stream:
`{"error":{"code":"...","request_id":"..."}}`. Codici HTTP 400 input,
403 origin, 404 bot, 429 limit, 503 dipendenze. SSE error non cambia HTTP già inviato.

```python
def encode_sse(event: str, payload: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()
```

- [ ] Rimuovere fallback CORS wildcard attuale per chat. Test OPTIONS autorizzato,
      POST altro bot stesso origin vietato, assente/null vietato, Vary presente.
- [ ] Rate counters e TTL in operazione atomica Redis; lease concorrenza con TTL e
      rinnovo, rilascio owner-safe su done/error/disconnect. Redis offline fail closed.
- [ ] Session server-generated, lookup per bot; massimo una richiesta contemporanea
      per conversazione (lease), seconda 409 per evitare history fuori ordine.
- [ ] Persist user/request_id iniziale e stato tentativo, poi assistant+citazioni
      e completamento user in una transazione finale. Su restart richiesta incompleta
      resta cancelled. Nessun endpoint pubblico per leggere altre conversazioni.
- [ ] Test ordine meta/delta/done, UTF-8, error midstream senza done, disconnect,
      rate limit concorrente, sessione di altro bot, input oltre limite.
- [ ] Header `Cache-Control: no-cache`, disabilitare buffering proxy nella guida;
      heartbeat SSE ogni 15s e cancellazione task in finally.

**Verifica:** `uv run pytest tests/unit/test_origins.py tests/integration/test_chat_api.py tests/integration/test_rate_limit.py -q`.
**Gate:** nessuna chiamata provider prima di controlli accesso/quote.

## Task 10 — Widget minimo su pagina reale

**File:** creare `widget/package.json`, lockfile npm, `widget/tsconfig.json`,
`widget/src/{index,sse}.ts`, `widget/tests/sse.test.ts`, `widget/tests/widget.test.ts`,
`examples/embed.html`; aggiungere mount statico a main.

**Contratto build:** `npm run build` produce `widget/dist/graft.js` singolo bundle;
`npm test` test deterministici; `npm run test:e2e` browser smoke. Usare bundler
minimo con versione fissata; nessun framework runtime. Toolchain dev distinta da runtime.

- [ ] Parser SSE accumula buffer e consuma frame completi; decoder UTF-8 streaming,
      supporta CRLF, commenti heartbeat e più righe data. Test suddivisione frame
      in ogni possibile byte boundary, inclusi caratteri multibyte.
- [ ] `document.currentScript` letto subito; backend base ricavata da URL script,
      bot da data-graft-bot. Shadow DOM contiene launcher, log e form.
- [ ] Usare textContent per output nella prima release; niente HTML/Markdown non
      sanificato. Fonti espandibili da done mostrano filename, pagina, estratto.
- [ ] Input label, button accessibili, focus al pannello, Escape chiude e restituisce
      focus; aria-live moderato, mobile 320px senza overflow. Stato errore riabilita invio.
- [ ] Sessione solo in memoria. Abort su chiusura richiesta/distruzione widget;
      non confondere chiusura pannello con eliminazione conversazione.
- [ ] Pagina demo servita via HTTP su porta diversa; verificare CSS ospite aggressivo,
      due inizializzazioni accidentali senza duplicare lo stesso widget.

**Verifica:** da widget `npm ci`, `npm test`, `npm run build`, `npm run test:e2e`.
**Gate:** una riga script mostra risposta con fonte su pagina esterna al backend.

## Task 11 — Valutazione RAG live e compatibilità minima

**File:** creare `server/tests/live/test_rag_live.py`, `server/scripts/evaluate_rag.py`,
`docs/evidence/rag-baseline.md`; consumare fixture task 7.

**Interfaccia CLI:** `uv run python scripts/evaluate_rag.py --cases tests/fixtures/rag/cases.json --output /tmp/graft-rag-results.json`.
Output per caso: provider/modello/fingerprint, chunk recuperati, risposta, citazioni,
tempi retrieval/primo token/totale, esito revisione umana. Mai chiavi o dati privati.

- [ ] Test live opt-in e credenziali da env dedicato. Scegliere primo provider con
      chiave disponibile dal collega; documentare esatto modello e data, non simulare.
- [ ] Eseguire almeno tre passaggi sui 20 casi. Metriche: fonti attese recuperate,
      citazioni valide, astensioni corrette, fatti supportati, contraddizioni rilevate.
- [ ] Gate iniziale: isolamento 100%; riferimenti inesistenti 0; 6/6 assenti con
      astensione per ogni passaggio; almeno 7/8 rispondibili corrette per passaggio;
      parziali e discordanti riviste manualmente senza affermazioni inventate.
- [ ] Se fallisce: distinguere parsing, retrieval e generazione; cambiare una sola
      variabile, ripetere e registrare confronto. Non aggiungere framework per mascherare errore.
- [ ] Riportare tempi osservati, senza inventare SLO universale dipendente dal provider.

**Gate B:** demo widget + report live con criteri superati. Se manca chiave, B resta
non verificato; unit test verdi non sostituiscono questo gate.

## Task 12 — Admin essenziale e consultazione conversazioni

**File:** creare `server/graft/static/admin/{index.html,app.js,style.css}`;
completare admin API task 5; test `server/tests/integration/test_admin_conversations.py`
e browser in `widget/tests/admin.test.ts` (harness riusato, non seconda toolchain).

- [ ] Login, elenco/creazione bot, configurazione provider, upload, polling stato,
      retry failed, delete, script da copiare e lettura conversazioni paginata.
- [ ] Poll ogni 3s soltanto con documenti pending/processing, stop al cambio pagina;
      segnalare worker indisponibile senza polling illimitato nascosto.
- [ ] UI distingue chiave impostata da campo vuoto; nessun token in localStorage.
      Spiegare che documenti del bot sono utilizzati da visitatori anonimi.
- [ ] Test login→bot→upload→ready→copia script, errore→retry e guard config embeddings 409.
      Filtri/listing di conversazioni sempre tramite bot autorizzato.

**Gate:** owner completa onboarding senza curl o accesso diretto DB.

## Task 13 — Deploy riproducibile, migrazione legacy, restore

**File:** modificare `server/Dockerfile`, `server/entrypoint.sh`, `docker-compose.yml`,
`.env.example`, `README.md`; creare `docker-compose.dev.yml`,
`docs/operations/first-release.md`; estendere `server/graft/cli.py`.

- [ ] Docker copia pyproject e uv.lock prima del sync frozen. Fissare versione/digest
      uv; includere build widget tramite stage Node fissato e npm ci. Nessun tool dev
      necessario a runtime. Verificare l'entrypoint con dipendenze già installate.
- [ ] App/worker condividono originali; DB/Redis persistenti; porte DB/Redis soltanto
      override dev. Health app prova DB, Redis e directory storage accessibile.
- [ ] CLI `legacy-report` elenca documenti senza fingerprint/originale; non inventa
      hash e non elimina chunk. Guida ricaricamento bot nuovo e conservazione legacy.
- [ ] CLI `cleanup-conversations --days 30` elimina per data con cascade messaggi;
      `cleanup-orphan-files --dry-run` elenca soltanto. Delete file richiede flag esplicito.
- [ ] Guida backup: fermare upload/worker, dump DB e volume coerenti, custodire Fernet;
      restore in ambiente temporaneo, decrypt test + lettura originale + query.
- [ ] Test installazione da clone pulito, bootstrap owner, ingest, restart worker,
      restart Redis, restore. Upgrade con worker fermo e migrazione una volta.
- [ ] Correggere README: script singolo riguarda integrazione frontend, non elimina
      setup TLS/CSP/reverse proxy. Documentare CSP script-src e connect-src, SSE buffering.

**Verifica:** `docker compose config --quiet`, `docker compose build`,
`docker compose up -d`; verifiche HTTP e smoke documentate con esiti reali.
Non lanciare comandi distruttivi su volumi esistenti per dimostrare restore.

## Task 14 — CI, documentazione finale e release gate

**File:** creare `.github/workflows/checks.yml`; aggiornare README, wiki engineering,
`wiki/project/{status,roadmap}.md`, `wiki/agent/{context,handoff,activity}.md`.

- [ ] CI backend: uv sync locked, unit, ruff, integration con Docker; CI widget:
      npm ci/test/build e smoke browser. Live separato e manuale con segreti protetti.
- [ ] Migrazioni corrispondono ai modelli; test warning-free. Nessuna credenziale
      richiesta per checks standard. Documentare baseline e limiti residui.
- [ ] Inserire report gate A/B/C e istruzioni eseguibili per nuovo collega.
- [ ] Prima distribuzione pubblica, proprietario sceglie licenza: non assegnarla
      arbitrariamente. Fino ad allora consegna privata tecnicamente verificata.

**Gate C:** installazione da zero e restore riusciti, owner usa admin, sito usa widget,
check CI verdi, limiti e provider verificati dichiarati senza promesse assolute.

## Task 15 — Estensione RBAC dopo prima release

**File:** estendere `security/auth.py`, `api/admin.py`, `models/bot.py` se necessario;
test `tests/integration/test_rbac.py` sotto server.

- [ ] Rimuovere limite a un owner solo quando aggiunta gestione utenti owner-only.
      Impedire eliminazione/disattivazione ultimo owner attivo con lock transazionale.
- [ ] Owner vede tutto; editor configura/documenta soltanto bot_members assegnati;
      viewer legge bot e conversazioni secondo matrice della specifica originale.
      Nessun ruolo legge chiavi in chiaro. Assegnazioni modificabili solo owner.
- [ ] Implementare API utenti e membership; per ogni endpoint test positivo e negativo,
      incluso accesso diretto document_id/conversation_id senza passare da elenco bot.
- [ ] Rivalutare con proprietario accesso globale viewer alle conversazioni prima
      di usarlo con team reali; se restringe, aggiornare matrice e test insieme.

**Gate:** matrice autorizzazioni verificata sul backend prima di nascondere pulsanti UI.

## Task 16 — Refine e validazione degli altri provider

**File:** creare `admin/` con package/lockfile e dataProvider per API esistenti;
estendere `server/tests/live/` per provider e `docs/evidence/provider-matrix.md`.

- [ ] Refine + Ant Design sostituisce UI essenziale mantenendo API e URL; non creare
      seconda API. dataProvider converte offset/limit e items/total; authProvider
      riusa login e accessControl riflette RBAC senza sostituirlo.
- [ ] Testare login, CRUD, upload/retry, assegnazioni e conversazioni per ruolo.
      Rimuovere vecchia UI solo dopo parità; aggiornare Docker a un solo admin build.
- [ ] Per ciascun backend già dichiarato: chat, stream interrotto, embeddings quando
      disponibili, modello errato, auth errata; registrare data/modello/esito.
      Anthropic usa embeddings separati. Non confondere models.list con prova modello.
- [ ] Parser opzionale entra in un piano distinto soltanto con fixture reali che
      pypdf non gestisce; ANN soltanto con benchmark che dimostri il limite KNN.

## Mappa dalla roadmap precedente

| Vecchio elemento | Nuova destinazione |
|---|---|
| Fasi 1/2/3a completate | Conservate; correzioni task 0–4 |
| Fase 3b worker | Task 2–6, include storage anticipato |
| Fase 4 RAG/chat | Task 7–9 e valutazione task 11 |
| Fase 5 auth/RBAC | Auth task 5; RBAC task 15 |
| Fase 6 Admin API | Minimo task 5; completamento task 12 |
| Fase 7 Refine | Task 16; UI essenziale task 12 |
| Fase 8 widget | Anticipata task 10 |

## Handoff da copiare al collega

> Parti da c16dbae o dal suo discendente attuale. Leggi prima la spec del
> 2026-09-10, poi questo piano. Conserva codice e dati esistenti. Esegui task 0–6
> fino al gate A, quindi 7–11 fino al gate B e 12–14 fino alla prima release.
> Non saltare isolamento, auth, controlli sui job o valutazione live per anticipare
> la demo. Non costruire task 15–16 prima della validazione della prima release.
> Per ogni PR riporta file cambiati, test eseguiti e limiti ancora aperti.
> Se il codice corrente diverge dalla baseline, riallinea il piano al diff prima
> di implementare. Non trattare questo documento come prova di test già passati.
