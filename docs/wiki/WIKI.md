# WIKI.md — schema

## Purpose

A durable record of agent runs on WANDERERS (NASA Space Apps 2026, Planet X and SPHEREx), so future agents know what happened, why, and what is left.

## Directory structure

```
docs/wiki/
  WIKI.md          # this schema
  wiki/
    index.md       # content catalog
    log.md         # append-only activity log
    synthesis/     # run records and overviews
```

## Rules

- Filenames: lowercase, hyphens, `.md`. Wikilinks: `[[filename-without-extension]]`.
- Each new page updates `index.md` and appends one entry to `log.md`.
- Write in ASD-STE100 Simplified Technical English.
- Commit wiki pages on a branch in `.worktrees/`, never directly on `main`.
