"""Convert audio between formats and shrink files: format, bitrate, sample rate, mono, or "fit into N MB"."""
import os
import numpy as np
import librosa
import soundfile as sf
from .common import output_root, track_name, check_input

# label -> (extension, codec, setting). Settings: soundfile subtype for PCM, kbps or "V<n>" for MP3, kbps for Vorbis/Opus.
FORMATS = {
    "MP3 · 320 kbps": ("mp3", "mp3", 320), "MP3 · 256 kbps": ("mp3", "mp3", 256), "MP3 · 192 kbps": ("mp3", "mp3", 192),
    "MP3 · 160 kbps": ("mp3", "mp3", 160), "MP3 · 128 kbps": ("mp3", "mp3", 128), "MP3 · 96 kbps": ("mp3", "mp3", 96),
    "MP3 · 64 kbps": ("mp3", "mp3", 64),
    "MP3 · VBR V0 (~245 kbps)": ("mp3", "mp3", "V0"), "MP3 · VBR V2 (~190 kbps)": ("mp3", "mp3", "V2"),
    "MP3 · VBR V5 (~130 kbps)": ("mp3", "mp3", "V5"),
    "Opus · 192 kbps": ("opus", "opus", 192), "Opus · 128 kbps": ("opus", "opus", 128), "Opus · 96 kbps": ("opus", "opus", 96),
    "Opus · 64 kbps": ("opus", "opus", 64), "Opus · 32 kbps (speech)": ("opus", "opus", 32),
    "Ogg Vorbis · 320 kbps": ("ogg", "vorbis", 320), "Ogg Vorbis · 192 kbps": ("ogg", "vorbis", 192),
    "Ogg Vorbis · 128 kbps": ("ogg", "vorbis", 128), "Ogg Vorbis · 96 kbps": ("ogg", "vorbis", 96),
    "FLAC · 24-bit (lossless)": ("flac", "pcm", "PCM_24"), "FLAC · 16-bit (lossless)": ("flac", "pcm", "PCM_16"),
    "WAV · 32-bit float": ("wav", "pcm", "FLOAT"), "WAV · 24-bit": ("wav", "pcm", "PCM_24"), "WAV · 16-bit": ("wav", "pcm", "PCM_16"),
    "AIFF · 24-bit": ("aiff", "pcm", "PCM_24"), "AIFF · 16-bit": ("aiff", "pcm", "PCM_16"),
}
SAMPLE_RATES = {"Keep original": None, "48000 Hz": 48000, "44100 Hz (CD)": 44100, "32000 Hz": 32000,
                "22050 Hz": 22050, "16000 Hz (speech)": 16000}
CHANNELS = ["Keep original", "Mono (about half the size for lossless formats)"]
TARGET_CODECS = ["MP3", "Opus (better quality at low bitrates)"]
MP3_CBR = [320, 256, 224, 192, 160, 128, 112, 96, 80, 64, 56, 48, 40, 32]
OPUS_RATES = [8000, 12000, 16000, 24000, 48000]   # Opus only stores these; others are resampled up to the nearest
LOSSY_PEAK = 10 ** (-1 / 20)   # -1 dBFS headroom before MP3 / Opus / Vorbis encoding
LOSSY_INPUTS = (".mp3", ".ogg", ".opus")


def _opus_level(kbps):
    """libsndfile's Opus compression_level runs from ~510 kbps (0.0) down to ~6 kbps (1.0), close to linearly."""
    return float(np.clip((510 - kbps) / 498, 0, 1))


def _write_opus(path, x, sr, kbps):
    """Opus is variable-bitrate and its quality knob is not linear (especially in mono), so encode, measure, correct.
    Ends at or just under the requested bitrate (within ~6%), in 1-5 encodes."""
    dur = len(x) / sr
    tried = []   # (level, measured kbps)
    level = _opus_level(kbps)
    for _ in range(5):
        sf.write(path, x, sr, format="OGG", subtype="OPUS", compression_level=level)
        got = os.path.getsize(path) * 8 / dur / 1000
        tried.append((level, got))
        if 0.9 * kbps <= got <= 1.02 * kbps: return
        lo = [t for t in tried if t[1] > kbps]; hi = [t for t in tried if t[1] < kbps]   # lower level = higher bitrate
        if lo and hi:   # bracketed: interpolate between the closest points on each side
            (l1, b1), (l2, b2) = max(lo, key=lambda t: t[0]), min(hi, key=lambda t: t[0])
            level = l1 + (l2 - l1) * (b1 - kbps) / (b1 - b2)
        else:
            level = float(np.clip(level + (got - kbps) / 498 * (2 if got < kbps else 1.5), 0, 1))
    best = max((t for t in tried if t[1] <= 1.02 * kbps), default=min(tried, key=lambda t: t[1]), key=lambda t: t[1])
    if best != tried[-1]:
        sf.write(path, x, sr, format="OGG", subtype="OPUS", compression_level=best[0])


def _write(path, x, sr, codec, setting):
    """x: (samples, channels) float32."""
    if codec == "pcm":
        y = x if setting == "FLOAT" else np.clip(x, -1, 1)
        kw = {"compression_level": 1.0} if path.endswith(".flac") else {}
        sf.write(path, y, sr, subtype=setting, **kw)
    elif codec == "opus":
        _write_opus(path, np.clip(x, -1, 1), sr, setting)
    else:  # mp3 / vorbis through Pedalboard (LAME / libvorbis)
        from pedalboard.io import AudioFile
        q = setting if codec == "mp3" else f"{setting} kbps"
        with AudioFile(path, "w", sr, x.shape[1], quality=q) as f:
            f.write(np.ascontiguousarray(np.clip(x, -1, 1).T))


def _unique(path):
    base, ext = os.path.splitext(path); i = 2
    while os.path.exists(path):
        path = f"{base} ({i}){ext}"; i += 1
    return path


def size_mb(path):
    return os.path.getsize(path) / 1e6


def plan_target(duration, target_mb, codec="MP3", channels=2):
    """Bitrate (and, for very small targets, mono / lower sample rate) that fits `target_mb`. -> (kbps, mono, sr or None)."""
    budget = target_mb * 8e6 / max(duration, 0.1) / 1000 * 0.97   # kbps, 3% for headers and VBR wobble
    if codec.startswith("Opus"):
        kbps = int(min(256, budget))
        if kbps < 8: raise ValueError(f"{target_mb:g} MB is too small for {duration / 60:.1f} minutes of audio, even as Opus.")
        return kbps, kbps < 24 and channels > 1, None   # below ~24 kbps, mono sounds better than squeezed stereo
    fits = [b for b in MP3_CBR if b <= budget]
    if fits: return fits[0], fits[0] < 64 and channels > 1, (22050 if fits[0] < 64 else None)
    raise ValueError(f"{target_mb:g} MB is too small for {duration / 60:.1f} minutes as MP3 (the lowest MP3 bitrate is 32 kbps, "
                     f"which needs {32 * duration / 8e3 / 0.97:.1f} MB). Choose Opus, or a bigger target.")


def convert(path, fmt_label=None, sample_rate="Keep original", channels="Keep original", target_mb=None,
            target_codec="MP3", out_dir=None, progress=lambda f, d="": None):
    """Convert one file. With target_mb set, the format is chosen to fit that size. -> dict with the result details."""
    check_input(path)
    out_dir = out_dir or os.path.join(output_root(), "Converted")
    os.makedirs(out_dir, exist_ok=True)
    if target_mb and size_mb(path) <= float(target_mb):   # already small enough: re-encoding would only lose quality
        import shutil
        out = _unique(os.path.join(out_dir, f"{track_name(path)}{os.path.splitext(path)[1].lower()}"))
        shutil.copy2(path, out)
        i = sf.info(path)
        return dict(source=path, output=out, format="Unchanged (already under the target)", sample_rate=i.samplerate,
                    channels=i.channels, duration=i.duration, before_mb=size_mb(path), after_mb=size_mb(out), change=0.0,
                    lossy_to_lossless=False)
    progress(0.1, f"Reading {os.path.basename(path)}")
    y, sr = librosa.load(path, sr=None, mono=False)
    x = (y[None] if y.ndim == 1 else y).T.astype(np.float32)   # (samples, channels)
    duration = len(x) / sr
    mono = channels.startswith("Mono")
    new_sr = SAMPLE_RATES.get(sample_rate)
    if target_mb:
        kbps, force_mono, force_sr = plan_target(duration, float(target_mb), target_codec, 1 if mono else x.shape[1])
        mono = mono or force_mono
        new_sr = min(new_sr or sr, force_sr or sr)
        ext, codec, setting = ("opus", "opus", kbps) if target_codec.startswith("Opus") else ("mp3", "mp3", kbps)
        label = f"{'Opus' if codec == 'opus' else 'MP3'} {kbps} kbps" + (" mono" if mono else "")
    else:
        ext, codec, setting = FORMATS[fmt_label]
        label = fmt_label.replace(" · ", " ")
    if mono and x.shape[1] > 1:
        x = x.mean(1, keepdims=True)
    if codec == "opus":   # Opus works at fixed rates only
        new_sr = min((r for r in OPUS_RATES if r >= (new_sr or sr)), default=48000)
    if codec == "mp3" and (new_sr or sr) > 48000:
        new_sr = 48000   # MP3 tops out at 48 kHz
    if new_sr and new_sr != sr:
        progress(0.4, f"Resampling to {new_sr} Hz")
        x = librosa.resample(x.T, orig_sr=sr, target_sr=new_sr, res_type="soxr_hq").T.astype(np.float32)
        sr = new_sr
    peak = float(np.abs(x).max()) if x.size else 0
    if codec != "pcm":   # lossy codecs overshoot on decode: keep peaks under -1 dBFS so the result doesn't clip
        if peak > LOSSY_PEAK: x = x * (LOSSY_PEAK / peak)
    elif setting != "FLOAT" and peak > 1:
        x = x / peak * 0.999   # resampling or mono summing pushed it over full scale
    progress(0.7, f"Encoding {label}")
    out = _unique(os.path.join(out_dir, f"{track_name(path)}.{ext}"))
    _write(out, x, sr, codec, setting)
    before, after = size_mb(path), size_mb(out)
    return dict(source=path, output=out, format=label, sample_rate=sr, channels=x.shape[1], duration=duration,
                before_mb=before, after_mb=after, change=(after / before - 1) * 100 if before else 0,
                lossy_to_lossless=codec == "pcm" and path.lower().endswith(LOSSY_INPUTS))
