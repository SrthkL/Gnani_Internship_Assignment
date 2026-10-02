# Gnani Internship Assignment

A local audio transcription backend built incrementally with FastAPI,
PostgreSQL, and the Gnani batch transcription API.

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
- A running local PostgreSQL development database.
- Gnani credentials for deliberate live transcription checks.
- FFmpeg when audio normalization and chunking are introduced.

This repository currently contains the project scope and ignore rules.
Dependency installation and application launch commands will be added with
the milestones that implement them.

## Development workflow

Run Git commands from the repository root and Python commands from `backend/`.
Implement and check each milestone before committing it. Add relevant tests
alongside each feature; keep ordinary tests isolated from live provider calls.
Commit an `.env.example` with placeholders when configuration is introduced.
Keep actual credentials, personal recordings, and generated files out of Git.

## Later features

LLM summaries, speaker diarization, cloud object storage, deployment,
authentication, and frontend integration follow the local transcription
milestone. They are not required for the initial implementation.
