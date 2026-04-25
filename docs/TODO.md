# TODO

## High Priority

- Add a GUI-visible HPGL preflight summary before real cutting.
- Add a user setting for pen-up settle delay if more hardware testing shows
  150 ms is too short or unnecessarily slow.
- Add a "safe travel mode" option that breaks long `PU` moves into smaller
  chunks for machines with unreliable lift timing.
- Re-test the 580 mm Barcelona job on paper after the English UI and splitter
  layout changes are installed.

## Medium Priority

- Add an HPGL analyzer command for dry-run files so suspicious `PD` and `PU`
  moves can be inspected without custom scripts.
- Persist splitter position once the user manually resizes preview/settings.
- Add a small fixture based on the Barcelona invitation SVG if licensing and
  privacy allow it.
- Document recommended settings for pen tests versus knife tests.

## Low Priority

- Add optional path reversal in nearest-neighbor sorting if it improves travel
  without affecting blade behavior.
- Add a preview overlay for path order and pen-up travel.
- Add release automation for DMG naming and changelog validation.
