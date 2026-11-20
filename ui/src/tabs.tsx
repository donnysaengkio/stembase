import React, { useEffect, useState } from "react";
import { Info, FileEntry, fileUrl } from "./api";
import {
  AudioResult, Check, Field, FileDrop, FileList, Md, MultiSelect, Ph, Radio, RunRow, Section, Select, ShellAudio, ShellFiles, ShellText,
  Slider, useDoneBefore, useJob,
} from "./components";

type TabProps = { info: Info; format: string; reset: () => void };
const join = (...p: string[]) => p.join(info_sep());
function info_sep() { return navigator.userAgent.includes("Windows") ? "\\" : "/"; }

/** A tab's own output format: starts at the default from Preferences, and follows it when that changes. */
function useFormat(def: string) {
  const [fmt, setFmt] = useState(def);
  useEffect(() => setFmt(def), [def]);
  return [fmt, setFmt] as const;
}

function FormatField({ info, value, onChange }: { info: Info; value: string; onChange: (v: string) => void }) {
  return <Field label="Output Format"><Select value={value} options={info.formats} onChange={onChange} /></Field>;
}

/** Until a job has run, the results column shows a faded outline of what will appear there. */
function Shell({ children }: { children: React.ReactNode }) {
  return <div className="shell" aria-hidden="true">{children}</div>;
}

/* ---------------- Analyze ---------------- */
type AnalyzeResult = {
  name: string; rows: [string, string][]; tiles: { label: string; value: string; sub: string }[];
  chords: null | { progression: string; usage: { chord: string; pct: number }[]; source: string; changes: { bar: number; beat: number; chord: string }[] };
  chords_midi: FileEntry | null; folder: string | null;
};

export function AnalyzeTab({ info, reset }: TabProps) {
  const [path, setPath] = useState<string[]>([]);
  const [lo, setLo] = useState(70);
  const [hi, setHi] = useState(180);
  const [chords, setChords] = useState(true);
  const [novox, setNovox] = useState(false);
  const job = useJob<AnalyzeResult>("analyze", "Open MIDI Folder", true);
  useDoneBefore("analyze", path[0] ? { path: path[0] } : null, "Open MIDI Folder");
  const r = job.result;
  return (
    <div className="cols">
      <div className="col">
        <FileDrop label="Track" exts={info.audio_exts} value={path} onChange={setPath} />
        <Section title="Tempo Range">
          <Field label="Lowest BPM"><Slider value={lo} min={40} max={120} step={1} onChange={setLo} /></Field>
          <Field label="Highest BPM"><Slider value={hi} min={120} max={220} step={1} onChange={setHi} /></Field>
          <p className="muted small">If a track reads at half or double its real speed, narrow this range to where you expect it,
            e.g. 60–90 for a ballad or 160–180 for drum &amp; bass.</p>
        </Section>
        <div className="block">
          <Check checked={chords} onChange={setChords} label="Detect Chords" info="Lists the chords bar by bar and saves them as a MIDI file." />
          <Check checked={novox} onChange={setNovox} label="Remove Vocals"
            info="Gives cleaner chords. Splits the song first, and every tab reuses that split. Not needed if you have already split this song." />
        </div>
        <RunRow label="Start" onReset={reset} job={job} onRun={() => job.run({ path: path[0], bpm_lo: lo, bpm_hi: hi, chords, remove_vocals: novox })}
          folder={r?.folder || info.output_dir} />
      </div>
      <div className="col">
        {!r ? (
          <Shell>
            <div className="block card">
              <div className="tiles">
                <div className="tile tile-wide"><div className="muted small">Track Name</div><div className="tile-value">—</div></div>
                {["Key", "Tempo", "Loudness", "Length"].map((l) => (
                  <div className="tile" key={l}><div className="muted small">{l}</div><div className="tile-value">—</div><Ph w="70%" h={10} /></div>
                ))}
              </div>
              <div className="sec">Main Chord Progression</div>
              <Ph w="55%" h={20} />
              <div className="sec">Most Used</div>
              <div className="chips">{["", "", "", ""].map((_, i) => <span className="chip" key={i}><Ph w="34px" h={10} /></span>)}</div>
            </div>
            <ShellFiles title="Chords as MIDI" />
            <div className="block"><div className="block-label">Info</div><ShellText bare lines={4} /></div>
          </Shell>
        ) : (
          <>
            <div className="block card">
              <div className="tiles">
                <div className="tile tile-wide"><div className="muted small">Track Name</div><div className="tile-value">{r.name}</div></div>
                {r.tiles.map((t) => (
                  <div className="tile" key={t.label}><div className="muted small">{t.label}</div><div className="tile-value">{t.value}</div><div className="muted small">{t.sub}</div></div>
                ))}
              </div>
              {r.chords && (r.chords.progression ? (
                <>
                  <div className="sec">Main Chord Progression</div>
                  <div className="prog">{r.chords.progression}</div>
                  <div className="sec">Most Used</div>
                  <div className="chips">{r.chords.usage.map((u) => <span className="chip" key={u.chord}><b>{u.chord}</b> {u.pct}%</span>)}</div>
                  <details className="sub">
                    <summary>Chord Changes</summary>
                    <div className="chips">{r.chords.changes.map((c, i) => (
                      <span className="chip" key={i}><i>{c.bar}{c.beat === 1 ? "" : "." + c.beat}</i><b>{c.chord}</b></span>
                    ))}</div>
                  </details>
                  <div className="muted small note">Chords read from {r.chords.source}. Bar 1 is the first downbeat. Treat busy sections as a guide.</div>
                </>
              ) : <div className="muted small note">No clear chords found. The track may be mostly drums or speech.</div>)}
            </div>
            {r.chords_midi && <FileList title="Chords as MIDI" files={[r.chords_midi]} />}
            <Section title="Info">
              <table className="table info-table"><tbody>{r.rows.map(([k, v]) => <tr key={k}><td className="muted">{k}</td><td>{v}</td></tr>)}</tbody></table>
            </Section>
          </>
        )}
      </div>
    </div>
  );
}

/* ---------------- Split ---------------- */
type SplitResult = { stems: (FileEntry & { stem: string; label: string })[]; midi: FileEntry[]; folder: string };

export function SplitTab({ info, format, reset }: TabProps) {
  const [path, setPath] = useState<string[]>([]);
  const [model, setModel] = useState(info.models[0]);
  const [midi, setMidi] = useState<string[]>([]);
  const [fmt, setFmt] = useFormat(format);
  const job = useJob<SplitResult>("separate", "Open Stems Folder");
  useDoneBefore("split", path[0] ? { path: path[0], model } : null, "Open Stems Folder");
  const r = job.result;
  return (
    <div className="cols">
      <div className="col">
        <FileDrop label="Track" exts={info.audio_exts} value={path} onChange={setPath} />
        <div className="block">
          <Field label="Model"><Select value={model} options={info.models} onChange={setModel} /></Field>
          <FormatField info={info} value={fmt} onChange={setFmt} />
          <div className="field">
            <span className="field-label">MIDI</span>
            <MultiSelect value={midi} options={info.midi_stems} onChange={setMidi}
              placeholder="Choose Stems to Make MIDI From" />
          </div>
        </div>
        <RunRow label="Start" onReset={reset} job={job} onRun={() => job.run({ path: path[0], model, midi, format: fmt })}
          folder={r?.folder || info.output_dir} />
      </div>
      <div className="col">
        {!r ? <Shell>{["Vocals", "Drums", "Bass", "Other", "Instrumental"].map((l) => <ShellAudio key={l} label={l} />)}</Shell> : (
          <>
            {r.stems.map((s) => <AudioResult key={s.path} f={s} label={s.label} />)}
            {r.midi.length > 0 && <FileList title="MIDI Files" files={r.midi} />}
          </>
        )}
      </div>
    </div>
  );
}

/* ---------------- MIDI ---------------- */
type MidiResult = { message: string; midi: FileEntry; preview: FileEntry; image: FileEntry; folder: string };

export function MidiTab({ info, reset }: TabProps) {
  const [path, setPath] = useState<string[]>([]);
  const [source, setSource] = useState(info.midi_source[0]);
  const [part, setPart] = useState(info.midi_parts[0]);
  const [sens, setSens] = useState(0.5);
  const [minMs, setMinMs] = useState(80);
  const [snap, setSnap] = useState(info.snap[0]);
  const job = useJob<MidiResult>("midi", "Open MIDI Folder");
  useDoneBefore("midi", path[0] ? { path: path[0] } : null, "Open MIDI Folder");
  const r = job.result;
  return (
    <div className="cols">
      <div className="col">
        <FileDrop label="Recording" exts={info.audio_exts} value={path} onChange={setPath} />
        <div className="block">
          <Field label="What Is This File?"><Radio value={source} options={info.midi_source} onChange={setSource} /></Field>
          <Field label="Part to Turn Into MIDI"><Select value={part} options={info.midi_parts} onChange={setPart} /></Field>
        </div>
        <Section title="Fine-Tune">
          <Field label="Sensitivity" info="Higher finds quieter notes and hits, but also more mistakes"><Slider value={sens} min={0} max={1} step={0.05} onChange={setSens} /></Field>
          <Field label="Shortest Note in ms" info="Ignored for drums"><Slider value={minMs} min={30} max={300} step={10} onChange={setMinMs} /></Field>
          <Field label="Snap to the Beat Grid"><Select value={snap} options={info.snap} onChange={setSnap} /></Field>
        </Section>
        <RunRow label="Start" onReset={reset} job={job} onRun={() => job.run({ path: path[0], source, part, sensitivity: sens, min_ms: minMs, snap })}
          folder={r?.folder || info.output_dir} />
      </div>
      <div className="col">
        {!r ? (
          <Shell>
            <ShellFiles title="MIDI File" />
            <ShellAudio label="Preview" />
            <div className="block"><div className="block-label">Piano Roll</div><div className="shell-roll" /></div>
            <ShellText />
          </Shell>
        ) : (
          <>
            <FileList title="MIDI File" files={[r.midi]} />
            <AudioResult f={r.preview} label="Preview" />
            <div className="block"><div className="block-label">Piano Roll</div><img className="roll" src={fileUrl(r.image.path)} alt="Piano Roll" /></div>
            <div className="block"><Md text={r.message} /></div>
          </>
        )}
      </div>
    </div>
  );
}

/* ---------------- Mix ---------------- */
type MixResult = { audio: FileEntry; message: string; folder: string };

export function MixTab({ info, format, reset }: TabProps) {
  const [voc, setVoc] = useState<string[]>([]);
  const [ins, setIns] = useState<string[]>([]);
  const [arr, setArr] = useState(info.arrange[0]);
  const [key, setKey] = useState("Auto");
  const [gain, setGain] = useState(0);
  const [model, setModel] = useState(info.models[0]);
  const [fmt, setFmt] = useFormat(format);
  const job = useJob<MixResult>("mashup", "Open Mashup Folder");
  useDoneBefore("mashup", voc[0] && ins[0] ? { vocals: voc[0], instrumental: ins[0] } : null, "Open Mashup Folder");
  const r = job.result;
  const keys = ["Auto", ...Array.from({ length: 13 }, (_, i) => (i - 6 > 0 ? "+" : "") + (i - 6))];
  return (
    <div className="cols">
      <div className="col">
        <FileDrop label="Take the Vocals From" exts={info.audio_exts} value={voc} onChange={setVoc} />
        <FileDrop label="Put Them Over the Music Of" exts={info.audio_exts} value={ins} onChange={setIns} />
        <div className="block">
          <Field label="Arrangement"><Radio value={arr} options={info.arrange} onChange={setArr} /></Field>
          <Field label="Vocal Key Shift in Semitones" info="Auto matches the instrumental's key."><Select value={key} options={keys} onChange={setKey} /></Field>
          <Field label="Vocal Level in dB"><Slider value={gain} min={-12} max={12} step={0.5} onChange={setGain} /></Field>
          <Field label="Separation Model"><Select value={model} options={info.models.slice(0, 2)} onChange={setModel} /></Field>
          <FormatField info={info} value={fmt} onChange={setFmt} />
        </div>
        <RunRow label="Start" onReset={reset} job={job}
          onRun={() => job.run({ vocals: voc[0], instrumental: ins[0], arrangement: arr, key, vocal_gain: gain, model, format: fmt })}
          folder={r?.folder || join(info.output_dir, "Mashups")} />
      </div>
      <div className="col">
        {!r ? <Shell><ShellAudio label="Mashup" /><ShellText lines={4} /></Shell> : (
          <>
            <AudioResult f={r.audio} label="Mashup" />
            <div className="block"><Md text={r.message} /></div>
          </>
        )}
      </div>
    </div>
  );
}

/* ---------------- Shift ---------------- */
type ShiftResult = { audio: FileEntry; message: string; folder: string };

export function ShiftTab({ info, format, reset }: TabProps) {
  const [path, setPath] = useState<string[]>([]);
  const [semis, setSemis] = useState(0);
  const [bpm, setBpm] = useState(0);
  const [fmt, setFmt] = useFormat(format);
  const job = useJob<ShiftResult>("shift", "Open Folder");
  useDoneBefore("shift", path[0] ? { path: path[0] } : null, "Open Folder");
  const r = job.result;
  return (
    <div className="cols">
      <div className="col">
        <FileDrop label="Track" exts={info.audio_exts} value={path} onChange={setPath} />
        <div className="block">
          <Field label="Key Shift in Semitones"><Slider value={semis} min={-12} max={12} step={1} onChange={setSemis} unit="st" /></Field>
          <Field label="Target BPM" info="0 keeps the tempo. The current tempo is detected for you.">
            <input type="number" min={0} step={0.01} value={bpm} onChange={(e) => setBpm(Number(e.target.value))} />
          </Field>
          <FormatField info={info} value={fmt} onChange={setFmt} />
        </div>
        <RunRow label="Start" onReset={reset} job={job} onRun={() => job.run({ path: path[0], semitones: semis, bpm, format: fmt })}
          folder={r?.folder || info.output_dir} />
      </div>
      <div className="col">
        {!r ? <Shell><ShellAudio label="Result" /><ShellText /></Shell> : (
          <>
            <AudioResult f={r.audio} label="Result" />
            <div className="block"><Md text={r.message} /></div>
          </>
        )}
      </div>
    </div>
  );
}

/* ---------------- Encode ---------------- */
type EncodeResult = { files: FileEntry[]; rows: string[][]; message: string; folder: string };

export function EncodeTab({ info, reset }: TabProps) {
  const [paths, setPaths] = useState<string[]>([]);
  const [mode, setMode] = useState(info.convert_modes[0]);
  const [fmt, setFmt] = useState("MP3 · 320 kbps");
  const [mb, setMb] = useState(8);
  const [codec, setCodec] = useState(info.target_codecs[0]);
  const [rate, setRate] = useState(info.sample_rates[0]);
  const [ch, setCh] = useState(info.channels[0]);
  const job = useJob<EncodeResult>("convert", "Open Converted Folder");
  useDoneBefore("convert", paths.length ? { paths } : null, "Open Converted Folder");
  const r = job.result;
  const fit = mode === info.convert_modes[1];
  return (
    <div className="cols">
      <div className="col">
        <FileDrop label="Audio Files" exts={info.audio_exts} value={paths} onChange={setPaths} multiple />
        <div className="block">
          <Field label="What to Do"><Radio value={mode} options={info.convert_modes} onChange={setMode} /></Field>
          {!fit ? (
            <Field label="Output Format and Quality"><Select value={fmt} options={info.convert_formats} onChange={setFmt} /></Field>
          ) : (
            <div className="row gap">
              <Field label="Target Size per File in MB"><input type="number" min={0.1} step={0.1} value={mb} onChange={(e) => setMb(Number(e.target.value))} /></Field>
              <Field label="Encode As"><Select value={codec} options={info.target_codecs} onChange={setCodec} /></Field>
            </div>
          )}
        </div>
        <Section title="Make It Smaller Still">
          <Field label="Sample Rate"><Select value={rate} options={info.sample_rates} onChange={setRate} /></Field>
          <Field label="Channels"><Radio value={ch} options={info.channels} onChange={setCh} /></Field>
        </Section>
        <RunRow label="Start" onReset={reset} job={job}
          onRun={() => job.run({ paths, mode, format: fmt, target_mb: mb, codec, sample_rate: rate, channels: ch })}
          folder={r?.folder || join(info.output_dir, "Converted")} />
      </div>
      <div className="col">
        {!r ? (
          <Shell>
            <ShellFiles title="Converted Files" count={2} />
            <ShellText lines={2} />
            <div className="block">
              <div className="block-label">Before and After</div>
              <ShellText bare lines={3} />
            </div>
          </Shell>
        ) : (
          <>
            {r.files.length > 0 && <FileList title="Converted Files" files={r.files} />}
            <div className="block"><Md text={r.message} /></div>
            {r.rows.length > 0 && (
              <div className="block scroll-x">
                <div className="block-label">Before and After</div>
                <table className="table">
                  <thead><tr>{["File", "Now", "Audio", "Before", "After", "Change", "Saved As"].map((h) => <th key={h}>{h}</th>)}</tr></thead>
                  <tbody>{r.rows.map((row, i) => <tr key={i}>{row.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
                </table>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
