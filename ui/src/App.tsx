import { useEffect, useState } from "react";
import { getCurrentWebview } from "@tauri-apps/api/webview";
import {
  IconChartBar, IconStack3, IconPiano, IconAdjustmentsHorizontal, IconPlusMinus, IconFileExport,
} from "@tabler/icons-react";
import { connect, inApp, Info, openLocation, waitReady } from "./api";
import { highlightDrop, ModalProvider, routeDrop } from "./components";
import { applyTheme, loadPrefs, MainMenu, MenuWindows, Prefs, savePrefs, useQuit, useShortcuts, useUpdates } from "./menu";
import { AnalyzeTab, EncodeTab, MidiTab, MixTab, ShiftTab, SplitTab } from "./tabs";

/** Logo T1e: a straight line, a gap, then black (white in the dark theme), blue and orange bars. */
export function Mark({ size = 34 }: { size?: number }) {
  const L: [number, number, number, number, string][] = [
    [4, 32, 28, 32, "var(--ink)"], [38, 22, 38, 42, "var(--ink)"], [46, 14, 46, 50, "var(--ink)"],
    [54, 18, 54, 46, "#2563EB"], [62, 26, 62, 38, "#2563EB"], [70, 20, 70, 44, "#EA580C"], [78, 28, 78, 36, "#EA580C"],
  ];
  return (
    <svg width={(size * 82) / 64} height={size} viewBox="0 0 82 64" fill="none" strokeWidth={5} strokeLinecap="round" aria-hidden="true">
      {L.map(([a, b, c, d, col], i) => <path key={i} d={`M${a} ${b}L${c} ${d}`} style={{ stroke: col }} />)}
    </svg>
  );
}

const TABS = [
  { id: "analyze", label: "Analyze", Icon: IconChartBar, C: AnalyzeTab },
  { id: "split", label: "Split", Icon: IconStack3, C: SplitTab },
  { id: "midi", label: "MIDI", Icon: IconPiano, C: MidiTab },
  { id: "mix", label: "Mix", Icon: IconAdjustmentsHorizontal, C: MixTab },
  { id: "shift", label: "Shift", Icon: IconPlusMinus, C: ShiftTab },
  { id: "encode", label: "Encode", Icon: IconFileExport, C: EncodeTab },
];

function Splash({ error }: { error: string | null }) {
  return (
    <div className="splash">
      <div className="brand big-brand"><Mark size={56} /><span className="wordmark">stembase</span></div>
      {error ? (
        <div className="block error-box"><b>The audio engine could not start.</b><pre>{error}</pre></div>
      ) : (
        <div className="muted">Starting the audio engine…</div>
      )}
    </div>
  );
}

function Main({ info, prefs, setPrefs, patchInfo }: { info: Info; prefs: Prefs; setPrefs: (p: Prefs) => void; patchInfo: (p: Partial<Info>) => void }) {
  const [tab, setTab] = useState("analyze");
  const [fresh, setFresh] = useState<Record<string, number>>({});   // bumping a tab's number starts it afresh (Reset)
  const checkUpdates = useUpdates(info, prefs);
  const quit = useQuit();
  const format = info.formats.includes(prefs.format) ? prefs.format : info.default_format;
  useShortcuts({
    checkUpdates, quit, tab: (i) => setTab(TABS[i].id), output: () => openLocation(info.output_dir),
  });
  return (
    <div className="app">
      <header className="top">
        <div className="brand"><Mark /><span className="wordmark">stembase</span></div>
        <div className="top-right">
          <MainMenu checkUpdates={checkUpdates} quit={quit} />
        </div>
      </header>
      <nav className="tabs" role="tablist">
        {TABS.map(({ id, label, Icon }) => (
          <button key={id} role="tab" aria-selected={tab === id} className={tab === id ? "on" : ""} onClick={() => setTab(id)}>
            <Icon size={22} stroke={1.75} /><span>{label}</span>
          </button>
        ))}
      </nav>
      <main>
        {TABS.map(({ id, C }) => (
          <section key={id} hidden={tab !== id}>
            <C key={fresh[id] || 0} info={info} format={format} reset={() => setFresh({ ...fresh, [id]: (fresh[id] || 0) + 1 })} />
          </section>
        ))}
      </main>
      <MenuWindows info={info} prefs={{ ...prefs, format }} setPrefs={setPrefs} checkUpdates={checkUpdates} patchInfo={patchInfo} mark={<Mark size={56} />} />
    </div>
  );
}

export default function App() {
  const [info, setInfo] = useState<Info | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [prefs, setPrefsState] = useState<Prefs>(loadPrefs);
  const setPrefs = (p: Prefs) => { setPrefsState(p); savePrefs(p); };

  useEffect(() => { applyTheme(prefs); }, [prefs]);
  useEffect(() => {
    connect().then(waitReady).then(setInfo).catch((e) => setError(String(e.message || e)));
  }, []);

  // Files dropped anywhere on the window go to the drop zone under the pointer.
  useEffect(() => {
    if (!inApp) return;
    const un = getCurrentWebview().onDragDropEvent((e) => {
      const p = e.payload as any;
      const dpr = window.devicePixelRatio || 1;
      const xy = p.position ? [p.position.x / dpr, p.position.y / dpr] : null;
      if (p.type === "over" || p.type === "enter") highlightDrop(xy && xy[0], xy && xy[1]);
      else if (p.type === "drop") { highlightDrop(null, null); if (xy) routeDrop(xy[0], xy[1], p.paths || []); }
      else highlightDrop(null, null);
    });
    return () => { un.then((f) => f()); };
  }, []);

  if (!info) return <Splash error={error} />;
  return <ModalProvider><Main info={info} prefs={prefs} setPrefs={setPrefs}
    patchInfo={(p) => setInfo({ ...info, ...p })} /></ModalProvider>;
}
