# Changelog

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
