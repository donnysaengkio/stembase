"""Chord detection: beat-synchronous chroma matched against chord templates, smoothed with a Viterbi pass.

Works on the harmonic part of the music. Vocals confuse it, so the caller passes an instrumental (stems without
vocals) when one is available. Chords are found per beat, changes are favoured on bar lines, and chords that belong
to the detected key get a small bonus.
"""
import numpy as np
import librosa

from .analysis import ASR, NAMES, FLATS

# quality -> (intervals, label suffix, prior). Sevenths need clear evidence, so they start a little behind triads.
QUALITIES = {
    "maj": ((0, 4, 7), "", 1.0),
    "min": ((0, 3, 7), "m", 1.0),
    "7": ((0, 4, 7, 10), "7", 0.9),
    "maj7": ((0, 4, 7, 11), "maj7", 0.9),
    "m7": ((0, 3, 7, 10), "m7", 0.9),
    "sus4": ((0, 5, 7), "sus4", 0.93),
    "dim": ((0, 3, 6), "dim", 0.92),
}
BASS_W = 0.2    # tuned on Vengeance kit chord loops with their MIDI as ground truth
MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
NATURAL_MINOR = (0, 2, 3, 5, 7, 8, 10)


def _templates(sevenths=True):
    labels, T, prior, roots, ivs = [], [], [], [], []
    for q, (iv, suf, p) in QUALITIES.items():
        if not sevenths and len(iv) > 3: continue
        for r in range(12):
            t = np.full(12, 0.0)
            for k, i in enumerate(iv):
                t[(r + i) % 12] = 1.0 if k < 3 else 0.7   # the 7th weighs a little less than the triad
            t[r] += 0.3                                   # the root is usually the strongest note
            labels.append((r, q)); T.append(t / np.linalg.norm(t)); prior.append(p); roots.append(r); ivs.append(iv)
    return labels, np.array(T), np.array(prior), np.array(roots), ivs


SHARP_KEYS = {("maj", p) for p in (7, 2, 9, 4, 11, 6)} | {("min", p) for p in (4, 11, 6, 1, 8, 3)}


def chord_name(root, quality, key_pc=0, key_mode="maj"):
    """Spelled with sharps in sharp keys (G, D, A, E, B, F# major and their relative minors), flats otherwise."""
    n = NAMES[root]
    if (key_mode, key_pc) not in SHARP_KEYS: n = FLATS.get(n, n)
    return n + QUALITIES[quality][1]


def _diatonic(root, quality, key_pc, key_mode):
    scale = NATURAL_MINOR if key_mode == "min" else MAJOR_SCALE
    pcs = {(key_pc + s) % 12 for s in scale}
    if key_mode == "min": pcs.add((key_pc + 11) % 12)   # harmonic minor: the major V chord
    return all((root + i) % 12 in pcs for i in QUALITIES[quality][0])


def beat_chroma(y, beats, sr=ASR):
    """-> (12 x n_beats treble chroma, 12 x n_beats bass chroma, energy per beat)."""
    hop = 512
    tre = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop, fmin=librosa.note_to_hz("C3"), n_octaves=4,
                                     bins_per_octave=36, norm=None)
    bas = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop, fmin=librosa.note_to_hz("E1"), n_octaves=2,
                                     bins_per_octave=36, norm=None)
    n = min(tre.shape[1], bas.shape[1])
    fr = librosa.time_to_frames(beats, sr=sr, hop_length=hop)
    fr = np.unique(np.clip(fr, 0, n))
    tre = librosa.util.sync(tre[:, :n], fr, aggregate=np.median)[:, :len(fr) - 1]
    bas = librosa.util.sync(bas[:, :n], fr, aggregate=np.median)[:, :len(fr) - 1]
    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    e = librosa.util.sync(rms[None, :n], fr, aggregate=np.mean)[0, :len(fr) - 1]
    return tre, bas, e, fr


def detect(y, bpm, t0, first_downbeat, key_pc, key_mode, sr=ASR, sevenths=True, beats_per_bar=4):
    """-> list of dict(start, end, chord, root, quality, bar, beat) over the track, one entry per chord change."""
    dur = len(y) / sr
    step = 60.0 / bpm
    start = t0 - step * np.ceil(t0 / step) if t0 > 0 else t0
    beats = np.arange(max(start, 0.0), dur + step, step)
    if len(beats) < 3: return []
    tre, bas, e, fr = beat_chroma(y, beats, sr)
    nb = tre.shape[1]
    beats = beats[:nb + 1]

    labels, T, prior, roots, _ = _templates(sevenths)
    X = np.log1p(10 * tre / (tre.max() + 1e-9))
    X = X / (np.linalg.norm(X, axis=0, keepdims=True) + 1e-9)
    B = bas / (bas.sum(0, keepdims=True) + 1e-9)
    score = T @ X                                         # cosine similarity, chords x beats
    score += BASS_W * B[roots, :]                         # a bass note on the root confirms the chord
    score *= prior[:, None]
    dia = np.array([_diatonic(r, q, key_pc, key_mode) for r, q in labels])
    score += 0.04 * dia[:, None]

    # "No chord" where the music is quiet or has no clear harmony.
    quiet = e < 0.08 * np.percentile(e, 95)

    # Viterbi: staying on a chord is free, changing costs more off the bar line than on it.
    nc = len(labels)
    bar_pos = np.round((beats[:nb] - first_downbeat) / step).astype(int) % beats_per_bar
    cost_on, cost_half, cost_off = 0.06, 0.10, 0.22
    D = np.zeros((nc, nb)); P = np.zeros((nc, nb), dtype=int)
    D[:, 0] = score[:, 0]
    for t in range(1, nb):
        pen = cost_on if bar_pos[t] == 0 else cost_half if bar_pos[t] == beats_per_bar // 2 else cost_off
        prev = D[:, t - 1]
        best = int(prev.argmax())
        stay = prev
        switch = prev[best] - pen
        take_switch = switch > stay
        D[:, t] = np.where(take_switch, switch, stay) + score[:, t]
        P[:, t] = np.where(take_switch, best, np.arange(nc))
    path = np.zeros(nb, dtype=int); path[-1] = int(D[:, -1].argmax())
    for t in range(nb - 1, 0, -1): path[t - 1] = P[path[t], t]
    # A chord that lasts a single beat off the bar line is usually a passing note or a fill: fold it into the chord before.
    for t in range(1, nb - 1):
        if path[t] != path[t - 1] and path[t + 1] != path[t] and bar_pos[t] != 0:
            path[t] = path[t - 1]

    out = []
    for t in range(nb):
        r, q = labels[path[t]]
        name = "N" if quiet[t] else chord_name(r, q, key_pc, key_mode)
        if out and out[-1]["chord"] == name:
            out[-1]["end"] = float(beats[t + 1]); continue
        rel = int(np.round((beats[t] - first_downbeat) / step))
        out.append(dict(start=float(beats[t]), end=float(beats[t + 1]), chord=name, root=r, quality=q,
                        bar=rel // beats_per_bar + 1, beat=rel % beats_per_bar + 1))
    return out


def summary(segs, top=6):
    """Most common progression and time per chord."""
    segs = [s for s in segs if s["chord"] != "N"]
    if not segs: return "", []
    time = {}
    for s in segs: time[s["chord"]] = time.get(s["chord"], 0) + s["end"] - s["start"]
    total = sum(time.values())
    usage = sorted(time.items(), key=lambda kv: -kv[1])[:top]
    # The repeating progression: the most frequent run of 4 consecutive chords.
    seq = [s["chord"] for s in segs]
    runs = {}
    for n in (4, 3, 2):
        for i in range(len(seq) - n + 1):
            k = tuple(seq[i:i + n])
            if len(set(k)) < 2: continue
            runs[k] = runs.get(k, 0) + 1
        if runs and max(runs.values()) >= 2: break
    prog = " – ".join(max(runs, key=runs.get)) if runs else " – ".join(dict.fromkeys(seq))
    return prog, [(c, round(100 * t / total)) for c, t in usage]


def to_midi(segs, bpm, path, title="Chords"):
    """Block chords (root position, around middle C, with the root an octave lower) on the chord timeline."""
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(initial_tempo=float(bpm))
    inst = pretty_midi.Instrument(program=0, name=title)
    for s in segs:
        if s["chord"] == "N": continue
        root = 48 + s["root"]
        notes = [root - 12] + [root + i for i in QUALITIES[s["quality"]][0]]
        for p in notes:
            inst.notes.append(pretty_midi.Note(velocity=90, pitch=int(p), start=s["start"], end=s["end"] - 0.01))
    pm.instruments.append(inst)
    pm.write(path)
    return path


def chord_source(path, remove_vocals=False, progress=lambda f, d="": None):
    """Audio to read chords from: an instrumental (no vocals) from earlier stems if there is one, or a fresh split if
    asked for; otherwise None (the caller uses the harmonic part of the full mix). -> (path or None, description)."""
    import os
    from . import separate as sep
    for m in ("htdemucs_ft", "htdemucs", "htdemucs_6s"):
        f = os.path.join(sep.cache_dir(path, m), "instrumental.wav")
        if os.path.exists(f): return f, "the instrumental from your earlier split (vocals removed)"
    if remove_vocals:
        files = sep.separate(path, "htdemucs", progress)
        return files["instrumental"], "an instrumental made for this (vocals removed)"
    return None, "the full mix (vocals included; tick “Remove vocals first” for cleaner chords)"


def from_track(path, details, remove_vocals=False, progress=lambda f, d="": None):
    """Chords for a track already analysed (details from analysis.analyze). -> (segments, source description)."""
    from .common import load_mono
    src, desc = chord_source(path, remove_vocals, lambda f, d="": progress(0.1 + 0.7 * f, d))
    if src:
        progress(0.85, "Reading the chords")
        y = librosa.effects.hpss(load_mono(src, ASR))[0]
    else:
        progress(0.85, "Reading the chords")
        y = details["harm"]
    g = details["grid"]
    segs = detect(y, g["bpm"], g["t0"], g["first_downbeat"], details["key_pc"], details["key_mode"])
    return segs, desc
