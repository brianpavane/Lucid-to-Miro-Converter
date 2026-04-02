# Lucid-to-Miro Converter

[![Release](https://img.shields.io/github/v/release/brianpavane/Lucid-to-Miro-Converter)](https://github.com/brianpavane/Lucid-to-Miro-Converter/releases/tag/v1.0.0)

Convert Lucidchart exports to Miro-importable JSON.

**Requires:** Python 3.8+ — no third-party packages needed. Works on macOS, Windows, and Linux.

**Supported input formats:**
| Format | How to export from Lucidchart |
|--------|-------------------------------|
| `.json` | File → Export → JSON |
| `.csv`  | File → Export → CSV |

**Features:**
- Multi-tab / multi-page diagrams → one Miro frame per tab, placed side-by-side
- Auto-layout: positions and sizes all shapes (neither export format carries coordinates)
- CSV: uses "Contained By" hierarchy to nest shapes inside containers with correct indentation
- JSON: clusters group-members together, then arranges groups in a grid
- 50+ shape type mappings (basic, flowchart, cloud-provider containers, arrows, callouts)
- SVGPathBlock2 / icon shapes → Miro image widgets
- Text-only shapes (MinimalTextBlock) → Miro text widgets
- Connectors with labels and arrow styles preserved
- Optional page filtering via `--pages`

## Usage

```bash
python lucid2miro.py <input.json|csv> [options]
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `-o, --output FILE` | Output file path | `<input>.miro.json` |
| `-t, --title TITLE` | Miro board title | Title from source file |
| `-s, --scale N` | Uniform coordinate scale factor | `1.0` |
| `--pretty` | Pretty-print output JSON | off |
| `--summary` | Print conversion stats to stdout | off |
| `--pages N[,N]` | Include only these pages (titles or 1-based indices) | all |

### Examples

```bash
# Convert a JSON export
python lucid2miro.py diagram.json

# Convert a CSV export with a custom title and pretty output
python lucid2miro.py diagram.csv -t "My Architecture" --pretty --summary

# Scale up all coordinates and export only two pages
python lucid2miro.py diagram.json --scale 1.5 --pages "HA,Forwarding Rules"

# Export only pages 1 and 3 by index
python lucid2miro.py diagram.csv --pages "1,3"
```

## Output format

The converter produces JSON compatible with the Miro REST API v2:

```json
{
  "version": "1",
  "board": {
    "title": "My Diagram",
    "widgets": [
      {
        "type": "frame",
        "id": "frame_page-0",
        "title": "HA",
        "position": { "x": 0, "y": 0 },
        "geometry": { "width": 1200, "height": 900 }
      },
      {
        "type": "shape",
        "parentId": "frame_page-0",
        "data": { "shape": "rectangle", "content": "Web Server" },
        "style": { "fillColor": "#ffffff", "borderColor": "#000000" },
        "position": { "x": 60, "y": 80 },
        "geometry": { "width": 160, "height": 80 }
      }
    ]
  }
}
```

### Widget type mapping

| Lucidchart element | Miro widget |
|--------------------|-------------|
| Page / tab | `frame` |
| Regular shape (Block, Rectangle, …) | `shape` |
| Container (Region, VPC, Subnet, AZ, …) | `shape` with light fill + blue border |
| SVGPathBlock2 / icon | `image` |
| MinimalTextBlock / label | `text` |
| Line / connector | `line` |

## Auto-layout

Because Lucidchart's CSV and JSON exports contain **no coordinate data**, the converter auto-lays out every diagram:

- **CSV** — uses the "Contained By" column to reconstruct the containment tree. Leaf shapes are sized to defaults (160×80 px for shapes, 80×80 for icons). Containers are sized bottom-up to wrap their children, then all top-level items are arranged in a sqrt(n)-column grid.
- **JSON** — no containment info is available, so shapes that share a `group_id` are clustered together and the clusters are arranged in a grid.

## Running tests

```bash
# Built-in unittest (no install needed)
python3 -m unittest discover -s tests -v

# Or with pytest
pip install pytest
pytest tests/ -v
```

51 tests covering parsers, shape mapping, layout engine, converter, and CLI.

## Project structure

```
lucid_to_miro/
├── model.py              Normalised data model (Document, Page, Item, Line)
├── parser/
│   ├── csv_parser.py     Lucidchart CSV parser
│   └── json_parser.py    Lucidchart JSON parser
└── converter/
    ├── miro.py           Miro JSON serialiser
    ├── shape_map.py      50+ shape type mappings
    └── layout.py         Auto-layout engine
lucid2miro.py             CLI entry point
tests/
├── test_converter.py     51 unit + integration tests
└── make_fixtures.py      Generates synthetic test fixtures
```
