"""
Parser for Lucidchart JSON exports.

Top-level structure:
  {
    "id": "...",
    "title": "...",
    "product": "lucidchart",
    "pages": [
      {
        "id": "...",
        "title": "...",
        "index": 0,
        "items": {
          "shapes": [ {id, class, textAreas:[{label,text}], customData, linkedData} ],
          "lines":  [ {id, endpoint1:{style,connectedTo}, endpoint2:{style,connectedTo}, textAreas} ],
          "groups": [ {id, members:[...]} ],
          "layers": []
        }
      }
    ]
  }

The JSON format has NO position data.
Group membership is tracked separately from containment; since there is no
containment info in this export, all shapes on a page are treated as peers
and the layout engine arranges them using group affinity.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Union

from lucid_to_miro.model import Document, Page, Item, Line, Style

# Lucidchart JSON class names that represent icons / SVG blocks
_ICON_CLASSES = {
    "svgpathblock2", "svgpathblock", "imageblock",
}

# Class names that are AWS/GCP/Azure containers
_CONTAINER_CLASSES = {
    "region", "availabilityzone", "vpc", "subnet", "vnet",
    "resourcegroup", "logicalgroupsofservices/instances",
    "instancegroup", "pool", "swimlaneh", "swimlanev",
}

# Well-known Lucidchart JSON class → human name mapping (for display)
_CLASS_DISPLAY: dict[str, str] = {
    "DefaultSquareBlock": "rectangle",
    "MinimalTextBlock": "text",
    "SVGPathBlock2": "icon",
    "SVGPathBlock": "icon",
    "Line": "line",
}


def _is_icon(cls: str) -> bool:
    return cls.lower() in _ICON_CLASSES


def _is_container(cls: str) -> bool:
    return cls.lower().replace(" ", "").replace("/", "") in _CONTAINER_CLASSES


def _arrow_style(raw: str | None) -> str:
    if not raw:
        return "none"
    mapping = {
        "none": "none",
        "arrow": "arrow",
        "openarrow": "open_arrow",
        "filled": "filled_triangle",
    }
    return mapping.get(raw.strip().lower(), "arrow")


def _extract_text(text_areas: list) -> tuple[str, list[str]]:
    """Return (primary_text, [extra_texts]) from a textAreas list."""
    texts = [ta.get("text", "").strip() for ta in (text_areas or []) if ta.get("text", "").strip()]
    return (texts[0] if texts else ""), texts[1:]


def parse_json(source: Union[str, Path, bytes]) -> Document:
    """
    Parse a Lucidchart JSON export.

    Args:
        source: File path (str or Path) or raw bytes / str content of the JSON.

    Returns:
        Normalised Document.
    """
    if isinstance(source, (str, Path)) and Path(source).exists():
        raw = json.loads(Path(source).read_text(encoding="utf-8"))
    elif isinstance(source, bytes):
        raw = json.loads(source.decode("utf-8"))
    else:
        raw = json.loads(source)  # assume already a JSON string

    doc_title = raw.get("title", "Lucidchart Import")
    pages: list[Page] = []

    for raw_page in raw.get("pages", []):
        page_id    = raw_page.get("id", "")
        page_title = raw_page.get("title", f"Page {raw_page.get('index', len(pages) + 1)}")
        raw_items  = raw_page.get("items", {})

        raw_shapes = raw_items.get("shapes", [])
        raw_lines  = raw_items.get("lines",  [])
        raw_groups = raw_items.get("groups", [])

        # Build group-membership lookup: shape_id → group_id
        shape_to_group: dict[str, str] = {}
        for g in raw_groups:
            gid = g.get("id", "")
            for member_id in g.get("members", []):
                shape_to_group[member_id] = gid

        items: list[Item] = []
        for s in raw_shapes:
            sid   = s.get("id", "")
            cls   = s.get("class", "DefaultSquareBlock")
            primary, extra = _extract_text(s.get("textAreas", []))

            item = Item(
                id=sid,
                name=cls,
                text=primary,
                extra_text=extra,
                page_id=page_id,
                parent_id=None,       # JSON export has no containment info
                group_id=shape_to_group.get(sid),
                is_container=_is_container(cls),
                is_icon=_is_icon(cls),
            )
            items.append(item)

        lines: list[Line] = []
        for l in raw_lines:
            lid = l.get("id", "")
            ep1 = l.get("endpoint1", {})
            ep2 = l.get("endpoint2", {})
            primary, _ = _extract_text(l.get("textAreas", []))

            line = Line(
                id=lid,
                source_id=ep1.get("connectedTo") or None,
                target_id=ep2.get("connectedTo") or None,
                source_arrow=_arrow_style(ep1.get("style")),
                target_arrow=_arrow_style(ep2.get("style")),
                text=primary,
            )
            lines.append(line)

        pages.append(Page(id=page_id, title=page_title, items=items, lines=lines))

    return Document(title=doc_title, pages=pages)
