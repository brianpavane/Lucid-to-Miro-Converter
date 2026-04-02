# Changelog

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
