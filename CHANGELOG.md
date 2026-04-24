# Changelog

All notable changes to RedsailCut will be recorded here. The format is based
on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] — 2026-04-24

First public release. Hardware-verified on a Redsail RS720C.

### Added

- **GUI** — PyQt6 main window with drag-and-drop SVG input, live preview
  with bounding box and millimetre label, aspect-ratio-locked scaling,
  speed/force controls, log pane, and a CUT / Stop button that runs the
  job on a background thread.
- **CLI** — `python -m redsailcut file.svg --width 400 --dry-run -o out.plt`
  for headless HPGL generation.
- **SVG parser** — `svgelements`-based loader with `reify=True`, per-segment
  adaptive curve sampling, and a control-polygon length approximation
  (barcelona.svg parses in under a second).
- **HPGL generator** — 40 units/mm, Y-flip from SVG top-left to HPGL
  bottom-left, banker's rounding, pen-up travel between polylines.
- **Blade compensation** — drag-knife offset extension at corners,
  overcut past the closing point of closed shapes, corner-threshold
  filter so sampled curves don't drift. Pen-mode (offset = 0) is the
  first-launch default.
- **Sharp-corner pivots** — splits polylines at corners below a
  configurable opening-angle threshold so the knife can rotate on
  pen-up instead of dragging through an acute turn.
- **Inside-first path ordering** — bounding-box containment heuristic
  sorts inner shapes before their containers so vinyl counters don't
  shift during cutting.
- **Motion-aware serial pacing** — each `PU`/`PD` line in
  `send_hpgl` sleeps for the move's actual physical duration
  (distance ÷ VS) so the cutter's input buffer can't overflow on
  long or slow jobs.
- **Dry run default ON** on first launch — writes a timestamped `.plt`
  to the Desktop instead of sending to hardware, preventing accidental
  first-run cuts.
- **Connection probe** — Settings → Tools → Test cutter connection…
  sends HPGL `OI;` / `OS;` / `OE;` / `OA;` and surfaces whatever the
  cutter replies.
- **Three flow-control modes** — None (default, verified on RS720C),
  RTS/CTS, XON/XOFF. Switchable under Settings → Advanced → Serial
  flow control.
- **Persistence** — port, baud, flow control, speed, force, dry-run
  state, blade-compensation values, and path-ordering preferences all
  round-trip via `QSettings`.
- **Warnings** in the UI when the design exceeds 400 mm wide or the
  estimated cut time exceeds 60 minutes.
- **Packaging** — `briefcase package macOS --adhoc-sign` produces a
  universal2 `.dmg` (~156 MB) that runs on Apple Silicon and Intel Macs.
- **Test suite** — 80+ unit tests covering HPGL generation, SVG parsing,
  blade compensation, inside-first sorting, sharp-corner pivots, and
  serial I/O (with `pyserial` mocks).

### Hardware-verified

The following sequence of findings was required to make the RS720C
actually cut and is included verbatim in the commit history:

1. Open port with `FlowControl.NONE` — hardware flow control lines
   on this cutter class aren't wired correctly; RTS/CTS false-OKs and
   the cutter silently discards bytes.
2. Assert `DTR` and `RTS` high explicitly after open, with a 300 ms
   settle — without this the cutter's UART ignores incoming bytes.
3. Emit only plain `FS{n};` (no HP-GL/2 `!FS{n};` prefix) — the
   bang-prefixed form crashes the RS720C's parser and it drops all
   subsequent commands.
4. Drop redundant standalone `PU;` between polylines — the next
   `PU<x>,<y>;` lifts the pen as part of its move and the spurious
   no-coord form confuses some firmwares.
5. Pace transmission by move duration, not by a flat per-line delay —
   at VS3 a single long move takes seconds; flat pacing overfills the
   buffer.

[0.1.0]: https://github.com/anders-pixel/RedsailCut/releases/tag/v0.1.0
