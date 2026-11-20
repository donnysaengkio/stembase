# ADR-0001: A Tauri desktop app around the Python audio engine

- **Status:** Accepted
- **Date:** 2026-11-19

## Context

Stem Studio, the earlier version, was a Python app with a Gradio interface in a desktop window, installed with an Inno
Setup installer on Windows only. Its audio engine (Demucs separation, analysis, chords, MIDI, mashups, key and tempo
changes, conversion) worked well, but the interface was hard to make look and feel like a native app, and it could
not be built for macOS and Linux.

## Decision

Stembase is a Tauri v2 app (Rust shell with a React and TypeScript interface) that starts the existing Python engine
as a separate local program:

- The engine (`server.py` and `engine/`) runs as a small local web server on a random port, protected by a token
  the app passes to it. It is built with PyInstaller into one folder and bundled with the app.
- The Demucs models are bundled too, so nothing is downloaded and everything runs offline.
- The old app stays in `legacy/` for reference.

## Options considered

- **Tauri with the Python engine (chosen):** reuses the proven engine unchanged; small native shell; builds for
  Windows, macOS and Linux; signed in-app updates.
- **Keep the Gradio app:** least work, but Windows-only packaging and a web-form look.
- **Rewrite the engine in another language:** Demucs, librosa and Basic Pitch are Python; a rewrite would be large
  and risky.
- **Electron:** would also work, but is larger and slower to start than Tauri.

## Consequences

- Installers are large (about 600–900 MB), mostly PyTorch and the models.
- Each system has to build its own engine, since PyInstaller cannot cross-compile; GitHub Actions does this (see
  [ADR-0004](0004-public-repo-and-releases.md)).
- The app waits for the engine to start listening before it connects.
