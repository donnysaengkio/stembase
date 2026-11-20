# ADR-0000: Record important decisions as ADRs

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

Stembase moved quickly from Stem Studio to a new app, a new name, GPU support and public releases. The reasons for
those choices lived only in conversations, so they would be hard to find later or to explain to anyone helping out.

## Decision

Important decisions are written down as short architecture decision records in `docs/adr/`, numbered in order, one
per file, using [`template.md`](template.md). "Important" means a decision that is hard to undo, costs money, changes
what users see or install, or that someone might reasonably question later.

## Consequences

- Each record says what was decided, why, and what it costs, so the reasoning survives.
- Old records are not rewritten: a changed decision gets a new record that replaces the old one.
- Small, easily reversed choices (a colour, a wording tweak) don't need a record.
