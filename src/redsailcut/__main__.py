"""CLI entry point for RedsailCut.

Usage:
    python -m redsailcut INPUT.svg --width 400 --dry-run -o out.plt

The CLI is a headless developer tool that converts an SVG to HPGL and writes
the result to a `.plt` file. Sending to a live cutter is the GUI's job.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from redsailcut.hpgl import polylines_to_hpgl
from redsailcut.svg_parser import svg_to_polylines, total_cut_length_mm


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="redsailcut",
        description="Convert an SVG to Redsail-compatible HPGL (.plt).",
    )
    p.add_argument("input", type=Path, help="Input SVG file")
    p.add_argument("--width", type=float, required=True,
                   help="Target cut width in millimetres (height follows proportionally)")
    p.add_argument("--speed", type=int, default=20,
                   help="Cutting speed in cm/s (1..80, default 20)")
    p.add_argument("--force", type=int, default=80,
                   help="Cutting force in grams (1..200, default 80)")
    p.add_argument("--dry-run", action="store_true",
                   help="Write HPGL to file instead of sending to a cutter (required)")
    p.add_argument("-o", "--output", type=Path,
                   help="Output .plt path (default: <input-stem>.plt next to input)")
    return p


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    # No CLI args → launch the GUI (this is also how the packaged .app starts)
    if not argv:
        from redsailcut.app import run_gui
        return run_gui()
    args = build_parser().parse_args(argv)

    if not args.dry_run:
        print(
            "error: live cutting requires the GUI; pass --dry-run to write a .plt file",
            file=sys.stderr,
        )
        return 2

    if not args.input.exists():
        print(f"error: input file not found: {args.input}", file=sys.stderr)
        return 1

    output = args.output or args.input.with_suffix(".plt")

    polylines, width_mm, height_mm = svg_to_polylines(args.input,
                                                      target_width_mm=args.width)
    hpgl = polylines_to_hpgl(polylines, height_mm=height_mm,
                             speed_cm_s=args.speed, force_g=args.force)
    output.write_text(hpgl, encoding="ascii")

    total_mm = total_cut_length_mm(polylines)
    est_s = total_mm / (args.speed * 10.0) if args.speed else 0.0
    print(f"Input:      {args.input}")
    print(f"Output:     {output}")
    print(f"Size:       {width_mm:.2f} x {height_mm:.2f} mm")
    print(f"Polylines:  {len(polylines)}")
    print(f"Cut length: {total_mm:.1f} mm")
    print(f"Speed:      {args.speed} cm/s    Force: {args.force} g")
    print(f"Est. time:  {est_s / 60:.1f} min (cut only, excludes pen-up travel)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
