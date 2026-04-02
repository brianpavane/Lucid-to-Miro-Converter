#!/usr/bin/env python3
"""
lucid2miro — Convert Lucidchart exports to Miro-importable JSON.

Supports:
  .json   Lucidchart JSON export  (File → Export → JSON)
  .csv    Lucidchart CSV export   (File → Export → CSV)

Usage:
  python lucid2miro.py <input> [options]
  python lucid2miro.py --help

Works on macOS, Windows, and Linux (Python 3.8+, no third-party dependencies).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lucid_to_miro.parser.csv_parser  import parse_csv
from lucid_to_miro.parser.json_parser import parse_json
from lucid_to_miro.converter.miro     import convert


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lucid2miro",
        description="Convert a Lucidchart .json or .csv export to Miro JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python lucid2miro.py diagram.json
  python lucid2miro.py diagram.csv -o board.json --pretty --summary
  python lucid2miro.py diagram.json -t "My Board" --scale 1.5
""",
    )
    p.add_argument("input",  help="Path to a .json or .csv Lucidchart export file")
    p.add_argument("-o", "--output",  metavar="FILE",
                   help="Output path (default: <input>.miro.json)")
    p.add_argument("-t", "--title",   metavar="TITLE",
                   help="Miro board title (default: document title from source)")
    p.add_argument("-s", "--scale",   metavar="N", type=float, default=1.0,
                   help="Uniform scale factor for all coordinates (default: 1.0)")
    p.add_argument("--pretty",  action="store_true",
                   help="Pretty-print the output JSON")
    p.add_argument("--summary", action="store_true",
                   help="Print a conversion summary to stdout")
    p.add_argument("--pages",   metavar="N[,N]",
                   help="Comma-separated list of page titles or 1-based indices to include "
                        "(default: all pages)")
    return p


def _filter_pages(doc, spec: str):
    """Keep only pages matching a comma-separated list of titles or 1-based indices."""
    wanted = {s.strip() for s in spec.split(",")}
    kept = []
    for i, page in enumerate(doc.pages, start=1):
        if str(i) in wanted or page.title in wanted:
            kept.append(page)
    doc.pages = kept


def main(argv=None):
    args = _build_parser().parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"Error: file not found — {input_path}")

    suffix = input_path.suffix.lower()
    if suffix not in (".json", ".csv"):
        sys.exit(f"Error: unsupported file type '{suffix}'. Use .json or .csv.")

    # ── Parse ────────────────────────────────────────────────────────────────
    try:
        if suffix == ".json":
            doc = parse_json(input_path)
            has_containment = False   # JSON export has no parent_id info
        else:
            doc = parse_csv(input_path)
            has_containment = True    # CSV export has "Contained By" column
    except Exception as exc:
        sys.exit(f"Error parsing {input_path.name}: {exc}")

    # ── Apply options ────────────────────────────────────────────────────────
    if args.title:
        doc.title = args.title

    if args.pages:
        _filter_pages(doc, args.pages)
        if not doc.pages:
            sys.exit("Error: --pages filter matched no pages.")

    # ── Convert ──────────────────────────────────────────────────────────────
    try:
        board = convert(doc, has_containment=has_containment, scale=args.scale)
    except Exception as exc:
        sys.exit(f"Error during conversion: {exc}")

    # ── Write output ─────────────────────────────────────────────────────────
    # Resolve to an absolute path so symlink traversal and relative ".." segments
    # are made explicit — the resolved path is what actually gets written.
    output_path = (Path(args.output) if args.output else input_path.with_suffix(".miro.json")).resolve()
    indent = 2 if args.pretty else None
    output_path.write_text(json.dumps(board, indent=indent, ensure_ascii=False), encoding="utf-8")

    # ── Summary ──────────────────────────────────────────────────────────────
    if args.summary:
        widgets  = board["board"]["widgets"]
        frames   = sum(1 for w in widgets if w["type"] == "frame")
        shapes   = sum(1 for w in widgets if w["type"] == "shape")
        texts    = sum(1 for w in widgets if w["type"] == "text")
        images   = sum(1 for w in widgets if w["type"] == "image")
        lines    = sum(1 for w in widgets if w["type"] == "line")
        skipped  = sum(1 for p in doc.pages if not p.items and not p.lines)

        print()
        print("Lucidchart → Miro conversion summary")
        print("─────────────────────────────────────")
        print(f"  Source  : {input_path}")
        print(f"  Format  : {'JSON' if suffix == '.json' else 'CSV'}")
        print(f"  Output  : {output_path}")
        print(f"  Pages   : {len(doc.pages)} total, {frames} exported as frames"
              + (f", {skipped} skipped (empty)" if skipped else ""))
        print(f"  Shapes  : {shapes}")
        print(f"  Text    : {texts}")
        print(f"  Images  : {images}")
        print(f"  Lines   : {lines}")
        print()
    else:
        print(f"Written → {output_path}")


if __name__ == "__main__":
    main()
