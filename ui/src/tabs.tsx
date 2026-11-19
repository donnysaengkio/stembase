import { useEffect, useState } from "react";
import { Info, FileEntry, fileUrl } from "./api";
import {
  AudioResult, Check, Field, FileDrop, FileList, Md, MultiSelect, Radio, RunRow, Section, Select, Slider, useDoneBefore, useJob,
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
  return <Field label="Output format"><Select value={value} options={info.formats} onChange={onChange} /></Field>;
}

/** Nothing in the results column until a job has run. */
function Empty(_: { text: string }) {
  return null;
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
  const job = useJob<AnalyzeResult>("analyze", "Open MIDI folder", true);
  useDoneBefore("analyze", path[0] ? { path: path[0] } : null, "Open MIDI folder");
  const r = job.result;
  return (
    <div className="cols">
      <div className="col">
        <FileDrop label="Track" exts={info.audio_exts} value={path} onChange={setPath} />
        <Section title="Tempo range">
          <Field label="Lowest BPM"><Slider value={lo} min={40} max={120} step={1} onChange={setLo} /></Field>
          <Field label="Highest BPM"><Slider value={hi} min={120} max={220} step={1} onChange={setHi} /></Field>
          <p className="muted small">If a track reads at half or double its real speed, narrow this range to where you expect it,
            e.g. 60–90 for a ballad or 160–180 for drum &amp; bass.</p>
        </Section>
        <div className="block">
          <Check checked={chords} onChange={setChords} label="Detect chords" info="Lists the chords bar by bar and saves them as a MIDI file." />
          <Check checked={novox} onChange={setNovox} label="Remove vocals first (cleaner chords)"
            info="Adds a stem split (about a minute or two on a CPU, then reused by every tab). Not needed if you have already split this song." />
        </div>
        <RunRow label="Start" onReset={reset} job={job} onRun={() => job.run({ path: path[0], bpm_lo: lo, bpm_hi: hi, chords, remove_vocals: novox })}
          folder={r?.folder || info.output_dir} />
      </div>
      <div className="col">
        {!r ? <Empty text="Drop a track and press Analyze. Key, tempo, loudness and chords appear here." /> : (
          <>
            <div className="block card">
              <div className="tiles">
                <div className="tile tile-wide"><div className="muted small">Track name</div><div className="tile-value">{r.name}</div></div>
                {r.tiles.map((t) => (
                  <div className="tile" key={t.label}><div className="muted small">{t.label}</div><div className="tile-value">{t.value}</div><div className="muted small">{t.sub}</div></div>
                ))}
              </div>
              {r.chords && (r.chords.progression ? (
                <>
                  <div className="sec">Main chord progression</div>
                  <div className="prog">{r.chords.progression}</div>
                  <div className="sec">Most used</div>
                  <div className="chips">{r.chords.usage.map((u) => <span className="chip" key={u.chord}><b>{u.chord}</b> {u.pct}%</span>)}</div>
                  <details className="sub">
                    <summary>Chord changes <span className="muted small">(bar number, then chord)</span></summary>
                    <div className="chips">{r.chords.changes.map((c, i) => (
                      <span className="chip" key={i}><i>{c.bar}{c.beat === 1 ? "" : "." + c.beat}</i><b>{c.chord}</b></span>
                    ))}</div>
                  </details>
                  <div className="muted small note">Chords read from {r.chords.source}. Bar 1 is the first downbeat. Treat busy sections as a guide.</div>
                </>
              ) : <div className="muted small note">No clear chords found (the track may be mostly drums or speech).</div>)}
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
  const job = useJob<SplitResult>("separate", "Open stems folder");
  useDoneBefore("split", path[0] ? { path: path[0], model } : null, "Open stems folder");
  const r = job.result;
  return (
    <div className="cols">
      <div className="col">
        <FileDrop label="Track" exts={info.audio_exts} value={path} onChange={setPath} />
        <div className="block">
          <Field label="Model"><Select value={model} options={info.models} onChange={setModel} /></Field>
          <FormatField info={info} value={fmt} onChange={setFmt} />
          <div className="field">
            <span className="field-label">MIDI (Optional)</span>
            <MultiSelect value={midi} options={info.midi_stems} onChange={setMidi}
              placeholder="Choose the stems to make MIDI from" />
          </div>
        </div>
        <RunRow label="Start" onReset={reset} job={job} onRun={() => job.run({ path: path[0], model, midi, format: fmt })}
          folder={r?.folder || info.output_dir} />
      </div>
      <div className="col">
        {!r ? <Empty text="Your stems appear here, ready to play, and are saved in your Music folder." /> : (
          <>
            {r.stems.map((s) => <AudioResult key={s.path} f={s} label={s.label} />)}
            {r.midi.length > 0 && <FileList title="MIDI files" files={r.midi} />}
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
  const job = useJob<MidiResult>("midi", "Open MIDI folder");
  useDoneBefore("midi", path[0] ? { path: path[0] } : null, "Open MIDI folder");
  const r = job.result;
  return (
    <div className="cols">
      <div className="col">
        <FileDrop label="Recording" exts={info.audio_exts} value={path} onChange={setPath} />
        <div className="block">
          <Field label="What is this file?"><Radio value={source} options={info.midi_source} onChange={setSource} /></Field>
          <Field label="Part to turn into MIDI"><Select value={part} options={info.midi_parts} onChange={setPart} /></Field>
        </div>
        <Section title="Fine-tune">
          <Field label="Sensitivity" info="Higher finds quieter notes and hits, but also more mistakes"><Slider value={sens} min={0} max={1} step={0.05} onChange={setSens} /></Field>
          <Field label="Shortest note (ms)" info="Ignored for drums"><Slider value={minMs} min={30} max={300} step={10} onChange={setMinMs} /></Field>
          <Field label="Snap to the beat grid"><Select value={snap} options={info.snap} onChange={setSnap} /></Field>
        </Section>
        <RunRow label="Start" onReset={reset} job={job} onRun={() => job.run({ path: path[0], source, part, sensitivity: sens, min_ms: minMs, snap })}
          folder={r?.folder || info.output_dir} />
      </div>
      <div className="col">
        {!r ? <Empty text="The MIDI file, a preview you can play and a piano roll appear here." /> : (
          <>
            <FileList title="MIDI file" files={[r.midi]} />
            <AudioResult f={r.preview} label="Preview (the MIDI played by a simple synth)" />
            <div className="block"><div className="block-label">Piano roll</div><img className="roll" src={fileUrl(r.image.path)} alt="Piano roll" /></div>
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
  const job = useJob<MixResult>("mashup", "Open mashup folder");
  useDoneBefore("mashup", voc[0] && ins[0] ? { vocals: voc[0], instrumental: ins[0] } : null, "Open mashup folder");
  const r = job.result;
  const keys = ["Auto", ...Array.from({ length: 13 }, (_, i) => (i - 6 > 0 ? "+" : "") + (i - 6))];
  return (
    <div className="cols">
      <div className="col">
        <FileDrop label="Take the vocals from" exts={info.audio_exts} value={voc} onChange={setVoc} />
        <FileDrop label="Put them over the music of" exts={info.audio_exts} value={ins} onChange={setIns} />
        <div className="block">
          <Field label="Arrangement"><Radio value={arr} options={info.arrange} onChange={setArr} /></Field>
          <Field label="Vocal key shift in semitones (Auto matches the instrumental's key)"><Select value={key} options={keys} onChange={setKey} /></Field>
          <Field label="Vocal level (dB)"><Slider value={gain} min={-12} max={12} step={0.5} onChange={setGain} /></Field>
          <Field label="Separation model"><Select value={model} options={info.models.slice(0, 2)} onChange={setModel} /></Field>
          <FormatField info={info} value={fmt} onChange={setFmt} />
        </div>
        <RunRow label="Start" onReset={reset} job={job}
          onRun={() => job.run({ vocals: voc[0], instrumental: ins[0], arrangement: arr, key, vocal_gain: gain, model, format: fmt })}
          folder={r?.folder || join(info.output_dir, "Mashups")} />
      </div>
      <div className="col">
        {!r ? <Empty text="Your mashup appears here with a report of how the two songs were matched." /> : (
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
  const job = useJob<ShiftResult>("shift", "Open folder");
  useDoneBefore("shift", path[0] ? { path: path[0] } : null, "Open folder");
  const r = job.result;
  return (
    <div className="cols">
      <div className="col">
        <FileDrop label="Track" exts={info.audio_exts} value={path} onChange={setPath} />
        <div className="block">
          <Field label="Key shift (semitones)"><Slider value={semis} min={-12} max={12} step={1} onChange={setSemis} unit="st" /></Field>
          <Field label="Target BPM" info="0 keeps the tempo; the current tempo is detected for you">
            <input type="number" min={0} step={0.01} value={bpm} onChange={(e) => setBpm(Number(e.target.value))} />
          </Field>
          <FormatField info={info} value={fmt} onChange={setFmt} />
        </div>
        <RunRow label="Start" onReset={reset} job={job} onRun={() => job.run({ path: path[0], semitones: semis, bpm, format: fmt })}
          folder={r?.folder || info.output_dir} />
      </div>
      <div className="col">
        {!r ? <Empty text="The shifted version appears here." /> : (
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
  const job = useJob<EncodeResult>("convert", "Open converted folder");
  useDoneBefore("convert", paths.length ? { paths } : null, "Open converted folder");
  const r = job.result;
  const fit = mode === info.convert_modes[1];
  return (
    <div className="cols">
      <div className="col">
        <FileDrop label="Audio files; add as many as you like" exts={info.audio_exts} value={paths} onChange={setPaths} multiple />
        <div className="block">
          <Field label="What to do"><Radio value={mode} options={info.convert_modes} onChange={setMode} /></Field>
          {!fit ? (
            <Field label="Output format and quality"><Select value={fmt} options={info.convert_formats} onChange={setFmt} /></Field>
          ) : (
            <div className="row gap">
              <Field label="Target size per file (MB)"><input type="number" min={0.1} step={0.1} value={mb} onChange={(e) => setMb(Number(e.target.value))} /></Field>
              <Field label="Encode as"><Select value={codec} options={info.target_codecs} onChange={setCodec} /></Field>
            </div>
          )}
        </div>
        <Section title="Make it smaller still">
          <Field label="Sample rate"><Select value={rate} options={info.sample_rates} onChange={setRate} /></Field>
          <Field label="Channels"><Radio value={ch} options={info.channels} onChange={setCh} /></Field>
        </Section>
        <RunRow label="Start" onReset={reset} job={job}
          onRun={() => job.run({ paths, mode, format: fmt, target_mb: mb, codec, sample_rate: rate, channels: ch })}
          folder={r?.folder || join(info.output_dir, "Converted")} />
      </div>
      <div className="col">
        {!r ? <Empty text="Converted files appear here with a before-and-after comparison." /> : (
          <>
            {r.files.length > 0 && <FileList title="Converted files" files={r.files} />}
            <div className="block"><Md text={r.message} /></div>
            {r.rows.length > 0 && (
              <div className="block scroll-x">
                <div className="block-label">Before and after</div>
                <table className="table">
                  <thead><tr>{["File", "Now", "Audio", "Before", "After", "Change", "Saved as"].map((h) => <th key={h}>{h}</th>)}</tr></thead>
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
