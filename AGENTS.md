# Codex Agent Instructions

This repo contains RedsailCut, a PyQt6 macOS app that converts SVG geometry to
Redsail-compatible HPGL and streams it over USB serial.

## Working Rules

- Keep all user-facing app text in English.
- Preserve Redsail RS720C compatibility unless hardware testing proves a
  change is safe.
- Do not remove explicit `PU;` lift commands or pen-up settle pacing without a
  hardware-tested replacement.
- Do not reintroduce the old 409.6 mm / 16383-unit hard block. The user's
  cutter can work at approximately 600 mm width.
- Prefer dry-run `.plt` inspection before changing serial or HPGL behavior.
- Run `pytest` before committing.
- Build with Briefcase only when the user needs a runnable app or DMG.

## Important Commands

```sh
pytest
briefcase update macOS
briefcase build macOS
briefcase package macOS --adhoc-sign
```

## Hardware Notes

- Verified default serial mode is no flow control.
- Redsail RS720C needs DTR high and RTS high after open, then a 300 ms settle.
- Plain `FS{n};` works. HP-GL/2 `!FS{n};` must not be emitted.
- One `PD` coordinate pair per line is intentional for firmware compatibility.
- `PU;` before coordinate travel plus a short settle delay helps avoid long
  stray lines when the knife lift lags.
