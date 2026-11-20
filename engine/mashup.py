"""Vocals from one track over the instrumental of another: key + tempo match, phrase-aligned arrangement."""
import os
import numpy as np
import soundfile as sf
import librosa
from pedalboard import Pedalboard, HighpassFilter, Compressor, Reverb, Limiter, NoiseGate, Gain, time_stretch
from .common import output_root, track_name, rms, fmt_time, save_audio, headroom_gain, DEFAULT_FORMAT, SR
from .analysis import ASR, grid_from, detect_key, minor_tonic, key_label, camelot, per_segment_rms
from .separate import separate


def _mono(path):
    y, sr = sf.read(path, dtype="float32")
    return librosa.resample(y.mean(1) if y.ndim == 2 else y, orig_sr=sr, target_sr=ASR)


def _stems(files):
    """Merge extra stems (guitar/piano from the 6-stem model) into 'other'."""
    music = [k for k in files if k not in ("vocals", "drums", "bass", "instrumental")]
    return files["vocals"], files["drums"], files["bass"], music


def _bars(x, start, bpm, dur):
    bar = 4 * 60 / bpm
    return per_segment_rms(x, np.arange(start, dur + bar, bar))


def plan(vocal_files, instr_files, key_shift="Auto", arrangement="sections", keep_intro_bars=16, keep_outro_bars=16):
    vv, vd, vb, vm = _stems(vocal_files); iv, idr, ib, im = _stems(instr_files)
    V = {k: _mono(p) for k, p in (("vocals", vv), ("drums", vd), ("bass", vb))}
    V["music"] = sum(_mono(instr) for instr in [vocal_files[m] for m in vm])
    I = {k: _mono(p) for k, p in (("drums", idr), ("bass", ib))}
    I["music"] = sum(_mono(instr_files[m]) for m in im)
    vfull = V["vocals"] + V["drums"] + V["bass"] + V["music"]
    ifull = I["drums"] + I["bass"] + I["music"]
    G_v = grid_from(V["drums"], V["bass"] + V["music"], vfull)
    G_i = grid_from(I["drums"], I["bass"] + I["music"], ifull)

    kv, ki = detect_key(V["bass"] + V["music"] + 0.5 * V["vocals"]), detect_key(I["bass"] + I["music"])
    if key_shift == "Auto":
        tv, ti = minor_tonic(kv[0][1], kv[0][2]), minor_tonic(ki[0][1], ki[0][2])
        shift = ((ti - tv + 6) % 12) - 6
    else:
        shift = int(key_shift)
    stretch = G_i["bpm"] / G_v["bpm"]

    vbar, ibar = 4 * 60 / G_v["bpm"], 4 * 60 / G_i["bpm"]
    pre = int(np.ceil(G_v["phrase_start"] / vbar)); v0 = G_v["phrase_start"] - pre * vbar
    i_pre = int(np.floor(G_i["phrase_start"] / ibar)); i0 = G_i["phrase_start"] - i_pre * ibar
    voc = _bars(V["vocals"], v0, G_v["bpm"], G_v["duration"])
    v_act = np.clip(voc / (np.percentile(voc, 90) + 1e-9), 0, 1); v_act[v_act < 0.15] = 0
    mus = _bars(I["bass"] + I["music"], i0, G_i["bpm"], G_i["duration"])
    m_act = np.clip(mus / (np.percentile(mus, 90) + 1e-9), 0, 1)
    music_on = m_act > 0.3
    if not music_on.any(): music_on[:] = True
    last_music = int(np.where(music_on)[0].max())
    def phase_ok(j0, k0): return ((k0 - i_pre) - (j0 - pre)) % 8 == 0

    segs = []
    if arrangement == "continuous":
        best = None
        for off in range(-((len(v_act) // 8) + 1) * 8, len(m_act), 8):
            sc = sum(a * (m_act[j - pre + i_pre + off] if 0 <= j - pre + i_pre + off < len(m_act) else -1.5)
                     for j, a in enumerate(v_act) if a)
            if best is None or sc > best[0]: best = (sc, off)
        k_first = -pre + i_pre + best[1]
        j0 = max(0, -k_first); j1 = min(len(v_act), len(m_act) - k_first)
        segs.append((j0, j1, k_first + j0))
    else:
        act = v_act > 0; runs, j = [], 0
        while j < len(act):
            if act[j]:
                k = j
                while k + 1 < len(act) and (act[k + 1] or (k + 3 < len(act) and act[k + 2: k + 4].any())): k += 1
                runs.append((j, k + 1)); j = k + 1
            else: j += 1
        blocks = [r for r in runs if v_act[r[0]: r[1]].sum() >= 3] or runs
        def fits(j0, j1, k0):
            k1 = k0 + (j1 - j0)
            if k0 < 0 or k1 > last_music + 1: return False
            a = v_act[j0:j1] > 0
            return (music_on[k0:k1][a].mean() if a.any() else 1) >= 0.75
        cursor, stop = keep_intro_bars - i_pre, max(last_music - keep_outro_bars, keep_intro_bars + 8)
        qi = misses = 0
        while blocks and cursor < stop and misses < len(blocks):
            j0, j1 = blocks[qi % len(blocks)]; j1 = min(j1 + 1, len(v_act)); qi += 1
            k0 = cursor
            while k0 < stop and not (phase_ok(j0, k0) and fits(j0, j1, k0) and k0 + (j1 - j0) <= stop + 1): k0 += 1
            if k0 >= stop: misses += 1; continue
            misses = 0; segs.append((j0, j1, k0)); cursor = k0 + (j1 - j0) + 8
    segments = [dict(src_start=v0 + a * vbar, src_end=v0 + b * vbar, dst=i0 + k * ibar, src_bars=[int(a), int(b)], dst_bar=int(k))
                for a, b, k in segs]
    return dict(vocal_grid=G_v, instr_grid=G_i, shift=int(shift), stretch=float(stretch),
                vocal_key=(kv[0][1], kv[0][2], kv[0][0]), instr_key=(ki[0][1], ki[0][2], ki[0][0]),
                segments=segments)


def _read(p):
    y, sr = sf.read(p, dtype="float32")
    if y.ndim == 1: y = np.stack([y, y], 1)
    return y


def master(x, target_rms_db=-14.0):
    x = (x * (10 ** (target_rms_db / 20) / rms(x))).astype(np.float32)
    y = Pedalboard([Compressor(threshold_db=-16, ratio=1.8, attack_ms=25, release_ms=200), Gain(2.5),
                    Limiter(threshold_db=-2.0, release_ms=80)])(np.ascontiguousarray(x.T), SR).T
    return y * (10 ** (-1 / 20) / (np.abs(y).max() + 1e-9))


def render(P, vocal_files, instr_files, out_dir, title, vocal_gain_db=0.0, fmt=DEFAULT_FORMAT,
           progress=lambda f, d="": None):
    vv, vd, vb, vm = _stems(vocal_files); iv, idr, ib, im = _stems(instr_files)
    drums, bass = _read(idr), _read(ib)
    other = sum(_read(instr_files[m]) for m in im)
    N = len(drums)
    voc = np.zeros((N, 2), np.float32); v = _read(vv)
    for i, seg in enumerate(P["segments"]):
        progress(0.1 + 0.4 * i / max(len(P["segments"]), 1), f"Stretching vocal section {i + 1}/{len(P['segments'])}")
        a, b = max(int(seg["src_start"] * SR), 0), int(seg["src_end"] * SR)
        lead = max(-int(seg["src_start"] * SR), 0)
        x = np.vstack([np.zeros((lead, 2), np.float32), v[a:b]])
        if len(x) < SR // 10: continue
        x = time_stretch(np.ascontiguousarray(x.T), SR, stretch_factor=P["stretch"],
                         pitch_shift_in_semitones=float(P["shift"]), preserve_formants=True).T
        fi, fo = int(0.03 * SR), min(int(0.25 * SR), len(x) // 2)
        x[:fi] *= np.linspace(0, 1, fi)[:, None]; x[-fo:] *= np.linspace(1, 0, fo)[:, None]
        d = max(int(round((seg["dst"] - 0.007) * SR)), 0); m = min(len(x), N - d)   # -7 ms: measured stretch latency
        if m > 0: voc[d: d + m] += x[:m]
    progress(0.55, "Cleaning up the vocals")
    voc = Pedalboard([NoiseGate(threshold_db=-48, ratio=4, release_ms=150), HighpassFilter(140),
                      Compressor(threshold_db=-22, ratio=3, attack_ms=5, release_ms=120),
                      Reverb(room_size=0.35, wet_level=0.12, dry_level=0.9, width=0.8)])(np.ascontiguousarray(voc.T), SR).T[:N]
    inst = drums + bass + other
    act = np.abs(voc).mean(1) > 0.01 * (np.abs(voc).max() + 1e-9)
    if act.any(): voc *= (rms(inst[act]) * 0.85 * 10 ** (vocal_gain_db / 20)) / rms(voc[act])
    outputs, stems = {}, [("Vocals", voc), ("Instrumental", inst),
                          ("Drums", drums), ("Bass", bass), ("Other", other)]
    progress(0.65, "Mixing the mashup")
    outputs["Mashup"] = save_audio(os.path.join(out_dir, f"{title} (Mashup)"), master(inst + voc), fmt)
    progress(0.9, "Saving stems")
    g = headroom_gain([x for _, x in stems], fmt)
    for nm, x in stems:
        save_audio(os.path.join(out_dir, "Stems", nm), x * g, fmt)
    return outputs


def make_mashup(vocal_path, instr_path, key_shift="Auto", arrangement="sections",
                vocal_gain_db=0.0, model="htdemucs", fmt=DEFAULT_FORMAT,
                progress=lambda f, d="": None):
    progress(0.02, "Separating the vocal track")
    vf = separate(vocal_path, model)
    progress(0.25, "Separating the instrumental track")
    inf = separate(instr_path, model)
    progress(0.45, "Matching beat grids, keys and phrases")
    P = plan(vf, inf, key_shift, arrangement)
    title = f"{track_name(vocal_path)} x {track_name(instr_path)}"
    out_dir = os.path.join(output_root(), "Mashups", title)
    outs = render(P, vf, inf, out_dir, title, vocal_gain_db, fmt,
                  lambda f, d="": progress(0.55 + 0.45 * f, d))
    return P, outs, out_dir, title


def report(P, vocal_path, instr_path):
    G_v, G_i = P["vocal_grid"], P["instr_grid"]
    kv, ki = P["vocal_key"], P["instr_key"]
    lines = [f"| | Vocals from | Instrumental from |", "|---|---|---|",
             f"| Track | {track_name(vocal_path)} | {track_name(instr_path)} |",
             f"| Tempo | {G_v['bpm']:.2f} BPM | {G_i['bpm']:.2f} BPM |",
             f"| Key | {key_label(kv[0], kv[1])} · {camelot(kv[0], kv[1])} | {key_label(ki[0], ki[1])} · {camelot(ki[0], ki[1])} |",
             "", f"**Vocals pitch-shifted** {P['shift']:+d} semitones · **tempo changed** {100 * (P['stretch'] - 1):+.2f}%", "",
             "**Where the vocal sections land:**", "", "| Vocal section (original time) | Placed at |", "|---|---|"]
    for s in P["segments"]:
        lines.append(f"| {fmt_time(max(s['src_start'], 0))} – {fmt_time(s['src_end'])} | {fmt_time(s['dst'])} · bar {s['dst_bar'] + 1} |")
    if not P["segments"]:
        lines.append("| No vocal sections found | – |")
    return "\n".join(lines)
