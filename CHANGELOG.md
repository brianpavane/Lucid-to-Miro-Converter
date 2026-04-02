# Changelog

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
