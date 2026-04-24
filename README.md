# RedsailCut

A minimal macOS app that drives a Redsail vinyl cutter (or any HPGL-compatible
plotter) from an SVG file over USB-to-serial.

It does one thing: **load an SVG, scale it in millimetres, and stream HPGL to
the machine.** No design tools, no print-and-cut, no multi-colour — just
reliable cutting of whatever you designed elsewhere.

Hardware-verified on a Redsail RS720C.

## Features

- Drag-and-drop or file picker for SVG input
- Live preview with bounding box + millimetre label
- Aspect-ratio-locked scaling by width or height
- Speed (`VS`) and force (`FS`) control, with sensible warnings for
  designs wider than 400 mm or jobs longer than 60 minutes
- **Dry run is the default on first launch** — writes a `.plt` file to
  the Desktop instead of sending to the cutter, so you can never
  accidentally cut on first use
- Drag-knife compensation: per-corner offset extension, closed-shape
  overcut, and automatic pen-up lifts at sharp corners
- Inside-first path ordering so letter counters (O, D, A) are cut
  before their outer contours
- Settings → Tools → Test cutter connection… — HPGL `OI;` probe that
  reports whether the cutter is replying
- Settings → Advanced → Serial flow control — pick between None
  (default, verified working on the RS720C), RTS/CTS, or XON/XOFF
- Stop button that emits a clean `PU;PU0,0;SP0;` abort sequence
- Motion-aware serial pacing: each `PU`/`PD` command waits for the
  cutter's actual physical move time based on `VS` and the distance,
  so the cutter's buffer can't overflow

## Install

### From DMG (recommended)

Download `RedsailCut-0.1.0.dmg` from the [Releases page][releases] (or
build it yourself — see below), then:

```sh
open RedsailCut-0.1.0.dmg
```

Drag `RedsailCut.app` into `Applications`. The first time you launch it,
**right-click → Open** — the app is ad-hoc-signed, so Gatekeeper blocks a
double-click on the first run.

[releases]: https://github.com/anders-pixel/RedsailCut/releases

### From source

```sh
brew install uv
git clone https://github.com/anders-pixel/RedsailCut.git
cd RedsailCut
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"

python -m redsailcut                               # launches the GUI
python -m redsailcut file.svg --width 400 \        # headless CLI
    --dry-run -o out.plt
```

## Hardware setup

1. Plug your USB-to-serial adapter into the Mac. Any FT232R or
   CH340/CP210-class adapter works.
2. The port appears as `/dev/cu.usbserial-*` or `/dev/cu.wchusbserial-*`.
3. macOS may prompt for permission the first time. If the app is
   blocked, open **System Settings → Privacy & Security** and allow it.
4. Connect the adapter to the cutter's serial port. Most Redsails
   default to 9600 baud, 8-N-1, no handshake.

## Cutting workflow (first time)

**Do not do everything at once.** Walk through these steps in order:

1. **Load SVG**, verify preview dimensions and orientation.
2. **Dry run** with blade compensation off. Open the `.plt` file in a
   text editor or an HPGL viewer — sanity-check the commands.
3. **Pen test**: swap the knife for a pen and draw on paper. Pen needs
   higher force (~200 g) than a knife because of the pen holder's
   return spring. Confirms path accuracy without risking vinyl.
4. **Small knife test**: 5 × 5 cm square on scrap vinyl at low force
   (start 70 g), increase 5–10 g at a time until the cut releases
   cleanly without cutting through the backing.
5. **Real cut.**

### Blade compensation (drag-knife)

- **Offset** (default 0 = pen mode): typically 0.20–0.30 mm for a
  45° blade, up to 0.30 mm for a 60° blade. Check your blade spec.
- **Overcut** (0.0–2.0 mm, default 0.5): extends closed paths past
  the closing point so vinyl separates cleanly. Only active when
  offset > 0.
- **Corner threshold** (default 5°): skip compensation for near-straight
  "corners" on sampled curves so they don't drift outward.
- **Lift knife on sharp corners**: splits polylines at corners below
  the sharp-corner threshold (default 30°) so the knife can rotate
  on pen-up before continuing.

## Known limits

- No design tools. Design in Illustrator / Inkscape / Affinity first,
  export to SVG.
- No print-and-cut, no multi-layer, no multi-colour (all paths are
  treated as black).
- No automatic cut-order optimisation beyond inside-first.
- Stroke-width is ignored — the cutter follows the path centreline.
- SVGs should have `viewBox="0 0 ..."` starting at the origin.
  Non-zero offsets may shift placement; "fit to artboard" in your
  design tool first if you see that.

## Build

```sh
briefcase create macOS
briefcase build macOS
briefcase package macOS --adhoc-sign
```

Output: `dist/RedsailCut-0.1.0.dmg` (ad-hoc-signed, ~156 MB universal2
bundle including PyQt6 and the numpy/svgelements support stack). For
wider distribution you'd need an Apple Developer ID and notarisation.

## Tests

```sh
pytest
```

~80 unit tests covering:

- HPGL generation: Y-flip correctness, 40 units/mm scaling, rounding
  at banker boundaries, pen-up travel between polylines
- SVG parsing: square perimeter, circle radial deviation, transform
  reification, per-segment adaptive sampling (including control-polygon
  length approximation so the Barcelona fixture parses in under a
  second)
- Blade offset, inside-first ordering, sharp-corner pivots
- Serial I/O with mocks: ordered writes, mid-stream abort sequence,
  Danish user-facing permission-error message, motion-aware pacing
  math

## Acknowledgements

The motion-aware serial pacing formulation is credited to Codex.

## License

MIT — see `LICENSE`.
