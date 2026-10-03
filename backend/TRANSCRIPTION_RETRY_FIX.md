# Transcription failure and retry fix

Verified on 3 October 2026.

## What happened

The recording showed `failed`, with no saved transcript. The original log
only recorded `HTTPStatusError`, so it did not retain the exact HTTP status
from that request. Its provider job was still `CREATED`. Starting that same
job later succeeded, and the provider completed transcription.

During recovery, Gnani returned HTTP 429 with `RATE_LIMITED` when requesting
completed job files. The client previously treated that temporary rejection
as a terminal failure. Recovery succeeded after adding backoff retries.

## Changes

- `app/gnani.py`: up to four attempts for HTTP 429, honoring `Retry-After`
  or waiting 10, 20, then 40 seconds. Safe reads and starting a known job also
  retry temporary server/transport errors. Creating a job does not retry
  ambiguous server/transport errors, avoiding duplicate job creation.
- Multipart audio is rewound before retries so each attempt includes all bytes.
- A start retry that returns 409 checks the known job's state; an active or
  completed job is accepted without creating another job.
- `app/tasks.py`: removes the duplicate processing function, preserves saved
  transcripts on summary retries, and records useful sanitized failure messages.
- `app/models.py` and `app/schemas.py`: map/expose the existing nullable
  `error_message` column. No database schema migration was performed.
- `../Frontend/src/app/page.tsx`: displays the saved failure reason and
  retrieves error metadata for a failed recording when it is still unknown.

## Result and checks

The recording was recovered from its existing provider job and saved with
status `completed`. It has a 2,410-character transcript and a 968-character
summary. Those counts verify result presence, not semantic accuracy.

- All 8 backend tests passed, including audio normalization/cleanup, retry
  upload integrity, Retry-After, retry exhaustion, already-started jobs,
  sanitized failures, and reuse of an existing transcript.
- Frontend ESLint and TypeScript checks passed.
- Fetching the completed recording through the frontend forwarding rule worked.
- Calling its transcription endpoint again returned HTTP 200 and `completed`,
  using the cached results instead of requesting another transcription.
- The backend was restarted on port 8010 with the updated client.

If an existing page still displays the old failed state, click **Retry
processing** once to retrieve the now-completed recording.

Provider flow: [Gnani batch STT documentation](https://docs.gnani.ai/api/STTBatch/Introduction).
