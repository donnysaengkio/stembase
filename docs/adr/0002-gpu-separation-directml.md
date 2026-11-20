# ADR-0002: Stem separation on the graphics card, with a CPU fallback

- **Status:** Accepted
- **Date:** 2026-11-19

## Context

Stem separation is the slowest job in Stembase. The development PC has an AMD Radeon RX 6950 XT, which CUDA (NVIDIA
only) cannot use. Microsoft's DirectML runs PyTorch on any DirectX 12 graphics card on Windows, but its
`torch-directml` package requires PyTorch 2.4 and cannot do the complex-number steps (STFT) inside HTDemucs.

## Decision

- Separation uses the graphics card when there is one: CUDA on NVIDIA, otherwise DirectML on Windows.
- The STFT steps of HTDemucs run on the CPU, and the rest of the model on the graphics card (`engine/gpu.py`).
- If the graphics card fails during a job, that job is redone on the CPU automatically.
- Preferences → Processing offers **Automatic**, **GPU** or **CPU**.
- The engine is built from a separate `.venv` with PyTorch 2.4.1 and `torch-directml`, so the main Python
  installation is left alone.
- Only separation uses the graphics card; analysis, MIDI, Shift and Encode stay on the CPU.

## Consequences

- Measured on a 60-second clip: 9 s on the GPU after warm-up (13 s for the first job) against 15 s on the CPU.
- PyTorch is held at 2.4 on Windows until `torch-directml` supports a newer version.
- macOS and Linux builds run separation on the CPU (or CUDA on Linux if built with a CUDA version of PyTorch).
