# ADR-0003: Version numbers start at 1.0.0

- **Status:** Accepted
- **Date:** 2026-11-19

## Context

Stembase was first numbered 2.0.0, carrying on from Stem Studio's installer, which had reached 1.3.0. Neither Stem
Studio nor Stembase 2.0 had ever been released publicly, so the 2.0 suggested a history users never saw.

## Decision

Stembase starts at **1.0.0**. The first public build is `1.0.0-preview.1`; the 2.0.0 preview release and its tag were
deleted before anyone relied on them.

## Consequences

- In-app updates only need each release to have a higher version than the last, so starting at 1.0 costs nothing.
- `1.0.0-preview.1` sorts before `1.0.0`, so the first full release will be offered to preview users.
- The version is set in `ui/src-tauri/tauri.conf.json`, `ui/src-tauri/Cargo.toml`, `ui/package.json` and
  `engine/meta.py`; they should be raised together.
