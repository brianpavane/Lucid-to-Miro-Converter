#!/usr/bin/env python3
"""
lucid2miro — Convert Lucidchart exports to Miro-importable JSON.

Single-file mode:
  python lucid2miro.py diagram.csv
  python lucid2miro.py diagram.json -o board.json --pretty --summary

Batch mode (pass a directory as input):
  python lucid2miro.py ./exports/ --format csv --output-dir ./miro/
  python lucid2miro.py ./exports/ --format json --output-dir ./miro/ --pretty

Supported formats: .csv  (File → Export → CSV)
                   .json (File → Export → JSON)

Works on macOS, Windows, and Linux (Python 3.8+, no third-party dependencies).
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from lucid_to_miro.parser.csv_parser  import parse_csv
from lucid_to_miro.parser.json_parser import parse_json
from lucid_to_miro.converter.miro     import convert


# ── Argument parser ───────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lucid2miro",
        description="Convert Lucidchart .json or .csv exports to Miro JSON.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Single-file examples:
  python lucid2miro.py diagram.csv
  python lucid2miro.py diagram.json -o board.json --pretty --summary
  python lucid2miro.py diagram.csv -t "My Board" --scale 1.5 --pages "HA,VPC"

Batch examples:
  python lucid2miro.py ./exports/ --format csv --output-dir ./miro/
  python lucid2miro.py ./exports/ --format json --output-dir ./miro/ --summary
""",
    )
    p.add_argument("input",
                   help="Path to a .json/.csv file  OR  a directory for batch mode")

    # ── Batch-specific ────────────────────────────────────────────────────────
    p.add_argument("--format", choices=["csv", "json"],
                   help="(Batch) Input format to look for: csv or json")
    p.add_argument("--output-dir", metavar="DIR",
                   help="(Batch) Directory to write converted files into")

    # ── Single-file & shared ──────────────────────────────────────────────────
    p.add_argument("-o", "--output", metavar="FILE",
                   help="(Single) Output file path (default: <input>.miro.json)")
    p.add_argument("-t", "--title", metavar="TITLE",
                   help="Miro board title (default: document title from source file)")
    p.add_argument("-s", "--scale", metavar="N", type=float, default=1.0,
                   help="Uniform scale factor for all coordinates (default: 1.0)")
    p.add_argument("--pretty",  action="store_true",
                   help="Pretty-print the output JSON")
    p.add_argument("--summary", action="store_true",
                   help="Print a conversion summary (per file in batch mode)")
    p.add_argument("--pages", metavar="N[,N]",
                   help="(Single) Comma-separated page titles or 1-based indices to include")
    return p


# ── Shared helpers ────────────────────────────────────────────────────────────

def _filter_pages(doc, spec: str) -> None:
    wanted = {s.strip() for s in spec.split(",")}
    doc.pages = [
        p for i, p in enumerate(doc.pages, start=1)
        if str(i) in wanted or p.title in wanted
    ]


def _parse_file(input_path: Path):
    """Parse a single .csv or .json file. Returns (doc, has_containment)."""
    suffix = input_path.suffix.lower()
    if suffix == ".csv":
        return parse_csv(input_path), True
    if suffix == ".json":
        return parse_json(input_path), False
    raise ValueError(f"Unsupported file type '{suffix}'. Use .json or .csv.")


def _convert_file(input_path: Path, output_path: Path, args) -> dict:
    """
    Parse, convert, and write one file.
    Returns a stats dict.  Raises on any error.
    """
    doc, has_containment = _parse_file(input_path)

    if getattr(args, "title", None):
        doc.title = args.title

    if getattr(args, "pages", None):
        _filter_pages(doc, args.pages)
        if not doc.pages:
            raise ValueError("--pages filter matched no pages")

    board = convert(doc, has_containment=has_containment, scale=args.scale)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    indent = 2 if args.pretty else None
    output_path.write_text(
        json.dumps(board, indent=indent, ensure_ascii=False), encoding="utf-8"
    )

    widgets = board["board"]["widgets"]
    return {
        "doc":    doc,
        "board":  board,
        "frames": sum(1 for w in widgets if w["type"] == "frame"),
        "shapes": sum(1 for w in widgets if w["type"] == "shape"),
        "texts":  sum(1 for w in widgets if w["type"] == "text"),
        "images": sum(1 for w in widgets if w["type"] == "image"),
        "lines":  sum(1 for w in widgets if w["type"] == "line"),
    }


def _print_summary(input_path: Path, output_path: Path, fmt: str, stats: dict) -> None:
    doc = stats["doc"]
    skipped = sum(1 for p in doc.pages if not p.items and not p.lines)
    print()
    print("Lucidchart → Miro conversion summary")
    print("─────────────────────────────────────")
    print(f"  Source  : {input_path}")
    print(f"  Format  : {fmt.upper()}")
    print(f"  Output  : {output_path}")
    print(f"  Pages   : {len(doc.pages)} total, {stats['frames']} exported as frames"
          + (f", {skipped} skipped (empty)" if skipped else ""))
    print(f"  Shapes  : {stats['shapes']}")
    print(f"  Text    : {stats['texts']}")
    print(f"  Images  : {stats['images']}")
    print(f"  Lines   : {stats['lines']}")
    print()


# ── Single-file mode ──────────────────────────────────────────────────────────

def _run_single(args) -> None:
    input_path = Path(args.input)

    suffix = input_path.suffix.lower()
    if suffix not in (".json", ".csv"):
        sys.exit(f"Error: unsupported file type '{suffix}'. Use .json or .csv.")

    output_path = (
        Path(args.output) if args.output else input_path.with_suffix(".miro.json")
    ).resolve()

    try:
        stats = _convert_file(input_path, output_path, args)
    except Exception as exc:
        sys.exit(f"Error: {exc}")

    if args.summary:
        _print_summary(input_path, output_path, suffix.lstrip("."), stats)
    else:
        print(f"Written → {output_path}")


# ── Batch mode ────────────────────────────────────────────────────────────────

def _run_batch(args) -> None:
    input_dir = Path(args.input)

    if not args.format:
        sys.exit("Error: --format csv|json is required in batch mode.")

    output_dir = Path(args.output_dir).resolve() if args.output_dir else input_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    glob_pattern = f"*.{args.format}"
    input_files  = sorted(input_dir.glob(glob_pattern))

    if not input_files:
        sys.exit(f"Error: no .{args.format} files found in {input_dir}")

    fmt          = args.format
    ok_count     = 0
    fail_count   = 0
    fail_details = []

    col_w = max(len(f.name) for f in input_files)

    print(f"\nBatch converting {len(input_files)} .{fmt} file(s)")
    print(f"  Input dir  : {input_dir.resolve()}")
    print(f"  Output dir : {output_dir}")
    print()

    for input_path in input_files:
        # Resolve to absolute path and assert it stays inside output_dir,
        # guarding against symlink traversal or unusual filesystem layouts.
        output_path = (output_dir / input_path.stem).with_suffix(".miro.json").resolve()
        if not str(output_path).startswith(str(output_dir)):
            print(f"  ✗  {input_path.name}  —  SKIPPED: resolved output path escapes output dir")
            fail_count += 1
            fail_details.append((input_path.name, "output path escapes output_dir"))
            continue
        label = input_path.name.ljust(col_w)

        try:
            stats = _convert_file(input_path, output_path, args)
            ok_count += 1
            if args.summary:
                _print_summary(input_path, output_path, fmt, stats)
            else:
                print(f"  ✓  {label}  →  {output_path.name}")
        except Exception as exc:
            fail_count += 1
            fail_details.append((input_path.name, str(exc)))
            print(f"  ✗  {label}  —  ERROR: {exc}")

    # ── Batch summary ─────────────────────────────────────────────────────────
    print()
    print(f"Done — {ok_count} succeeded, {fail_count} failed "
          f"out of {len(input_files)} file(s)")

    if fail_details:
        print("\nFailed files:")
        for name, err in fail_details:
            print(f"  {name}: {err}")
        print()
        sys.exit(1)   # non-zero exit so CI/scripts can detect partial failure


# ── Entry point ───────────────────────────────────────────────────────────────

def main(argv=None) -> None:
    args = _build_parser().parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"Error: path not found — {input_path}")

    if input_path.is_dir():
        _run_batch(args)
    else:
        _run_single(args)


if __name__ == "__main__":
    main()
