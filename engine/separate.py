"""Stem separation with Demucs. Full-quality results are cached per track and model, then exported in any format."""
import os
import numpy as np
import soundfile as sf
import torch
from .common import output_root, MODELS_DIR, track_name, load_stereo, save_float, save_audio, headroom_gain, DEFAULT_FORMAT

MODELS = {
    "Balanced: 4 stems (htdemucs)": "htdemucs",
    "Best quality: 4 stems, ~4x slower (htdemucs_ft)": "htdemucs_ft",
    "6 stems: adds guitar and piano (htdemucs_6s)": "htdemucs_6s",
}
LABELS = {"vocals": "Vocals", "drums": "Drums", "bass": "Bass", "other": "Other instruments", "guitar": "Guitar", "piano": "Piano",
          "instrumental": "Instrumental (no vocals)"}
_cache = {}


def device():
    return "cuda" if torch.cuda.is_available() else "cpu"


def _model(name):
    if name not in _cache:
        folder = os.path.join(MODELS_DIR, name)
        if os.path.exists(os.path.join(folder, f"{name}.yaml")):   # shipped with the app: no download needed
            import yaml
            from demucs.apply import BagOfModels
            from demucs.hf import load_safetensors_model
            with open(os.path.join(folder, f"{name}.yaml")) as f:
                bag = yaml.safe_load(f)
            m = BagOfModels([load_safetensors_model(os.path.join(folder, f"{sig}.safetensors")) for sig in bag["models"]],
                            bag.get("weights"), bag.get("segment"))
        else:
            from demucs.pretrained import get_model
            m = get_model(name)
        m.eval(); _cache[name] = m
    return _cache[name]


def cache_dir(path, model):
    return os.path.join(output_root(), track_name(path), ".cache", model)


def stem_dir(path, model):
    return os.path.join(output_root(), track_name(path), f"Stems ({model})")


def separate(path, model="htdemucs", progress=lambda f, d="": None):
    """Full-quality (32-bit float WAV) stems in the cache. -> dict source -> path. Used by the mashup engine."""
    from demucs.apply import apply_model
    cdir = cache_dir(path, model)
    m = _model(model)
    files = {s: os.path.join(cdir, f"{s}.wav") for s in list(m.sources) + ["instrumental"]}
    if all(os.path.exists(f) for f in files.values()):
        progress(0.9, "Using stems from an earlier run")
        return files
    progress(0.05, "Loading audio")
    x = load_stereo(path, m.samplerate)
    wav = torch.tensor(x.T)
    ref = wav.mean(0); mean, std = ref.mean(), ref.std() + 1e-8
    label = f"Separating on {device().upper()}"
    progress(0.1, label)
    # One overall figure across every model in the bag (Best quality runs 4 models one after another), 10% → 90%.
    n, best = wav.shape[-1], [0.0]

    def tick(d):
        if d.get("state") != "end": return
        f = (d["model_idx_in_bag"] + min(1.0, d["segment_offset"] / n)) / max(1, d["models"])
        if f > best[0]:
            best[0] = f
            progress(0.1 + 0.8 * f, label)

    with torch.no_grad():
        stems = apply_model(m, ((wav - mean) / std)[None], device=device(), shifts=1, split=True,
                            overlap=0.25, callback=tick)[0]
    stems = (stems * std + mean).cpu().numpy()
    inst = np.zeros_like(stems[0])
    for s, a in zip(m.sources, stems):
        save_float(files[s], a.T)
        if s != "vocals": inst += a
    save_float(files["instrumental"], inst.T)
    return files


def export(path, model="htdemucs", fmt=DEFAULT_FORMAT, progress=lambda f, d="": None):
    """Separate (or reuse the cache) and write named stems in the chosen format. -> dict source -> exported path."""
    files = separate(path, model, progress)
    progress(0.95, "Saving stems")
    data = {s: sf.read(p, dtype="float32")[0] for s, p in files.items()}
    g = headroom_gain(list(data.values()), fmt)
    out, name = stem_dir(path, model), track_name(path)
    return {s: save_audio(os.path.join(out, f"{name} - {LABELS[s]}"), x * g, fmt) for s, x in data.items()}
