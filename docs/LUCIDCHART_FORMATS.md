# LucidChart Export Formats

This document explains all export formats available from LucidChart, what
data each format preserves, and which format to choose for each use case.

---

## Summary recommendation

| Use case | Recommended format |
|----------|--------------------|
| **Automated Miro upload (best fidelity)** | **Visio (.vsdx)** ⭐ |
| Cloud / network diagrams (VPC, AWS, GCP, Azure) | **Visio (.vsdx)** or CSV |
| Flowcharts with nested swimlanes | **Visio (.vsdx)** or CSV |
| Flat diagrams (no containers) | CSV, JSON, or Visio — equivalent |
| Exact class names needed for custom shape mapping | **JSON** |
| Round-trip to Microsoft Visio or draw.io | **Visio (.vsdx)** |
| Static reference copy (non-editable) | **SVG** or **PDF** |

**Bottom line:** Export as **Visio (.vsdx)** for all Miro uploads.  VSDX
preserves original layout coordinates, containment, styling, and embedded
icons — no auto-layout approximation needed.  Use CSV as a fallback when
a VSDX export is unavailable.

---

## Format 1 — CSV  ✅ Recommended

**How to export:** File → Export → CSV

### What is preserved

| Field | CSV column | Notes |
|-------|-----------|-------|
| Shape ID | `Id` | Unique identifier for each element |
| Shape name / type | `Name` | e.g. `Block`, `Region`, `SVGPathBlock2` |
| Shape library | `Shape Library` | e.g. `AWS 2021`, `GCP 2018`, `Azure 2021` |
| Page / tab | `Page ID` | Numeric ID matching a `Name == "Page"` row |
| Parent container | `Contained By` | Pipe-separated ancestor chain (innermost last) |
| Group membership | `Group` | Shared group ID for grouped shapes |
| Connector source | `Line Source` | Source shape ID |
| Connector target | `Line Destination` | Target shape ID |
| Source arrow style | `Source Arrow` | `none`, `arrow`, `openarrow`, `filled`, `diamond` |
| Target arrow style | `Destination Arrow` | Same values as Source Arrow |
| Text labels | `Text Area 1`, `Text Area 2`, … | Multiple text blocks per shape |
| Document title | `Name == "Document"`, `Text Area 1` | Top-level title row |

### Why CSV is preferred

The `Contained By` column encodes the full nesting hierarchy.  For a shape
inside Subnet → AZ → VPC → Region, the column value is:

```
region-id|vpc-id|az-id|subnet-id
```

The converter reads the last ID as the direct parent, reconstructs the full
tree, and lays out containers wrapping their children — exactly as they appear
in the original diagram.

**Example containment tree from CSV:**

```
Region (us-east-1)
  └── VPC (10.0.0.0/16)
        ├── AZ (us-east-1a)
        │     ├── Subnet (10.0.1.0/24) — public
        │     │     ├── EC2 instance
        │     │     └── Load Balancer
        │     └── Subnet (10.0.2.0/24) — private
        │           └── RDS database
        └── AZ (us-east-1b)
              └── Subnet (10.0.3.0/24)
                    └── EC2 instance
```

This nesting becomes a proper Miro layout with containers wrapping children.

### CSV limitations

- No pixel coordinates (layout is auto-generated)
- No shape-level styling metadata (fill colours, border widths from LucidChart)
- Exact internal class names are not available (e.g. `DefaultSquareBlock`)

### Multi-page (tab) support

Each row with `Name == "Page"` defines a tab.  Items reference their page
via the `Page ID` column.  The converter creates one Miro Frame per page.

---

## Format 2 — JSON

**How to export:** File → Export → JSON

### What is preserved

| Field | JSON path | Notes |
|-------|----------|-------|
| Document title | `title` | Top-level field |
| Page ID | `pages[].id` | |
| Page title | `pages[].title` | |
| Shape ID | `pages[].items.shapes[].id` | |
| Shape class | `pages[].items.shapes[].class` | Exact internal class name |
| Text labels | `pages[].items.shapes[].textAreas[].text` | Array of text blocks |
| Group membership | `pages[].items.groups[].members[]` | Shape IDs in group |
| Connector source | `pages[].items.lines[].endpoint1.connectedTo` | |
| Connector target | `pages[].items.lines[].endpoint2.connectedTo` | |
| Connector arrow | `pages[].items.lines[].endpoint1.style` | `none`, `arrow`, `openarrow` |

### Why JSON is limited

The JSON export **omits containment hierarchy entirely**.  Every shape on a
page is a flat peer — there is no parent/child relationship encoded.  The
converter falls back to grouping shapes by their `group_id` and arranging
groups in a grid.

For cloud architecture diagrams, this means a VPC containing three subnets
each containing several EC2 instances will be rendered as ~15 flat shapes
in a grid instead of the correct nested layout.

### When JSON is acceptable

- The diagram is intentionally flat (shapes connected by arrows, no containers)
- A CSV export is unavailable for that specific diagram
- You need the exact internal class name for custom shape mapping

### JSON-only advantages

| Feature | JSON | CSV |
|---------|------|-----|
| Exact class name (`DefaultSquareBlock`, `SVGPathBlock2`) | ✅ | ❌ |
| Structured multi-text-area array | ✅ | partial |
| Containment hierarchy | ❌ | ✅ |
| Shape Library metadata | ❌ | ✅ |

---

## Format 3 — Visio (.vsdx) ⭐ Recommended for Miro upload

**How to export:** File → Export → Visio (`.vsdx`)

### What is preserved

- Shapes, connectors, labels  
- Container/lane structure (preserved as Visio groups)  
- Multi-page tabs (each page → a Visio page)  
- **Pixel-accurate layout** — original `x/y/width/height` from LucidChart  
- Fill colour, border colour, and font styling per shape  
- Custom icons embedded as images inside the archive  

### Why VSDX is recommended

| Advantage | Details |
|-----------|---------|
| **Original layout preserved** | Visio geometry is converted at 96 dpi — the Miro board matches your LucidChart diagram exactly, no auto-layout approximation |
| **No coordinate guessing** | CSV/JSON carry no pixel positions; VSDX does |
| **Embedded icons** | Cloud-provider and custom icons are extracted automatically; a template icon map is generated for you |
| **Containment + styling** | Group nesting and per-shape fill/border colours are read directly from the Visio XML |
| **Fully automatable** | `lucid2miro.py` parses VSDX and uploads via REST API in one command |

### How to use VSDX with lucid2miro

```bash
# Offline: convert to Miro JSON
python lucid2miro.py diagram.vsdx

# Offline: write a Visio file for Miro "Import from Visio"
python lucid2miro.py diagram.json --output-format vsdx

# Validate page/tab and object counts before and after writing
python lucid2miro.py diagram.json --output-format vsdx --debug-counts

# Direct upload to a new Miro board
export MIRO_TOKEN=your_token_here
python lucid2miro.py diagram.vsdx --upload

# Batch convert all VSDX files in a folder
python lucid2miro.py ./exports/ --format vsdx --upload

# Preview without uploading
python lucid2miro.py diagram.vsdx --upload --dry-run --summary
```

### Manual Miro Visio import (UI only — not automated)

1. Export from LucidChart: File → Export → Visio (`.vsdx`)
2. In Miro: **+** → **Upload from computer** → select the `.vsdx` file
3. Each non-empty Visio page becomes a Miro Frame

> **Prefer the REST API path** (`lucid2miro --upload`) over the manual UI
> import — it supports batch processing, custom naming, icon mapping, and
> dry-run preview.

### Notes

- Some LucidChart-specific shape types may render as generic rectangles in
  Miro (no native Miro equivalent); use `--icon-map` to restore cloud icons
- Connectors are preserved; complex polyline routing is straightened to
  straight connectors in Miro
- Custom icons are extracted to `<stem>_icons/`; update
  `<stem>_icon_map.json` with hosted URLs and pass `--icon-map` to include them
- Generated `.vsdx` output skips empty pages; `--debug-counts` can be used to
  confirm how many pages/tabs and objects were read from the source and written
  to the output file
- `--debug-counts` also prints a per-page breakdown with page titles and
  counts for items, lines, and icon-shapes, plus whether a page was skipped
  on output because it was empty

---

## Format 4 — SVG

**How to export:** File → Export → SVG  
*(Export one page at a time — LucidChart exports the current page only)*

### What is preserved

- Full visual fidelity (pixel-perfect rendering)  
- Custom icons and shapes preserved as vector paths  
- Fonts, colours, shadows  

### Limitations

- **Not editable in Miro** — imported as a static vector image  
- One export per page (multi-tab requires multiple exports)  
- Shapes cannot be selected, moved, or connected in Miro  

### Use case

Best for static reference boards where the goal is visual documentation,
not collaborative editing.

### Multi-page SVG workflow

```
For each LucidChart tab:
  1. Navigate to that tab
  2. File → Export → SVG → download
  3. In Miro: + → Upload → select SVG → place in a new Frame
  4. Rename the Frame to match the original tab name
```

---

## Format 5 — PDF

**How to export:** File → Print / Export → PDF

### What is preserved

- Full visual fidelity (all pages in one file)  
- Custom icons and all styling  
- Multi-page as PDF pages  

### Limitations

- **Not editable** — Miro imports PDFs as static image pages  
- No shape, connector, or text element isolation  

### Use case

Read-only reference or documentation boards.  Not suitable for
collaborative diagram editing in Miro.

---

## Format comparison table

| Feature | Visio (.vsdx) ⭐ | CSV | JSON | SVG | PDF |
|---------|-----------------|-----|------|-----|-----|
| **Recommended for Miro upload** | ⭐ Yes | Fallback | Flat only | ❌ | ❌ |
| Containment hierarchy | ✅ | ✅ | ❌ | — | — |
| Nested layout in Miro | ✅ | ✅ auto | ❌ flat | — | — |
| Original layout preserved | ✅ pixel-accurate | ❌ auto | ❌ auto | ✅ | ✅ |
| Per-shape styling (fill/border) | ✅ | ❌ | ❌ | ✅ | ✅ |
| Multi-tab support | ✅ | ✅ | ✅ | ❌ one page | ✅ |
| Editable shapes in Miro | ✅ | ✅ | ✅ | ❌ | ❌ |
| Custom icons (embedded) | ✅ extracted | ❌ | ❌ | ✅ | ✅ |
| Shape Library metadata | partial | ✅ | ❌ | — | — |
| Exact internal class names | — | ❌ | ✅ | — | — |
| Automatable (REST API upload) | ✅ | ✅ | ✅ | ❌ | ❌ |
| Zero-dependency tool support | ✅ | ✅ | ✅ | ❌ | ❌ |

---

## Miro import method comparison: File Upload vs REST API

This table compares importing into Miro via the **Miro UI file upload** (manual,
browser-based) versus using **`lucid2miro --upload`** (REST API, automated).

| Capability | Miro UI file upload | `lucid2miro --upload` (REST API) |
|------------|--------------------|---------------------------------|
| Supported input formats | `.vsdx` only | `.vsdx`, `.csv`, `.json` |
| Automation / scripting | ❌ manual | ✅ fully automated |
| CI/CD integration | ❌ | ✅ |
| Batch import (multiple files) | ❌ one at a time | ✅ `--format vsdx` on a directory |
| Original Visio layout | ✅ (`.vsdx`) | ✅ (`.vsdx`) |
| Auto-layout for CSV/JSON | — | ✅ containment tree (CSV) / grid (JSON) |
| Custom board naming | ❌ uses filename | ✅ `--board-name` |
| Frame prefix / suffix | ❌ | ✅ `--frame-prefix`, `--frame-suffix` |
| Custom icon mapping | ❌ | ✅ `--icon-map` |
| Page filtering | ❌ all pages | ✅ `--pages` |
| Upload to existing board | ❌ creates new | ✅ `--board-id` |
| Dry-run / preview | ❌ | ✅ `--dry-run --summary` |
| Count validation | ❌ | ✅ `--debug-counts` for offline output |
| Editable shapes in Miro | ✅ | ✅ |
| Miro token required | ❌ (browser auth) | ✅ `MIRO_TOKEN` env var or `--token` |
| No install required | ✅ browser | ✅ single Python file |

**When to use each:**

- **Miro UI upload** — one-off import of a single VSDX file; no token setup needed.
- **`lucid2miro --upload`** — any scenario requiring automation, batching, naming
  control, icon mapping, or CI/CD integration.  Also the only path for CSV and JSON
  inputs.

---

## How to export from LucidChart

### CSV export

1. Open your diagram in LucidChart.
2. **File** → **Export** → **CSV** → **Download**.
3. The exported file contains all pages in a single flat CSV.

### JSON export

1. Open your diagram in LucidChart.
2. **File** → **Export** → **JSON** → **Download**.
3. The exported file contains a JSON object with `pages[]` array.

### Visio export

1. Open your diagram in LucidChart.
2. **File** → **Export** → **Visio (.vsdx)** → **Download**.
3. Each LucidChart page becomes a Visio page.

### SVG export (per page)

1. Navigate to the page you want to export.
2. **File** → **Export** → **SVG** → **Download**.
3. Repeat for each page.

---

## Icons and custom images

CSV and JSON exports **omit image data**.  Visio (.vsdx) embeds icon images
inside the ZIP archive; the converter extracts them automatically (see below).
SVG and PDF always carry full visual content but are not editable in Miro.
Icons from cloud provider shape libraries (AWS, GCP, Azure) and custom SVG
icons appear as empty `image` placeholders in the converter output.

### Resolving icons with the REST API upload mode

Supply an icon map file (see `docs/MIRO_AUTH.md § Custom icons`) that maps
shape IDs or shape names to publicly accessible image URLs:

```json
{
  "by_name": {
    "AmazonEC2":        "https://icon.horse/icon/aws.amazon.com",
    "AWSLambda":        "https://cdn.example.com/icons/lambda.png",
    "GoogleComputeEngine": "https://cdn.example.com/icons/gce.png"
  },
  "default": "https://cdn.example.com/icons/cloud-placeholder.svg"
}
```

### Finding shape names for icon mapping

1. Run a dry-run upload to see all shape names and IDs:
   ```bash
   python lucid2miro.py diagram.csv --upload --dry-run --summary
   ```
2. Look for `[icon skipped — no URL]` lines in the output — they include the
   Lucidchart shape ID and shape name.
3. Add those to your icon map JSON.

---

## Auto-layout behaviour

**Neither CSV nor JSON exports carry pixel coordinates.**  The converter
auto-assigns positions:

### CSV layout (containment tree)

1. Build tree from `Contained By` column.
2. Size leaf nodes with defaults (160×80 px shapes, 80×80 px icons, 200×40 px text).
3. Size container nodes bottom-up to wrap their children (padding: 40 px sides, 30 px label).
4. Arrange top-level items in a √n-column grid.
5. Propagate absolute positions down the tree.

Result: nested containers wrap their children, matching the logical structure
of the original diagram even though exact positions differ.

### JSON layout (group clustering)

1. Cluster items by `group_id`.
2. Arrange each cluster horizontally.
3. Arrange clusters in a √n-column grid with wider gaps between clusters.

Result: flat grid.  No nesting, regardless of original diagram complexity.

### Adjusting layout scale

Use `--scale N` to uniformly scale all coordinates:

```bash
python lucid2miro.py diagram.csv --upload --scale 1.5   # 50% larger
python lucid2miro.py diagram.csv --upload --scale 0.75  # 25% smaller
```
