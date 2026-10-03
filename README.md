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

See [local development and startup fixes](docs/local-development.md) for
configuration, annotated commands, troubleshooting, and verification results.

## Initial goal

Accept an audio recording, retain the original file on local disk, and store
its metadata, processing status, and transcript in PostgreSQL. Clients will
retrieve results as JSON through the API.

The first prototype will transcribe one small recording. Later milestones
will introduce a separate durable worker, bounded audio chunks, progress
reporting, and recovery of interrupted jobs.

## Storage design

- Local disk retains original audio under `STORAGE_DIR/audio/`.
- PostgreSQL stores upload metadata, job state, and transcript text.
- Temporary audio conversion and chunk files are removed after processing.
- Exporting finished transcripts to text files is an optional later feature.

## Local development prerequisites

- Git and Git Bash on Windows.
- Python 3.12 and uv for virtual environments and dependency locking.
- Node.js LTS and npm for the frontend.
- A reachable PostgreSQL database configured by `backend/.env`.
- Gnani credentials for deliberate live transcription checks.
- FFmpeg when audio normalization and chunking are introduced.

The backend virtual environment is `backend/.venv`. Its activation prompt
may say `backend`; this does not change the environment's directory name.
The frontend dependencies are installed separately in `Frontend/node_modules`.

The frontend currently uploads recordings and displays the returned recording
ID. Transcription and summary endpoints are available in the backend; connecting
those controls to the frontend is the next interface milestone.

## Development workflow

Run Git commands from the repository root and Python commands from `backend/`.
Implement and check each milestone before committing it. Add relevant tests
alongside each feature; keep ordinary tests isolated from live provider calls.
Commit an `.env.example` with placeholders when configuration is introduced.
Keep actual credentials, personal recordings, and generated files out of Git.

## Later features

Frontend transcription controls, speaker diarization, cloud object storage,
deployment, authentication, and durable job recovery are later milestones.
