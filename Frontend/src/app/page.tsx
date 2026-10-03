"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

type Upload = {
  id: string;
  status: string;
  filename?: string;
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

function AudioMark({ large = false }: { large?: boolean }) {
  return (
    <svg width={large ? 48 : 22} height={large ? 48 : 22} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
      <path d="M3 10v4M7.5 6v12M12 3v18M16.5 7v10M21 10v4" />
    </svg>
  );
}

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
      className="result-panel"
    >
      <div className="result-toolbar">
        <h2 id={headingId}>{title}</h2>
        <div className="result-actions">
          <button
            type="button"
            onClick={copyText}
            disabled={copying}
            aria-label={`Copy ${title.toLowerCase()}`}
            className="secondary-button"
          >
            {copying ? "Copying…" : "Copy"}
          </button>
          <button
            type="button"
            onClick={downloadText}
            aria-label={`Download ${title.toLowerCase()} as text`}
            className="secondary-button"
          >
            Download .txt
          </button>
        </div>
      </div>
      {feedback && (
        <p
          role={feedback.failed ? "alert" : "status"}
          className={feedback.failed ? "error-message" : "success-message"}
        >
          {feedback.message}
        </p>
      )}
      <p className="result-prose">{text}</p>
    </section>
  );
}

export default function Home() {
  const [resultTab, setResultTab] = useState<"Summary" | "Transcript">("Summary");
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
          filename: typeof data.filename === "string" ? data.filename : undefined,
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

      setUpload({ id: data.id, status: data.status, progress: 0, filename: file.name });
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
    <div className="sonora-shell">
      <aside className="sidebar" aria-label="Workspace navigation">
        <Link className="brand" href="/" aria-label="Sonora home">
          <span className="brand-mark"><AudioMark /></span>
          sonora<span className="brand-dot">.</span>
        </Link>
        <p className="brand-credit">BY GNANI.AI</p>
        <p className="nav-label">YOUR WORKSPACE</p>
        <a className="nav-item current" href="#workspace" aria-current="page">
          <AudioMark /> Audio notes
          {session?.user && recordings && <span className="nav-count">{recordings.length}</span>}
        </a>
        <div className="sidebar-note"><span className="little-line" /><p>A little clarity,<br />every day.</p></div>
        <div className="sidebar-account">
          <span className="avatar">{session?.user?.name.charAt(0).toUpperCase() || "S"}</span>
          <div><strong>{session?.user ? "Personal workspace" : "Guest workspace"}</strong><small>{session?.user ? "Your notes, just for you." : "One conversation to get started."}</small></div>
        </div>
      </aside>

      <div className="main-column">
        <header className="topbar">
          <span className="mobile-brand">sonora<span>.</span></span>
          <span className="breadcrumb">Workspace <span>/</span> <strong>Audio notes</strong></span>
          <span className="privacy-label"><span />{session?.user ? "Private workspace" : "A little clarity starts here"}</span>
        </header>

        <main className="workspace-main" id="workspace">
          <div className="page-heading">
            <div><p className="eyebrow">LISTEN LESS. REMEMBER MORE.</p><h1>Make room for the good ideas<span>.</span></h1><p className="subtitle">Turn your conversations into notes you can actually use.</p></div>
            <div className="heading-art"><AudioMark large /></div>
          </div>

          <section aria-label="Account" className="account-banner">
            <div>
              <p className="account-title">{session?.user ? session.user.name : "Your first conversation is on us."}</p>
              <p className="account-description">{session?.user ? "Your recordings, transcripts and summaries are saved privately." : `Try one recording as a guest. Results stay temporary for ${session?.guest_result_minutes ?? 60} minutes; sign in before uploading to save your notes.`}</p>
              {guestLimitReached && <p className="limit-message">Your guest recording has been used. Sign in to upload more.</p>}
              {sessionError && <p role="alert" className="error-message">{sessionError}</p>}
            </div>
            {session?.user ? <button type="button" onClick={logout} disabled={isBusy} className="secondary-button">Sign out</button>
              : session?.google_enabled ? <a href="/api/auth/google" className="google-button"><span aria-hidden="true">G</span>Sign in with Google</a>
                : <span className="session-status">{session ? "Google sign-in awaits configuration." : "Loading session…"}</span>}
          </section>

          <form aria-busy={isBusy} onSubmit={(event) => { event.preventDefault(); void uploadAudio(); }} className="upload-card">
            <div className="upload-icon" aria-hidden="true"><svg width="25" height="25" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"><path d="M12 16V3m-5 5 5-5 5 5M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5" /></svg></div>
            <div className="upload-copy">
              <h2>{file ? file.name : "Every great note starts with a conversation."}</h2>
              <p>{file ? `${(file.size / 1048576).toFixed(1)} MB · Ready to turn into notes` : "Choose an audio file from your device to get started."}</p>
              <small id="formats">WAV, MP3, M4A, FLAC or OGG <span>·</span> Up to 50 MB</small>
              <label className="file-picker" htmlFor="audio">Choose your recording
                <input ref={audioInputRef} id="audio" type="file" accept=".wav,.mp3,.m4a,.flac,.ogg" disabled={isBusy || !session || guestLimitReached} aria-describedby="formats"
                  onChange={(event) => { setFile(event.target.files?.[0] ?? null); setUpload(null); setResultTab("Summary"); setError(""); }} />
              </label>
            </div>
            <button type="submit" disabled={!file || isBusy || !session || guestLimitReached} className="primary-button">{uploading ? "Uploading…" : "Upload recording"}<span aria-hidden="true">↗</span></button>
          </form>
          {error && <p role="alert" className="error-banner">{error}</p>}

          <div className="section-heading"><h2>Your audio notes</h2><span>Less searching. More remembering.</span></div>
          <div className="notes-workspace">
            <section aria-labelledby="history-heading" aria-busy={loadingHistory} className="history-panel">
              <div className="history-heading"><h2 id="history-heading">{session?.user ? "Recent recordings" : "Your workspace"}</h2>{session?.user && <button type="button" onClick={loadRecordings} disabled={loadingHistory} className="text-button">{loadingHistory ? "Loading…" : recordings === null ? "Load recordings" : "Refresh recordings"}</button>}</div>
              {session?.user ? <>
                {historyError && <p role="alert" className="history-hint error-message">{historyError}</p>}
                {recordings === null && !historyError && <p className="history-hint">Load your recordings to pick up where you left off.</p>}
                {recordings?.length === 0 && <p className="history-hint">Your notes will appear here after your first upload.</p>}
                <ul className="recording-list">{recordings?.map((recording) => <li key={recording.id}><button type="button" disabled={isBusy} aria-current={upload?.id === recording.id ? "true" : undefined}
                  className={`recording-item ${upload?.id === recording.id ? "selected" : ""}`}
                  onClick={() => { setFile(null); if (audioInputRef.current) audioInputRef.current.value = ""; setUpload(recording); setResultTab("Summary"); setError(recording.status === "failed" ? recording.error_message || "Processing failed. You can retry processing." : ""); }}>
                  <span className="recording-icon"><AudioMark /></span><span className="recording-info"><strong>{recording.filename}</strong><span className={`status-badge ${recording.status}`}>{recording.status}</span></span>
                </button></li>)}</ul>
              </> : <div className="guest-history"><span className="lock-icon" aria-hidden="true">◇</span><h3>Keep the good ideas.</h3><p>Sign in to build a personal library of transcripts and summaries.</p>{session?.google_enabled && <a className="text-button" href="/api/auth/google">Save notes with Google <span aria-hidden="true">↗</span></a>}</div>}
              <p className="history-footer">{session?.user ? "Only you can access your saved notes." : "Guest notes aren't added to history."}</p>
            </section>

            <section className="detail-panel" aria-label="Recording workspace">
              {upload ? <>
                <div className="detail-heading"><p className="eyebrow">YOUR CONVERSATION, MADE CLEAR</p><h2>{upload.filename || file?.name || "Your recording"}</h2><span className={`status-badge ${upload.status}`}>{upload.status}</span></div>
                <div className="processing-card">
                  <div className="progress-label"><span id="transcription-progress-label">Transcription progress</span><strong>{transcriptionProgress}%</strong></div>
                  <div role="progressbar" aria-labelledby="transcription-progress-label" aria-valuemin={0} aria-valuemax={100} aria-valuenow={transcriptionProgress} className="progress-track"><div style={{ width: `${transcriptionProgress}%` }} className="progress-fill" /></div>
                  <p>{upload.status === "summarizing" ? "Transcription complete. Generating summary…" : upload.status === "completed" ? "Transcription and summary complete." : upload.status === "failed" ? "Processing stopped. You can retry." : upload.status === "uploaded" ? "Ready to start transcription." : "Updates after each audio chunk is transcribed."}</p>
                  {["uploaded", "failed"].includes(upload.status) && <button type="button" onClick={startTranscription} disabled={isBusy} className="primary-button">{startingTranscription ? "Starting…" : upload.status === "failed" ? "Retry processing" : "Start transcription"}<span aria-hidden="true">→</span></button>}
                </div>
                <div className="result-tabs" role="tablist" aria-label="Recording results">{(["Summary", "Transcript"] as const).map((tab) => <button key={tab} id={`tab-${tab.toLowerCase()}`} role="tab" type="button" aria-selected={resultTab === tab} aria-controls="recording-result" tabIndex={resultTab === tab ? 0 : -1} onClick={() => setResultTab(tab)} onKeyDown={(event) => { if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) { event.preventDefault(); const next = event.key === "Home" ? "Summary" : event.key === "End" ? "Transcript" : tab === "Summary" ? "Transcript" : "Summary"; setResultTab(next); document.getElementById(`tab-${next.toLowerCase()}`)?.focus(); } }}>{tab === "Summary" ? "AI summary" : "Transcript"}</button>)}</div>
                <div id="recording-result" role="tabpanel" aria-labelledby={`tab-${resultTab.toLowerCase()}`} tabIndex={0}>
                  {(resultTab === "Summary" ? upload.summary : upload.transcript) ? <ResultPanel key={`${resultTab}-${upload.id}`} title={resultTab} text={(resultTab === "Summary" ? upload.summary : upload.transcript)!} filename={`${resultTab.toLowerCase()}-${upload.id}.txt`} /> : <p className="result-empty">{resultTab === "Summary" ? "Your summary will appear here when processing is complete." : "Your transcript will appear here once the audio is transcribed."}</p>}
                </div>
              </> : <div className="detail-empty"><span className="empty-mark"><AudioMark large /></span><p className="eyebrow">FROM CONVERSATION TO CLARITY</p><h2>A home for your good ideas.</h2><p>Upload a recording or open a saved note.<br />We&apos;ll take care of the words.</p></div>}
            </section>
          </div>
          <footer className="page-footer"><span>Made for the moments worth remembering.</span><span>sonora <span className="footer-dot">·</span> Gnani.ai</span></footer>
        </main>
      </div>
    </div>
  );
}
