# Deploy the internship app

The prepared target is **Railway**, with two Docker services and your existing
Neon PostgreSQL provider. This is a single-instance internship demo deployment.
Neither service has been published, and no paid resources have been created.

## What runs where

```text
Browser --HTTPS--> Next.js frontend
                       |
                   /api/* proxy (private network)
                       |
                  FastAPI backend
                    |       |          |
                 Neon DB  /data      Gnani + hosted LLM
                          volume
```

The browser uses the same `/api` paths as local development. Keep the backend
private. A persistent volume stores original recordings; PostgreSQL stores
filenames, statuses, transcripts, and summaries. Temporary WAV chunks are removed
after processing. Credentials belong only in backend service variables.

## Choose hosting

| Option | Fit for this project |
| --- | --- |
| Railway | Recommended: two Docker services, private networking, persistent volume, and managed HTTPS. Hobby starts at $5/month with $5 of usage included; total usage can exceed this. |
| Render | Good alternative. Starter services begin at $7/month each; persistent disks cost extra and require paid compute. |
| Heroku | Possible, but its ephemeral filesystem means original audio needs object storage. That requires more code changes than the volume approach. |
| Cloud VM | These Dockerfiles also work on a VM. You manage HTTPS, updates, backups, and uptime yourself. |

Pricing checked on 2026-10-03. See [Railway pricing](https://docs.railway.com/pricing/plans),
[Render pricing](https://render.com/pricing), and
[Heroku filesystem rules](https://devcenter.heroku.com/articles/dynos#ephemeral-filesystem).
LLM and speech-provider usage have separate costs.

## 1. Set up cloud configuration

Use a **separate database or Neon branch** for this deployment. The local computer
and cloud container must not run jobs against the same `uploads` table: container
startup marks interrupted jobs retryable, and local disk files do not exist in
the cloud automatically.

Set these backend variables in Railway, without committing their values:

| Variable | Value / purpose |
| --- | --- |
| `DATABASE_URL` | Deployment PostgreSQL connection URL. `postgresql://` and `postgresql+asyncpg://` are supported; Neon `sslmode=require` is translated for asyncpg. |
| `GNANI_API_KEY` | Your speech-provider credential. |
| `LLM_BASE_URL` | A reachable OpenAI-compatible chat endpoint base ending in `/v1`. |
| `LLM_MODEL` | The exact model identifier supported by that endpoint. |
| `LLM_API_KEY` | Hosted LLM bearer credential, if its endpoint requires authentication. |
| `STORAGE_DIR` | `/data`, matching the attached volume. |
| `APP_ENV` | `production`. |
| `PORT` | `8010`, fixed so the frontend private URL stays predictable. |
| `HOST` | `0.0.0.0` for a new Railway environment with IPv4 private networking. |
| `RAILWAY_RUN_UID` | `0` for the backend volume; Railway mounts volumes as root. |

Ollama on your laptop (`localhost:11434`) is not reachable from a cloud container.
Use a hosted compatible endpoint, or run Ollama as another private service with
sufficient memory and a downloaded model. Merely setting `LLM_API_KEY` does not
change the model or create an LLM service. Startup rejects a localhost summary
endpoint in production so this mistake is caught immediately.

The backend Dockerfile normally runs as an unprivileged user. Railway documents
the UID override for its root-owned volumes:
[volume permissions](https://docs.railway.com/volumes#permissions).

## 2. Create the backend Railway service

1. Commit/push the prepared files yourself when ready. Connect Railway to that
   GitHub repository; grant access to the specific private repository.
2. Create a service named `backend`, set its **Root Directory** to `/backend`.
   Railway detects `Dockerfile` there. Keep its Start Command empty so the
   Dockerfile's `python -m app.start` is used.
3. Add the variables above and attach a persistent volume mounted at **`/data`**.
4. Set the healthcheck path to **`/ready`**, timeout to 120 seconds.
5. Use **one replica** and disable serverless/app sleeping for background work.
   Keep this service private: it does not need a public domain.

Startup verifies storage, creates missing tables on a fresh database, and marks
previous `transcribing`/`summarizing` rows `failed` with a retry message. Completed
transcripts survive, so a summary retry can reuse them. Startup does **not**
silently retry paid speech requests. This is manual recovery, not a durable queue.

`create_all` does not migrate an existing table. If using an old database with
missing columns, apply a reviewed migration separately; `/ready` checks every
mapped column and fails until the schema is compatible.

## 3. Create the frontend Railway service

1. Add another service from the same repository named `frontend`.
2. Set Root Directory to **`/Frontend`** (capital F matters on Linux).
3. Set **`BACKEND_URL=http://backend.railway.internal:8010`** before building.
   Use the backend's actual private domain if you named the service differently.
4. Set `PORT=3000`; keep Start Command empty to use `node server.js`.
5. Set healthcheck path **`/api/ready`**, timeout 120 seconds.

The frontend build argument becomes its server-side rewrite destination.
**Rebuild/redeploy the frontend after changing `BACKEND_URL`.** Setting only a
runtime variable on an already-built image will not replace those rewrites.
Both services must be in the same project environment and region.

The frontend image includes Next.js standalone output, public files, and static
assets. No Node development server is used in production.

## 4. Access and launch

This application currently has **no login or per-user recording permissions**.
Anyone who can reach it can list recordings and submit jobs. Before generating
a public frontend domain, place it behind an authenticated access gateway or
add application authentication. Use a fresh demo database and non-sensitive
sample audio. Keeping the backend private does not authenticate requests coming
through the frontend proxy.

After access protection and both service healthchecks are ready, generate the
frontend HTTPS domain on port 3000. Verify:

1. `/api/live` returns `{"status":"ok"}`.
2. `/api/ready` returns `{"status":"ready"}`.
3. Upload one short sample, start processing, and retrieve transcript/summary.
4. Confirm cloud logs show successful Gnani and LLM requests without credentials.
5. Restart the backend after the job completes; the recording/results should
   remain. Original audio must still be under `/data/audio/`.
6. Check Copy and Download .txt in an ordinary browser over HTTPS.

## Optional: verify containers locally or on a private VM

Docker Engine/Desktop is a system runtime, not a package in a Python venv.
The current computer has no available Docker CLI, so container builds/runs must
be checked on a machine with Docker or by the included GitHub workflow.

From the repository root in PowerShell:

```powershell
Copy-Item backend/.env.example backend/.env.production
# Edit .env.production: use a separate database, speech key, and hosted LLM settings.
docker compose build
docker compose up -d
```

Open `http://localhost:3005`. Compose binds only loopback; it keeps the backend
internal and stores audio in the named `audio-data` volume. The example
localhost LLM setting must be replaced before production startup can succeed.
`docker compose down` retains that volume. Do not use `down -v` when retaining
recordings. Back up both the database and audio volume; one does not replace the
other. Existing laptop recordings are not transferred by this setup.

For a VM, keep port 3005 private and put an HTTPS reverse proxy with access
authentication in front. Railway handles HTTPS for its generated domains.

## Limits that deployment does not remove

- One backend instance/worker; in-process tasks are interrupted by a crash or
  deploy. Wait for active jobs before redeploying. A failed job can be manually
  retried, but a speech chunk sent before a crash might incur another charge.
- Summaries currently accept at most **8,000 UTF-8 bytes** of transcript.
  Longer transcripts retain their transcription but need chunked summarization
  before the summary can finish. No semantic-quality guarantee comes from unit tests.
- Upload size/concurrency quotas, durable queued workers, and user isolation are
  future work. This configuration is for a controlled demo, not unrestricted
  public traffic or horizontal scaling.

## Files prepared

- `backend/Dockerfile`, `Frontend/Dockerfile`: production service images.
- `.dockerignore` in each directory: excludes credentials, recordings, and local environments.
- `backend/requirements.in`, `requirements.txt`, `requirements-dev.txt`: runtime pins/lock and separate tests.
- `backend/app/start.py`: container initialization and interrupted-job recovery.
- `backend/app/health.py`, `/ready`: schema/storage readiness checks.
- `LLM_API_KEY`: hosted-summary authentication while preserving keyless local Ollama.
- `compose.yaml`: two services and persistent audio volume.
- `.github/workflows/ci.yml`: isolated tests, lint, and Linux Docker builds when pushed.

Official deployment references:
[Railway Dockerfiles](https://docs.railway.com/builds/dockerfiles),
[private networking](https://docs.railway.com/networking/private-networking),
[volumes](https://docs.railway.com/volumes),
[Next.js self hosting](https://nextjs.org/docs/app/guides/self-hosting).

## Local verification on 2026-10-03

- All 14 backend tests passed, including hosted LLM header handling, restart
  recovery, and readiness failures. Provider requests were mocked.
- Frontend lint, production compilation, and TypeScript checks passed.
- The standalone production server served the page (HTTP 200) and proxied
  `/api/live`, `/api/ready`, a WAV upload (201), and retrieval (200).
- The smoke test used an isolated SQLite database and generated silent WAV,
  not the live Neon database or a paid transcription request. Metadata and
  original audio survived a backend restart.
- Runtime dependencies resolved for Python 3.12/Linux. Compose and GitHub
  workflow YAML parsed successfully; Git whitespace checks passed.
- Docker image builds, Linux runtime behavior, hosted LLM connectivity, and
  Railway healthchecks remain to be verified in CI/the deployment environment.
  The local production check ran directly on Windows, not inside containers.
