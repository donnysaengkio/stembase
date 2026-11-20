"""Which processor runs the stem-separation models.

- CUDA: NVIDIA graphics cards (when the engine is built with a CUDA build of PyTorch).
- DirectML: any DirectX 12 graphics card on Windows (AMD, Intel or NVIDIA), through Microsoft's torch-directml.
- Otherwise the CPU.

Preferences chooses Automatic (a graphics card when there is one), GPU or CPU. DirectML can't do the complex-number
spectrogram steps inside HTDemucs, so patch_demucs() runs just those on the CPU, as Demucs itself does for Apple and
Intel GPUs; everything else stays on the graphics card.
"""
import torch
from .meta import setting, save_setting

MODES = ["Automatic", "GPU", "CPU"]
_found = []   # [(kind, device, name)] or [None], filled on first use


def gpu():
    """(kind, torch device, name) of the graphics card the engine can use, or None."""
    if not _found:
        g = None
        try:
            if torch.cuda.is_available():
                g = ("cuda", torch.device("cuda"), torch.cuda.get_device_name(0))
        except Exception:
            pass
        if g is None:
            try:
                import torch_directml
                if torch_directml.device_count() > 0:
                    g = ("directml", torch_directml.device(0), torch_directml.device_name(0).replace("\x00", "").strip())
            except Exception:
                pass
        _found.append(g)
    return _found[0]


def mode():
    m = setting("processing", "Automatic")
    return m if m in MODES else "Automatic"


def set_mode(m):
    if m not in MODES: raise ValueError(f"Processing must be one of {', '.join(MODES)}.")
    save_setting("processing", m)


def device():
    """The torch device separation runs on now: the graphics card unless Preferences says CPU (or there is none)."""
    g = gpu()
    return g[1] if g and mode() != "CPU" else torch.device("cpu")


def kind():
    """'cuda', 'directml' or 'cpu' for the current choice."""
    g = gpu()
    return g[0] if g and mode() != "CPU" else "cpu"


def label():
    """How the app names the processor in use, e.g. 'GPU (AMD Radeon RX 6950 XT)' or 'CPU'."""
    g = gpu()
    return g[2] if g and mode() != "CPU" else "CPU"


def patch_demucs():
    """Let HTDemucs run on DirectML: the STFT, the complex mask and the inverse STFT go to the CPU and back."""
    from demucs import htdemucs as H
    if getattr(H, "_stembase_patched", False): return
    spectro, mask, ispec = H.spectro, H.HTDemucs._mask, H.HTDemucs._ispec

    def on_dml(t):
        return t.device.type == "privateuseone"

    def spectro_cpu(x, *a, **k):
        return spectro(x.cpu() if on_dml(x) else x, *a, **k)

    def mask_cpu(self, z, m):
        if on_dml(m):
            self._stembase_device = m.device   # where the result has to go back to
            m = m.cpu()
        return mask(self, z, m)

    def ispec_back(self, z, length=None, scale=0):
        x = ispec(self, z, length, scale)
        d = getattr(self, "_stembase_device", None)
        if d is not None:
            self._stembase_device = None
            x = x.to(d)
        return x

    H.spectro, H.HTDemucs._mask, H.HTDemucs._ispec = spectro_cpu, mask_cpu, ispec_back
    H._stembase_patched = True
