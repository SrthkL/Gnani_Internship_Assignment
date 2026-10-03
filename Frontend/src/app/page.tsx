"use client";

import { useEffect, useState } from "react";

type Upload = {
  id: string;
  status: string;
  transcript?: string | null;
  summary?: string | null;
};

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [upload, setUpload] = useState<Upload | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [startingTranscription, setStartingTranscription] = useState(false);
  const uploadId = upload?.id;
  const isProcessing =
    upload?.status === "transcribing" ||
    upload?.status === "summarizing";
  const isBusy = uploading || startingTranscription || isProcessing;

  // A completed POST contains only ID/status, so retrieve its results once too.
  const shouldRefresh =
    isProcessing ||
    (upload?.status === "completed" &&
      (upload.transcript === undefined || upload.summary === undefined));

  useEffect(() => {
    if (!uploadId || !shouldRefresh) return;

    let active = true;
    let timer: number | undefined;
    const controller = new AbortController();

    async function refreshStatus() {
      try {
        const response = await fetch(`/api/uploads/${uploadId}`, {
          cache: "no-store",
          signal: controller.signal,
        });

        if (!response.ok) {
          throw new Error("Could not retrieve processing status.");
        }

        const data = await response.json();

        if (data?.id !== uploadId || typeof data?.status !== "string") {
          throw new Error("Unexpected processing response.");
        }

        if (!active) return;

        setUpload({
          id: data.id,
          status: data.status,
          transcript:
            typeof data.transcript === "string" ? data.transcript : null,
          summary: typeof data.summary === "string" ? data.summary : null,
        });

        setError(
          data.status === "failed"
            ? "Processing failed. You can retry processing."
            : "",
        );
      } catch {
        if (active) {
          setError("Unable to refresh the status. Retrying…");
        }
      } finally {
        // Wait until this request finishes before scheduling another.
        if (active) {
          timer = window.setTimeout(refreshStatus, 3000);
        }
      }
    }

    void refreshStatus();

    return () => {
      active = false;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [uploadId, shouldRefresh]);

  async function uploadAudio() {
    if (!file || isBusy) return;

    setError("");
    setUpload(null);

    if (file.size === 0) {
      setError("Choose an audio file that isn't empty.");
      return;
    }

    setUploading(true);

    try {
      // "file" matches the parameter expected by FastAPI.
      const body = new FormData();
      body.append("file", file);

      const response = await fetch("/api/uploads", {
        method: "POST",
        body,
      });

      // The browser sets the multipart Content-Type automatically.
      const data = await response.json().catch(() => null);

      if (!response.ok) {
        throw new Error(
          typeof data?.detail === "string"
            ? data.detail
            : `Upload failed (${response.status}).`,
        );
      }

      if (
        typeof data?.id !== "string" ||
        typeof data?.status !== "string"
      ) {
        throw new Error("The server returned an unexpected response.");
      }

      setUpload({ id: data.id, status: data.status });
    } catch (error) {
      setError(
        error instanceof Error ? error.message : "Upload failed. Try again.",
      );
    } finally {
      // Restore the controls whether the upload succeeds or fails.
      setUploading(false);
    }
  }

  async function startTranscription() {
    if (!upload || isBusy || !["uploaded", "failed"].includes(upload.status)) {
      return;
    }

    setError("");
    setStartingTranscription(true);

    try {
      // Start processing the recording that was already uploaded.
      const response = await fetch(
        `/api/uploads/${upload.id}/transcribe`,
        { method: "POST" },
      );

      const data = await response.json().catch(() => null);

      if (!response.ok) {
        throw new Error(
          typeof data?.detail === "string"
            ? data.detail
            : `Could not start transcription (${response.status}).`,
        );
      }

      if (
        data?.id !== upload.id ||
        typeof data?.status !== "string"
      ) {
        throw new Error("The server returned an unexpected response.");
      }

      // Preserve the transcript when retrying a failed summary.
      setUpload((current) =>
        current && current.id === data.id
          ? { ...current, status: data.status, summary: undefined }
          : current,
      );
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Could not start transcription.",
      );
    } finally {
      setStartingTranscription(false);
    }
  }

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-16 text-slate-100">
      <div className="mx-auto max-w-2xl space-y-8">
        <header>
          <p className="mb-3 text-sm font-medium text-sky-400">
            Audio Notes
          </p>
          <h1 className="text-4xl font-semibold tracking-tight">
            Turn conversations into clear notes.
          </h1>
          <p className="mt-4 text-slate-400">
            Upload a recording to begin.
          </p>
        </header>

        <form
          aria-busy={isBusy}
          onSubmit={(event) => {
            event.preventDefault();
            void uploadAudio();
          }}
          className="space-y-5 rounded-2xl border border-slate-800 bg-slate-900 p-6"
        >
          <label htmlFor="audio" className="block font-medium">
            Choose your recording
          </label>

          <input
            id="audio"
            type="file"
            accept=".wav,.mp3,.m4a,.flac,.ogg"
            disabled={isBusy}
            aria-describedby="formats"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setUpload(null);
              setError("");
            }}
            className="block w-full text-sm file:mr-4 file:rounded-lg file:border-0 file:bg-slate-800 file:px-4 file:py-3 file:text-slate-100"
          />

          <p id="formats" className="text-sm text-slate-400">
            WAV, MP3, M4A, FLAC or OGG
          </p>

          <button
            type="submit"
            disabled={!file || isBusy}
            className="rounded-lg bg-sky-400 px-5 py-3 font-semibold text-slate-950 hover:bg-sky-300 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {uploading ? "Uploading…" : "Upload recording"}
          </button>

          {error && (
            <p role="alert" className="text-sm text-red-400">
              {error}
            </p>
          )}

          {upload && (

            <div
              role="status"
              className="rounded-lg bg-emerald-400/10 p-4"
            >
              <p className="font-medium text-emerald-300">
                Audio saved successfully.
              </p>
              <p className="mt-2 break-all text-xs text-slate-400">
                Recording ID: {upload.id}
              </p>
              <p className="mt-3 text-sm text-slate-300">
                  Status: {upload.status}
              </p>
              <button
                type="button"
                onClick={startTranscription}
                disabled={
                  isBusy ||
                  !["uploaded", "failed"].includes(upload.status)
                }
                className="mt-4 rounded-lg bg-sky-400 px-4 py-2 font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {startingTranscription
                  ? "Starting…"
                  : upload.status === "failed"
                    ? "Retry processing"
                    : "Start transcription"}
              </button>

            </div>
          )}
        </form>

        {upload?.transcript && (
          <section
            aria-labelledby="transcript-heading"
            className="rounded-2xl border border-slate-800 bg-slate-900 p-6"
          >
            <h2 id="transcript-heading" className="mb-4 text-xl font-semibold">
              Transcript
            </h2>
            <p className="whitespace-pre-wrap leading-7 text-slate-300">
              {upload.transcript}
            </p>
          </section>
        )}

        {upload?.summary && (
          <section
            aria-labelledby="summary-heading"
            className="rounded-2xl border border-slate-800 bg-slate-900 p-6"
          >
            <h2 id="summary-heading" className="mb-4 text-xl font-semibold">
              Summary
            </h2>
            <p className="whitespace-pre-wrap leading-7 text-slate-300">
              {upload.summary}
            </p>
          </section>
        )}
      </div>
    </main>
  );
}
