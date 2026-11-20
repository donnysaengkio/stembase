// The main menu (☰) and what it opens, as in Try Linux: Check For Updates, Preferences, Keyboard Shortcuts, About and
// Quit, each with its keyboard shortcut; plus the theme (Dark or Light, or following the system) that Preferences sets.
import { ReactNode, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { check, Update } from "@tauri-apps/plugin-updater";
import { relaunch } from "@tauri-apps/plugin-process";
import { openUrl } from "@tauri-apps/plugin-opener";
import { open as pickFolder } from "@tauri-apps/plugin-dialog";
import { IconFolder, IconSettings, IconX } from "@tabler/icons-react";
import { inApp, Info, openLocation, setOutputFolder, setProcessing } from "./api";
import { Check, Select, useModal } from "./components";

const REPO = "https://github.com/donnysaengkio/stembase";
export const MAC = navigator.userAgent.includes("Macintosh");
const MOD = MAC ? "⌘" : "Ctrl";

/* ---------------- preferences (kept in this computer's app data) ---------------- */
export type Prefs = { theme: "dark" | "light"; followSystem: boolean; checkUpdates: boolean; format: string };
const DEFAULTS: Prefs = { theme: "dark", followSystem: true, checkUpdates: true, format: "" };

export function loadPrefs(): Prefs {
  try { return { ...DEFAULTS, ...JSON.parse(localStorage.getItem("stembase.prefs") || "{}") }; } catch { return DEFAULTS; }
}
export function savePrefs(p: Prefs) {
  try { localStorage.setItem("stembase.prefs", JSON.stringify(p)); } catch { /* not saved: still applies now */ }
}
export function applyTheme(p: Prefs) {
  document.documentElement.dataset.theme = p.followSystem ? "system" : p.theme;
}

/* ---------------- which window is open ---------------- */
type Shown = "preferences" | "shortcuts" | "about" | null;
let show: (d: Shown) => void = () => {};

/* ---------------- updates (signed installers from the GitHub release, checked against the key built in) ---------------- */
export function useUpdates(info: Info, prefs: Prefs) {
  const modal = useModal();

  async function install(u: Update) {
    modal.show({ kind: "working", title: `Updating to Stembase ${u.version}`, desc: "Downloading", pct: 0 });
    let got = 0, total = 0;
    try {
      await u.downloadAndInstall((e) => {
        if (e.event === "Started") total = e.data.contentLength ?? 0;
        else if (e.event === "Progress") {
          got += e.data.chunkLength;
          modal.show({ kind: "working", title: `Updating to Stembase ${u.version}`, desc: "Downloading", pct: total ? Math.round((got / total) * 100) : null });
        } else if (e.event === "Finished") modal.show({ kind: "working", title: `Updating to Stembase ${u.version}`, desc: "Installing", pct: null });
      });
      await relaunch();
    } catch (e) {
      modal.show({ kind: "error", title: "Couldn't Update Stembase", body: String(e) });
    }
  }

  function offer(u: Update) {
    const notes = u.body?.trim() ? `\n\n${u.body.trim()}` : "";
    modal.show({
      kind: "ask", title: `Stembase ${u.version} is available`, ok: "Update", onOk: () => install(u),
      body: `You have ${u.currentVersion}. Stembase downloads it, closes, installs it and opens again.` +
        (modal.busy ? "\n\nThe job that's running now stops." : "") + notes,
    });
  }

  async function checkNow() {
    if (!inApp) return modal.show({ kind: "ask", title: "Check For Updates", body: "Updates are checked in the installed app." });
    modal.show({ kind: "working", title: "Checking for Updates", desc: "Asking GitHub for the latest Stembase", pct: null });
    try {
      const u = await check({ timeout: 20000 });
      if (u) offer(u);
      else upToDate();
    } catch (e) {
      const err = String(e);
      // No full release published yet (only previews), so GitHub has no latest.json: nothing newer to offer.
      if (/valid release JSON/i.test(err)) upToDate();
      else if (/sending request|connect|dns|timed out|timeout|network/i.test(err))
        modal.show({ kind: "error", title: "Couldn't Check for Updates", body: "Stembase couldn't reach GitHub. Check your internet connection and try again." });
      else modal.show({ kind: "error", title: "Couldn't Check for Updates", body: err });
    }
  }

  function upToDate() {
    modal.show({ kind: "ask", title: "You Have the Latest Version", body: `Stembase ${info.version} is the newest version.` });
  }

  // Each time Stembase opens, quietly (Preferences can turn this off): a notice only when there is a newer version.
  useEffect(() => {
    if (!inApp || !prefs.checkUpdates) return;
    check({ timeout: 20000 }).then((u) => {
      if (u) modal.toast({ text: `Stembase ${u.version} is available`, sub: `You have ${u.currentVersion}.`, action: { label: "Update", run: () => offer(u) } });
    }).catch(() => { /* offline: no news */ });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return checkNow;
}

/* ---------------- quitting ---------------- */
export function useQuit() {
  const modal = useModal();
  return () => {
    const go = () => (inApp ? invoke("quit") : window.close());
    if (!modal.busy) return go();
    modal.show({
      kind: "ask", title: "Quit Stembase?", ok: "Quit", onOk: go,
      body: "A job is still running. Quitting stops it; files it already saved are kept.",
    });
  };
}

/* ---------------- keyboard shortcuts ---------------- */
export const SHORTCUTS: [string, string][] = [
  ["General", ""],
  [`${MOD}+U`, "Check for Updates"],
  [`${MOD}+,`, "Preferences"],
  [`${MOD}+?`, "Keyboard Shortcuts"],
  [`${MOD}+Q`, "Quit Stembase"],
  ["Working", ""],
  [`${MOD}+1 … 6`, "Go to Analyze, Split, MIDI, Mix, Shift or Encode"],
  [`${MOD}+O`, "Choose an Audio File for This Tab"],
  [`${MOD}+Enter`, "Start This Tab's Job"],
  [`${MOD}+Shift+R`, "Open the Output Folder"],
  ["Esc", "Close a Dialog or Menu"],
];

export function useShortcuts(acts: {
  checkUpdates: () => void; quit: () => void; tab: (i: number) => void; output: () => void;
}) {
  const ref = useRef(acts);
  ref.current = acts;
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const mod = MAC ? e.metaKey : e.ctrlKey;
      if (!mod || e.altKey) return;
      const k = e.key.toLowerCase();
      const a = ref.current;
      const section = () => [...document.querySelectorAll<HTMLElement>("main section")].find((s) => !s.hidden);
      let act: (() => void) | null = null;
      if (k === "u") act = a.checkUpdates;
      else if (k === ",") act = () => show("preferences");
      else if (k === "?" || k === "/") act = () => show("shortcuts");
      else if (k === "q") act = a.quit;
      else if (e.shiftKey && k === "r") act = a.output;
      else if (/^[1-6]$/.test(e.key)) act = () => a.tab(Number(e.key) - 1);
      else if (k === "o") act = () => section()?.querySelector<HTMLButtonElement>(".drop, button.link")?.click();
      else if (k === "enter") act = () => section()?.querySelector<HTMLButtonElement>(".run-row button.primary:not(:disabled)")?.click();
      if (act) { e.preventDefault(); act(); }
    };
    addEventListener("keydown", key);
    return () => removeEventListener("keydown", key);
  }, []);
}

/* ---------------- the ☰ menu ---------------- */
export function MainMenu({ checkUpdates, quit }: { checkUpdates: () => void; quit: () => void }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    addEventListener("mousedown", away); addEventListener("keydown", esc);
    return () => { removeEventListener("mousedown", away); removeEventListener("keydown", esc); };
  }, [open]);
  const items: ([string, string, () => void] | null)[] = [
    ["Check For Updates", `${MOD}+U`, checkUpdates],
    null,
    ["Preferences", `${MOD}+,`, () => show("preferences")],
    ["Keyboard Shortcuts", `${MOD}+?`, () => show("shortcuts")],
    ["About Stembase", "", () => show("about")],
    null,
    ["Quit Stembase", `${MOD}+Q`, quit],
  ];
  return (
    <div className="menu-wrap" ref={box}>
      <button className="icon-btn gear-btn" title="Settings" aria-label="Settings" aria-expanded={open} onClick={() => setOpen(!open)}>
        <IconSettings size={24} stroke={1.75} />
      </button>
      {open && (
        <div className="menu" role="menu">
          {items.map((it, i) => it === null ? <div key={i} className="menu-line" /> : (
            <button key={it[0]} role="menuitem" className="menu-item" onClick={() => { setOpen(false); it[2](); }}>
              <span>{it[0]}</span>{it[1] && <kbd>{it[1]}</kbd>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/* ---------------- the windows it opens ---------------- */
function Window({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    addEventListener("keydown", esc);
    return () => removeEventListener("keydown", esc);
  }, [onClose]);
  return (
    <div className="modal-back" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal app-window" role="dialog" aria-modal="true" aria-label={title}>
        <div className="window-head"><h3>{title}</h3><button className="icon-btn" aria-label="Close" onClick={onClose}><IconX size={18} /></button></div>
        {children}
      </div>
    </div>
  );
}

function Keys({ keys }: { keys: string }) {
  return <span className="keys">{keys.split("+").map((k, i) => <span key={i}>{i > 0 && <span className="plus">+</span>}<kbd>{k}</kbd></span>)}</span>;
}

type PrefsProps = { info: Info; prefs: Prefs; setPrefs: (p: Prefs) => void; checkUpdates: () => void; patchInfo: (p: Partial<Info>) => void };

/** The Output folder: shown in full, with Change…, Open and (once changed) Use Default. */
function OutputFolder({ info, patchInfo }: { info: Info; patchInfo: (p: Partial<Info>) => void }) {
  const { busy } = useModal();
  const [error, setError] = useState("");
  const use = async (path: string | null) => {
    setError("");
    try { patchInfo({ output_dir: await setOutputFolder(path) }); } catch (e: any) { setError(String(e.message || e)); }
  };
  const change = async () => {
    const dir = inApp
      ? await pickFolder({ directory: true, defaultPath: info.output_dir, title: "Choose the Output Folder" })
      : prompt("Output Folder", info.output_dir);   // browser preview has no folder dialog
    if (typeof dir === "string" && dir) use(dir);
  };
  const isDefault = info.output_dir === info.default_output_dir;
  return (
    <>
      <div className="pref-row top">
        <span className="pref-label">Output Folder</span>
        <div className="pref-control wide">
          <div className="folder-path" title={info.output_dir}><IconFolder size={16} /><span>{info.output_dir}</span></div>
          <div className="pref-buttons">
            <button disabled={busy} title={busy ? "Wait for the Current Job to Finish" : undefined} onClick={change}>Change…</button>
            <button onClick={() => openLocation(info.output_dir)}>Open</button>
            {!isDefault && <button disabled={busy} onClick={() => use(null)}>Use Default</button>}
          </div>
        </div>
      </div>
      {error && <p className="small pref-error">{error}</p>}
    </>
  );
}

/** Automatic / GPU / CPU for stem separation, with the graphics card Stembase found. */
function Processing({ info, patchInfo }: { info: Info; patchInfo: (p: Partial<Info>) => void }) {
  const { busy } = useModal();
  const [error, setError] = useState("");
  const change = async (mode: string) => {
    setError("");
    try { const r = await setProcessing(mode); patchInfo({ processing: r.processing, device: r.device }); }
    catch (e: any) { setError(String(e.message || e)); }
  };
  return (
    <>
      <div className="pref-row">
        <span className="pref-label">Processor</span>
        <div className={"pref-control" + (busy || !info.gpu ? " disabled" : "")}>
          <Select value={info.gpu ? info.processing : "CPU"} options={info.gpu ? info.processing_modes : ["CPU"]} onChange={change} />
        </div>
      </div>
      <p className="muted small pref-note">
        {info.gpu
          ? <>Stem separation runs on <b>{info.device}</b>. Automatic uses the {info.gpu} and falls back to the CPU if it fails; CPU never uses it. Takes effect from the next job.</>
          : <>No supported graphics card was found, so everything runs on the CPU.</>}
      </p>
      {error && <p className="small pref-error">{error}</p>}
    </>
  );
}

function Preferences({ info, prefs, setPrefs, checkUpdates, patchInfo }: PrefsProps) {
  const system = MAC ? "macOS" : navigator.userAgent.includes("Windows") ? "Windows" : "your desktop";
  return (
    <>
      <div className="pref-heading">Appearance</div>
      <div className="pref-row">
        <span className="pref-label">Theme</span>
        <div className={"pref-control" + (prefs.followSystem ? " disabled" : "")}>
          <Select value={prefs.theme === "light" ? "Light" : "Dark"} options={["Dark", "Light"]}
            onChange={(v) => setPrefs({ ...prefs, theme: v === "Light" ? "light" : "dark" })} />
        </div>
      </div>
      <Check checked={prefs.followSystem} onChange={(v) => setPrefs({ ...prefs, followSystem: v })} label="Follow System" />
      <p className="muted small pref-note">Light while {system} shows apps in light mode, and Dark otherwise.</p>
      <div className="pref-heading">Output</div>
      <OutputFolder info={info} patchInfo={patchInfo} />
      <p className="muted small pref-note">New results are saved here; results already saved stay where they are.</p>
      <div className="pref-row">
        <span className="pref-label">Default Format</span>
        <div className="pref-control wide"><Select value={prefs.format} options={info.formats} onChange={(v) => setPrefs({ ...prefs, format: v })} /></div>
      </div>
      <p className="muted small pref-note">Split, Mix and Shift start with this format; each can be changed in the tab.</p>
      <div className="pref-heading">Processing</div>
      <Processing info={info} patchInfo={patchInfo} />
      <div className="pref-heading">Updates</div>
      <Check checked={prefs.checkUpdates} onChange={(v) => setPrefs({ ...prefs, checkUpdates: v })} label="Check for Updates When Stembase Opens" />
      <p className="muted small pref-note">You have Stembase {info.version}.</p>
      <button onClick={() => { show(null); checkUpdates(); }}>Check For Updates</button>
    </>
  );
}

function About({ info, mark }: { info: Info; mark: ReactNode }) {
  const os = MAC ? "your Mac" : navigator.userAgent.includes("Windows") ? "Windows" : "Linux";
  const links: [string, () => void][] = [
    ["Website", () => openUrl(REPO)],
    ["Report an Issue", () => openUrl(REPO + "/issues")],
    ["Open Output Folder", () => openLocation(info.output_dir)],
    ["Open Log Folder", () => openLocation(info.data_dir)],
  ];
  return (
    <div className="about">
      <div className="brand big-brand">{mark}<span className="wordmark">stembase</span></div>
      <div className="about-version">Version {info.version}</div>
      <p>Analyze music, split it into stems, turn audio into MIDI, make mashups, change key or tempo and convert audio,
        all on {os}. Nothing is uploaded.</p>
      <p className="muted small">Audio engine on {info.device} · Demucs (stems), Basic Pitch (MIDI), librosa (analysis) · Icons by Tabler<br />
        <span title={info.output_dir}>Output: {info.output_dir}</span></p>
      <div className="about-links">{links.map(([label, go]) => <button key={label} onClick={go}>{label}</button>)}</div>
      <p className="muted small">Only release stems, mashups or edits of music you have the rights to.</p>
    </div>
  );
}

/** Sits once in the app and draws whichever window is open. */
export function MenuWindows(props: PrefsProps & { mark: ReactNode }) {
  const [shown, setShown] = useState<Shown>(null);
  useEffect(() => { show = setShown; return () => { show = () => {}; }; }, []);
  const close = () => setShown(null);
  if (shown === "preferences") return <Window title="Preferences" onClose={close}><Preferences {...props} /></Window>;
  if (shown === "shortcuts") return (
    <Window title="Keyboard Shortcuts" onClose={close}>
      <div className="shortcuts">
        {SHORTCUTS.map(([keys, what]) => what === ""
          ? <div key={keys} className="pref-heading">{keys}</div>
          : <div key={keys} className="shortcut"><Keys keys={keys} /><span>{what}</span></div>)}
      </div>
    </Window>
  );
  if (shown === "about") return <Window title="About Stembase" onClose={close}><About info={props.info} mark={props.mark} /></Window>;
  return null;
}
