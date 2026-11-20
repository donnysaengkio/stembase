"""Tempo (exact beat-grid fit), key + Camelot, downbeats/phrases, loudness."""
import numpy as np
import librosa
from .common import load_mono, load_stereo, fmt_time, SR

ASR = 22050
NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
FLATS = {'C#': 'Db', 'D#': 'Eb', 'F#': 'Gb', 'G#': 'Ab', 'A#': 'Bb'}
MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
CAMELOT_MIN = {8: 1, 3: 2, 10: 3, 5: 4, 0: 5, 7: 6, 2: 7, 9: 8, 4: 9, 11: 10, 6: 11, 1: 12}   # pitch class -> number
CAMELOT_MAJ = {11: 1, 6: 2, 1: 3, 8: 4, 3: 5, 10: 6, 5: 7, 0: 8, 7: 9, 2: 10, 9: 11, 4: 12}


def key_label(pc, mode):
    n = NAMES[pc]; n = f"{n}/{FLATS[n]}" if n in FLATS else n
    return f"{n} {'minor' if mode == 'min' else 'major'}"


def camelot(pc, mode):
    return f"{CAMELOT_MIN[pc]}A" if mode == "min" else f"{CAMELOT_MAJ[pc]}B"


def detect_key(y, sr=ASR):
    """-> list of (correlation, pitch_class, 'maj'|'min'), best first."""
    ch = librosa.feature.chroma_cqt(y=y, sr=sr).mean(1)
    res = [(float(np.corrcoef(ch, np.roll(p, i))[0, 1]), i, m) for i in range(12) for m, p in (("maj", MAJ), ("min", MIN))]
    return sorted(res, reverse=True)


def minor_tonic(pc, mode):
    """Express a key as its relative-minor tonic so C minor and Eb major count as the same notes."""
    return pc if mode == "min" else (pc + 9) % 12


def grid_fit(perc, sr=ASR, bpm_lo=70, bpm_hi=180):
    """Exact constant-tempo beat grid: searches tempo (0.001 BPM) and phase that best match the onsets."""
    hop = 64
    o = librosa.onset.onset_strength(y=perc, sr=sr, hop_length=hop)
    fps = sr / hop
    t0 = float(librosa.feature.tempo(onset_envelope=o, sr=sr, hop_length=hop, start_bpm=125, max_tempo=bpm_hi)[0])
    while t0 < bpm_lo: t0 *= 2
    while t0 > bpm_hi: t0 /= 2
    best = (-1.0, t0, 0.0)
    for stage in range(2):
        lo, hi, step = (t0 - 4, t0 + 4, 0.02) if stage == 0 else (best[1] - 0.03, best[1] + 0.03, 0.001)
        for bpm in np.arange(max(lo, bpm_lo), min(hi, bpm_hi), step):
            p = 60 / bpm * fps
            k = np.arange(int((len(o) - p) / p))
            if len(k) < 8: continue
            ph = np.arange(0, p, 1.0)
            sc = o[np.rint(ph[:, None] + k[None, :] * p).astype(int)].sum(1)
            j = int(sc.argmax())
            if sc[j] > best[0]: best = (float(sc[j]), float(bpm), float(ph[j] / fps))
    return best[1], best[2]


def per_segment_rms(x, edges, sr=ASR):
    idx = np.clip((np.asarray(edges) * sr).astype(int), 0, len(x))
    return np.array([np.sqrt(np.mean(x[a:b] ** 2)) if b > a else 0.0 for a, b in zip(idx[:-1], idx[1:])])


def downbeats(harm, full, bpm, t0, sr=ASR):
    """Which beat is beat 1 (chord changes + energy jumps), and which bar starts the 8-bar phrases."""
    bt = np.arange(t0, len(full) / sr, 60 / bpm)
    C = librosa.feature.chroma_cqt(y=harm, sr=sr, hop_length=512)
    fr = librosa.time_to_frames(bt, sr=sr, hop_length=512); fr = fr[fr < C.shape[1]]
    if len(fr) < 16: return 0, 0
    cb = np.stack([C[:, a:b].mean(1) if b > a else C[:, a] for a, b in zip(fr[:-1], fr[1:])], 1)
    nov = np.r_[0, np.linalg.norm(np.diff(cb, axis=1), axis=0)]
    e = per_segment_rms(full, bt[: len(nov) + 1], sr)[: len(nov)]
    jump = np.r_[0, np.maximum(np.diff(np.log(e + 1e-4)), 0)]
    s4 = [nov[i::4].mean() / (nov.mean() + 1e-9) + jump[i::4].mean() / (jump.mean() + 1e-9) for i in range(4)]
    db = int(np.argmax(s4))
    ebar = per_segment_rms(full, bt[db::4], sr)
    jb = np.r_[0, np.maximum(np.diff(np.log(ebar + 1e-4)), 0)]
    ph = int(np.argmax([jb[i::8].sum() for i in range(8)]))
    return db, ph


def grid_from(drums_or_perc, harmonic, full, sr=ASR, bpm_range=(70, 180)):
    bpm, t0 = grid_fit(drums_or_perc, sr, *bpm_range)
    db, ph = downbeats(harmonic, full, bpm, t0, sr)
    first_bar = t0 + db * 60 / bpm
    return dict(bpm=bpm, t0=t0, downbeat_beat=db, first_downbeat=first_bar,
                phrase_start=first_bar + ph * 4 * 60 / bpm, duration=len(full) / sr)


def loudness(path):
    try:
        import pyloudnorm as pyln
        x = load_stereo(path, SR)
        lufs = pyln.Meter(SR).integrated_loudness(x)
        return round(float(lufs), 1), round(float(20 * np.log10(np.abs(x).max() + 1e-12)), 1)
    except Exception:
        return None, None


def file_info(path):
    """Format, sample rate, bit depth and channels as stored in the file."""
    try:
        import soundfile as sf
        i = sf.info(path)
        depth = {"PCM_16": "16-bit", "PCM_24": "24-bit", "PCM_32": "32-bit", "FLOAT": "32-bit float", "DOUBLE": "64-bit float",
                 "PCM_U8": "8-bit", "PCM_S8": "8-bit"}.get(i.subtype, i.subtype_info)
        return {"File Format": f"{i.format_info.split(' (')[0]}, {depth}", "Sample Rate": f"{i.samplerate} Hz",
                "Channels": {1: "Mono", 2: "Stereo"}.get(i.channels, str(i.channels))}
    except Exception:
        return {}


def analyze(path, bpm_range=(70, 180), progress=lambda f, d="": None, details=None):
    """-> dict of label -> value for display. If `details` is a dict, it is filled with the raw results
    (y, harm, grid, key_pc, key_mode, lufs, peak) for later steps such as chord detection."""
    progress(0.05, "Loading audio")
    y = load_mono(path, ASR)
    progress(0.2, "Splitting harmonic and percussive parts")
    harm, perc = librosa.effects.hpss(y)
    progress(0.4, "Fitting the beat grid")
    g = grid_from(perc, harm, y, ASR, bpm_range)
    progress(0.75, "Detecting key")
    keys = detect_key(harm)
    r, pc, mode = keys[0]
    rel = (pc + 3) % 12 if mode == "min" else (pc + 9) % 12
    alts = [f"{key_label(p, m)} · {camelot(p, m)} · {c:.2f}" for c, p, m in keys[1:4]]
    progress(0.9, "Measuring loudness")
    lufs, peak = loudness(path)
    if details is not None:
        details.update(y=y, harm=harm, grid=g, key_pc=pc, key_mode=mode, key_conf=r, lufs=lufs, peak=peak)
    return {
        **file_info(path),
        "Duration": fmt_time(g["duration"]),
        "Tempo": f"{g['bpm']:.2f} BPM",
        "Half / Double Time": f"{g['bpm'] / 2:.2f} / {g['bpm'] * 2:.2f}",
        "Key": key_label(pc, mode),
        "Camelot": camelot(pc, mode),
        "Key Confidence": f"{r:.2f} · 0.6+ is strong, under 0.4 is unclear",
        "Relative Key": key_label(rel, "maj" if mode == "min" else "min"),
        "Other Likely Keys": "; ".join(alts),
        "First Beat": f"{g['t0']:.3f} s",
        "First Downbeat": f"{g['first_downbeat']:.3f} s",
        "8-Bar Phrases Start": f"{g['phrase_start']:.3f} s",
        "Loudness": f"{lufs} LUFS" if lufs is not None else "n/a",
        "Peak": f"{peak} dBFS" if peak is not None else "n/a",
    }
