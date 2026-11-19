"""Shared audio I/O and paths."""
import os, re
import numpy as np
import librosa
import soundfile as sf
from .meta import APP_NAME, APP_VERSION, APP_DIR, output_root, MODELS_DIR  # noqa: F401  (re-exported)
SR = 44100
SUPPORTED = (".wav", ".mp3", ".flac", ".ogg", ".opus", ".aif", ".aiff")


def track_name(path):
    """File name without extension, YouTube ids like ' [abc123XYZ_-]' and characters Windows dislikes."""
    base = os.path.splitext(os.path.basename(path))[0]
    base = re.sub(r"\s*\[[A-Za-z0-9_-]{11}\]$", "", base)
    return re.sub(r'[<>:"/\\|?*]', "_", base).strip() or "Track"


def check_input(path):
    if not path:
        raise ValueError("Choose an audio file first.")
    if not os.path.exists(path):
        raise ValueError(f"File not found: {path}")
    if os.path.splitext(path)[1].lower() not in SUPPORTED:
        raise ValueError(f"Unsupported file type. Use one of: {', '.join(SUPPORTED)}")


def load_stereo(path, sr=SR):
    """-> float32 array (samples, 2)."""
    y, _ = librosa.load(path, sr=sr, mono=False)
    if y.ndim == 1:
        y = np.stack([y, y])
    return np.ascontiguousarray(y[:2].T, dtype=np.float32)


def load_mono(path, sr=22050):
    y, _ = librosa.load(path, sr=sr, mono=True)
    return y.astype(np.float32)


# label -> (extension, soundfile subtype or MP3 kbps, approx MB per stereo minute)
FORMATS = {
    "WAV 32-bit float (largest, never clips) · ~21 MB/min": ("wav", "FLOAT"),
    "WAV 24-bit (studio) · ~16 MB/min": ("wav", "PCM_24"),
    "WAV 16-bit (CD quality) · ~11 MB/min": ("wav", "PCM_16"),
    "FLAC 24-bit (lossless) · ~8-11 MB/min": ("flac", "PCM_24"),
    "FLAC 16-bit (lossless, CD quality) · ~5-7 MB/min": ("flac", "PCM_16"),
    "MP3 320 kbps (high) · ~2.4 MB/min": ("mp3", 320),
    "MP3 192 kbps (medium) · ~1.4 MB/min": ("mp3", 192),
    "MP3 128 kbps (smallest) · ~1 MB/min": ("mp3", 128),
}
DEFAULT_FORMAT = "WAV 24-bit (studio) · ~16 MB/min"


def is_float_format(fmt):
    return FORMATS.get(fmt, ("wav", "PCM_24"))[1] == "FLOAT"


def save_audio(path_no_ext, x, fmt=DEFAULT_FORMAT, sr=SR):
    """Write x (samples, channels) in the chosen format; returns the file path. Integer/MP3 formats are clipped to +-1."""
    ext, q = FORMATS.get(fmt, ("wav", "PCM_24"))
    path = f"{path_no_ext}.{ext}"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    x = np.asarray(x, np.float32)
    if q != "FLOAT": x = np.clip(x, -1, 1)
    if ext == "mp3":
        from pedalboard.io import AudioFile
        with AudioFile(path, "w", sr, x.shape[1] if x.ndim == 2 else 1, quality=q) as f:
            f.write(np.ascontiguousarray(x.T if x.ndim == 2 else x[None]))
    else:
        sf.write(path, x, sr, subtype=q, format=ext.upper())
    return path


def headroom_gain(arrays, fmt):
    """One shared gain so a set of stems fits under -0.3 dBFS in integer/MP3 formats (they still sum to the mix)."""
    if is_float_format(fmt): return 1.0
    peak = max(float(np.abs(a).max()) for a in arrays)
    return min(1.0, 10 ** (-0.3 / 20) / (peak + 1e-12))


def save_float(path, x, sr=SR):
    """32-bit float WAV: never clips, opens in every DAW."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sf.write(path, x, sr, subtype="FLOAT")
    return path


def save_master(path, x, sr=SR):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sf.write(path, np.clip(x, -1, 1), sr, subtype="PCM_24")
    return path


def rms(x):
    return float(np.sqrt(np.mean(np.square(x))) + 1e-12)


def fmt_time(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"
