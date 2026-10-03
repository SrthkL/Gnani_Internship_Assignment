"use client";

import { useEffect, useRef, useState } from "react";

type Upload = {
  id: string;
  status: string;
  transcript?: string | null;
  summary?: string | null;
  error_message?: string | null;
};

type RecentUpload = Upload & {
  filename: string;
};

function ResultPanel({
  title,
  text,
  filename,
}: {
  title: "Transcript" | "Summary";
  text: string;
  filename: string;
}) {
  const [copying, setCopying] = useState(false);
  const [feedback, setFeedback] = useState<{
    message: string;
    failed: boolean;
  } | null>(null);
  const headingId = `${title.toLowerCase()}-heading`;

  async function copyText() {
    if (copying) return;
    setCopying(true);
    setFeedback(null);

    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("Clipboard unavailable");
      }
      await navigator.clipboard.writeText(text);
      setFeedback({ message: `${title} copied.`, failed: false });
    } catch {
      setFeedback({
        message: "Could not copy. Use Download .txt or select the text instead.",
        failed: true,
      });
    } finally {
      setCopying(false);
    }
  }

  function downloadText() {
    setFeedback(null);
    let objectUrl: string | undefined;
    let link: HTMLAnchorElement | undefined;

    try {
      // Export the saved text as UTF-8, including multilingual characters.
      objectUrl = URL.createObjectURL(new Blob([text], {
        type: "text/plain;charset=utf-8",
      }));
      link = document.createElement("a");
      link.href = objectUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
    } catch {
      setFeedback({ message: "Could not start the download. Please retry.", failed: true });
    } finally {
      link?.remove();
      if (objectUrl) {
        const urlToRelease = objectUrl;
        // Give the browser time to begin downloading before releasing the URL.
        window.setTimeout(() => URL.revokeObjectURL(urlToRelease), 1000);
      }
    }
  }

  return (
    <section
      aria-labelledby={headingId}
      className="rounded-2xl border border-slate-800 bg-slate-900 p-6"
    >
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 id={headingId} className="text-xl font-semibold">{title}</h2>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={copyText}
            disabled={copying}
            aria-label={`Copy ${title.toLowerCase()}`}
            className="rounded-lg bg-slate-800 px-3 py-2 text-sm hover:bg-slate-700 disabled:opacity-50"
          >
            {copying ? "Copying…" : "Copy"}
          </button>
          <button
            type="button"
            onClick={downloadText}
            aria-label={`Download ${title.toLowerCase()} as text`}
            className="rounded-lg bg-slate-800 px-3 py-2 text-sm hover:bg-slate-700"
          >
            Download .txt
          </button>
        </div>
      </div>
      {feedback && (
        <p
          role={feedback.failed ? "alert" : "status"}
          className={`mb-4 text-sm ${feedback.failed ? "text-red-400" : "text-emerald-300"}`}
        >
          {feedback.message}
        </p>
      )}
      <p className="whitespace-pre-wrap leading-7 text-slate-300">{text}</p>
    </section>
  );
}

export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [upload, setUpload] = useState<Upload | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [startingTranscription, setStartingTranscription] = useState(false);
  const [recordings, setRecordings] = useState<RecentUpload[] | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const audioInputRef = useRef<HTMLInputElement>(null);
  const uploadId = upload?.id;
  const isProcessing =
    upload?.status === "transcribing" ||
    upload?.status === "summarizing";
  const isBusy = uploading || startingTranscription || isProcessing;

  // A completed POST contains only ID/status, so retrieve its results once too.
  const shouldRefresh =
    isProcessing ||
    (upload?.status === "failed" && upload.error_message === undefined) ||
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
          error_message:
            typeof data.error_message === "string" ? data.error_message : null,
        });

        setError(
          data.status === "failed"
            ? (typeof data.error_message === "string" && data.error_message
              ? data.error_message
              : "Processing failed. You can retry processing.")
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

  async function loadRecordings() {
    if (loadingHistory) return;

    setLoadingHistory(true);
    setHistoryError("");

    try {
      // Read saved results; this endpoint does not start transcription.
      const response = await fetch("/api/uploads", { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`Could not load recordings (${response.status}).`);
      }

      const data: unknown = await response.json();
      if (
        !Array.isArray(data) ||
        !data.every(
          (recording) =>
            recording &&
            typeof recording.id === "string" &&
            typeof recording.filename === "string" &&
            typeof recording.status === "string",
        )
      ) {
        throw new Error("Unexpected recording history response.");
      }

      setRecordings(data as RecentUpload[]);
    } catch (error) {
      setHistoryError(
        error instanceof Error ? error.message : "Could not load recordings.",
      );
    } finally {
      setLoadingHistory(false);
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
          ? { ...current, status: data.status, summary: undefined, error_message: undefined }
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
            ref={audioInputRef}
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

        <section
          aria-labelledby="history-heading"
          aria-busy={loadingHistory}
          className="rounded-2xl border border-slate-800 bg-slate-900 p-6"
        >
          <div className="flex items-center justify-between gap-4">
            <h2 id="history-heading" className="text-xl font-semibold">
              Recent recordings
            </h2>
            <button
              type="button"
              onClick={loadRecordings}
              disabled={loadingHistory}
              className="rounded-lg bg-slate-800 px-4 py-2 text-sm hover:bg-slate-700 disabled:opacity-50"
            >
              {loadingHistory
                ? "Loading…"
                : recordings === null
                  ? "Load recordings"
                  : "Refresh recordings"}
            </button>
          </div>

          {historyError && (
            <p role="alert" className="mt-4 text-sm text-red-400">
              {historyError}
            </p>
          )}

          {recordings === null && !historyError && (
            <p className="mt-4 text-sm text-slate-400">
              Load your recordings to reopen saved transcripts and summaries.
            </p>
          )}

          {recordings?.length === 0 && (
            <p className="mt-4 text-sm text-slate-400">No recordings yet.</p>
          )}

          <ul className="mt-4 space-y-3">
            {recordings?.map((recording) => (
              <li key={recording.id}>
                <button
                  type="button"
                  disabled={isBusy}
                  aria-current={upload?.id === recording.id ? "true" : undefined}
                  onClick={() => {
                    // Clear the previous file selection when reopening a saved recording.
                    setFile(null);
                    if (audioInputRef.current) audioInputRef.current.value = "";
                    setUpload(recording);
                    setError(
                      recording.status === "failed"
                        ? recording.error_message || "Processing failed. You can retry processing."
                        : "",
                    );
                  }}
                  className="w-full rounded-lg border border-slate-700 p-4 text-left hover:border-sky-400 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <p className="break-words font-medium">{recording.filename}</p>
                  <p className="mt-1 text-sm text-slate-400">{recording.status}</p>
                </button>
              </li>
            ))}
          </ul>
        </section>

        {upload?.transcript && (
          <ResultPanel
            key={`transcript-${upload.id}`}
            title="Transcript"
            text={upload.transcript}
            filename={`transcript-${upload.id}.txt`}
          />
        )}

        {upload?.summary && (
          <ResultPanel
            key={`summary-${upload.id}`}
            title="Summary"
            text={upload.summary}
            filename={`summary-${upload.id}.txt`}
          />
        )}
      </div>
    </main>
  );
}
