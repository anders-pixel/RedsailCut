# RedsailCut

En lille macOS-app til at sende SVG-filer til en Redsail vinylskærer over USB-til-serial.
Gør én ting: **åbner en SVG, lader dig skalere i mm, og sender HPGL til maskinen**.

## Features

- Drag-and-drop eller fil-dialog for SVG
- Preview med bbox og mm-label
- Skalering med aspect-ratio lock
- Speed (VS) og Force (FS) kontrol
- **Dry run default on first launch** — gemmer `.plt` til Desktop i stedet for at skære
- Stop-knap med ordentlig abort-sekvens (`PU;PU0,0;SP0;`)
- Advarsler hvis design er > 400 mm eller estimeret tid > 60 min
- Settings > Advanced > Serial flow control (RTS/CTS / XON/XOFF)

## Install

### Fra DMG (anbefales)

```sh
open dist/RedsailCut-0.1.0.dmg
```
Træk RedsailCut.app til Programmer. Første gang du åbner den, højreklik → Åbn for at omgå Gatekeeper (ad-hoc-signeret).

### Fra kildekode

```sh
brew install uv
git clone <repo> redsailcut && cd redsailcut
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev]"
python -m redsailcut                   # launcher GUI
python -m redsailcut file.svg --width 400 --dry-run -o out.plt  # CLI
```

## Hardware-opsætning

1. Slut din CH340/CP210-baserede USB-til-serial-adapter til Mac'en
2. Porten dukker op som `/dev/cu.wchusbserial*` eller lignende
3. Første gang vil macOS spørge om tilladelse — gå til **Systemindstillinger > Privatliv & Sikkerhed** og tillad appen hvis den blokeres

## Skær-workflow (første gang)

**GØRE IKKE alt på én gang.** Rækkefølge:

1. Indlæs SVG, kontroller preview-størrelse
2. **Dry run** → åbn den genererede `.plt` i en tekst-editor eller HPGL-viewer; bekræft at kommandoer ser rigtige ud
3. **Pen-test**: indsæt en pen (ikke kniv!) i cutteren, kør på papir. Resultatet skal matche preview
4. **Lille testskæring**: 5×5 cm kvadrat på affaldsvinyl ved lav force
5. **Rigtig skæring**

## Kendte begrænsninger

- Ingen design-værktøjer (brug Illustrator/Inkscape først)
- Ingen print-and-cut, ingen multi-layer, ingen auto-optimering af skære-rækkefølge
- Kun én farve (alle paths behandles som sorte)
- SVG'er skal have `viewBox="0 0 ..."` startende ved (0,0) — ikke-standard offsets kan give forskudt placering; fit til artboard i dit designværktøj først

## Build

```sh
briefcase create macOS
briefcase build macOS
briefcase package macOS --adhoc-sign
```
Output: `dist/RedsailCut-0.1.0.dmg`.

## Tests

```sh
pytest
```
Unit tests dækker HPGL-generator (Y-flip, rounding, flow), SVG-parser (square perimeter, circle deviation, transform reify, Barcelona fixture), og serial I/O (mock: ordered writes, abort sequence, Danish permission error).

## License

MIT — see `LICENSE`.
