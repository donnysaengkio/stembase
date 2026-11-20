# Architecture decision records

Short notes on the important decisions behind Stembase: what was decided, why, and what follows from it. They are
written when a decision is made and kept afterwards, even when a later decision replaces them, so the reasoning
stays findable.

## How to add one

1. Copy [`template.md`](template.md) to the next number, e.g. `0007-short-title.md`.
2. Fill it in: keep it to a page. Say what was decided in plain words and what it costs.
3. Add it to the list below.
4. When a decision changes, don't rewrite the old record: write a new one, set the old one's status to
   *Replaced by [ADR-00NN](…)*, and link back from the new one.

Status is one of **Proposed**, **Accepted**, **Replaced by ADR-00NN** or **Dropped**.

## Decisions

| ADR | Decision | Status | Date |
|---|---|---|---|
| [0000](0000-record-decisions.md) | Record important decisions as ADRs | Accepted | 2026-11-20 |
| [0001](0001-tauri-app-python-engine.md) | A Tauri desktop app around the Python audio engine | Accepted | 2026-11-19 |
| [0002](0002-gpu-separation-directml.md) | Stem separation on the graphics card, with a CPU fallback | Accepted | 2026-11-19 |
| [0003](0003-version-starts-at-1-0.md) | Version numbers start at 1.0.0 | Accepted | 2026-11-19 |
| [0004](0004-public-repo-and-releases.md) | Public GitHub repository, releases built by GitHub Actions, previews as pre-releases | Accepted | 2026-11-19 |
| [0005](0005-unsigned-installers-for-now.md) | Installers stay unsigned for now | Accepted | 2026-11-20 |
| [0006](0006-label-style.md) | Labels in Title Case, without parentheses | Accepted | 2026-11-20 |
