"use client";

import { useEffect, useRef, useState } from "react";

type Upload = {
  id: string;
  status: string;
  progress?: number;
  transcript?: string | null;
  summary?: string | null;
  error_message?: string | null;
};

type RecentUpload = Upload & {
  filename: string;
};

type Session = {
  user: { name: string; email: string } | null;
  google_enabled: boolean;
  guest_used: boolean;
  guest_result_minutes: number;
  guest_upload: Upload | null;
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
  const [session, setSession] = useState<Session | null>(null);
  const [sessionError, setSessionError] = useState("");
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
  const guestLimitReached = !!session && !session.user && session.guest_used;

  useEffect(() => {
    const controller = new AbortController();
    async function loadSession() {
      try {
        const response = await fetch("/api/auth/me", { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error("Unable to start your session. Refresh to retry.");
        const data: Session = await response.json();
        if (controller.signal.aborted) return;
        setSession(data);
        if (!data.user && data.guest_upload) setUpload(data.guest_upload);
        if (new URLSearchParams(window.location.search).has("auth_error")) {
          setSessionError("Google sign-in was not completed. Please try again.");
          window.history.replaceState(null, "", window.location.pathname);
        }
      } catch (error) {
        if (!controller.signal.aborted) setSessionError(error instanceof Error ? error.message : "Session unavailable.");
      }
    }
    void loadSession();
    return () => controller.abort();
  }, []);

  async function logout() {
    try {
      const response = await fetch("/api/auth/logout", { method: "POST" });
      if (!response.ok) throw new Error("Could not sign out. Please retry.");
      // Clear account results from the page as well as revoking the server session.
      window.location.reload();
    } catch (error) {
      setSessionError(error instanceof Error ? error.message : "Could not sign out.");
    }
  }
  const transcriptionProgress = upload?.transcript ||
    upload?.status === "summarizing" || upload?.status === "completed"
    ? 100
    : Math.min(100, Math.max(0, Math.floor(upload?.progress ?? 0)));

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
          if (response.status === 401 || response.status === 404) {
            const data = await response.json().catch(() => null);
            setUpload(null);
            setError(typeof data?.detail === "string" ? data.detail : "Recording unavailable. Refresh to continue.");
            active = false;
            return;
          }
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
          progress: typeof data.progress === "number" && Number.isFinite(data.progress)
            ? data.progress : 0,
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
    if (!file || isBusy || !session || guestLimitReached) return;

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

      setUpload({ id: data.id, status: data.status, progress: 0 });
      if (!session.user) setSession({ ...session, guest_used: true });
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
    if (loadingHistory || !session?.user) return;

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
          ? {
            ...current,
            status: data.status,
            progress: current.transcript ? 100 : 0,
            summary: undefined,
            error_message: undefined,
          }
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

        <section aria-label="Account" className="rounded-2xl border border-slate-800 bg-slate-900 p-6">
          {session?.user ? (
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="font-medium">{session.user.name}</p>
                <p className="mt-1 text-sm text-slate-400">Recordings are saved privately to your account.</p>
              </div>
              <button type="button" onClick={logout} disabled={isBusy} className="rounded-lg bg-slate-800 px-4 py-2 text-sm disabled:opacity-50">Sign out</button>
            </div>
          ) : (
            <>
              <p className="font-medium">Try one recording as a guest</p>
              <p className="mt-2 text-sm text-slate-400">
                Guest results are temporary and expire after {session?.guest_result_minutes ?? 60} minutes or a server restart.
                Sign in before uploading to save recordings and see your history.
              </p>
              {session?.google_enabled ? (
                <a href="/api/auth/google" className="mt-4 inline-block rounded-lg bg-white px-4 py-2 font-medium text-slate-950">Sign in with Google</a>
              ) : (
                <p className="mt-3 text-sm text-slate-400">{session ? "Google sign-in is awaiting configuration." : "Loading session…"}</p>
              )}
              {guestLimitReached && <p className="mt-3 text-sm text-amber-300">Your guest recording has been used. Sign in to upload more.</p>}
            </>
          )}
          {sessionError && <p role="alert" className="mt-3 text-sm text-red-400">{sessionError}</p>}
        </section>

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
            disabled={isBusy || !session || guestLimitReached}
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
            disabled={!file || isBusy || !session || guestLimitReached}
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
                {session?.user ? "Audio saved to your account." : "Guest audio ready for processing."}
              </p>
              <p className="mt-2 break-all text-xs text-slate-400">
                Recording ID: {upload.id}
              </p>
              <p className="mt-3 text-sm text-slate-300">
                  Status: {upload.status}
              </p>
              <div className="mt-4">
                <div className="mb-2 flex items-center justify-between text-sm">
                  <span id="transcription-progress-label">Transcription progress</span>
                  <span className="tabular-nums">{transcriptionProgress}%</span>
                </div>
                <div
                  role="progressbar"
                  aria-labelledby="transcription-progress-label"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={transcriptionProgress}
                  className="h-2 overflow-hidden rounded-full bg-slate-800"
                >
                  <div
                    style={{ width: `${transcriptionProgress}%` }}
                    className="h-full rounded-full bg-sky-400 transition-[width] duration-300 motion-reduce:transition-none"
                  />
                </div>
                <p className="mt-2 text-xs text-slate-400">
                  {upload.status === "summarizing"
                    ? "Transcription complete. Generating summary…"
                    : upload.status === "completed"
                      ? "Transcription and summary complete."
                      : upload.status === "failed"
                        ? "Processing stopped. You can retry."
                        : upload.status === "uploaded"
                          ? "Ready to start transcription."
                          : "Updates after each audio chunk is transcribed."}
                </p>
              </div>
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

        {session?.user && <section
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
        </section>}

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
