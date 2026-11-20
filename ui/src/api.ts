// Talks to the Stembase engine: a local web API started by the app (see src-tauri/src/lib.rs and server.py).
import { invoke } from "@tauri-apps/api/core";

export type Info = {
  name: string; version: string; output_dir: string; default_output_dir: string; data_dir: string; device: string;
  processing: string; processing_modes: string[]; gpu: string | null;
  formats: string[]; default_format: string; audio_exts: string[];
  models: string[]; midi_stems: string[]; midi_source: string[]; midi_parts: string[]; snap: string[];
  arrange: string[]; convert_modes: string[]; convert_formats: string[]; sample_rates: string[];
  channels: string[]; target_codecs: string[];
};
export type FileEntry = { path: string; name: string; size: number };
export type Found = { title: string; body: string; folder: string } | null;
export type JobView = {
  id: string; kind: string; state: "queued" | "running" | "done" | "error" | "cancelled"; message: string;
  progress: number; desc: string; elapsed: number; result: any; error: string | null;
};

let base = "";
let token = "";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** True inside the app; false when the interface is opened in an ordinary browser for development. */
export const inApp = "__TAURI_INTERNALS__" in window;

/** Waits for the engine process to start listening. */
export async function connect(): Promise<void> {
  if (!inApp) {   // browser preview: http://localhost:1420/?port=<engine port>&token=<token> with `python server.py` running
    const q = new URLSearchParams(location.search);
    base = `http://127.0.0.1:${q.get("port")}`; token = q.get("token") || "";
    return;
  }
  for (;;) {
    const e = await invoke<{ port: number | null; token: string; error: string | null }>("engine");
    if (e.error) throw new Error(e.error);
    if (e.port) { base = `http://127.0.0.1:${e.port}`; token = e.token; return; }
    await sleep(200);
  }
}

async function call<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(base + path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "x-stembase-token": token, "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || data.detail || `Engine error ${r.status}`);
  return data as T;
}

/** Waits until the audio engines have loaded (torch, demucs and friends take a few seconds). */
export async function waitReady(): Promise<Info> {
  // The engine prints its port just before its web server starts listening, so the first requests can be refused:
  // keep trying for a while before calling it a failure.
  const giveUp = Date.now() + 60_000;
  for (;;) {
    let s: { ready: boolean; info?: Info; error?: string; log?: string };
    try {
      s = await call("/api/status");
    } catch (e) {
      if (e instanceof TypeError && Date.now() < giveUp) { await sleep(300); continue; }   // not listening yet
      throw e;
    }
    if (s.error) throw new Error(`${s.error}\n\nLog: ${s.log}`);
    if (s.ready && s.info) return s.info;
    await sleep(400);
  }
}

export const startJob = (kind: string, params: object) => call<JobView>(`/api/jobs/${kind}`, params);
export const jobStatus = (id: string) => call<JobView>(`/api/jobs/${id}`);
export const cancelJob = (id: string) => call<JobView>(`/api/jobs/${id}/cancel`, {});
export const checkDone = (kind: string, params: object) =>
  call<{ found: Found }>(`/api/check/${kind}`, params).then((r) => r.found).catch(() => null);
/** Saves new results in another folder from now on; null goes back to Music/Stembase. Returns the folder in use. */
export const setOutputFolder = (path: string | null) =>
  call<{ output_dir: string }>("/api/output-folder", { path }).then((r) => r.output_dir);
/** Automatic, GPU or CPU for stem separation; returns the setting and the processor now in use. */
export const setProcessing = (mode: string) =>
  call<{ processing: string; device: string }>("/api/processing", { mode });
export const openLocation =(path?: string | null) => call("/api/open", { path: path || null }).catch(() => null);

/** The waveform outline of an audio file (peaks between 0 and 1) and its length in seconds. */
export const peaksOf = (path: string, n = 600) =>
  call<{ peaks: number[]; duration: number }>(`/api/peaks?path=${encodeURIComponent(path)}&n=${n}`);

/** URL the window can play or show a local file from. */
export const fileUrl = (path: string) => `${base}/api/file?path=${encodeURIComponent(path)}&t=${token}`;

export function baseName(path: string) {
  return path.split(/[\\/]/).pop() || path;
}

export function sizeLabel(bytes: number) {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(2)} GB`;
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1e3))} KB`;
}
