# ADR-0005: Installers stay unsigned for now

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

The Windows installer is not code-signed, so Windows SmartScreen shows *Windows protected your PC* when it is run.
The Mac apps are not signed or notarized by Apple, so macOS blocks a normal first open. Removing these warnings needs
a code-signing identity in the developer's own name:

| Option | Cost |
|---|---|
| Azure Trusted Signing (Windows) | about $10 a month, with an identity check |
| Standard (OV) code-signing certificate (Windows) | roughly $200–400 a year |
| Apple Developer Program (macOS) | $99 a year |

## Decision

Keep the installers unsigned for now. The README tells people how to get past the warnings: on Windows, **More info**
then **Run anyway**; on a Mac, right-click → **Open** the first time.

## Consequences

- No cost while Stembase is in preview.
- Every new user sees a warning, which some will find off-putting.
- Revisit before a wider release. Azure Trusted Signing fits the GitHub Actions build best, signing each Windows
  installer automatically. This is separate from the update-signing key (see
  [ADR-0004](0004-public-repo-and-releases.md)), which Windows and macOS don't look at.
