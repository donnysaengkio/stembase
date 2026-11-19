"""Change key and/or tempo of a track (Rubber Band via Pedalboard)."""
import os
import numpy as np
from pedalboard import time_stretch
from .common import output_root, track_name, load_stereo, load_mono, save_audio, DEFAULT_FORMAT, SR
from .analysis import grid_fit, ASR
import librosa


def change(path, semitones=0.0, target_bpm=0.0, fmt=DEFAULT_FORMAT, progress=lambda f, d="": None):
    progress(0.05, "Loading audio")
    x = load_stereo(path)
    stretch, src_bpm = 1.0, None
    if target_bpm and target_bpm > 0:
        progress(0.15, "Detecting the current tempo")
        _, perc = librosa.effects.hpss(load_mono(path, ASR))
        src_bpm, _ = grid_fit(perc)
        stretch = target_bpm / src_bpm
    if abs(stretch - 1) < 1e-6 and abs(semitones) < 1e-6:
        raise ValueError("Nothing to change: set a key shift or a target BPM.")
    progress(0.4, "Stretching / shifting (high quality)")
    y = time_stretch(np.ascontiguousarray(x.T), SR, stretch_factor=float(stretch),
                     pitch_shift_in_semitones=float(semitones), preserve_formants=True).T
    peak = np.abs(y).max()
    if peak > 0.98: y *= 0.98 / peak
    tag = []
    if semitones: tag.append(f"{semitones:+g} st")
    if target_bpm: tag.append(f"{target_bpm:g} BPM")
    out = save_audio(os.path.join(output_root(), track_name(path), f"{track_name(path)} ({', '.join(tag)})"), y, fmt)
    return out, src_bpm, stretch
