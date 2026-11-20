# ADR-0004: Public GitHub repository, releases built by GitHub Actions, previews as pre-releases

- **Status:** Accepted
- **Date:** 2026-11-19

## Context

Stembase needs installers for Windows, Apple silicon and Intel Macs, and Linux, and each system has to build its own
engine. The app's Check For Updates downloads a `latest.json` and signed update files from GitHub releases.

## Decision

- The code is in the public repository [donnysaengkio/stembase](https://github.com/donnysaengkio/stembase).
- The **Build and release** workflow builds all four systems on GitHub's machines and publishes one release with
  every installer and `latest.json`. It is started by hand from the Actions tab.
- Builds marked **preview** are published as GitHub *pre-releases*. A preview can be replaced by deleting its release
  and tag and building again under the same version.
- Updates are signed with the private key `~/.tauri/stembase.key`, stored in the repository's secret
  `TAURI_SIGNING_PRIVATE_KEY`; its public half is in `tauri.conf.json`. The key is never put in the repository.
- The Demucs models are kept in a separate release tagged `models` (marked as a pre-release so it never becomes
  "latest"), which the workflow downloads.

## Options considered

- **Public repository (chosen):** free, unlimited Actions minutes, including macOS; installed apps can download
  updates without signing in.
- **Private repository:** keeps the code private, but updates can't be downloaded from it, and macOS build minutes
  count ten times against the free allowance.

## Consequences

- Check For Updates only sees full releases, never pre-releases. Until a full release exists, it reports that you
  have the latest version.
- Replacing a preview under the same version means people who already installed it aren't told about the new build.
- Losing the signing key means installed copies can't be updated; it must be backed up.
- Only release stems, mashups or edits of music you have the rights to.
