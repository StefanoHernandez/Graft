# Operating a Graft instance

Everything here has been run against a real stack, except where it says otherwise.

## What must survive

Three things, and losing any one of them is a different kind of bad day:

| | Where | If you lose it |
|---|---|---|
| The database | `graft_db` volume | Bots, documents, chunks and transcripts are gone |
| The originals | `graft_uploads` volume | Documents cannot be re-ingested; they must be uploaded again |
| `ENCRYPTION_KEY` | your `.env` | **Every stored provider key becomes unreadable.** The rows survive and decrypt to nothing; each bot needs its key entered again |

The Redis volume is not on that list. It holds queued jobs, and the worker rebuilds the
queue from the database every minute — losing it costs latency, not work.

## Upgrading

Migrations run **once**, from the app's entrypoint. The worker deliberately does not run
Alembic: if both did, every deploy would be a race.

```bash
docker compose stop worker          # let the current job finish or be re-claimed later
git pull
docker compose build
docker compose up -d app            # runs `alembic upgrade head`, then serves
docker compose up -d worker         # starts only once the app reports ready
```

Stopping the worker mid-job is safe. The document keeps its lease, the lease expires, and
the per-minute sweep re-queues it. A worker killed between committing a result and
acknowledging the job replays it, sees the document is already `ready`, and exits.

## Backup

Take both volumes from the same quiet moment, and keep the Fernet key somewhere else.

```bash
docker compose stop worker app      # no uploads and no ingestion while copying

docker compose exec -T db pg_dump -U graft graft | gzip > graft-db-$(date +%F).sql.gz

docker run --rm -v graft_graft_uploads:/data -v "$PWD":/out alpine \
  tar czf /out/graft-uploads-$(date +%F).tar.gz -C /data .

docker compose start app worker
```

`ENCRYPTION_KEY` belongs in a password manager or a secrets store, **not** next to the
dump. A backup that contains both is a backup that leaks every provider key if it leaks.

## Restore, verified

A restore nobody has tested is a hope. Do this into a throwaway project name so the live
instance is never touched:

```bash
COMPOSE_PROJECT_NAME=graft-restore docker compose up -d db redis

gunzip -c graft-db-2026-09-11.sql.gz | \
  COMPOSE_PROJECT_NAME=graft-restore docker compose exec -T db psql -U graft graft

docker run --rm -v graft-restore_graft_uploads:/data -v "$PWD":/in alpine \
  tar xzf /in/graft-uploads-2026-09-11.tar.gz -C /data

COMPOSE_PROJECT_NAME=graft-restore docker compose up -d app worker
```

Then prove three separate things, because each can fail on its own:

1. **The key still decrypts.** Open `/admin/`, pick a bot, press **Test connection**. A
   green answer means the Fernet key in this environment matches the one that encrypted
   the stored keys.
2. **An original is readable.** In the same bot, press **Try again** on any document (or
   upload a small new one) and watch it reach *Ready to answer*. That reads the file off
   the restored volume and runs it through the real provider.
3. **Retrieval answers.** Ask the widget, or `curl` the chat endpoint, a question the
   corpus can answer, and check that the reply carries a citation.

Then tear the copy down: `COMPOSE_PROJECT_NAME=graft-restore docker compose down -v`.

## Routine cleanup

All three commands report by default and only act with `--apply`.

```bash
# conversations older than 30 days, messages follow by cascade
docker compose exec app /app/.venv/bin/python -m graft.cli cleanup-conversations --days 30
docker compose exec app /app/.venv/bin/python -m graft.cli cleanup-conversations --days 30 --apply

# stored originals with no document row (a delete whose file cleanup failed)
docker compose exec app /app/.venv/bin/python -m graft.cli cleanup-orphan-files
docker compose exec app /app/.venv/bin/python -m graft.cli cleanup-orphan-files --apply
```

A daily cron for the first is reasonable. The second is a sweep, not a schedule: run it
when the disk looks larger than the document list explains.

## Documents from before the lifecycle migration

Migration `0003` added the stored original and the embedding fingerprint. Rows written
before it have neither, so retrieval skips them — deliberately, because their vectors
belong to an unknown model and comparing them would produce a confident answer built on
the wrong corpus.

```bash
docker compose exec app /app/.venv/bin/python -m graft.cli legacy-report
```

It lists them and changes nothing. There is no migration path that recovers them: the
original file was never kept, and a document cannot be rebuilt from its chunks. To bring
that content back, upload the files again to a bot whose embedding configuration is the
one you intend to keep. The old rows stay where they are; nothing deletes them for you.

## Things that will look like bugs and are not

- **A document sits in "Waiting to be read".** The worker is not running, or cannot reach
  Redis. The admin stops polling after a minute and says so rather than spinning forever.
  Check `docker compose logs worker`.
- **A document fails three times and stops.** That is the ceiling. Fix the cause — usually
  a provider key or a scanned PDF — and press **Try again**, which resets the count.
- **The embedding model cannot be changed.** Once a bot has documents, changing it is
  refused with `409`. Old and new vectors are not comparable, so the only honest options
  are a new bot or a re-upload. Rotating the *key* is always allowed.
- **Every answer arrives at once instead of streaming.** A proxy is buffering. See the
  reverse-proxy notes in the README.

## Not covered here

No high-availability story, no multi-node deployment, no object storage: the app and the
worker share a local volume, so they must run on the same host. Nothing in this document
has been tested under load.
