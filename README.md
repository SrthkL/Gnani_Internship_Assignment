# Gnani Internship Assignment

A local audio notes project built incrementally with a FastAPI backend,
PostgreSQL, the Gnani batch transcription API, and a Next.js frontend.

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

See [deployment setup](DEPLOYMENT.md) for Railway configuration, production
containers, persistent storage, and deployment limitations. See
[transcription retry fixes](backend/TRANSCRIPTION_RETRY_FIX.md) for provider
error handling and recovery.

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

Speaker diarization, cloud object storage, authentication, and a durable worker
queue are later milestones. Deployment configuration is available in
[DEPLOYMENT.md](DEPLOYMENT.md).
