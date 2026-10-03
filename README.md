# Sonora · Gnani.ai Audio Notes

Turn audio recordings into searchable transcripts and concise AI summaries. Sonora combines a Next.js interface with a FastAPI backend, Gnani speech recognition, and an OpenAI-compatible summarization service.

**[Live demo](https://sonora-notes.up.railway.app/)** · **[Architecture](architecture.md)**

## Features

- Upload WAV, MP3, M4A, FLAC, or OGG recordings up to **50 MiB**.
- Transcribe audio in ordered chunks, with a **0–100% progress bar** updated after each completed chunk.
- Generate summaries through Groq in the deployed app, or Ollama locally.
- Copy or download transcripts and summaries as `.txt` files.
- Sign in with Google to save recordings and reopen private results.
- Try one recording per browser session as a guest.
- Retry failed processing; an existing transcript is reused when only summarization needs another attempt.

## How the application works

```text
Browser → Next.js /api proxy → FastAPI
                                ├─ FFmpeg → Gnani → transcript → Groq → summary
                                ├─ PostgreSQL: accounts, sessions, saved results
                                └─ Disk / Railway volume: audio files
```

1. **Upload:** the backend validates the recording and stores its audio file. Uploading does not start transcription automatically.
2. **Transcribe:** the frontend starts processing, then polls for updates. FFmpeg converts the audio to mono, 16 kHz WAV chunks, each at most 240 seconds long. Gnani transcribes them in order.
3. **Summarize:** the combined transcript is passed to the LLM. Long transcripts are split into bounded requests, summarized, and merged.
4. **Retrieve:** the frontend displays the transcript, summary, and status. Text downloads are generated in the browser.

Progress measures **completed chunks**, not elapsed time. For example, two chunks produce 0%, 50%, and 100%. The transcription bar can reach 100% while the summary is still being generated; the processing status distinguishes these stages.

### Guest and account storage

| Mode | Recording access | Result storage |
| --- | --- | --- |
| Guest | One recording per browser session | Temporary server memory; results expire after 60 minutes and are lost on backend restart |
| Google account | Private recording history | Audio on disk; metadata, transcripts, and summaries in PostgreSQL |

Sign in **before uploading** to save a recording. Signing in later does not import a guest result. PostgreSQL stores guest session and quota information, but does not store guest transcripts or summaries. Requests check recording ownership, and signing out revokes the session.

## Project structure

The tree below stops at two levels and omits dependencies, generated output, and local credentials.

```text
Gnani_Internship_Assignment/
├── Frontend/
│   ├── src/                     # Pages, layout, styles, and upload guard
│   ├── public/
│   ├── .env.example
│   ├── next.config.ts           # Backend rewrites and standalone build
│   ├── package.json
│   └── Dockerfile
├── backend/
│   ├── app/                     # Auth, database, audio, and provider logic
│   ├── tests/
│   ├── .env.example
│   ├── main.py                  # FastAPI application and upload routes
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   └── Dockerfile
├── .github/
│   └── workflows/               # CI checks
├── start-backend.ps1
├── start-frontend.ps1
├── compose.yaml
├── architecture.md
└── README.md
```

## Local initialization

### 1. Prerequisites and clone

Install **Python 3.12**, **Node.js 24 with npm**, and **Git**. Have a reachable PostgreSQL database and a Gnani API key ready. FFmpeg is supplied by the `imageio-ffmpeg` dependency.

The following commands use **PowerShell**. The repository is private, so cloning requires GitHub access.

```powershell
git clone https://github.com/SrthkL/Gnani_Internship_Assignment.git
cd Gnani_Internship_Assignment
```

### 2. Install the backend

From the repository root:

```powershell
py -3.12 -m venv backend/.venv
& ./backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
Copy-Item backend/.env.example backend/.env
```

Edit `backend/.env`. Supply `DATABASE_URL` and `GNANI_API_KEY`, then choose a summary provider:

```dotenv
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/DATABASE
GNANI_API_KEY=your-gnani-key
STORAGE_DIR=./storage
APP_URL=http://localhost:3000
AUDIO_CHUNK_SECONDS=240
```

For a hosted PostgreSQL database that requires TLS, use its provided connection URL. The backend accepts PostgreSQL URLs and translates `sslmode` options for the asyncpg driver. The database itself must exist before schema initialization.

**Option A — local Ollama**

Install and start Ollama, then download the model:

```powershell
ollama pull llama3.2:3b
```

Keep these settings in `backend/.env`:

```dotenv
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=llama3.2:3b
LLM_API_KEY=
```

**Option B — Groq, matching the live app**

```dotenv
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=openai/gpt-oss-20b
LLM_API_KEY=your-groq-key
```

Keep credentials in environment files or hosting variables. Never commit real keys.

### 3. Install the frontend

From the repository root:

```powershell
cd Frontend
npm.cmd ci
Copy-Item .env.example .env.local
cd ..
```

`Frontend/.env.local` should contain:

```dotenv
BACKEND_URL=http://127.0.0.1:8010
```

This is a server-side setting. Next.js compiles the backend rewrite during a production build, so rebuild after changing it.

### 4. Start both services

Open two PowerShell terminals at the repository root.

**Terminal 1 — backend**

```powershell
./start-backend.ps1
```

The script initializes database tables and applies the project's schema upgrades before starting FastAPI on port **8010**.

**Terminal 2 — frontend**

```powershell
./start-frontend.ps1
```

Open **http://localhost:3000**. Keep both terminals running.

| URL | Purpose |
| --- | --- |
| `http://localhost:3000` | Application |
| `http://127.0.0.1:8010/docs` | Interactive API documentation |
| `http://localhost:3000/api/live` | Process liveness |
| `http://localhost:3000/api/ready` | Database and storage readiness |

Use `localhost:3000` consistently because `APP_URL` controls the allowed browser origin. On Windows, the supplied backend script deliberately omits Uvicorn `--reload` so asynchronous FFmpeg subprocesses work reliably.

### 5. Enable Google sign-in

Guest processing works without Google credentials. To enable saved account history, create a **Web application** OAuth client in Google Auth Platform. Register:

```text
http://localhost:3000/api/auth/google/callback
https://sonora-notes.up.railway.app/api/auth/google/callback
```

Set these backend variables:

```dotenv
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
AUTH_SECRET=your-random-secret
```

Generate an authentication secret with:

```powershell
& ./backend/.venv/Scripts/python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

Restart the backend after changing settings. While the Google OAuth app is in **Testing**, only configured test users can sign in. The deployed OAuth configuration currently uses this mode.

## API overview

The frontend reaches these routes through `/api`; FastAPI serves them without that prefix.

| Method | Backend route | Purpose |
| --- | --- | --- |
| POST | `/uploads` | Upload multipart audio; returns a recording ID |
| POST | `/uploads/{id}/transcribe` | Start processing or retry a failed job |
| GET | `/uploads/{id}` | Retrieve status, progress, transcript, and summary |
| GET | `/uploads` | List the signed-in user's saved recordings |
| GET | `/auth/me` | Read the current session |
| GET | `/auth/google` | Start Google sign-in |
| GET | `/auth/google/callback` | Complete Google sign-in |
| POST | `/auth/logout` | Revoke the current session |
| GET | `/live`, `/ready` | Health checks |

Processing runs asynchronously inside the backend process. The start request returns before transcription finishes; clients poll the recording route for results.

## Validation

Install the backend test dependencies and run the suite:

```powershell
& ./backend/.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
cd backend
& ./.venv/Scripts/python.exe -m pytest tests -q --basetemp=./.pytest_cache/tmp
cd ..
```

The explicit temporary directory avoids Windows permissions problems with shared pytest folders. Tests cover audio chunking, authentication and ownership, storage failures, provider retries, summary chunking, and deployment configuration. Provider responses are mocked in the automated suite; real Gnani and LLM calls are separate integration checks.

Check the frontend:

```powershell
cd Frontend
npm.cmd run lint
npm.cmd run build
cd ..
```

GitHub Actions runs backend tests, frontend lint, and both Docker builds.

## Railway deployment

The deployed system uses **three services**: Next.js frontend, FastAPI backend, and PostgreSQL. A persistent volume mounted at `/data` retains saved audio. The frontend proxies requests to the private backend address.

| Service | Essential configuration |
| --- | --- |
| Frontend | Root `/Frontend`; `BACKEND_URL=http://backend.railway.internal:8010`; port `3000`; health check `/api/ready` |
| Backend | Root `/backend`; `APP_ENV=production`; `APP_URL=https://sonora-notes.up.railway.app`; `STORAGE_DIR=/data`; port `8010`; health check `/ready` |
| PostgreSQL | Backend `DATABASE_URL` references the database service |

Set Gnani, Groq, Google OAuth, and authentication secrets in Railway Variables. The hosted summary provider uses Groq with `openai/gpt-oss-20b`; a laptop's Ollama `localhost` address is not reachable from Railway.

The container entry point initializes the schema and marks interrupted saved jobs as failed so users can retry them. Keep the backend at **one worker and one replica**: guest results and background tasks are held in process memory. A durable queue and shared temporary store are needed before scaling to multiple instances.

The current Railway volume runs with `RAILWAY_RUN_UID=0` to allow writes to its root-owned mount. A deployment using a non-root container user needs matching volume permissions.

For service relationships and storage details, see [architecture.md](architecture.md).

## Current scope and future work

Processing currently uses one backend instance, temporary guest results, and persistent storage for signed-in recordings. Speaker diarization and a durable worker queue are not yet implemented.

- **Lossless audio compression:** evaluate FLAC for large recordings to reduce upload bandwidth and storage while preserving decoded audio samples. Benchmark compression cost and savings under concurrent use; pair it with shared storage and a durable queue to support more users.
- **Noise reduction before transcription:** explore wavelet analysis and empirical mode decomposition (EMD) to suppress noise while preserving speech. Compare transcript accuracy and processing time against unprocessed audio, and retain the original recording because denoising changes the signal.
