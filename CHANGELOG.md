# Changelog

## [1.13.0] — 2026-04-02

### Added

- **`Line.start_x / start_y / end_x / end_y`** (`model.py`) — optional pixel
  coordinates for connectors whose endpoints are not attached to a shape ID.
  Used by the VSDX parser for position-based connectors and honoured by both
  the Miro JSON converter and the VSDX writer.

- **Position-based connector parsing** (`vsdx_parser.py`) — Lucidchart VSDX
  often encodes connectors as ordinary `Shape` elements carrying
  `BeginX`/`BeginY`/`EndX`/`EndY` cells rather than `<Connects>` topology.
  These are now detected and parsed as `Line` objects with `start_x/y/end_x/y`
  pixel coordinates (Y-axis inverted from Visio inches).

- **Connector shape detection broadened** (`vsdx_parser.py`,
  `_collect_connector_ids()`) — shapes that carry `BeginX` or `EndX` cells are
  now identified as connectors and excluded from the `Item` list even when
  absent from `<Connects>`.

- **Richer OPC package** (`vsdx_writer.py`) — generated `.vsdx` files now
  include the additional parts present in native Lucid/Visio output:
  - `docProps/app.xml` and `docProps/core.xml`
  - `visio/windows.xml` with viewport metadata
  - Expanded `visio/document.xml` with `DocumentSettings`
  - Full `PageSheet` metadata (margins, scale, orientation, snap settings)
    embedded inline in `visio/pages/pages.xml` per page

- **Floating connector endpoints in writer** (`vsdx_writer.py`,
  `_connector_xml()`) — when a `Line` has `start_x/y` or `end_x/y` set and no
  resolvable shape ID, the writer uses the pixel coordinates (converted back to
  Visio inches with Y inversion) instead of fixed default positions.

- **Floating connector endpoints in Miro converter** (`converter/miro.py`,
  `_build_line_widget()`) — same fallback: `line.start_x/y` and `line.end_x/y`
  are used when shape IDs are unresolvable.

### Changed

- `_parse_connectors()` now receives `page_height` to correctly invert Y for
  position-based connector coordinates
- `_pages_xml()` now receives pre-computed `page_sizes` and embeds per-page
  `PageSheet` cells directly in `pages.xml`
- Page size computation refactored into a single pre-pass before ZIP assembly
- Version bump to 1.13.0

### Security

- Pre-release scan performed (`/shannon` skill unavailable; manual review conducted)
- **No new attack surface:** all changes are XML parsing and string formatting;
  no subprocess, exec, eval, or external network calls
- Connector cell values parsed via `float()` inside `try/except (TypeError, ValueError)`
- All checks passed (99 tests)

## [1.12.0] — 2026-04-02

### Changed

- **VSDX writer — improved Miro/Visio compatibility:**
  - Geometry cells now written in dual form: `V="..."` attribute **and**
    element text content (e.g. `<PinX V="3.95">3.95</PinX>`) for maximum
    consumer compatibility
  - Dual form applied to: `PageWidth`, `PageHeight`, `PinX`, `PinY`,
    `Width`, `Height`, `LocPinX`, `LocPinY`, connector geometry, and arrow cells
  - Shape elements now include direct `Cell` entries for all key transform
    values in addition to the `<XForm>` block
  - Each shape now includes an explicit rectangle `<Section N="Geometry">`
    (`MoveTo` + four `LineTo` rows) so shapes have visible geometry for all
    Visio consumers, including Miro's native Import from Visio flow
  - Inline `lucid2miro.py` Section 5C updated to match
- 1 new test; 99 total

### Security

- Pre-release scan performed (`/shannon` skill unavailable; manual review conducted)
- **No new attack surface:** all changes are string formatting within the
  existing ZIP/XML writer; no subprocess, exec, eval, or external calls
- All checks passed

## [1.11.0] — 2026-04-02

### Changed

- Version bump to 1.11.0

### Security

- Pre-release scan performed (`/shannon` skill unavailable; manual review conducted)
- All checks passed (98 tests)

## [1.10.0] — 2026-04-02

### Changed

- VSDX writer now writes key geometry values in both forms expected by Visio
  consumers:
  - `V="..."` attributes
  - element text content, e.g. `<PinX V="3.95">3.95</PinX>`
- This dual-form output is now applied to:
  - page bounds (`PageWidth`, `PageHeight`)
  - shape geometry (`PinX`, `PinY`, `Width`, `Height`, `LocPinX`, `LocPinY`)
  - connector geometry and arrow cells
- Generated shape elements now also include:
  - direct singleton `Cell` entries for key transform values
  - a simple rectangle `Geometry` section (`MoveTo` + `LineTo` rows) so
    shapes have explicit visible geometry for Visio consumers
- Generated VSDX packages now also include richer document-level parts that
  better match native Lucid/Visio output:
  - `visio/windows.xml`
  - `docProps/app.xml`
  - `docProps/core.xml`
  - expanded `visio/document.xml` settings
  - page-level metadata in `visio/pages/pages.xml`
- Intended to improve compatibility with Miro's native **Import from Visio**
  flow in cases where generated `.vsdx` files previously imported as blank
- Native `.vsdx -> .vsdx` conversion now uses a true passthrough path when no
  transformations are requested (`--pages`, `--title`, `--scale` absent), so
  the output preserves the original Lucid file byte-for-byte
- Native Lucid connector-like shapes with `BeginX`/`EndX` cells are now parsed
  as `Line` objects instead of being misclassified as generic items
- Documentation updated with VSDX import compatibility notes and retest guidance
- Version bump to 1.10.0

### Security

- Pre-release scan performed (`/shannon` skill unavailable; manual review conducted)
- All checks passed (98 tests)

## [1.9.0] — 2026-04-02

### Changed

- `vsdx_writer.py`: `_page_xml()` now accepts and writes both `PageWidth` and
  `PageHeight` in `<PageSheet><PageProps>`, providing full page bounds to
  consumers (previously only `PageHeight` was written)
- `lucid2miro.py`: standalone VSDX writer now uses the same page-bounds logic
  and no longer fails on missing `DPI` in the single-file path
- `lucid2miro.py`: JSON/CSV → VSDX standalone conversion now correctly calls
  `_layout_page()` in the single-file CLI path
- New CLI flag: `--debug-counts` prints page/tab and object counts from parsed
  input, then re-opens the written output and prints the resulting counts
- `--debug-counts` now includes a per-page breakdown with page titles plus
  item, line, and icon counts, making empty-page skips visible in the CLI
- Documentation updated to clarify that generated `.vsdx` output skips empty
  pages, and that Miro imports each non-empty Visio page as a Frame
- Version bump to 1.9.0

### Security

- Pre-release scan performed (`/shannon` skill unavailable; manual review conducted)
- All checks passed (98 tests)

## [1.8.0] — 2026-04-02

### Changed

- Version bump (minor increment)
- No functional changes

### Security

- Pre-release scan performed (`/shannon` skill unavailable; manual review conducted)
- All checks passed

## [1.7.0] — 2026-04-02

### Added

- **VSDX writer — `--output-format vsdx`** — converts any LucidChart export
  (`.vsdx`, `.csv`, `.json`) to a `.vsdx` Visio file that can be imported
  into Miro via **"Import from Visio"** with no REST API or token required:
  ```bash
  python lucid2miro.py diagram.vsdx --output-format vsdx  # layout preserved
  python lucid2miro.py diagram.csv  --output-format vsdx  # auto-layout → VSDX
  python lucid2miro.py diagram.json --output-format vsdx  # auto-layout → VSDX
  python lucid2miro.py ./exports/ --format csv --output-format vsdx --output-dir ./out/
  ```
  - Produces a valid OPC/ZIP archive with all required parts
    (`[Content_Types].xml`, `_rels/`, `visio/document.xml`,
    `visio/pages/pages.xml`, `visio/pages/page{n}.xml`)
  - Each LucidChart page → a Visio page (imported as a Miro frame)
  - Geometry written in `<XForm>` with element-name cells so the Visio
    schema and the round-trip parser agree on coordinate interpretation
  - `<PageSheet><PageProps><PageHeight>` written per page so Y-axis
    inversion is correct on re-import
  - Connector shapes written as `Type="Edge"` with `<Connects>` topology
  - Per-shape fill and border colours preserved in `Cell/@N` attributes
  - Text labels preserved in `<Text>` child elements
  - Empty pages (no items, no lines) excluded from the output archive

- **`lucid_to_miro/converter/vsdx_writer.py`** (modular package):
  - `write_vsdx(doc, dest, has_containment, scale)` — public API
  - Runs auto-layout (CSV/JSON) or skips it (VSDX passthrough)
  - `dest` accepts `str`, `Path`, or a writable binary `IO` object

- **12 new tests** (`TestVsdxWriter`) covering ZIP validity, OPC members,
  multi-page, page titles, coordinate round-trip (write → parse → compare),
  text content, connectors with `<Connect>` elements, CSV layout integration,
  scale factor, file-path output, and empty-page exclusion (97 total)

### Changed

- CLI `--output-format json|vsdx` flag added (default: `json`); controls
  whether offline output is a Miro JSON file or a Visio `.vsdx` file
- `_convert_file()` branches on `output_format`; VSDX path calls `write_vsdx()`
- Single-file mode: when `--output-format vsdx` and input is already `.vsdx`,
  output is written as `<stem>_converted.vsdx` to avoid overwriting the source
- Batch mode: `--output-format vsdx` produces `.vsdx` output files
- CLI epilog updated with VSDX output examples
- `--pretty` flag described as JSON-only in help text
- `lucid_to_miro/converter/__init__.py` now exports `write_vsdx`

### Security

- Pre-release scan performed (`/shannon` skill unavailable; manual review conducted)
- **No new attack surface:** writer uses `zipfile.ZipFile` write-only +
  string formatting; no subprocess, no exec, no eval, no external calls
- Output filenames are derived from `page.title` values which are XML-escaped
  with `_esc()` before inclusion in the archive
- All other checks passed

## [1.6.0] — 2026-04-02

### Changed

- **VSDX now the recommended input format** — documentation updated throughout
  to recommend Visio (`.vsdx`) export from LucidChart as the primary format for
  all Miro uploads; CSV retained as the recommended fallback
- **`docs/LUCIDCHART_FORMATS.md`** restructured:
  - Summary recommendation table updated: VSDX promoted to top recommendation
    with ⭐ marker; CSV noted as fallback
  - Format 3 (Visio) section expanded with "Why VSDX is recommended" table,
    full CLI usage examples, and comparison vs manual Miro UI import
  - Format comparison table reordered: VSDX column first
  - **New section: "Miro import method comparison: File Upload vs REST API"** —
    full capability table comparing Miro UI drag-and-drop import vs
    `lucid2miro --upload` across 15 dimensions (automation, batch, naming,
    icon mapping, dry-run, supported formats, etc.)
- **README** updated:
  - Supported input formats table now lists `.vsdx` first with ⭐ recommendation
  - Quick start examples lead with VSDX
  - Usage synopsis updated to `vsdx|csv|json`
  - "CSV vs JSON" section replaced by "Which format to use" covering all three
    formats with a unified capability table
  - Auto-layout section clarifies VSDX bypasses auto-layout entirely
  - Features list updated; test count corrected to 85
  - LucidChart export formats summary updated; project structure shows
    `vsdx_parser.py`

### Security

- Pre-release scan performed (`/shannon` skill unavailable; manual review conducted)
- No new code changes; documentation-only release
- All other checks passed

## [1.5.0] — 2026-04-02

### Added

- **Visio (.vsdx) input format** — third supported input format alongside CSV and JSON:
  - `python lucid2miro.py diagram.vsdx`
  - `python lucid2miro.py diagram.vsdx --upload`
  - `python lucid2miro.py ./exports/ --format vsdx --output-dir ./miro/`
  - Parsed using stdlib only (`zipfile` + `xml.etree.ElementTree`; zero new dependencies)

- **Original layout preservation** — VSDX exports carry Visio geometry (`PinX`, `PinY`,
  `Width`, `Height` in inches).  The parser converts these to Miro pixels at 96 dpi and
  sets them on each `Item`.  The auto-layout engine is skipped for VSDX input
  (`Document.has_coordinates = True`), so the Miro board matches the original diagram layout.

- **Embedded icon extraction** — shapes with `Type="Foreign"` (cloud-provider icons, custom
  SVG/PNG icons) have their raw image bytes stored in `item.image_data`.  On conversion or
  upload, icons are automatically written to `<stem>_icons/` and a template
  `<stem>_icon_map.json` is generated.  Update the map with hosted URLs and pass
  `--icon-map <stem>_icon_map.json` to include icons in the Miro board.

- **Richer per-shape styling** — fill colour and border colour are read directly from Visio
  Cell values (`FillForegnd`, `LineColor`) and carried through to Miro widgets.

- **Container detection from Visio groups** — group shapes that contain child shapes are
  automatically treated as containers (rendered with light fill + distinct border).

- **`lucid_to_miro/parser/vsdx_parser.py`** (modular package):
  - `parse_vsdx(source)` — returns `Document` with `has_coordinates=True`
  - `extract_media(doc, output_dir)` — writes embedded images, returns `{item_id: Path}`

- **`lucid_to_miro/converter/layout.frame_from_items()`** — computes frame dimensions
  from pre-set item coordinates (used for VSDX, replaces auto-layout for that path)

- **13 new tests** covering coordinate conversion, connector routing, master name lookup,
  icon extraction, layout-skip guarantee, and end-to-end conversion (85 total)

### Changed

- `Document` dataclass gains `has_coordinates: bool = False`
- `Item` dataclass gains `image_data: Optional[bytes] = None` (repr=False)
- `--format` CLI flag now accepts `csv | json | vsdx`
- `_parse_file()` dispatches `.vsdx` to `parse_vsdx()`
- `convert()` and `upload_document()` check `doc.has_coordinates` to skip layout

### Security

- Pre-release scan performed (`/shannon` skill unavailable; manual review conducted)
- **MEDIUM fixed:** `extract_media()` and `_vextract_media()` now sanitise `item.id`
  with `re.sub(r"[^\w\-]", "_", item.id)` before constructing the output filename,
  preventing path traversal if a crafted VSDX encodes `../` sequences in a shape ID
- **False positive:** scanner flagged `token="your_pat_here"` in `miro_client.py`
  docstring — this is an example string in documentation, not a hardcoded credential
- **No new attack surface:** VSDX parsing uses `zipfile.ZipFile` read-only +
  `xml.etree.ElementTree`; no subprocess, no exec, no eval, no external network calls
- **Note:** Python's `xml.etree.ElementTree` does not resolve external entities and
  is not vulnerable to billion-laughs attacks.  For untrusted VSDX files from unknown
  sources, additional sandboxing is recommended.

## [1.4.0] — 2026-04-02

### Added

- **REST API upload mode (`--upload`)** — upload a Lucidchart diagram directly
  to a live Miro board without generating an intermediate JSON file.
  - `--token TOKEN` — Miro Personal Access Token (or `MIRO_TOKEN` env var)
  - `--team-id TEAM_ID` — target a specific Miro workspace for new boards
  - `--board-id BOARD_ID` — append content to an existing board
  - `--board-name NAME` — override the Miro board title
  - `--frame-prefix PREFIX` / `--frame-suffix SUFFIX` — customize frame names
    (e.g. `--frame-prefix "Sprint 3: "` → `"Sprint 3: Production VPC"`)
  - `--icon-map FILE` — JSON file mapping Lucidchart shape IDs/names to image
    URLs, enabling custom icon restoration
  - `--access private|view|comment|edit` — board sharing policy (default: private)
  - `--dry-run` — simulate upload, print what would be created, no API calls
  - Batch upload: pass a directory with `--format csv|json --upload` to upload
    all matching files, each to its own new board
  - Automatic retry on HTTP 429 (rate limit) with `Retry-After` respected, and
    exponential back-off on transient 5xx errors (up to 3 attempts)

- **`lucid_to_miro/api/` package** (modular counterpart of the inlined code):
  - `miro_client.py` — zero-dependency `MiroClient` with `get()` / `post()`
  - `uploader.py` — `upload_document()` function; `load_icon_map()` helper

- **`docs/MIRO_AUTH.md`** — comprehensive authentication guide covering:
  - Personal Access Token (PAT) setup step-by-step
  - OAuth 2.0 flow for app integrations
  - CI/CD setup (GitHub Actions, GitLab CI)
  - All naming options (board name, frame prefix/suffix)
  - Custom icon map format and workflow
  - Troubleshooting for HTTP 401, 403, 429

- **`docs/LUCIDCHART_FORMATS.md`** — full export format comparison covering:
  - CSV (recommended) — containment hierarchy, multi-tab, auto-layout
  - JSON — flat/group-based, when acceptable
  - Visio (.vsdx) — round-trip to Miro via native Visio import
  - SVG / PDF — static reference boards
  - Icon handling across all formats

### Changed

- CLI description updated to document both offline and upload modes
- `--output-dir` flag description now notes it is offline-only
- `--pretty` flag description notes it is offline-only
- README restructured: Quick start section, separate offline/upload examples,
  authentication and format links to new docs

### Security

- Pre-release scan to be performed with `/shannon` before merge to main
- **No new attack surface:** upload mode uses `urllib.request` (stdlib only);
  no subprocess, no shell interpolation, no eval, no unsafe deserialization
- Token is never written to disk or included in output files
- `--dry-run` allows full validation without transmitting credentials to Miro

## [1.3.0] — 2026-04-01

### Added
- **`--clean-names` flag** — when `--output-dir` points to a different directory than the input, outputs are named `<stem>.json` instead of `<stem>.miro.json` (e.g. `diagram.csv` → `diagram.json`)
  - Batch mode: requires `--output-dir` to differ from input directory; exits with an error if they are the same to prevent source files being overwritten
  - Single-file mode: exits with an error if `--clean-names` would overwrite a `.json` source file; safe when `-o` is specified explicitly
- **README — CSV vs JSON recommendation** section: explains why CSV is the preferred input format (containment hierarchy → proper nested layout) and when JSON is acceptable (flat diagrams)
- 10 new tests for `--clean-names` covering batch/single-file modes, happy paths, and all safety guards (72 total)

### Security
- Pre-release scan performed (`/shannon` AgentShield invocation failed — fallback manual review; failure flagged to user)
- **MEDIUM fixed:** Batch output path escape check replaced `str.startswith()` string comparison with `Path.relative_to()` (raises `ValueError` on escape), making the guard correct under case-insensitive filesystems and symlink scenarios
- All other checks passed

## [1.2.0] — 2026-04-01

### Added
- **Single-file distribution** — `lucid2miro.py` is now fully self-contained; all six previously separate modules (model, shape map, layout engine, CSV parser, JSON parser, Miro converter) are inlined in dependency order under clearly labelled section headers. No package directory required for execution.
- `--version` flag added to CLI (`python lucid2miro.py --version`)

### Retrieving the single file
```bash
# macOS / Linux
curl -o lucid2miro.py https://raw.githubusercontent.com/brianpavane/Lucid-to-Miro-Converter/main/lucid2miro.py

# Windows (PowerShell)
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/brianpavane/Lucid-to-Miro-Converter/main/lucid2miro.py" -OutFile "lucid2miro.py"
```

### Security
- Pre-release scan performed (`/shannon` skill unavailable; manual review conducted)
- **MEDIUM fixed:** Bare `except` in CSV page-sort key narrowed to `except (ValueError, TypeError)` to avoid swallowing `KeyboardInterrupt`/`SystemExit`
- **MEDIUM acknowledged:** Single-file `--output` path is resolved via `Path.resolve()` and documented; equivalent to batch-mode behaviour
- All other checks passed (no subprocess, no unsafe deserialization, no hardcoded secrets, no ReDoS risk)

## [1.1.0] — 2026-04-01

### Added
- **Batch / bulk conversion mode** — pass a directory as `input` to convert all files of a given format at once
  - `--format csv|json` selects which file type to glob (required in batch mode)
  - `--output-dir DIR` sets the destination directory (created automatically if absent, including nested paths; defaults to input directory)
  - Output filename = input stem + `.miro.json` (e.g. `diagram.csv` → `diagram.miro.json`)
  - All existing flags (`--scale`, `--pretty`, `--summary`, `--title`) apply to every file in the batch
  - Per-file `✓`/`✗` progress lines; final tally printed on completion
  - Non-zero exit code on any failure so CI/scripts detect partial failures
  - 11 new tests (62 total)

### Security
- Pre-release scan performed (`/shannon` skill unavailable; manual review conducted)
- **HIGH fixed:** Batch output paths now resolved via `Path.resolve()` and asserted to remain inside `output_dir`, preventing symlink-based traversal
- All other checks passed

## [1.0.0] — 2026-04-01

### Changed (from Node.js prototype)
- Rewritten in Python 3.8+ — zero third-party dependencies, works on macOS, Windows, and Linux

### Input formats
- Replaced `.lucid` ZIP parsing with native Lucidchart exports:
  - `.json` (File → Export → JSON) — parses `pages[].items.{shapes,lines,groups}`
  - `.csv` (File → Export → CSV) — parses all columns including `Contained By`, `Group`, `Line Source/Destination`, `Text Area 1-N`

### Features
- Multi-tab support: each Lucidchart page → a Miro frame, laid out side-by-side with 150 px gaps
- Auto-layout engine (neither export format carries coordinates):
  - CSV path: reconstructs containment tree from "Contained By" column; bottom-up sizing; top-level grid
  - JSON path: clusters group-members together; sqrt(n)-column grid of clusters
- 50+ shape name → Miro shape type mappings (basic, flowchart, AWS/GCP/Azure containers, arrows, callouts)
- SVGPathBlock2 / icon shapes → Miro `image` widgets
- MinimalTextBlock / text-only shapes → Miro `text` widgets
- Connectors with labels, source/destination arrow styles
- Containers (Region, VPC, Subnet, AZ, …) rendered with light fill + distinct border + top-aligned label
- `--pages` flag to export a subset of pages by title or index
- `--scale` flag for uniform coordinate scaling
- 51 unit and integration tests

### Security
- Pre-release security scan performed (manual review; `/shannon` skill not available in environment)
- **MEDIUM fixed:** Output path is now resolved to an absolute path via `Path.resolve()` before write, preventing symlink traversal and ambiguous `..` segments (`lucid2miro.py`)
- All other checks passed: no command injection, no unsafe deserialization, no hardcoded secrets, no subprocess calls, no external network requests, no sensitive data in output
