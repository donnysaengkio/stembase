# ADR-0006: Labels in Title Case, without parentheses

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

The interface mixed sentence case and Title Case, and many labels carried explanations in parentheses, such as
"Remove vocals first (cleaner chords)" or "WAV 24-bit (studio)". That made labels long and the screens busy.

## Decision

- **Title Case** for everything that works as a label: tabs, buttons, field names, choices, headings, window titles,
  tooltips and menu items. Small words (a, an, the, and, or, of, to, in, for…) stay lowercase in the middle of a
  label, as in "Put Them Over the Music Of".
- **Full sentences** (notes under fields, messages after a job) stay in normal sentence case.
- **No parentheses** anywhere in the app's text. Useful information moves into the sentence or the note under the
  field. For example, "Auto matches the instrumental's key" became a note under *Vocal Key Shift in Semitones*.
- Shorter names: stems **Other** and **Instrumental**; MIDI sources **A Track Stem** and **A Full Song**; Mix
  arrangements **Fit to the Music** and **One Continuous Take**; the checkbox **Remove Vocals**; the player
  **Preview**.

## Consequences

- Saved files and folders keep their existing names where Stembase recognizes earlier results by them, such as
  `Stems (htdemucs)`, `(Mashup)` and Shift's `Song (+2 st, 128 BPM)`. Renaming those would hide earlier results.
- New stem files are named with the short names, e.g. `Song - Other.wav`; files from older splits keep their names.
- Option names are also the values the app sends to the engine, so changing one means changing both sides.
