"""
Parser for Lucidchart CSV exports.

CSV column layout (as exported from Lucidchart):
  Id, Name, Shape Library, Page ID, Contained By, Group,
  Line Source, Line Destination, Source Arrow, Destination Arrow,
  Status, Text Area 1 … Text Area N, Comments

Special rows:
  Name = "Document"  → row 1, document metadata (Text Area 1 = doc title)
  Name = "Page"      → page definition (Id = page id, Text Area 1 = title)
  Name = "Line"      → connector (uses Line Source / Destination columns)
  Name = "Group N"   → group definition (ignored for layout; used for grouping)
  everything else    → shape / icon

"Contained By" is a "|"-separated list of ancestor container IDs ordered
from outermost to innermost; we take the LAST value as the direct parent.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Union

from lucid_to_miro.model import Document, Page, Item, Line, Style

# Shape Library values that indicate a container (region, VPC, subnet, etc.)
_CONTAINER_LIBRARIES = {
    "AWS 2021", "AWS 2019", "AWS 2017",
    "Google Cloud 2018", "Google Cloud 2021",
    "Azure 2021", "Azure 2019", "Azure 2015",
    "GCP", "Network",
}

# Shape names that are containers regardless of library
_CONTAINER_NAMES = {
    "region", "vpc", "subnet", "availability zone", "availabilityzone",
    "vnet", "resource group", "logical groups of services / instances",
    "instance group", "pool", "lane", "swimlane",
}

# Class names that indicate an icon (no meaningful label)
_ICON_NAMES = {
    "svgpathblock2", "svgpathblock", "imageblock",
}


def _is_container(name: str, library: str) -> bool:
    if library in _CONTAINER_LIBRARIES and name.lower() not in _ICON_NAMES:
        return True
    return name.lower().replace(" ", "") in {n.replace(" ", "") for n in _CONTAINER_NAMES}


def _is_icon(name: str) -> bool:
    return name.lower() in _ICON_NAMES


def _parse_parent(contained_by: str) -> str | None:
    """Return the direct parent id (last entry in pipe-separated list)."""
    if not contained_by:
        return None
    parts = [p.strip() for p in contained_by.split("|") if p.strip()]
    return parts[-1] if parts else None


def _arrow_style(raw: str) -> str:
    """Normalise Lucidchart arrow style string to a simple token."""
    mapping = {
        "none": "none",
        "arrow": "arrow",
        "openarrow": "open_arrow",
        "filled": "filled_triangle",
        "diamond": "filled_diamond",
        "opendiamond": "open_diamond",
        "circle": "circle",
    }
    return mapping.get(raw.strip().lower(), "arrow")


def parse_csv(source: Union[str, Path, bytes]) -> Document:
    """
    Parse a Lucidchart CSV export.

    Args:
        source: File path (str or Path) or raw bytes content of the CSV.

    Returns:
        Normalised Document.
    """
    if isinstance(source, (str, Path)):
        text = Path(source).read_text(encoding="utf-8-sig")
    else:
        text = source.decode("utf-8-sig")

    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)

    doc_title = "Lucidchart Import"
    pages: dict[str, Page] = {}     # id → Page
    items: dict[str, Item] = {}     # id → Item
    lines: list[Line] = []

    for row in rows:
        row_id   = row.get("Id", "").strip()
        name     = row.get("Name", "").strip()
        library  = row.get("Shape Library", "").strip()
        page_id  = row.get("Page ID", "").strip()
        contained_by = row.get("Contained By", "").strip()
        group    = row.get("Group", "").strip()
        line_src = row.get("Line Source", "").strip()
        line_dst = row.get("Line Destination", "").strip()
        src_arr  = row.get("Source Arrow", "none").strip()
        dst_arr  = row.get("Destination Arrow", "arrow").strip()
        status   = row.get("Status", "").strip()

        # Collect all non-empty text areas
        text_areas = [
            v.strip()
            for k, v in row.items()
            if k and k.startswith("Text Area") and v and v.strip()
        ]
        primary_text = text_areas[0] if text_areas else ""
        extra_text   = text_areas[1:] if len(text_areas) > 1 else []

        # ── Document metadata ────────────────────────────────────────────────
        if name == "Document":
            if primary_text:
                doc_title = primary_text
            continue

        # ── Page definition ──────────────────────────────────────────────────
        if name == "Page":
            title = primary_text or f"Page {row_id}"
            pages[row_id] = Page(id=row_id, title=title)
            continue

        # ── Group definition (structural, not a visual shape) ────────────────
        if name.lower().startswith("group"):
            # Groups are handled by the "Group" column on their member shapes;
            # we don't create a widget for the group row itself.
            continue

        # ── Line / connector ─────────────────────────────────────────────────
        if name == "Line":
            line = Line(
                id=row_id,
                source_id=line_src or None,
                target_id=line_dst or None,
                source_arrow=_arrow_style(src_arr),
                target_arrow=_arrow_style(dst_arr),
                text=primary_text,
            )
            lines.append((page_id, line))
            continue

        # ── Shape / icon ─────────────────────────────────────────────────────
        item = Item(
            id=row_id,
            name=name,
            text=primary_text,
            extra_text=extra_text,
            page_id=page_id,
            parent_id=_parse_parent(contained_by),
            group_id=group or None,
            is_container=_is_container(name, library),
            is_icon=_is_icon(name),
        )
        items[row_id] = item

    # ── Build Document ───────────────────────────────────────────────────────
    # Ensure all referenced pages exist (some CSVs omit explicit Page rows)
    referenced_pages: set[str] = set()
    for item in items.values():
        if item.page_id:
            referenced_pages.add(item.page_id)
    for pid, line_tuple in lines:
        if pid:
            referenced_pages.add(pid)

    for pid in referenced_pages:
        if pid not in pages:
            pages[pid] = Page(id=pid, title=f"Page {pid}")

    # Distribute items and lines to their pages
    for item in items.values():
        if item.page_id in pages:
            pages[item.page_id].items.append(item)

    for page_id, line in lines:
        if page_id in pages:
            pages[page_id].lines.append(line)

    # Sort pages by numeric id where possible
    def _page_sort_key(p: Page):
        try:
            return (0, int(p.id))
        except ValueError:
            return (1, p.id)

    sorted_pages = sorted(pages.values(), key=_page_sort_key)

    return Document(title=doc_title, pages=sorted_pages)
