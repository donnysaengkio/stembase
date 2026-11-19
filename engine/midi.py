"""Audio to MIDI. Pitched parts use Spotify's Basic Pitch (Apache-2.0, small ONNX model, runs offline);
drums use a band-split onset detector that writes General MIDI kick / snare / hi-hat notes.
Also: per-part settings, optional grid snapping, a MIDI file at the song's tempo, an audio preview and a piano-roll image."""
import os
import numpy as np
import librosa
import soundfile as sf
from .common import output_root, track_name, check_input, SR

# What each part is, which stem holds it in a full song, and how to transcribe it.
PARTS = {
    "Vocals / lead melody": dict(stem="vocals", kind="pitched", mono=True, fmin=80, fmax=1100, program=0),
    "Bass": dict(stem="bass", kind="pitched", mono=True, fmin=28, fmax=330, program=33),
    "Chords & instruments": dict(stem="other", kind="pitched", mono=False, fmin=40, fmax=4200, program=0),
    "Piano": dict(stem="piano", kind="pitched", mono=False, fmin=27, fmax=4200, program=0),
    "Guitar": dict(stem="guitar", kind="pitched", mono=False, fmin=80, fmax=1400, program=25),
    "Drums": dict(stem="drums", kind="drums"),
}
STEM_PART = {"vocals": "Vocals / lead melody", "bass": "Bass", "other": "Chords & instruments", "piano": "Piano",
             "guitar": "Guitar", "drums": "Drums"}
SNAP = {"Off (keep the exact timing)": 0, "1/8 notes": 2, "1/16 notes": 4, "1/32 notes": 8}   # grid steps per beat
DRUM_NOTES = {"kick": 36, "snare": 38, "hihat": 42}
DRUM_NAMES = {36: "Kick", 38: "Snare / clap", 42: "Hi-hat"}
_model = None


def _bp_model():
    global _model
    if _model is None:
        from basic_pitch import ICASSP_2022_MODEL_PATH
        from basic_pitch.inference import Model
        _model = Model(ICASSP_2022_MODEL_PATH)
    return _model


# ---------------- transcription ----------------
def _monophonic(notes):
    """One note at a time (voice, bass): where notes overlap, the louder one wins and the other is trimmed or dropped."""
    out = []
    for n in sorted(notes, key=lambda n: (n[0], -n[3])):
        if out and n[0] < out[-1][1]:
            p = out[-1]
            if n[3] > p[3] and n[0] - p[0] > 0.04:
                out[-1] = (p[0], n[0], p[2], p[3]); out.append(n)
            elif n[1] > p[1] and n[3] > p[3]:
                out[-1] = n
            continue
        out.append(n)
    return out


def pitched(path, part, sensitivity=0.5, min_ms=80):
    """-> list of (start s, end s, midi pitch, amplitude 0-1)."""
    from basic_pitch.inference import predict
    cfg = PARTS[part]
    onset = float(np.interp(sensitivity, [0, 1], [0.75, 0.3]))   # higher sensitivity -> lower thresholds -> more notes
    frame = float(np.interp(sensitivity, [0, 1], [0.45, 0.2]))
    _, _, events = predict(path, _bp_model(), onset_threshold=onset, frame_threshold=frame, minimum_note_length=min_ms,
                           minimum_frequency=cfg["fmin"], maximum_frequency=cfg["fmax"], multiple_pitch_bends=False,
                           melodia_trick=True)
    notes = [(float(s), float(e), int(p), float(a)) for s, e, p, a, *_ in events]
    return _monophonic(notes) if cfg["mono"] else notes


def drums(path, sensitivity=0.5):
    """Band-split onset detection: low band -> kick, body+crack band -> snare/clap, top band -> hi-hat.
    A hit in a band only counts if that band rises clearly more than the bands next to it (stops a kick's click
    or a snare's sizzle from also being written as a hi-hat)."""
    y, sr = librosa.load(path, sr=SR, mono=True)
    hop = 256
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop))
    f = librosa.fft_frequencies(sr=sr, n_fft=2048)
    L = np.log1p(100 * S)
    flux = np.maximum(np.diff(L, axis=1, prepend=L[:, :1]), 0)

    def band(lo, hi):
        return flux[(f >= lo) & (f < hi)].mean(0)

    # Settings tuned on loops built from real one-shots with known patterns (house, breakbeat, ghost notes):
    # precision 82-99% and recall 85-95% per drum at the default sensitivity.
    env = {"kick": band(30, 140), "snare": band(1000, 6000), "hihat": band(7000, 16000)}
    for k in env: env[k] = env[k] / (np.percentile(env[k], 99.5) + 1e-9)
    keep = float(np.interp(sensitivity, [0, 1], [0.7, 0.3]))   # hit must reach this share of the band's strong hits
    wait = {"kick": 0.07, "snare": 0.07, "hihat": 0.045}
    notes = []
    for k, e in env.items():
        peaks = librosa.util.peak_pick(e, pre_max=3, post_max=3, pre_avg=40, post_avg=10, delta=0.02,
                                       wait=int(wait[k] * sr / hop))
        if not len(peaks): continue
        strong = np.percentile(e[peaks], 95)
        for p in peaks:
            if e[p] < keep * strong: continue                                  # bleed / ghost of another drum
            if k == "hihat" and e[p] < 1.0 * env["snare"][p]: continue          # snare sizzle, not a hat
            if k == "kick" and e[p] < 0.8 * env["snare"][p]: continue           # snare body, not a kick
            t = p * hop / sr
            notes.append((t, t + 0.1, DRUM_NOTES[k], float(np.clip(e[p] / strong, 0.05, 1))))
    return sorted(notes)


# ---------------- tempo, snapping, files ----------------
def tempo_grid(path_or_y, sr=22050, percussive=False):
    """(bpm, first beat s) from the percussive part; None if there is no clear beat.
    percussive=True for a drum stem: it is already percussive, so the slow harmonic/percussive split is skipped."""
    from .analysis import grid_fit
    try:
        y = librosa.load(path_or_y, sr=sr, mono=True)[0] if isinstance(path_or_y, str) else path_or_y
        perc = y if percussive else librosa.effects.hpss(y)[1]
        bpm, t0 = grid_fit(perc, sr)
        return bpm, t0
    except Exception:
        return None


def snap(notes, grid, steps_per_beat, keep_length=True):
    if not steps_per_beat or not grid: return notes
    bpm, t0 = grid
    q = 60 / bpm / steps_per_beat
    out = []
    for s, e, p, a in notes:
        s2 = t0 + round((s - t0) / q) * q
        e2 = s2 + max(q, round((e - s) / q) * q) if keep_length else s2 + (e - s)
        out.append((max(s2, 0.0), e2, p, a))
    return out


def write_midi(path, notes, is_drum, bpm=120.0, program=0, name="Part"):
    """Notes are in seconds; the tempo is stored so a DAW shows them on the right bars and beats."""
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(initial_tempo=float(bpm or 120))
    inst = pretty_midi.Instrument(program=program, is_drum=is_drum, name=name)
    for s, e, p, a in notes:
        inst.notes.append(pretty_midi.Note(velocity=int(np.clip(30 + 97 * a, 1, 127)), pitch=int(p), start=s, end=max(e, s + 0.02)))
    pm.instruments.append(inst)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pm.write(path)
    return path


# ---------------- preview audio and picture ----------------
def preview(notes, is_drum, duration, sr=SR):
    """A simple synth rendering of the MIDI, so you can hear what was transcribed."""
    out = np.zeros(int((duration + 1) * sr), np.float32)
    rng = np.random.default_rng(0)
    for s, e, p, a in notes:
        i = int(s * sr)
        if is_drum:
            n = int((0.3 if p == 36 else 0.18 if p == 38 else 0.06) * sr)
            t = np.arange(n) / sr
            if p == 36:
                x = np.sin(2 * np.pi * np.cumsum(50 + 110 * np.exp(-t * 30)) / sr) * np.exp(-t * 12)
            elif p == 38:
                x = 0.5 * np.sin(2 * np.pi * 190 * t) * np.exp(-t * 30) + rng.standard_normal(n) * np.exp(-t * 22) * 0.6
            else:
                x = np.diff(rng.standard_normal(n + 1)) * np.exp(-t * 70) * 0.35
        else:
            n = int((e - s + 0.12) * sr)
            t = np.arange(n) / sr
            hz = 440 * 2 ** ((p - 69) / 12)
            env = np.minimum(t / 0.01, 1) * np.exp(-t * 1.6) * np.clip((e - s + 0.12 - t) / 0.12, 0, 1)
            x = (np.sin(2 * np.pi * hz * t) + 0.35 * np.sin(4 * np.pi * hz * t) + 0.15 * np.sin(6 * np.pi * hz * t)) * env
        x = (x * (0.25 + 0.75 * a)).astype(np.float32)
        m = min(len(x), len(out) - i)
        if m > 0: out[i: i + m] += x[:m]
    peak = np.abs(out).max()
    return out * (0.8 / peak) if peak > 0 else out


def piano_roll(notes, is_drum, duration, width=1400, height=420):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (width, height), (17, 24, 39))
    d = ImageDraw.Draw(img)
    if not notes: d.text((20, 20), "No notes found", fill=(200, 200, 200)); return img
    left = 56
    if is_drum:
        rows = [42, 38, 36]
        y_of = {p: 30 + i * (height - 60) // 3 for i, p in enumerate(rows)}
        rh = (height - 60) // 3 - 6
        for p in rows: d.text((6, y_of[p] + rh // 2 - 6), DRUM_NAMES[p].split(" ")[0], fill=(160, 160, 170))
    else:
        lo, hi = min(n[2] for n in notes) - 2, max(n[2] for n in notes) + 2
        rh = max(2, (height - 20) / (hi - lo + 1))
        y_of = {p: int(height - 10 - (p - lo + 1) * rh) for p in range(lo, hi + 1)}
        for p in range(lo, hi + 1):
            if p % 12 == 0:
                d.line([(left, y_of[p] + rh), (width, y_of[p] + rh)], fill=(55, 65, 81))
                d.text((6, y_of[p] + rh / 2 - 6), f"C{p // 12 - 1}", fill=(160, 160, 170))
    xs = lambda t: left + (width - left - 8) * t / max(duration, 0.1)
    for s, e, p, a in notes:
        if p not in y_of: continue
        c = (int(80 + 170 * a), int(120 + 60 * a), 255) if not is_drum else (249, int(115 + 100 * (1 - a)), 22)
        x0, x1 = xs(s), max(xs(e), xs(s) + 2)
        d.rectangle([x0, y_of[p], x1, y_of[p] + max(rh - 1, 1)], fill=c)
    return img


# ---------------- high level ----------------
def _key_summary(notes):
    from .analysis import NAMES
    if not notes: return ""
    pcs = np.bincount([n[2] % 12 for n in notes], weights=[n[1] - n[0] for n in notes], minlength=12)
    return ", ".join(NAMES[i] for i in np.argsort(pcs)[::-1][:4] if pcs[i] > 0)


def transcribe(audio_path, part, out_path, sensitivity=0.5, min_ms=80, snap_label=None, grid=None, title=None):
    """Audio of one part -> MIDI file. -> dict(midi, notes, is_drum, grid, info)."""
    cfg = PARTS[part]
    is_drum = cfg["kind"] == "drums"
    notes = drums(audio_path, sensitivity) if is_drum else pitched(audio_path, part, sensitivity, min_ms)
    if grid is None: grid = tempo_grid(audio_path)
    steps = SNAP.get(snap_label or "", 0)
    notes = snap(notes, grid, steps, keep_length=not is_drum)
    bpm = grid[0] if grid else 120.0
    write_midi(out_path, notes, is_drum, bpm, cfg.get("program", 0), title or part)
    return dict(midi=out_path, notes=notes, is_drum=is_drum, grid=grid, bpm=bpm)


def describe(r, part):
    n = r["notes"]
    if not n: return "No notes were found. Try a higher sensitivity, or check the right part is selected."
    lines = [f"**{len(n)} notes** · tempo in the file {r['bpm']:.2f} BPM"]
    if r["is_drum"]:
        c = {k: sum(1 for x in n if x[2] == k) for k in DRUM_NAMES}
        lines.append(" · ".join(f"{DRUM_NAMES[k]}: {v}" for k, v in c.items()) + " (General MIDI drum notes 36 / 38 / 42)")
    else:
        lo, hi = min(x[2] for x in n), max(x[2] for x in n)
        nm = lambda p: f"{librosa.midi_to_note(p, unicode=False)}"
        lines.append(f"Range {nm(lo)}–{nm(hi)} · most used notes: {_key_summary(n)}")
    return "\n\n".join(lines)


def audio_to_midi(path, part, full_song=False, sensitivity=0.5, min_ms=80, snap_label=None, progress=lambda f, d="": None):
    """The Audio to MIDI tab. -> dict(midi, preview, image, info, folder)."""
    check_input(path)
    name, cfg = track_name(path), PARTS[part]
    folder = os.path.join(output_root(), name, "MIDI")
    src, grid = path, None
    if full_song:
        from .separate import separate
        model = "htdemucs_6s" if cfg["stem"] in ("piano", "guitar") else "htdemucs"
        progress(0.05, f"Separating the {cfg['stem']} from the song (cached after the first time)")
        files = separate(path, model, lambda f, d="": progress(0.05 + 0.6 * f, d))
        src = files[cfg["stem"]]
        progress(0.68, "Finding the tempo")
        grid = tempo_grid(files["drums"], percussive=True)   # the drum stem gives the steadiest beat
    progress(0.75, f"Transcribing the {part.lower()}")
    out = os.path.join(folder, f"{name} - {part.replace(' / ', ' & ')}.mid")
    r = transcribe(src, part, out, sensitivity, min_ms, snap_label, grid, title=f"{name} {part}")
    progress(0.92, "Rendering a preview")
    dur = sf.info(src).duration
    prev = os.path.join(folder, ".preview", f"{name} - {part.replace(' / ', ' & ')} (MIDI preview).wav")
    os.makedirs(os.path.dirname(prev), exist_ok=True)
    sf.write(prev, preview(r["notes"], r["is_drum"], dur), SR, subtype="PCM_16")
    return dict(midi=out, preview=prev, image=piano_roll(r["notes"], r["is_drum"], dur), info=describe(r, part), folder=folder)


def stems_to_midi(stem_files, stems, out_dir, name, progress=lambda f, d="": None):
    """Separate tab: MIDI for the chosen stems, next to the exported audio stems. -> dict stem -> .mid path."""
    grid = tempo_grid(stem_files["drums"], percussive=True) if "drums" in stem_files else None
    done = {}
    for i, s in enumerate(stems):
        if s not in stem_files or s not in STEM_PART: continue
        progress(i / max(len(stems), 1), f"MIDI from the {s} stem")
        part = STEM_PART[s]
        out = os.path.join(out_dir, f"{name} - {part.replace(' / ', ' & ')}.mid")
        done[s] = transcribe(stem_files[s], part, out, grid=grid, title=f"{name} {part}")["midi"]
    return done
