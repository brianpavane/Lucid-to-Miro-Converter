# Lucid-to-Miro Converter

[![Release](https://img.shields.io/github/v/release/brianpavane/Lucid-to-Miro-Converter)](https://github.com/brianpavane/Lucid-to-Miro-Converter/releases/latest)

Convert Lucidchart exports to Miro-importable JSON.

**Requires:** Python 3.8+ — no third-party packages needed. Works on macOS, Windows, and Linux.

**Supported input formats:**
| Format | How to export from Lucidchart |
|--------|-------------------------------|
| `.csv`  | File → Export → CSV  |
| `.json` | File → Export → JSON |

---

## Getting the tool

### Single file — download `lucid2miro.py` only

The entire converter ships as a single, self-contained Python file. You only need this one file to run it.

**macOS / Linux:**
```bash
curl -o lucid2miro.py https://raw.githubusercontent.com/brianpavane/Lucid-to-Miro-Converter/main/lucid2miro.py
```

**Windows (PowerShell):**
```powershell
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/brianpavane/Lucid-to-Miro-Converter/main/lucid2miro.py" -OutFile "lucid2miro.py"
```

**GitHub CLI:**
```bash
gh api repos/brianpavane/Lucid-to-Miro-Converter/contents/lucid2miro.py \
  --jq '.content' | base64 --decode > lucid2miro.py
```

**Git sparse-checkout (if you want to stay in sync with updates):**
```bash
git clone --filter=blob:none --sparse https://github.com/brianpavane/Lucid-to-Miro-Converter.git
cd Lucid-to-Miro-Converter
git sparse-checkout set lucid2miro.py
```

### Full repository clone
```bash
git clone https://github.com/brianpavane/Lucid-to-Miro-Converter.git
cd Lucid-to-Miro-Converter
```

---

## Usage

```bash
# Single file
python lucid2miro.py <input.csv|json> [options]

# Batch — convert every .csv (or .json) in a folder
python lucid2miro.py <input-dir/> --format csv|json [--output-dir <dir/>] [options]
```

### Options

**Batch flags** (only when `input` is a directory):

| Flag | Description | Default |
|------|-------------|---------|
| `--format csv\|json` | File type to convert *(required)* | — |
| `--output-dir DIR` | Directory for converted files | Input directory |

**Single-file & shared flags:**

| Flag | Description | Default |
|------|-------------|---------|
| `-o, --output FILE` | Output path *(single-file only)* | `<input>.miro.json` |
| `-t, --title TITLE` | Miro board title | Title from source file |
| `-s, --scale N` | Uniform coordinate scale factor | `1.0` |
| `--pretty` | Pretty-print output JSON | off |
| `--summary` | Print conversion stats (per file in batch) | off |
| `--pages N[,N]` | Page titles or 1-based indices to include *(single-file only)* | all |
| `--clean-names` | Name outputs `<stem>.json` instead of `<stem>.miro.json` — requires `--output-dir` to differ from input dir in batch mode | off |
| `--version` | Print version and exit | — |

### Single-file examples

```bash
# Basic conversion
python lucid2miro.py diagram.csv

# Custom title, pretty output, and per-page summary
python lucid2miro.py diagram.csv -t "My Architecture" --pretty --summary

# Specific pages by title
python lucid2miro.py diagram.json --pages "HA,Forwarding Rules"

# Specific pages by index, scaled up
python lucid2miro.py diagram.csv --pages "1,3" --scale 1.5

# Explicit output path
python lucid2miro.py diagram.csv -o ~/Desktop/board.json --pretty
```

### Batch examples

```bash
# Convert all CSVs in ./exports/ → ./miro/  (outputs: diagram.miro.json)
python lucid2miro.py ./exports/ --format csv --output-dir ./miro/

# Clean output names — same stem, just .json  (outputs: diagram.json)
python lucid2miro.py ./exports/ --format csv --output-dir ./miro/ --clean-names

# Convert all JSONs with per-file summaries
python lucid2miro.py ./exports/ --format json --output-dir ./miro/ --summary

# Output defaults to same folder as input files
python lucid2miro.py ./exports/ --format csv --scale 1.5 --pretty
```

**Output filenames:**

| Mode | Output name |
|------|-------------|
| Default | `diagram.csv` → `diagram.miro.json` |
| `--clean-names` | `diagram.csv` → `diagram.json` |

`--clean-names` requires `--output-dir` to point to a **different** directory than the input — the converter will refuse if they are the same to prevent source files from being overwritten.

The output directory is created automatically (including nested paths) if it does not exist.

---

## Output format

Produces JSON compatible with the Miro REST API v2:

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

---

## CSV vs JSON — which format to use

**Use CSV.** It produces significantly better results and is the recommended input format.

### Why CSV is preferred

Lucidchart's CSV export includes a `Contained By` column that encodes the full containment hierarchy for every shape — which region contains which Availability Zone, which subnet sits inside which VPC, and so on. The converter uses this to reconstruct a proper nesting tree and lay out containers wrapping their children, exactly as they appear in the original diagram.

Lucidchart's JSON export omits all position and containment data entirely. Every shape on a page is a peer with no parent; the converter can only cluster shapes that share a `group_id` and arrange those clusters in a flat grid. The resulting Miro board is structurally flat regardless of how deeply nested the original diagram was.

| Capability | CSV | JSON |
|---|---|---|
| Containment hierarchy (`Contained By`) | ✅ | ❌ |
| Nested layout (VPC → AZ → Subnet → shape) | ✅ | ❌ |
| Shape Library name (AWS 2021, GCP 2018…) | ✅ | ❌ |
| Exact internal class name (`DefaultSquareBlock`) | ❌ | ✅ |
| Structured text-area labels | ❌ | ✅ |

The containment hierarchy advantage is decisive for any cloud architecture, network, or swimlane diagram. The JSON class-name and text-label advantages are minor in practice — the CSV `Name` + `Shape Library` columns provide enough signal to map every shape type correctly.

### When JSON is acceptable

Use JSON only when:
- The diagram is intentionally flat (no containers — just shapes connected by lines), in which case both formats produce equivalent results
- A CSV export is unavailable for that diagram

## Auto-layout

Neither Lucidchart export format carries coordinate data, so the converter auto-lays out every diagram:

- **CSV** — reconstructs the containment tree from the `Contained By` column. Leaf shapes get default dimensions (160×80 px; 80×80 for icons). Containers are sized bottom-up to wrap their children. All top-level items are arranged in a √n-column grid.
- **JSON** — no containment data is available. Shapes sharing a `group_id` are clustered together; clusters are arranged in a grid.

---

## Features

- Single self-contained file — one download, no package installation
- Batch / bulk mode — convert an entire folder in one command
- Multi-tab support — each Lucidchart page → a Miro frame, placed side-by-side
- 50+ shape type mappings (basic, flowchart, AWS/GCP/Azure containers, arrows, callouts)
- Connectors with labels and arrow styles
- Optional page filtering and coordinate scaling

---

## Running tests

The repository includes 62 tests for the importable package (`lucid_to_miro/`):

```bash
# Built-in unittest (no install needed)
python3 -m unittest discover -s tests -v

# Or with pytest
pip install pytest && pytest tests/ -v
```

---

## Project structure

```
lucid2miro.py             ← single-file standalone converter (start here)

lucid_to_miro/            ← importable package (same logic, modular layout)
├── model.py
├── parser/
│   ├── csv_parser.py
│   └── json_parser.py
└── converter/
    ├── miro.py
    ├── shape_map.py
    └── layout.py

tests/
├── test_converter.py     62 unit + integration tests
└── make_fixtures.py      Generates synthetic test fixtures
```
