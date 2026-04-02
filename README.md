# Lucid-to-Miro Converter

[![Release](https://img.shields.io/github/v/release/brianpavane/Lucid-to-Miro-Converter)](https://github.com/brianpavane/Lucid-to-Miro-Converter/releases/latest)

Convert Lucidchart exports to Miro — either as local JSON files or by uploading
directly to a Miro board via the REST API.

**Requires:** Python 3.8+ — no third-party packages needed. Works on macOS, Windows, and Linux.

**Supported input formats:**
| Format | How to export from Lucidchart | Notes |
|--------|-------------------------------|-------|
| `.vsdx` | File → Export → Visio (.vsdx) | ⭐ **Recommended** — preserves original layout, styling, and icons |
| `.csv`  | File → Export → CSV  | Auto-layout with containment hierarchy |
| `.json` | File → Export → JSON | Auto-layout, flat only |

**Three output modes:**
| Mode | When to use |
|------|-------------|
| **Offline VSDX** (`--output-format vsdx`) | Generate a `.vsdx` file → import into Miro via "Import from Visio" (no token, no REST API) |
| **Offline JSON** *(default)* | Generate a local `.miro.json` file for scripting or manual import |
| **REST API upload** (`--upload`) | Create a live Miro board directly from the command line |

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

## Quick start

### Offline VSDX output (no Miro account or token needed)

Import the output via Miro **→ "Import from Visio"** — no REST API required.
Each non-empty source page/tab is written as a Visio page; Miro imports those
pages as Frames.
Recent compatibility fixes also write geometry values in both Visio forms
(`V="..."` attributes and element text) to improve cases where generated VSDX
files previously appeared blank when imported into Miro.
Generated shapes now also include explicit rectangle geometry sections, not just
position and size metadata.
Generated packages now also include richer document-level Visio parts such as
`visio/windows.xml`, `docProps/app.xml`, `docProps/core.xml`, and expanded page
metadata in `visio/pages/pages.xml`.

```bash
# VSDX passthrough — original layout preserved
python lucid2miro.py diagram.vsdx --output-format vsdx

# CSV/JSON → VSDX (auto-layout applied, then written as Visio)
python lucid2miro.py diagram.csv  --output-format vsdx
python lucid2miro.py diagram.json --output-format vsdx

# Batch — convert all CSVs to VSDX
python lucid2miro.py ./exports/ --format csv --output-format vsdx --output-dir ./out/

# Debug counts — compare parsed input vs written output
python lucid2miro.py diagram.json --output-format vsdx --debug-counts
```

### Offline JSON output (no Miro account needed)

```bash
python lucid2miro.py diagram.vsdx          # → diagram.miro.json  (recommended)
python lucid2miro.py diagram.csv           # → diagram.miro.json
python lucid2miro.py diagram.json -o board.json --pretty --summary
python lucid2miro.py ./exports/ --format vsdx --output-dir ./miro/
```

### REST API upload (direct to Miro)

```bash
# 1. Get a Personal Access Token from Miro (see docs/MIRO_AUTH.md)
export MIRO_TOKEN=your_token_here

# 2. Upload VSDX — preserves original layout, styling, and icons (recommended)
python lucid2miro.py diagram.vsdx --upload

# 3. Upload CSV — auto-layout with containment hierarchy
python lucid2miro.py diagram.csv --upload

# 4. Preview without uploading
python lucid2miro.py diagram.vsdx --upload --dry-run --summary
```

---

## Usage

```bash
# Single file (offline)
python lucid2miro.py <input.vsdx|csv|json> [options]

# Batch (offline)
python lucid2miro.py <input-dir/> --format vsdx|csv|json [--output-dir <dir/>] [options]

# Single file (upload)
python lucid2miro.py <input.vsdx|csv|json> --upload [upload-options]

# Batch (upload)
python lucid2miro.py <input-dir/> --format vsdx|csv|json --upload [upload-options]
```

### Shared flags

| Flag | Description | Default |
|------|-------------|---------|
| `-t, --title TITLE` | Board title | Title from source file |
| `-s, --scale N` | Uniform coordinate scale factor | `1.0` |
| `--summary` | Print conversion / upload stats | off |
| `--debug-counts` | Print overall and per-page page/tab counts, titles, object counts, and icon diagnostics for parsed input and written output | off |
| `--pages N[,N]` | Page titles or 1-based indices to include | all |
| `--version` | Print version and exit | — |

### Offline-only flags

| Flag | Description | Default |
|------|-------------|---------|
| `--format vsdx\|csv\|json` | *(Batch)* File type to convert *(required)* | — |
| `--output-dir DIR` | *(Batch)* Directory for converted files | Input directory |
| `-o, --output FILE` | *(Single)* Output file path | `<input>.miro.json` |
| `--pretty` | Pretty-print output JSON | off |
| `--clean-names` | Output `<stem>.json` instead of `<stem>.miro.json` | off |

### Upload flags (`--upload` mode)

| Flag | Description | Default |
|------|-------------|---------|
| `--upload` | Upload directly to Miro via REST API | off |
| `--token TOKEN` | Miro Personal Access Token | `MIRO_TOKEN` env var |
| `--team-id TEAM_ID` | Miro team/workspace for new boards | token default |
| `--board-id BOARD_ID` | Upload into an existing board | create new |
| `--board-name NAME` | Override board title | source title |
| `--frame-prefix PREFIX` | Prepend text to each frame name | `""` |
| `--frame-suffix SUFFIX` | Append text to each frame name | `""` |
| `--icon-map FILE` | JSON file mapping shape IDs/names to image URLs | none |
| `--access private\|view\|comment\|edit` | Sharing policy for new boards | `private` |
| `--dry-run` | Simulate upload without API calls | off |

### Naming options (upload mode)

Control how the board and frames are named:

```bash
# Custom board name
python lucid2miro.py diagram.csv --upload --board-name "Q3 Architecture"

# Add a prefix to every frame (tab → frame)
python lucid2miro.py diagram.csv --upload --frame-prefix "Sprint 3: "
# → "Sprint 3: Production VPC", "Sprint 3: Staging", ...

# Combine prefix and suffix
python lucid2miro.py diagram.csv --upload \
  --frame-prefix "2026 " --frame-suffix " [Draft]"
# → "2026 Production VPC [Draft]"
```

### Offline examples

```bash
# VSDX — preserves original layout (recommended)
python lucid2miro.py diagram.vsdx

# CSV — auto-layout with containment hierarchy
python lucid2miro.py diagram.csv

# Custom title, pretty output, summary
python lucid2miro.py diagram.vsdx -t "My Architecture" --pretty --summary

# Debug page and object counts before/after writing
python lucid2miro.py diagram.json --output-format vsdx --debug-counts

# Specific pages by title
python lucid2miro.py diagram.vsdx --pages "HA,Forwarding Rules"

# Batch — all VSDX files in ./exports/ → ./miro/
python lucid2miro.py ./exports/ --format vsdx --output-dir ./miro/

# Clean output names (diagram.vsdx → diagram.json)
python lucid2miro.py ./exports/ --format vsdx --output-dir ./miro/ --clean-names
```

### Upload examples

```bash
# Upload VSDX — original layout + styling (recommended)
python lucid2miro.py diagram.vsdx --upload

# Upload CSV — auto-layout with containment hierarchy
python lucid2miro.py diagram.csv --upload

# Upload to an existing board
python lucid2miro.py diagram.vsdx --upload --board-id uXjVPabc1234=

# Name the board and frames
python lucid2miro.py diagram.vsdx --upload \
  --board-name "Prod Infrastructure" \
  --frame-prefix "Env: "

# Batch upload all VSDX files in ./exports/
python lucid2miro.py ./exports/ --format vsdx --upload --summary

# Dry run — see what would be created without calling the API
python lucid2miro.py diagram.vsdx --upload --dry-run --summary

# With custom icons (generated from VSDX extraction)
python lucid2miro.py diagram.vsdx --upload --icon-map diagram_icon_map.json
```

**`--clean-names`** requires `--output-dir` to point to a **different** directory than the input to prevent source files from being overwritten.

The output directory is created automatically (including nested paths) if it does not exist.

`--debug-counts` is especially helpful when validating multi-tab conversions. It
reports source page counts, non-empty vs empty pages, and object totals from the
parsed input, then re-opens the written file and reports the same counts for the
output. It also prints a per-page breakdown with page titles, item counts, line
counts, icon diagnostics, and whether a page was skipped on output. Empty pages
are intentionally skipped in generated `.vsdx` output.

For clarity, the debug output distinguishes between:
- `icon-like shapes`: shapes recognized as icon objects from CSV/JSON metadata or VSDX shape type
- `embedded image data` / `embedded image icons`: icons that actually carry image bytes in the file and can round-trip as true embedded image objects

Example per-page debug lines:

```text
Read icons    : 164 icon-like shapes, 0 with embedded image data
Output icons  : 0 icon-like shapes, 0 embedded image icons
[01] HA: read 41 items/20 lines/22 icon-like/0 embedded -> out 41 items/20 lines/0 icon-like/0 embedded
[27] Page 27: read 0 items/0 lines/0 icon-like/0 embedded [empty] -> out skipped
```

If a generated `.vsdx` still imports as blank in Miro, compare it against a
native Lucid `.vsdx` import and retest with the latest writer first. The most
recent compatibility update changed the generated XML so page and shape geometry
is written both as attributes and as element text, and visible shapes now carry
an explicit rectangle geometry section, which some Visio consumers appear to
require. The generated package now also includes window and document metadata
that more closely matches native Lucid `.vsdx` output.

For native `.vsdx` input specifically, `--output-format vsdx` now takes a true
passthrough path when no transformations are requested. That means:
- no `--pages`
- no `--title`
- `--scale 1.0`

In that case the output `.vsdx` is a byte-for-byte copy of the original Lucid
file, which is the best-fidelity option for Miro's native Visio import.

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

## Which format to use

**Use VSDX.** It is the recommended format for all Miro uploads.

### Why VSDX is best

Lucidchart's VSDX export embeds exact pixel coordinates, per-shape styling (fill colour, border colour), containment grouping, and custom icon images. The converter uses these directly — no layout approximation. The resulting Miro board matches the original LucidChart diagram as closely as possible.

| Capability | VSDX ⭐ | CSV | JSON |
|---|---|---|---|
| Original layout preserved (pixel coords) | ✅ | ❌ auto | ❌ auto |
| Containment hierarchy | ✅ | ✅ | ❌ |
| Per-shape fill / border styling | ✅ | ❌ | ❌ |
| Custom icons (embedded) | ✅ extracted | ❌ | ❌ |
| Shape Library metadata | partial | ✅ | ❌ |
| Exact internal class names | — | ❌ | ✅ |
| Automatable via REST API | ✅ | ✅ | ✅ |

### When to use CSV

Use CSV when a VSDX export is unavailable. The `Contained By` column encodes
the full nesting hierarchy and the auto-layout engine reconstructs proper
container wrapping — a significantly better result than JSON for cloud
architecture and swimlane diagrams.

### When JSON is acceptable

Use JSON only when:
- The diagram is intentionally flat (shapes connected by arrows, no containers)
- Neither VSDX nor CSV is available for that diagram

## Auto-layout

VSDX input carries exact coordinates — no auto-layout is run; the Miro board
matches the original diagram pixel-for-pixel (scaled to 96 dpi).

For CSV and JSON, neither format carries coordinate data, so the converter
auto-lays out the diagram:

- **CSV** — reconstructs the containment tree from the `Contained By` column. Leaf shapes get default dimensions (160×80 px; 80×80 for icons). Containers are sized bottom-up to wrap their children. All top-level items are arranged in a √n-column grid.
- **JSON** — no containment data is available. Shapes sharing a `group_id` are clustered together; clusters are arranged in a grid.

---

## Features

- Single self-contained file — one download, no package installation
- **Three input formats:** VSDX (recommended), CSV, JSON
- **Three output modes:** VSDX (no API needed), Miro JSON, REST API upload
- **VSDX output** (`--output-format vsdx`): any input → Visio file → import via Miro "Import from Visio"
- **Debug validation** (`--debug-counts`): compare page/tab and object counts before and after writing output
- **VSDX input:** original layout, per-shape styling, and embedded icons preserved
- Batch / bulk mode — convert an entire folder in one command
- Multi-tab support — each Lucidchart page → a Miro frame, placed side-by-side
- 50+ shape type mappings (basic, flowchart, AWS/GCP/Azure containers, arrows, callouts)
- Connectors with labels and arrow styles
- Optional page filtering and coordinate scaling
- Direct REST API upload (`--upload`) with dry-run support

---

## Running tests

The repository includes 97 tests for the importable package (`lucid_to_miro/`):

```bash
# Built-in unittest (no install needed)
python3 -m unittest discover -s tests -v

# Or with pytest
pip install pytest && pytest tests/ -v
```

---

## Authentication

See **[docs/MIRO_AUTH.md](docs/MIRO_AUTH.md)** for the full guide covering:

- Creating a Personal Access Token (PAT) — step-by-step
- OAuth 2.0 for app integrations
- CI/CD setup (GitHub Actions, GitLab)
- Naming options (board name, frame prefix/suffix)
- Custom icon mapping
- Troubleshooting (401, 403, 429)

---

## LucidChart export formats

See **[docs/LUCIDCHART_FORMATS.md](docs/LUCIDCHART_FORMATS.md)** for a full comparison of:

- **Visio (.vsdx)** ⭐ — recommended; preserves original layout, styling, and icons
- **CSV** — auto-layout with containment hierarchy; fallback when VSDX unavailable
- **JSON** — flat only; use for simple diagrams without containers
- **SVG / PDF** — static reference boards
- **Miro UI file upload vs REST API** — full capability comparison table

---

## Project structure

```
lucid2miro.py             ← single-file standalone converter (start here)

lucid_to_miro/            ← importable package (same logic, modular layout)
├── model.py
├── parser/
│   ├── csv_parser.py
│   ├── json_parser.py
│   └── vsdx_parser.py    ← Visio reader (new in v1.5.0)
├── converter/
│   ├── miro.py
│   ├── shape_map.py
│   ├── layout.py
│   └── vsdx_writer.py    ← Visio writer
└── api/                  ← REST API client and uploader (new in v1.4.0)
    ├── miro_client.py
    └── uploader.py

docs/
├── MIRO_AUTH.md          ← Authentication guide + naming options
└── LUCIDCHART_FORMATS.md ← Export format comparison

tests/
├── test_converter.py     62 unit + integration tests
└── make_fixtures.py      Generates synthetic test fixtures
```
