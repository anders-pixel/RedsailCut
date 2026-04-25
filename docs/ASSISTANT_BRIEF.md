# Assistant Brief

## Project Snapshot

RedsailCut is a small macOS GUI and CLI for SVG-to-HPGL cutting on Redsail
vinyl plotters. The active hardware target is a Redsail RS720C connected over
USB serial.

## Current Priorities

- Keep A2 / 580-600 mm wide cutting possible.
- Prevent long stray cut lines by validating generated HPGL before sending.
- Keep movement smooth enough for traced artwork and curved ornament details.
- Keep the GUI simple and English-only.

## Key Implementation Areas

- `src/redsailcut/svg_parser.py`: SVG flattening and import cleanup entrypoint.
- `src/redsailcut/cut_optimizer.py`: traced SVG cleanup, simplification, and
  optional smoothing.
- `src/redsailcut/hpgl.py`: HPGL generation, coordinate normalization, and
  safety preflight.
- `src/redsailcut/serial_io.py`: serial open configuration and motion-aware
  pacing.
- `src/redsailcut/app.py`: PyQt6 GUI, cut pipeline, warnings, and dry-run flow.

## Cut Pipeline

1. Parse SVG into polylines.
2. Apply import cleanup preset.
3. Apply rotation.
4. Sort paths either inside-first or nearest-neighbor.
5. Add sharp-corner pivots if enabled.
6. Apply blade compensation and overcut.
7. Generate HPGL.
8. Run HPGL safety preflight.
9. Write dry-run `.plt` or stream to the cutter.

## Known Risk Pattern

If a dry-run `.plt` contains long `PU` travel but no long diagonal `PD` cut
segments, the generated HPGL is not commanding a cut line. The physical cutter
may be lagging on knife lift. Keep explicit `PU;` and settle pacing in place.
