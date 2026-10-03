# Gnani Internship Assignment

A local audio notes project built incrementally with a FastAPI backend,
PostgreSQL, the Gnani batch transcription API, and a Next.js frontend.

## Google sign-in and private recordings

Guests can process one recording per browser session. Guest audio uses temporary
files; transcripts and summaries stay in server memory for 60 minutes after
processing, never in PostgreSQL. They disappear on expiry or server restart.
Sign in **before uploading** to save audio, transcripts and summaries privately
to your account. Signing in does not import a temporary guest result. Each API
request checks ownership; existing unowned demo recordings are inaccessible.
Browser session cookies are HttpOnly, and Secure in production. Signing out
revokes the session. Opening a new browser session starts a new guest allowance;
this is not a limit on a person's identity.

In [Google Auth Platform](https://console.cloud.google.com/auth/clients), create
a project, configure Branding and Audience, and create a **Web application**
OAuth client. While the Google app is in testing, add your account as a test user.
Register these authorized redirect URIs:

- Local: `http://localhost:3000/api/auth/google/callback`
- Railway: `https://frontend-production-ef98.up.railway.app/api/auth/google/callback`

Add these backend variables in your local `.env` or Railway Variables:

```dotenv
APP_URL=http://localhost:3000
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
AUTH_SECRET=your-random-secret-of-at-least-32-characters
```

For Railway, set `APP_URL=https://frontend-production-ef98.up.railway.app`.
Generate `AUTH_SECRET` with Python's `secrets.token_urlsafe(32)`. Keep both
secrets out of Git. Restart the backend after changing variables. Google sign-in
stays disabled until client credentials are supplied; production startup requires
an authentication secret and an HTTPS frontend origin.

The local startup script and container entry point apply the ownership migration
automatically. If starting Uvicorn manually, run `python -m app.init_db` first.
Guest jobs still require one backend instance; multiple replicas need a shared
temporary job store. PostgreSQL holds only guest session hashes, quota flags and
expiry timestamps, not guest transcripts.

## Start the project

Open two PowerShell terminals. These scripts locate the project themselves,
so your terminal's current directory does not matter.

Backend terminal:

```powershell
& "C:\Users\capta\Gnani_Internship_Assignment\start-backend.ps1"
```

Frontend terminal:

```powershell
& "C:\Users\capta\Gnani_Internship_Assignment\start-frontend.ps1"
```

Keep both terminals open. Open `http://localhost:3000` for the upload page.
Check `http://localhost:3000/api/live` for `{"status":"ok"}`.
If the frontend is already running, leave that terminal open instead of
starting a second copy.

See [architecture](architecture.md) for the Railway services, provider flow,
persistent storage, and deployment limitations.

## Initial goal

Accept an audio recording, retain the original file on local disk, and store
its metadata, processing status, and transcript in PostgreSQL. Clients will
retrieve results as JSON through the API.

Audio is normalized and split into bounded chunks before transcription.
Processing reports its stage; summaries reuse stored transcripts when retried.
The container entry point also makes interrupted jobs available for manual retry.

## Storage design

- Local disk retains original audio under `STORAGE_DIR/audio/`.
- PostgreSQL stores upload metadata, job state, and transcript text.
- Temporary audio conversion and chunk files are removed after processing.
- The frontend exports finished transcripts and summaries to text files.

## Local development prerequisites

- Git and Git Bash on Windows.
- Python 3.12 and uv for virtual environments and dependency locking.
- Node.js LTS and npm for the frontend.
- A reachable PostgreSQL database configured by `backend/.env`.
- Gnani credentials for deliberate live transcription checks.
- FFmpeg is bundled through the `imageio-ffmpeg` Python dependency.

The backend virtual environment is `backend/.venv`. Its activation prompt
may say `backend`; this does not change the environment's directory name.
The frontend dependencies are installed separately in `Frontend/node_modules`.

The frontend uploads recordings, starts transcription, polls processing status,
and displays saved transcripts and summaries. Recent recordings can be reopened;
results have Copy and Download .txt controls.

## Development workflow

Run Git commands from the repository root and Python commands from `backend/`.
Implement and check each milestone before committing it. Add relevant tests
alongside each feature; keep ordinary tests isolated from live provider calls.
Commit an `.env.example` with placeholders when configuration is introduced.
Keep actual credentials, personal recordings, and generated files out of Git.

## Later features

Speaker diarization, cloud object storage, and a durable worker queue are
later milestones. Google authentication and private recording history are implemented.
