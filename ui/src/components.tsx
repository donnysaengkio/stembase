import { createContext, ReactNode, useContext, useEffect, useId, useRef, useState } from "react";
import { open } from "@tauri-apps/plugin-dialog";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { IconFolder, IconUpload, IconX, IconMusic, IconFileMusic, IconChevronDown, IconPlayerPlayFilled, IconPlayerPauseFilled, IconRefresh } from "@tabler/icons-react";
import { baseName, cancelJob, checkDone, peaksOf, fileUrl, FileEntry, Found, inApp, jobStatus, JobView, openLocation, sizeLabel, startJob } from "./api";

/* ---------------- Markdown (engine messages) ---------------- */
export function Md({ text, className }: { text: string; className?: string }) {
  const html = DOMPurify.sanitize(marked.parse(text || "", { async: false }) as string);
  return <div className={"md " + (className || "")} dangerouslySetInnerHTML={{ __html: html }} />;
}

/* ---------------- pop-up window ---------------- */
export type ModalState =
  | null
  | { kind: "progress"; job: JobView; onCancel: () => void; onHide: () => void }
  | { kind: "done" | "found"; title: string; body: string; folder?: string | null; openLabel: string }
  | { kind: "error"; body: string; title?: string }
  | { kind: "ask"; title: string; body: string; ok?: string; onOk?: () => void }
  | { kind: "working"; title: string; desc: string; pct: number | null };

export type Toast = { text: string; sub?: string; action?: { label: string; run: () => void } } | null;

type ModalApi = {
  show: (m: ModalState) => void; current: ModalState; busy: boolean; setBusy: (b: boolean) => void; toast: (t: Toast) => void;
};
const ModalCtx = createContext<ModalApi>({ show: () => {}, current: null, busy: false, setBusy: () => {}, toast: () => {} });
export const useModal = () => useContext(ModalCtx);

function clock(s: number) {
  const t = isFinite(s) && s > 0 ? Math.floor(s) : 0;
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
}

export function ModalProvider({ children }: { children: ReactNode }) {
  const [m, setM] = useState<ModalState>(null);
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<Toast>(null);
  const close = () => setM(null);
  useEffect(() => {   // Esc closes a dialog, but never hides a job's progress
    const k = (e: KeyboardEvent) => { if (e.key === "Escape" && m && m.kind !== "progress" && m.kind !== "working") setM(null); };
    addEventListener("keydown", k);
    return () => removeEventListener("keydown", k);
  }, [m]);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 15000);
    return () => clearTimeout(t);
  }, [toast]);
  return (
    <ModalCtx.Provider value={{ show: setM, current: m, busy, setBusy, toast: setToast }}>
      {children}
      {toast && (
        <div className="toast" role="status">
          <div className="grow"><div className="toast-text">{toast.text}</div>{toast.sub && <div className="muted small">{toast.sub}</div>}</div>
          {toast.action && <button className="primary" onClick={() => { setToast(null); toast.action!.run(); }}>{toast.action.label}</button>}
          <button className="icon" aria-label="Dismiss" onClick={() => setToast(null)}><IconX size={16} /></button>
        </div>
      )}
      {m && (
        <div className="modal-back">
          <div className="modal" role="dialog" aria-modal="true">
            {m.kind === "progress" && (
              <>
                <Md text={"⏳ " + m.job.message} />
                <div className="bar-label">
                  {(m.job.state === "queued" ? "Waiting for the Previous Job" : m.job.desc || "Starting") +
                    ` · ${(m.job.progress * 100).toFixed(1)}%`}
                </div>
                <div className="bar"><div style={{ width: `${m.job.progress * 100}%` }} /></div>
                <div className="muted small">Elapsed {clock(m.job.elapsed)}</div>
                <div className="row gap modal-actions">
                  <button className="grow" disabled={m.job.desc === "Cancelling…"} onClick={m.onCancel}>
                    {m.job.desc === "Cancelling…" ? "Cancelling…" : "Cancel"}</button>
                  <button className="grow" title="Keep Working in the Background" onClick={m.onHide}>Hide</button>
                </div>
              </>
            )}
            {(m.kind === "done" || m.kind === "found") && (
              <>
                <h3>{m.kind === "done" ? "✅ " : "📁 "}{m.title}</h3>
                <Md text={m.body} />
                <div className="row gap">
                  {m.folder && (
                    <button className="primary grow" onClick={() => openLocation(m.folder)}>
                      <IconFolder size={18} /> {m.openLabel}
                    </button>
                  )}
                  <button className="grow" onClick={close}>Close</button>
                </div>
              </>
            )}
            {m.kind === "error" && (
              <>
                <h3>❌ {m.title || "Stopped"}</h3>
                <Md text={m.body} className="error-text" />
                <div className="row"><button className="grow" onClick={close}>Close</button></div>
              </>
            )}
            {m.kind === "ask" && (
              <>
                <h3>{m.title}</h3>
                <Md text={m.body} />
                <div className="row gap">
                  {m.ok && <button className="primary grow" onClick={() => { close(); m.onOk?.(); }}>{m.ok}</button>}
                  <button className="grow" onClick={close}>{m.ok ? "Cancel" : "Close"}</button>
                </div>
              </>
            )}
            {m.kind === "working" && (
              <>
                <h3>{m.title}</h3>
                <div className="bar-label">{m.desc}{m.pct !== null ? ` · ${m.pct}%` : ""}</div>
                <div className={"bar" + (m.pct === null ? " indeterminate" : "")}><div style={{ width: `${m.pct ?? 35}%` }} /></div>
              </>
            )}
          </div>
        </div>
      )}
    </ModalCtx.Provider>
  );
}

/* ---------------- running a job ---------------- */
/** Starts an engine job, shows its progress in the pop-up, then a confirmation (or closes, with autoClose). */
export function useJob<R = any>(kind: string, openLabel = "Open Folder", autoClose = false) {
  const modal = useModal();
  const [result, setResult] = useState<R | null>(null);
  const [running, setRunning] = useState<JobView | null>(null);   // this tab's job while it runs
  const jobId = useRef<string | null>(null);
  const hidden = useRef(false);   // the progress window was hidden: keep working, don't show it again
  const showProgress = (job: JobView) => {
    setRunning(job);
    if (!hidden.current) modal.show({ kind: "progress", job, onCancel: cancel, onHide: () => { hidden.current = true; modal.show(null); } });
  };
  async function cancel() {
    if (!jobId.current) return;
    try { showProgress(await cancelJob(jobId.current)); } catch { /* the poll below reports what happened */ }
  }
  async function run(params: object) {
    let job: JobView;
    try {
      job = await startJob(kind, params);
    } catch (e: any) {
      modal.show({ kind: "error", body: e.message });
      return;
    }
    setResult(null);
    jobId.current = job.id;
    hidden.current = false;
    modal.setBusy(true);
    showProgress(job);
    try {
      for (;;) {
        await new Promise((r) => setTimeout(r, 350));
        job = await jobStatus(job.id);
        if (job.state === "done") {
          setResult(job.result);
          if (autoClose) modal.show(null);
          else modal.show({ kind: "done", title: job.result.title, body: job.result.message, folder: job.result.folder, openLabel });
          break;
        }
        if (job.state === "cancelled") { modal.show(null); modal.toast({ text: "Cancelled", sub: "Nothing more was done." }); break; }
        if (job.state === "error") { modal.show({ kind: "error", body: job.error || "Unknown error" }); break; }
        showProgress(job);
      }
    } catch (e: any) {
      modal.show({ kind: "error", body: `Lost contact with the audio engine: ${e.message}` });
    } finally {
      modal.setBusy(false);
      setRunning(null);
      jobId.current = null;
    }
  }
  return { result, run, cancel, running, busy: modal.busy };
}

/** Asks the engine whether these inputs were processed before; if so, says so in the pop-up. */
export function useDoneBefore(kind: string, params: object | null, openLabel: string) {
  const modal = useModal();
  const key = JSON.stringify(params);
  useEffect(() => {
    if (!params) return;
    let live = true;
    checkDone(kind, params).then((f: Found) => {
      if (live && f) modal.show({ kind: "found", title: f.title, body: f.body, folder: f.folder, openLabel });
    });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
}

/* ---------------- dropping and choosing files ---------------- */
// Tauri reports dropped files for the whole window; App routes them to the drop zone under the pointer.
const dropTargets = new Map<string, (paths: string[]) => void>();
export function routeDrop(x: number, y: number, paths: string[]) {
  const el = (document.elementFromPoint(x, y) as HTMLElement | null)?.closest("[data-drop]") as HTMLElement | null;
  const id = el?.dataset.drop;
  if (id && dropTargets.has(id)) dropTargets.get(id)!(paths);
}
export function highlightDrop(x: number | null, y: number | null) {
  document.querySelectorAll(".drop.over").forEach((e) => e.classList.remove("over"));
  if (x === null || y === null) return;
  (document.elementFromPoint(x, y) as HTMLElement | null)?.closest("[data-drop]")?.classList.add("over");
}

type DropProps = { label: string; exts: string[]; value: string[]; onChange: (p: string[]) => void; multiple?: boolean };

export function FileDrop({ label, exts, value, onChange, multiple }: DropProps) {
  const id = useId();
  const modal = useModal();
  const keep = (ps: string[]) => ps.filter((p) => exts.some((e) => p.toLowerCase().endsWith(e)));
  const cb = useRef(onChange);
  cb.current = onChange;
  useEffect(() => {
    dropTargets.set(id, (ps) => {
      const ok = keep(ps);
      if (ok.length) cb.current(multiple ? Array.from(new Set([...value, ...ok])) : [ok[0]]);
      const skipped = ps.filter((p) => !ok.includes(p));
      if (skipped.length && (!ok.length || multiple)) {   // say why a dropped file did nothing
        const names = skipped.slice(0, 5).map((p) => "- `" + baseName(p) + "`").join("\n")
          + (skipped.length > 5 ? `\n- and ${skipped.length - 5} more` : "");
        const hint = skipped.some((p) => /\.(asd|reapeaks|pk|peak)$/i.test(p))
          ? "\n\nFiles like `.asd` are a music app's analysis files saved next to the audio; drop the audio file itself (for example the `.wav`)."
          : "";
        const what = skipped.length === 1 ? "This isn't an audio file" : "These aren't audio files";
        modal.show({ kind: "error", title: "Not an Audio File", body: `${what} Stembase can open:\n\n${names}\n\nUse ${exts.join(", ")}.${hint}` });
      }
    });
    return () => { dropTargets.delete(id); };
  });
  async function choose() {
    if (!inApp) return;   // browser preview has no file dialog: the path box below is used instead
    const r = await open({ multiple: !!multiple, filters: [{ name: "Audio", extensions: exts.map((e) => e.slice(1)) }] });
    if (!r) return;
    const ps = Array.isArray(r) ? r : [r];
    onChange(multiple ? Array.from(new Set([...value, ...ps])) : [ps[0]]);
  }
  const empty = value.length === 0;
  return (
    <div className="block" data-drop={id}>
      <div className="block-label"><IconMusic size={14} /> {label}</div>
      {empty ? (
        <button className="drop" onClick={choose}>
          <IconUpload size={26} />
          <span className="drop-title">Drop Audio Here</span>
          <span className="muted">Or Click to Choose {multiple ? "Files" : "a File"}</span>
        </button>
      ) : (
        <div className="picked">
          {value.map((p) => (
            <div className="picked-row" key={p}>
              <IconFileMusic size={18} />
              <span className="grow ellipsis" title={p}>{baseName(p)}</span>
              <button className="icon" title="Remove" onClick={() => onChange(value.filter((x) => x !== p))}><IconX size={16} /></button>
            </div>
          ))}
          {!multiple && <Waveform path={value[0]} />}
          <button className="link" onClick={choose}>{multiple ? "Add More Files" : "Choose Another File"}</button>
        </div>
      )}
      {!inApp && (
        <input className="dev-path" placeholder="Browser preview: paste a file path, then press Enter"
          onKeyDown={(e) => {
            const v = (e.target as HTMLInputElement).value.trim();
            if (e.key === "Enter" && v) { onChange(multiple ? Array.from(new Set([...value, v])) : [v]); (e.target as HTMLInputElement).value = ""; }
          }} />
      )}
    </div>
  );
}

/* ---------------- results ---------------- */
export function AudioResult({ f, label }: { f: FileEntry; label?: string }) {
  return (
    <div className="block result">
      <div className="row">
        <div className="grow">
          <div className="result-title">{label || f.name}</div>
          <div className="muted small ellipsis" title={f.path}>{label ? f.name + " · " : ""}{sizeLabel(f.size)}</div>
        </div>
        <button className="icon" title="Show in Folder" onClick={() => openLocation(f.path)}><IconFolder size={18} /></button>
      </div>
      <Waveform path={f.path} />
    </div>
  );
}

/* ---------------- waveform player ---------------- */
let playingNow: HTMLAudioElement | null = null;   // one player at a time: starting one pauses the others

/** Plays an audio file over its waveform: click or drag on the waveform to jump. */
export function Waveform({ path }: { path: string }) {
  const audio = useRef<HTMLAudioElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [wave, setWave] = useState<{ peaks: number[]; duration: number } | null>(null);
  const [failed, setFailed] = useState(false);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    let live = true;
    setWave(null); setFailed(false); setT(0); setPlaying(false);
    peaksOf(path).then((w) => live && setWave(w)).catch(() => live && setFailed(true));
    return () => { live = false; };
  }, [path]);

  useEffect(() => {   // redraw when the window resizes
    const c = canvas.current;
    if (!c) return;
    const ro = new ResizeObserver(() => setWidth(c.clientWidth));
    ro.observe(c);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {   // smooth progress while playing
    if (!playing) return;
    let id = 0;
    const tick = () => { if (audio.current) setT(audio.current.currentTime); id = requestAnimationFrame(tick); };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [playing]);

  const duration = (audio.current && isFinite(audio.current.duration) && audio.current.duration) || wave?.duration || 0;

  useEffect(() => {
    const c = canvas.current;
    if (!c || !width) return;
    const dpr = window.devicePixelRatio || 1, h = 56;
    c.width = Math.round(width * dpr); c.height = Math.round(h * dpr);
    const g = c.getContext("2d")!;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, width, h);
    const css = getComputedStyle(document.documentElement);
    const played = css.getPropertyValue("--accent").trim() || "#ea580c";
    const rest = css.getPropertyValue("--muted").trim() || "#a1a1aa";
    const bar = 2, gap = 1, count = Math.max(1, Math.floor(width / (bar + gap)));
    const peaks = wave?.peaks;
    const at = duration ? t / duration : 0;
    for (let i = 0; i < count; i++) {
      const v = peaks ? peaks[Math.min(peaks.length - 1, Math.floor((i / count) * peaks.length))] : 0.04;
      const bh = Math.max(2, v * (h - 4));
      g.fillStyle = i / count < at ? played : rest;
      g.globalAlpha = i / count < at ? 1 : 0.5;
      g.fillRect(i * (bar + gap), (h - bh) / 2, bar, bh);
    }
  }, [wave, t, width, duration]);

  function toggle() {
    const a = audio.current;
    if (!a) return;
    if (a.paused) {
      if (playingNow && playingNow !== a) playingNow.pause();
      playingNow = a;
      a.play().catch(() => setFailed(true));
    } else a.pause();
  }
  function seek(e: React.PointerEvent<HTMLCanvasElement>) {
    const a = audio.current;
    if (!a || !duration) return;
    const r = e.currentTarget.getBoundingClientRect();
    a.currentTime = Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)) * duration;
    setT(a.currentTime);
  }
  return (
    <div className="wave">
      <button className="wave-play" aria-label={playing ? "Pause" : "Play"} onClick={toggle}>
        {playing ? <IconPlayerPauseFilled size={16} /> : <IconPlayerPlayFilled size={16} />}
      </button>
      <canvas ref={canvas} className="wave-canvas" title={failed ? "This file can't be shown as a waveform" : "Click to jump"}
        onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); seek(e); }}
        onPointerMove={(e) => { if (e.buttons & 1) seek(e); }} />
      <span className="wave-time">{clock(t)} / {clock(duration)}</span>
      <audio ref={audio} preload="metadata" src={fileUrl(path)}
        onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
        onEnded={() => { setPlaying(false); setT(0); if (audio.current) audio.current.currentTime = 0; }}
        onLoadedMetadata={() => setT(audio.current?.currentTime || 0)} />
    </div>
  );
}

export function FileList({ title, files }: { title: string; files: FileEntry[] }) {
  return (
    <div className="block">
      <div className="block-label">{title}</div>
      {files.map((f) => (
        <div className="picked-row" key={f.path}>
          <IconFileMusic size={18} />
          <span className="grow ellipsis" title={f.path}>{f.name}</span>
          <span className="muted small">{sizeLabel(f.size)}</span>
          <button className="icon" title="Show in Folder" onClick={() => openLocation(f.path)}><IconFolder size={16} /></button>
        </div>
      ))}
    </div>
  );
}

/* ---------------- form controls ---------------- */
export function Field({ label, info, children }: { label: string; info?: string; children: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {info && <span className="muted small">{info}</span>}
    </label>
  );
}

export function Select({ value, options, onChange }: { value: string; options: string[]; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)}>
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  );
}

export function Radio({ value, options, onChange }: { value: string; options: string[]; onChange: (v: string) => void }) {
  return (
    <div className="radios">
      {options.map((o) => (
        <label key={o} className={"radio" + (o === value ? " on" : "")}>
          <input type="radio" checked={o === value} onChange={() => onChange(o)} /> {o}
        </label>
      ))}
    </div>
  );
}

export function Check({ checked, onChange, label, info }: { checked: boolean; onChange: (b: boolean) => void; label: string; info?: string }) {
  return (
    <label className="check">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span><span>{label}</span>{info && <span className="muted small block-line">{info}</span>}</span>
    </label>
  );
}

/** A dropdown with a checkbox per option; the chosen ones show as chips in the closed box. */
export function MultiSelect({ value, options, onChange, placeholder, note }: {
  value: string[]; options: string[]; onChange: (v: string[]) => void; placeholder: string;
  note?: (o: string) => string | undefined;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); setOpen(false); } };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc, true);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc, true); };
  }, [open]);
  const toggle = (o: string) => onChange(value.includes(o) ? value.filter((x) => x !== o) : options.filter((x) => x === o || value.includes(x)));
  return (
    <div className="multi" ref={ref}>
      <button type="button" className={"multi-box" + (open ? " open" : "")} aria-haspopup="listbox" aria-expanded={open}
        onClick={() => setOpen(!open)}>
        <span className="multi-chips">
          {value.length === 0 ? <span className="muted">{placeholder}</span>
            : value.map((v) => <span key={v} className="chip">{v}</span>)}
        </span>
        {value.length > 0 && (
          <span className="multi-clear" role="button" title="Clear" onClick={(e) => { e.stopPropagation(); onChange([]); }}>
            <IconX size={15} /></span>
        )}
        <IconChevronDown size={18} className="multi-arrow" />
      </button>
      {open && (
        <div className="multi-menu" role="listbox" aria-multiselectable="true">
          {options.map((o) => <Check key={o} checked={value.includes(o)} onChange={() => toggle(o)} label={o} info={note?.(o)} />)}
        </div>
      )}
    </div>
  );
}

export function Slider({ value, min, max, step, onChange, unit }: { value: number; min: number; max: number; step: number; onChange: (v: number) => void; unit?: string }) {
  return (
    <div className="slider">
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
      <span className="slider-value">{value > 0 && unit === "st" ? "+" : ""}{value}{unit ? ` ${unit}` : ""}</span>
    </div>
  );
}

export function Section({ title, children, open: o }: { title: string; children: ReactNode; open?: boolean }) {
  return (
    <details className="block section" open={o}>
      <summary>{title}</summary>
      <div className="section-body">{children}</div>
    </details>
  );
}

/** A tab's buttons: Start, Cancel (while this tab's job runs), Open Folder (where this tab saves) and Reset. */
export function RunRow({ label, onRun, folder, onReset, job }: {
  label: string; onRun: () => void; folder: string; onReset?: () => void;
  job?: { running: JobView | null; cancel: () => void };
}) {
  const { busy } = useModal();
  const mine = job?.running;
  const cancelling = mine?.desc === "Cancelling…";
  return (
    <div className="run-row">
      <button className="primary big" disabled={busy} onClick={onRun}>
        {mine ? `Working… ${Math.round(mine.progress * 100)}%` : label}
      </button>
      {job && (
        <button className="big" disabled={!mine || cancelling} title={mine ? "Stop This Job" : "Nothing Is Running"} onClick={job.cancel}>
          {cancelling ? "Cancelling…" : "Cancel"}
        </button>
      )}
      <button className="big" onClick={() => openLocation(folder)}><IconFolder size={18} /> Open Folder</button>
      {onReset && (
        <button className="big" disabled={busy} title="Clear This Tab" onClick={onReset}>
          <IconRefresh size={18} /> Reset
        </button>
      )}
    </div>
  );
}

/* ---------------- placeholders for the results column ---------------- */
/** A grey bar standing in for text that a result will fill in. */
export function Ph({ w = "60%", h = 12 }: { w?: string; h?: number }) {
  return <span className="ph" style={{ width: w, height: h }} />;
}

/** The outline of an audio result (title, file line, waveform player) before there is one. */
export function ShellAudio({ label }: { label: string }) {
  return (
    <div className="block result">
      <div className="result-title">{label}</div>
      <Ph w="45%" h={10} />
      <div className="wave">
        <span className="wave-play shell-play"><IconPlayerPlayFilled size={16} /></span>
        <span className="shell-wave" />
        <span className="wave-time">0:00 / 0:00</span>
      </div>
    </div>
  );
}

/** The outline of a list of saved files. */
export function ShellFiles({ title, count = 1 }: { title: string; count?: number }) {
  return (
    <div className="block">
      <div className="block-label">{title}</div>
      {Array.from({ length: count }, (_, i) => (
        <div className="picked-row" key={i}><IconFileMusic size={18} /><Ph w="55%" /><span className="grow" /><Ph w="48px" h={10} /></div>
      ))}
    </div>
  );
}

/** The outline of a written report: a few lines of grey bars. */
export function ShellText({ lines = 3, bare }: { lines?: number; bare?: boolean }) {
  const widths = ["92%", "78%", "85%", "60%", "70%"];
  return <div className={(bare ? "" : "block ") + "shell-lines"}>{Array.from({ length: lines }, (_, i) => <Ph key={i} w={widths[i % widths.length]} />)}</div>;
}
