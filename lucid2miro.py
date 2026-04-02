#!/usr/bin/env python3
"""
lucid2miro — Convert Lucidchart exports to Miro-importable JSON,
             or upload directly to Miro via the REST API.

Self-contained single file. No third-party packages required.
Works on macOS, Windows, and Linux (Python 3.8+).

Supported input formats:
  .csv    Lucidchart CSV export   (File → Export → CSV)
  .json   Lucidchart JSON export  (File → Export → JSON)

Single-file usage (offline JSON output):
  python lucid2miro.py diagram.csv
  python lucid2miro.py diagram.json -o board.json --pretty --summary

Batch usage (pass a directory):
  python lucid2miro.py ./exports/ --format csv --output-dir ./miro/
  python lucid2miro.py ./exports/ --format json --output-dir ./miro/ --summary

REST API upload (direct to Miro):
  export MIRO_TOKEN=<your_token>
  python lucid2miro.py diagram.csv --upload
  python lucid2miro.py diagram.csv --upload --board-name "My Board" --summary
  python lucid2miro.py ./exports/ --format csv --upload   # batch upload

See docs/MIRO_AUTH.md for authentication setup.
See docs/LUCIDCHART_FORMATS.md for export format details.
"""
from __future__ import annotations

# ── Standard-library imports (only) ──────────────────────────────────────────
import argparse
import csv
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

__version__ = "1.5.0"

# ═════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Data model
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class Style:
    fill_color:   str  = "#ffffff"
    stroke_color: str  = "#000000"
    stroke_width: int  = 1
    font_size:    int  = 14
    font_color:   str  = "#000000"
    text_align:   str  = "center"
    bold:         bool = False
    italic:       bool = False


@dataclass
class Item:
    id:           str
    name:         str                        # Shape Library name / Lucid class
    text:         str             = ""       # Primary label
    extra_text:   List[str]       = field(default_factory=list)
    page_id:      str             = ""
    parent_id:    Optional[str]   = None     # Direct containing shape (CSV only)
    group_id:     Optional[str]   = None     # Group membership
    is_container: bool            = False
    is_icon:      bool            = False
    style:        Style           = field(default_factory=Style)
    # Set by layout engine (CSV/JSON) or VSDX parser (actual coordinates):
    x:      float = 0
    y:      float = 0
    width:  float = 0
    height: float = 0
    # VSDX only — raw embedded image bytes (None for CSV/JSON):
    image_data: Optional[bytes] = field(default=None, repr=False)


@dataclass
class Line:
    id:           str
    source_id:    Optional[str]
    target_id:    Optional[str]
    source_arrow: str   = "none"
    target_arrow: str   = "arrow"
    text:         str   = ""
    style:        Style = field(default_factory=Style)


@dataclass
class Page:
    id:    str
    title: str
    items: List[Item] = field(default_factory=list)
    lines: List[Line] = field(default_factory=list)


@dataclass
class Document:
    title: str
    pages: List[Page] = field(default_factory=list)
    # True when item coordinates are set by the parser (VSDX); layout is skipped.
    has_coordinates: bool = False


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Shape type mapping
# ═════════════════════════════════════════════════════════════════════════════

_SHAPE_MAP: Dict[str, str] = {
    # Basic shapes
    "rectangle":            "rectangle",
    "block":                "rectangle",
    "defaultsquareblock":   "rectangle",
    "square":               "rectangle",
    "roundedrectangle":     "round_rectangle",
    "roundrect":            "round_rectangle",
    "circle":               "circle",
    "ellipse":              "circle",
    "oval":                 "circle",
    "diamond":              "rhombus",
    "rhombus":              "rhombus",
    "triangle":             "triangle",
    "righttriangle":        "right_triangle",
    "parallelogram":        "parallelogram",
    "trapezoid":            "trapezoid",
    "pentagon":             "pentagon",
    "hexagon":              "hexagon",
    "octagon":              "octagon",
    "star":                 "star",
    "cross":                "cross",
    "plus":                 "plus",
    # Arrows
    "arrow":                "arrow",
    "rightarrow":           "arrow",
    "right arrow":          "arrow",
    "leftarrow":            "left_arrow",
    "doublearrow":          "left_right_arrow",
    "uparrow":              "up_arrow",
    "downarrow":            "down_arrow",
    # Flowchart
    "process":              "flow_chart_process",
    "terminator":           "flow_chart_terminator",
    "decision":             "flow_chart_decision",
    "data":                 "flow_chart_data",
    "document":             "flow_chart_document",
    "predefinedprocess":    "flow_chart_predefined_process",
    "manualinput":          "flow_chart_manual_input",
    "preparation":          "flow_chart_preparation",
    "merge":                "flow_chart_merge",
    "connector":            "flow_chart_connector",
    "delay":                "flow_chart_delay",
    "display":              "flow_chart_display",
    "magneticdisk":         "flow_chart_magnetic_disk",
    "sort":                 "flow_chart_sort",
    "extract":              "flow_chart_extract",
    "collate":              "flow_chart_collate",
    "sumjunction":          "flow_chart_summing_junction",
    "or":                   "flow_chart_or",
    # Callouts
    "callout":              "wedge_round_rectangle_callout",
    "cloudcallout":         "cloud_callout",
    # Cloud / infra
    "cloud":                "cloud",
    "cylinder":             "can",
    "database":             "can",
    "can":                  "can",
    # Cloud provider containers
    "region":               "rectangle",
    "availabilityzone":     "rectangle",
    "vpc":                  "rectangle",
    "vnet":                 "rectangle",
    "subnet":               "rectangle",
    "privatesubnet":        "rectangle",
    "publicsubnet":         "rectangle",
    "resourcegroup":        "rectangle",
    "instancegroup":        "rectangle",
    "logicalgroupsofservices/instances": "rectangle",
    # AWS common
    "autoscaling":          "rectangle",
    "loadbalancer":         "rectangle",
    "elasticnetworkinterface": "rectangle",
    "elasticloadbalancing": "rectangle",
    # Text / label
    "minimaltextblock":     "rectangle",
    "text":                 "rectangle",
    "label":                "rectangle",
}


def _to_miro_shape(lucid_name: str) -> str:
    if not lucid_name:
        return "rectangle"
    key = lucid_name.lower().replace("-", "").replace(" ", "").replace("_", "")
    return _SHAPE_MAP.get(key, "rectangle")


def _is_text_only(lucid_name: str) -> bool:
    return lucid_name.lower().replace(" ", "") in {"minimaltextblock", "text", "label", "textbox"}


def _is_icon_shape(lucid_name: str) -> bool:
    key = lucid_name.lower()
    return "svgpathblock" in key or key in {"imageblock", "icon", "customicon"}


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Auto-layout engine
# ═════════════════════════════════════════════════════════════════════════════

SHAPE_W   = 160
SHAPE_H   =  80
ICON_W    =  80
ICON_H    =  80
TEXT_W    = 200
TEXT_H    =  40
ITEM_GAP  =  20
CONT_PAD  =  40
LABEL_H   =  30
FRAME_GAP = 150


def _default_size(item: Item):
    if item.is_icon:
        return ICON_W, ICON_H
    if item.name.lower() in ("minimaltextblock", "text", "label"):
        return TEXT_W, TEXT_H
    return SHAPE_W, SHAPE_H


def _grid_layout(items: List[Item], origin_x: float = 0, origin_y: float = 0):
    if not items:
        return 0, 0
    cols  = max(1, math.ceil(math.sqrt(len(items))))
    x, y  = origin_x, origin_y
    row_h = 0
    col   = 0
    max_x = origin_x
    for item in items:
        item.x = x
        item.y = y
        row_h  = max(row_h, item.height)
        x     += item.width + ITEM_GAP
        max_x  = max(max_x, item.x + item.width)
        col   += 1
        if col >= cols:
            col, x, y, row_h = 0, origin_x, y + row_h + ITEM_GAP, 0
    return max_x - origin_x, (y + row_h) - origin_y


def _build_tree(items: List[Item]):
    item_by_id: Dict[str, Item] = {it.id: it for it in items}
    children:   Dict[str, List[Item]] = {}
    for item in items:
        pid = item.parent_id if (item.parent_id and item.parent_id in item_by_id) else ""
        children.setdefault(pid, []).append(item)
    return item_by_id, children


def _layout_subtree(item: Item, children_map: Dict[str, List[Item]]) -> None:
    kids = children_map.get(item.id, [])
    if not kids:
        item.width, item.height = _default_size(item)
        return
    for kid in kids:
        _layout_subtree(kid, children_map)
    inner_w, inner_h = _grid_layout(kids, origin_x=CONT_PAD, origin_y=CONT_PAD + LABEL_H)
    item.is_container = True
    item.width  = inner_w + CONT_PAD * 2
    item.height = inner_h + CONT_PAD + LABEL_H


def _propagate_positions(items: List[Item], children_map: Dict[str, List[Item]]) -> None:
    for item in items:
        kids = children_map.get(item.id, [])
        for kid in kids:
            kid.x += item.x
            kid.y += item.y
        _propagate_positions(kids, children_map)


def _layout_csv_page(page: Page):
    if not page.items:
        return 800, 600
    _, children_map = _build_tree(page.items)
    top_level = children_map.get("", [])
    for item in top_level:
        _layout_subtree(item, children_map)
    total_w, total_h = _grid_layout(top_level, origin_x=CONT_PAD, origin_y=CONT_PAD)
    _propagate_positions(top_level, children_map)
    return max(total_w + CONT_PAD * 2, 400), max(total_h + CONT_PAD * 2, 300)


def _cluster_by_group(items: List[Item]) -> List[List[Item]]:
    groups: Dict[str, List[Item]] = {}
    singletons: List[Item] = []
    for item in items:
        if item.group_id:
            groups.setdefault(item.group_id, []).append(item)
        else:
            singletons.append(item)
    return list(groups.values()) + [[s] for s in singletons]


def _layout_cluster(cluster: List[Item]):
    for item in cluster:
        item.width, item.height = _default_size(item)
    x = max_h = 0.0
    for item in cluster:
        item.x, item.y = x, 0.0
        x    += item.width + ITEM_GAP
        max_h = max(max_h, item.height)
    return x - ITEM_GAP, max_h


def _layout_json_page(page: Page):
    if not page.items:
        return 800, 600
    clusters = _cluster_by_group(page.items)
    sizes    = [_layout_cluster(c) for c in clusters]
    cols     = max(1, math.ceil(math.sqrt(len(clusters))))
    x = y = float(CONT_PAD)
    row_h = max_x = 0.0
    col   = 0
    for cluster, (cw, ch) in zip(clusters, sizes):
        for item in cluster:
            item.x += x
            item.y += y
        max_x = max(max_x, x + cw)
        row_h = max(row_h, ch)
        col  += 1
        x    += cw + ITEM_GAP * 3
        if col >= cols:
            col, x, y, row_h = 0, float(CONT_PAD), y + row_h + ITEM_GAP * 3, 0.0
    return max(max_x, 400), max(y + row_h + CONT_PAD, 300)


def _layout_page(page: Page, has_containment: bool):
    return _layout_csv_page(page) if has_containment else _layout_json_page(page)


def _frame_from_items(page: Page):
    """Frame size from pre-set item coordinates (VSDX input)."""
    if not page.items:
        return 800.0, 600.0
    max_x = max(item.x + item.width  for item in page.items)
    max_y = max(item.y + item.height for item in page.items)
    return max(max_x + CONT_PAD, 400.0), max(max_y + CONT_PAD, 300.0)


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 4 — CSV parser
# ═════════════════════════════════════════════════════════════════════════════

_CSV_CONTAINER_LIBRARIES = {
    "AWS 2021", "AWS 2019", "AWS 2017",
    "Google Cloud 2018", "Google Cloud 2021",
    "Azure 2021", "Azure 2019", "Azure 2015",
    "GCP", "Network",
}
_CSV_CONTAINER_NAMES = {
    "region", "vpc", "subnet", "availability zone", "availabilityzone",
    "vnet", "resource group", "logical groups of services / instances",
    "instance group", "pool", "lane", "swimlane",
}
_CSV_ICON_NAMES = {"svgpathblock2", "svgpathblock", "imageblock"}


def _csv_is_container(name: str, library: str) -> bool:
    if library in _CSV_CONTAINER_LIBRARIES and name.lower() not in _CSV_ICON_NAMES:
        return True
    return name.lower().replace(" ", "") in {n.replace(" ", "") for n in _CSV_CONTAINER_NAMES}


def _csv_parse_parent(contained_by: str) -> Optional[str]:
    parts = [p.strip() for p in contained_by.split("|") if p.strip()]
    return parts[-1] if parts else None


def _csv_arrow(raw: str) -> str:
    return {"none": "none", "arrow": "arrow", "openarrow": "open_arrow",
            "filled": "filled_triangle", "diamond": "filled_diamond",
            "opendiamond": "open_diamond", "circle": "circle"}.get(
        raw.strip().lower(), "arrow")


def parse_csv(source: Union[str, Path, bytes]) -> Document:
    """Parse a Lucidchart CSV export into a normalised Document."""
    if isinstance(source, (str, Path)):
        text = Path(source).read_text(encoding="utf-8-sig")
    else:
        text = source.decode("utf-8-sig")

    rows      = list(csv.DictReader(io.StringIO(text)))
    doc_title = "Lucidchart Import"
    pages:    Dict[str, Page] = {}
    items:    Dict[str, Item] = {}
    lines:    list            = []   # [(page_id, Line)]

    for row in rows:
        row_id  = row.get("Id", "").strip()
        name    = row.get("Name", "").strip()
        library = row.get("Shape Library", "").strip()
        page_id = row.get("Page ID", "").strip()
        cont_by = row.get("Contained By", "").strip()
        group   = row.get("Group", "").strip()
        src_id  = row.get("Line Source", "").strip()
        dst_id  = row.get("Line Destination", "").strip()
        src_arr = row.get("Source Arrow", "none").strip()
        dst_arr = row.get("Destination Arrow", "arrow").strip()

        text_areas = [v.strip() for k, v in row.items()
                      if k and k.startswith("Text Area") and v and v.strip()]
        primary = text_areas[0] if text_areas else ""
        extra   = text_areas[1:] if len(text_areas) > 1 else []

        if name == "Document":
            if primary:
                doc_title = primary
            continue

        if name == "Page":
            pages[row_id] = Page(id=row_id, title=primary or f"Page {row_id}")
            continue

        if name.lower().startswith("group"):
            continue

        if name == "Line":
            lines.append((page_id, Line(
                id=row_id,
                source_id=src_id or None,
                target_id=dst_id or None,
                source_arrow=_csv_arrow(src_arr),
                target_arrow=_csv_arrow(dst_arr),
                text=primary,
            )))
            continue

        items[row_id] = Item(
            id=row_id, name=name, text=primary, extra_text=extra,
            page_id=page_id,
            parent_id=_csv_parse_parent(cont_by),
            group_id=group or None,
            is_container=_csv_is_container(name, library),
            is_icon=name.lower() in _CSV_ICON_NAMES,
        )

    # Ensure pages exist for any referenced page_id
    for pid in {i.page_id for i in items.values()} | {pid for pid, _ in lines}:
        if pid and pid not in pages:
            pages[pid] = Page(id=pid, title=f"Page {pid}")

    for item in items.values():
        if item.page_id in pages:
            pages[item.page_id].items.append(item)
    for page_id, line in lines:
        if page_id in pages:
            pages[page_id].lines.append(line)

    def _sort_key(p: Page):
        try:    return (0, int(p.id))
        except (ValueError, TypeError): return (1, p.id)

    return Document(title=doc_title, pages=sorted(pages.values(), key=_sort_key))


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 5 — JSON parser
# ═════════════════════════════════════════════════════════════════════════════

_JSON_ICON_CLASSES      = {"svgpathblock2", "svgpathblock", "imageblock"}
_JSON_CONTAINER_CLASSES = {
    "region", "availabilityzone", "vpc", "subnet", "vnet",
    "resourcegroup", "logicalgroupsofservices/instances",
    "instancegroup", "pool", "swimlaneh", "swimlanev",
}


def _json_arrow(raw: Optional[str]) -> str:
    if not raw:
        return "none"
    return {"none": "none", "arrow": "arrow",
            "openarrow": "open_arrow", "filled": "filled_triangle"}.get(
        raw.strip().lower(), "arrow")


def _json_extract_text(text_areas: list):
    texts = [ta.get("text", "").strip() for ta in (text_areas or []) if ta.get("text", "").strip()]
    return (texts[0] if texts else ""), texts[1:]


def parse_json(source: Union[str, Path, bytes]) -> Document:
    """Parse a Lucidchart JSON export into a normalised Document."""
    if isinstance(source, (str, Path)) and Path(source).exists():
        raw = json.loads(Path(source).read_text(encoding="utf-8"))
    elif isinstance(source, bytes):
        raw = json.loads(source.decode("utf-8"))
    else:
        raw = json.loads(source)

    pages: List[Page] = []
    for raw_page in raw.get("pages", []):
        page_id    = raw_page.get("id", "")
        page_title = raw_page.get("title", f"Page {raw_page.get('index', len(pages) + 1)}")
        raw_items  = raw_page.get("items", {})

        # Group membership lookup
        shape_to_group: Dict[str, str] = {}
        for g in raw_items.get("groups", []):
            gid = g.get("id", "")
            for mid in g.get("members", []):
                shape_to_group[mid] = gid

        items: List[Item] = []
        for s in raw_items.get("shapes", []):
            sid     = s.get("id", "")
            cls     = s.get("class", "DefaultSquareBlock")
            primary, extra = _json_extract_text(s.get("textAreas", []))
            items.append(Item(
                id=sid, name=cls, text=primary, extra_text=extra,
                page_id=page_id, parent_id=None,
                group_id=shape_to_group.get(sid),
                is_container=cls.lower().replace(" ", "").replace("/", "") in _JSON_CONTAINER_CLASSES,
                is_icon=cls.lower() in _JSON_ICON_CLASSES,
            ))

        lines: List[Line] = []
        for l in raw_items.get("lines", []):
            ep1     = l.get("endpoint1", {})
            ep2     = l.get("endpoint2", {})
            primary, _ = _json_extract_text(l.get("textAreas", []))
            lines.append(Line(
                id=l.get("id", ""),
                source_id=ep1.get("connectedTo") or None,
                target_id=ep2.get("connectedTo") or None,
                source_arrow=_json_arrow(ep1.get("style")),
                target_arrow=_json_arrow(ep2.get("style")),
                text=primary,
            ))

        pages.append(Page(id=page_id, title=page_title, items=items, lines=lines))

    return Document(title=raw.get("title", "Lucidchart Import"), pages=pages)


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 5B — Visio (.vsdx) parser
# ═════════════════════════════════════════════════════════════════════════════
#
# A .vsdx file is a ZIP archive (OPC).  Relevant paths:
#   visio/document.xml                   — document title
#   visio/pages/pages.xml                — ordered page list
#   visio/pages/_rels/pages.xml.rels     — page XML path resolution
#   visio/pages/page{n}.xml              — shapes, groups, connectors
#   visio/pages/_rels/page{n}.xml.rels   — image rel targets
#   visio/masters/masters.xml            — master shape names
#   visio/media/                         — embedded PNG/SVG images
#
# Coordinate conversion:
#   Visio inches, bottom-left origin, Y increases up
#   → Miro pixels at 96 dpi, top-left origin, Y increases down
#     miro_x = (PinX - LocPinX) * 96
#     miro_y = (page_height - (PinY - LocPinY) - height) * 96
# ─────────────────────────────────────────────────────────────────────────────

_VSDX_NS  = "http://schemas.microsoft.com/office/visio/2012/main"
_VSDX_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_DPI      = 96   # pixels per inch

_VSDX_ARROW: Dict[int, str] = {
    0: "none", 1: "arrow", 2: "filled_triangle", 3: "arrow",
    4: "arrow", 5: "circle", 13: "open_diamond", 14: "filled_diamond",
    45: "open_arrow",
}

_VSDX_CONTAINER_KEYS: Set[str] = {
    "region", "vpc", "subnet", "vnet", "availabilityzone",
    "resourcegroup", "instancegroup", "swimlane", "lane", "pool",
    "logicalgroupsofservices/instances",
}

_VSDX_ICON_KEYS: Set[str] = {
    "svgpathblock2", "svgpathblock", "imageblock", "icon", "customicon",
}


def _vt(local: str) -> str:
    return f"{{{_VSDX_NS}}}{local}"


def _vfloat(parent: ET.Element, local: str, default: float = 0.0) -> float:
    child = parent.find(_vt(local))
    if child is None:
        return default
    raw = child.get("V") or (child.text or "")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _vtext(elem: Optional[ET.Element]) -> str:
    if elem is None:
        return ""
    parts: List[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if child.tail:
            parts.append(child.tail)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _vcell(shape: ET.Element, name: str) -> Optional[str]:
    for cell in shape.iter(_vt("Cell")):
        if cell.get("N") == name:
            return cell.get("V") or cell.text or None
    return None


def _vnorm_color(raw: Optional[str]) -> str:
    if not raw:
        return "#ffffff"
    raw = raw.strip()
    if re.match(r"^#[0-9a-fA-F]{6}$", raw):
        return raw.lower()
    if "THEMEVAL" in raw or "Theme" in raw:
        return "#ffffff"
    m = re.match(r"RGB\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", raw, re.I)
    if m:
        return "#{:02x}{:02x}{:02x}".format(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    try:
        v = int(raw)
        return "#{:02x}{:02x}{:02x}".format(v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF)
    except (TypeError, ValueError):
        return "#ffffff"


def _varrow(raw: Optional[str]) -> str:
    if not raw:
        return "none"
    try:
        return _VSDX_ARROW.get(int(float(raw)), "arrow")
    except (TypeError, ValueError):
        return "none"


def _vmkey(name: str) -> str:
    return name.lower().replace(" ", "").replace("-", "").replace("/", "")


def _vinfer_ext(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n": return ".png"
    if data[:3] == b"\xff\xd8\xff":      return ".jpg"
    if data[:4] == b"GIF8":              return ".gif"
    if b"<svg" in data[:64]:             return ".svg"
    return ".bin"


def _vtry_read(zf: zipfile.ZipFile, *paths: str) -> Optional[bytes]:
    for p in paths:
        try:
            return zf.read(p)
        except KeyError:
            continue
    return None


def _vparse_rels(zf: zipfile.ZipFile, rels_path: str) -> Dict[str, str]:
    data = _vtry_read(zf, rels_path)
    if not data:
        return {}
    root = ET.fromstring(data)
    return {r.get("Id", ""): r.get("Target", "") for r in root if r.get("Id")}


def _vrels_path(page_xml: str) -> str:
    parts = page_xml.rsplit("/", 1)
    return (f"{parts[0]}/_rels/{parts[1]}.rels" if len(parts) == 2
            else f"_rels/{page_xml}.rels")


def _vresolve_media(rel_target: str, page_xml: str) -> str:
    base = page_xml.rsplit("/", 1)[0]
    parts = (base + "/" + rel_target).split("/")
    resolved: List[str] = []
    for p in parts:
        if p == "..":
            if resolved: resolved.pop()
        elif p and p != ".":
            resolved.append(p)
    return "/".join(resolved)


def _vparse_masters(zf: zipfile.ZipFile) -> Dict[str, str]:
    data = _vtry_read(zf, "visio/masters/masters.xml")
    if not data:
        return {}
    root = ET.fromstring(data)
    return {m.get("ID", ""): (m.get("NameU") or m.get("Name") or "")
            for m in root.iter(_vt("Master")) if m.get("ID")}


def _vshape_coords(shape: ET.Element, cont_h: float,
                   px: float, py: float) -> Tuple[float, float, float, float]:
    xf = shape.find(_vt("XForm"))
    if xf is None:
        return px, py, 1.0, 1.0
    w   = _vfloat(xf, "Width",   1.0)
    h   = _vfloat(xf, "Height",  1.0)
    pinx = _vfloat(xf, "PinX",  w / 2)
    piny = _vfloat(xf, "PinY",  h / 2)
    lpx  = _vfloat(xf, "LocPinX", w / 2)
    lpy  = _vfloat(xf, "LocPinY", h / 2)
    return (
        px + (pinx - lpx) * _DPI,
        py + (cont_h - (piny - lpy) - h) * _DPI,
        max(1.0, w * _DPI),
        max(1.0, h * _DPI),
    )


def _vparse_shapes(shapes_root: ET.Element, page_id: str,
                   masters: Dict[str, str], page_rels: Dict[str, str],
                   zf: zipfile.ZipFile, cont_h: float,
                   abs_x: float, abs_y: float,
                   conn_ids: Set[str],
                   parent_item_id: Optional[str] = None) -> List[Item]:
    items: List[Item] = []
    for shape in shapes_root.findall(_vt("Shape")):
        raw_id     = shape.get("ID", "")
        shape_type = shape.get("Type", "Shape")
        master_id  = shape.get("Master", "")
        if not raw_id or raw_id in conn_ids:
            continue

        master_name = masters.get(master_id, "")
        mkey        = _vmkey(master_name)
        xf          = shape.find(_vt("XForm"))
        sh_h        = _vfloat(xf, "Height", 1.0) if xf is not None else 1.0

        ax, ay, aw, ah = _vshape_coords(shape, cont_h, abs_x, abs_y)
        label = _vtext(shape.find(_vt("Text")))
        style = Style(
            fill_color=_vnorm_color(_vcell(shape, "FillForegnd")),
            stroke_color=_vnorm_color(_vcell(shape, "LineColor")),
        )

        is_icon_flag = (shape_type == "Foreign" or mkey in _VSDX_ICON_KEYS)

        image_data: Optional[bytes] = None
        if is_icon_flag:
            foreign = shape.find(_vt("ForeignData"))
            if foreign is not None:
                rel_e = foreign.find(_vt("Rel"))
                if rel_e is not None:
                    rid = rel_e.get(f"{{{_VSDX_REL}}}id", "")
                    if rid and rid in page_rels:
                        image_data = _vtry_read(zf, page_rels[rid])

        child_shapes = shape.find(_vt("Shapes"))
        has_kids     = child_shapes is not None and len(child_shapes) > 0
        is_cont_flag = (
            (shape_type == "Group" and has_kids)
            or mkey in _VSDX_CONTAINER_KEYS
        )

        item_id = f"{page_id}_{raw_id}"
        items.append(Item(
            id=item_id,
            name=master_name or {"Group": "Region", "Foreign": "ImageBlock"}.get(shape_type, "Block"),
            text=label,
            page_id=page_id,
            parent_id=parent_item_id,
            is_container=is_cont_flag,
            is_icon=is_icon_flag,
            style=style,
            x=round(ax, 1), y=round(ay, 1),
            width=round(aw, 1), height=round(ah, 1),
            image_data=image_data,
        ))

        if child_shapes is not None and has_kids:
            items.extend(_vparse_shapes(
                child_shapes, page_id, masters, page_rels, zf,
                cont_h=sh_h, abs_x=ax, abs_y=ay,
                conn_ids=conn_ids, parent_item_id=item_id,
            ))
    return items


def _vcollect_conn_ids(root: ET.Element) -> Set[str]:
    connects = root.find(_vt("Connects"))
    if connects is None:
        return set()
    return {c.get("FromSheet", "") for c in connects.findall(_vt("Connect"))
            if c.get("FromSheet")}


def _vparse_lines(root: ET.Element, page_id: str) -> List[Line]:
    connects = root.find(_vt("Connects"))
    if connects is None:
        return []
    conn_map: Dict[str, Dict[str, str]] = {}
    for c in connects.findall(_vt("Connect")):
        fid = c.get("FromSheet", ""); fc = c.get("FromCell", ""); ts = c.get("ToSheet", "")
        if fid and fc and ts:
            conn_map.setdefault(fid, {})[fc] = ts

    shape_by_id: Dict[str, ET.Element] = {}
    sr = root.find(_vt("Shapes"))
    if sr is not None:
        for s in sr.iter(_vt("Shape")):
            sid = s.get("ID", "")
            if sid:
                shape_by_id[sid] = s

    lines: List[Line] = []
    for cid, cells in conn_map.items():
        src_raw = cells.get("BeginX") or cells.get("FromBeginX")
        tgt_raw = cells.get("EndX")   or cells.get("FromEndX")
        if src_raw is None and tgt_raw is None:
            continue
        cs = shape_by_id.get(cid)
        lines.append(Line(
            id=f"{page_id}_{cid}",
            source_id=f"{page_id}_{src_raw}" if src_raw else None,
            target_id=f"{page_id}_{tgt_raw}" if tgt_raw else None,
            source_arrow=_varrow(_vcell(cs, "BeginArrow") if cs else None),
            target_arrow=_varrow(_vcell(cs, "EndArrow")   if cs else None),
            text=_vtext(cs.find(_vt("Text"))) if cs else "",
        ))
    return lines


def _vparse_page(zf: zipfile.ZipFile, page_xml: str,
                 page_id: str, page_title: str,
                 masters: Dict[str, str]) -> Page:
    data = _vtry_read(zf, page_xml)
    if not data:
        return Page(id=page_id, title=page_title)

    root        = ET.fromstring(data)
    page_height = 8.5
    ps          = root.find(_vt("PageSheet"))
    if ps is not None:
        pp = ps.find(_vt("PageProps"))
        if pp is not None:
            page_height = _vfloat(pp, "PageHeight", page_height)

    rels_raw  = _vparse_rels(zf, _vrels_path(page_xml))
    page_rels = {rid: _vresolve_media(t, page_xml) for rid, t in rels_raw.items()}

    shapes_root = root.find(_vt("Shapes"))
    if shapes_root is None:
        return Page(id=page_id, title=page_title)

    conn_ids = _vcollect_conn_ids(root)
    items    = _vparse_shapes(shapes_root, page_id, masters, page_rels, zf,
                               cont_h=page_height, abs_x=0.0, abs_y=0.0,
                               conn_ids=conn_ids)
    lines    = _vparse_lines(root, page_id)
    return Page(id=page_id, title=page_title, items=items, lines=lines)


def parse_vsdx(source: Union[str, Path, bytes]) -> Document:
    """
    Parse a Lucidchart Visio (.vsdx) export into a normalised Document.

    Coordinates are taken from the Visio geometry (96 dpi, top-left origin).
    doc.has_coordinates is True — the auto-layout engine is skipped.
    Icon shapes store raw image bytes in item.image_data.
    """
    raw = Path(source).read_bytes() if isinstance(source, (str, Path)) else bytes(source)

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        masters = _vparse_masters(zf)

        # Document title
        title = "Visio Import"
        doc_data = _vtry_read(zf, "visio/document.xml")
        if doc_data:
            dr = ET.fromstring(doc_data)
            for el in dr.iter():
                if el.tag.endswith("Title") and el.text and el.text.strip():
                    title = el.text.strip()
                    break

        pages_data = _vtry_read(zf, "visio/pages/pages.xml")
        if not pages_data:
            return Document(title=title, has_coordinates=True)

        pages_root = ET.fromstring(pages_data)
        pages_rels = _vparse_rels(zf, "visio/pages/_rels/pages.xml.rels")

        pages: List[Page] = []
        for idx, pel in enumerate(pages_root.findall(_vt("Page")), start=1):
            pid    = pel.get("ID", str(idx))
            ptitle = pel.get("Name") or pel.get("NameU") or f"Page {idx}"
            pxml   = f"visio/pages/page{idx}.xml"
            rel_e  = pel.find(_vt("Rel"))
            if rel_e is not None:
                rid = rel_e.get(f"{{{_VSDX_REL}}}id", "")
                if rid and rid in pages_rels:
                    pxml = f"visio/pages/{pages_rels[rid].lstrip('./')}"
            page = _vparse_page(zf, pxml, pid, ptitle, masters)
            if page.items or page.lines:
                pages.append(page)

    return Document(title=title, pages=pages, has_coordinates=True)


def _vextract_media(doc: Document, output_dir: Path) -> Dict[str, Path]:
    """Write embedded icon images to disk; return {item_id: Path}."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written: Dict[str, Path] = {}
    for page in doc.pages:
        for item in page.items:
            if item.is_icon and item.image_data:
                ext       = _vinfer_ext(item.image_data)
                # Sanitise item.id before use as a filename — prevents path
                # traversal if a malicious VSDX encodes "../" in a shape ID.
                safe_name = re.sub(r"[^\w\-]", "_", item.id)
                dest      = output_dir / f"{safe_name}{ext}"
                dest.write_bytes(item.image_data)
                written[item.id] = dest
    return written


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 6 — Miro JSON converter
# ═════════════════════════════════════════════════════════════════════════════

_CONTAINER_FILLS = ["#EEF4FB", "#F0F9EE", "#FEF9EC", "#F9EEFF"]
_ARROW_MAP = {
    "none": "none", "arrow": "arrow", "open_arrow": "open_arrow",
    "filled_triangle": "filled_triangle", "filled_diamond": "filled_diamond",
    "open_diamond": "open_diamond", "circle": "circle",
}


def _sanitise(text: str) -> str:
    return re.sub(r"<[^>]*>", "", text or "").strip()


def _item_widget(item: Item, frame_id: str, board_x: float, depth: int = 0) -> Dict[str, Any]:
    ax = round(item.x + board_x)
    ay = round(item.y)
    w  = max(1, round(item.width))
    h  = max(1, round(item.height))

    label = _sanitise(item.text)
    if item.extra_text:
        extra = "\n".join(_sanitise(t) for t in item.extra_text if t.strip())
        if extra:
            label = f"{label}\n{extra}".strip()

    if _is_icon_shape(item.name):
        return {"type": "image", "id": item.id or None, "parentId": frame_id,
                "data": {"title": label}, "style": {"backgroundColor": "#ffffff"},
                "position": {"x": ax, "y": ay}, "geometry": {"width": w, "height": h}}

    if _is_text_only(item.name):
        return {"type": "text", "id": item.id or None, "parentId": frame_id,
                "data": {"content": label},
                "style": {"color": "#000000", "fontSize": 14,
                          "textAlign": "left", "fontFamily": "arial"},
                "position": {"x": ax, "y": ay}, "geometry": {"width": w, "height": h}}

    fill = _CONTAINER_FILLS[depth % len(_CONTAINER_FILLS)] if item.is_container else "#ffffff"
    return {
        "type": "shape", "id": item.id or None, "parentId": frame_id,
        "data": {"shape": _to_miro_shape(item.name), "content": label},
        "style": {
            "fillColor":         fill,
            "borderColor":       "#555555" if item.is_container else "#000000",
            "borderWidth":       2 if item.is_container else 1,
            "borderStyle":       "normal",
            "fillOpacity":       1,
            "fontSize":          13 if item.is_container else 14,
            "color":             "#333333" if item.is_container else "#000000",
            "textAlign":         "left"   if item.is_container else "center",
            "textAlignVertical": "top"    if item.is_container else "middle",
            "fontFamily":        "arial",
        },
        "position": {"x": ax, "y": ay},
        "geometry": {"width": w, "height": h},
    }


def _line_widget(line: Line, frame_id: str,
                 item_lookup: Dict[str, Item], board_x: float) -> Optional[Dict[str, Any]]:
    def _centre(it: Item):
        return round(it.x + it.width / 2 + board_x), round(it.y + it.height / 2)

    src = item_lookup.get(line.source_id) if line.source_id else None
    tgt = item_lookup.get(line.target_id) if line.target_id else None
    if src is None and tgt is None:
        return None

    sx, sy = _centre(src) if src else (round(board_x + 100), 100)
    ex, ey = _centre(tgt) if tgt else (round(board_x + 200), 200)

    return {
        "type": "line", "id": line.id or None, "parentId": frame_id,
        "data": {"content": _sanitise(line.text),
                 "startShapeId": line.source_id, "endShapeId": line.target_id},
        "style": {
            "lineColor":     "#444444", "lineThickness": 1, "lineStyle": "normal",
            "lineStartType": _ARROW_MAP.get(line.source_arrow, "none"),
            "lineEndType":   _ARROW_MAP.get(line.target_arrow, "arrow"),
        },
        "startPosition": {"x": sx, "y": sy},
        "endPosition":   {"x": ex, "y": ey},
    }


def convert(doc: Document, has_containment: bool = True,
            scale: float = 1.0) -> Dict[str, Any]:
    """Convert a normalised Document to a Miro board JSON dict."""
    widgets: List[Dict[str, Any]] = []
    board_x = 0.0

    for page in doc.pages:
        if not page.items and not page.lines:
            continue

        # VSDX: coordinates pre-set — compute frame from bounding box.
        # CSV/JSON: run auto-layout engine.
        if doc.has_coordinates:
            frame_w, frame_h = _frame_from_items(page)
        else:
            frame_w, frame_h = _layout_page(page, has_containment)

        if scale != 1.0:
            frame_w *= scale
            frame_h *= scale
            for item in page.items:
                item.x *= scale; item.y *= scale
                item.width *= scale; item.height *= scale

        frame_id = f"frame_{page.id}"
        widgets.append({
            "type": "frame", "id": frame_id, "title": page.title,
            "style": {"fillColor": "#f5f5f5"},
            "position": {"x": round(board_x), "y": 0},
            "geometry": {"width": round(frame_w), "height": round(frame_h)},
        })

        item_lookup: Dict[str, Item] = {it.id: it for it in page.items}

        for item in page.items:
            depth, cursor = 0, item.parent_id
            while cursor and cursor in item_lookup:
                depth += 1
                cursor = item_lookup[cursor].parent_id
            widgets.append(_item_widget(item, frame_id, board_x, depth))

        for line in page.lines:
            w = _line_widget(line, frame_id, item_lookup, board_x)
            if w:
                widgets.append(w)

        board_x += frame_w + FRAME_GAP

    return {"version": "1", "board": {"title": doc.title, "widgets": widgets}}


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 7 — Miro REST API client
# ═════════════════════════════════════════════════════════════════════════════

_MIRO_BASE_URL = "https://api.miro.com"
_API_MAX_RETRIES = 3
_API_RETRY_ON    = {500, 502, 503, 504}


class MiroAuthError(Exception):
    """Token is missing, malformed, or rejected (HTTP 401 / 403)."""


class MiroAPIError(Exception):
    """Non-retryable API error."""
    def __init__(self, status: int, body: str) -> None:
        self.status = status
        super().__init__(f"Miro API HTTP {status}: {body[:400]}")


class MiroRateLimitError(MiroAPIError):
    """Rate limit hit and retries exhausted."""


class MiroClient:
    """
    Thin, zero-dependency HTTP client for the Miro REST API v2.

    Pass a Personal Access Token (PAT) directly or via the MIRO_TOKEN
    environment variable.  See docs/MIRO_AUTH.md for full details.
    """

    def __init__(self, token: str) -> None:
        if not token or not token.strip():
            raise MiroAuthError(
                "Miro access token is required.\n"
                "  Option 1 (recommended): export MIRO_TOKEN=<your_token>\n"
                "  Option 2: pass --token <your_token> on the CLI\n"
                "  See docs/MIRO_AUTH.md for how to create a token."
            )
        self._token = token.strip()

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type":  "application/json",
            "Accept":        "application/json",
        }

    def request(self, method: str, path: str,
                body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Authenticated HTTP request with automatic retry on 429 / 5xx."""
        url  = f"{_MIRO_BASE_URL}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        for attempt in range(_API_MAX_RETRIES):
            req = urllib.request.Request(
                url, data=data, headers=self._headers(), method=method
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read().decode("utf-8")
                    return json.loads(raw) if raw.strip() else {}
            except urllib.error.HTTPError as exc:
                status = exc.code
                rbody  = exc.read().decode("utf-8", errors="replace")
                if status == 401:
                    raise MiroAuthError(
                        "Authentication failed (HTTP 401).\n"
                        "  • Verify the token is copied correctly.\n"
                        "  • Confirm the token has not expired or been revoked.\n"
                        "  • Check the token scope includes boards:write.\n"
                        f"  API response: {rbody[:200]}\n"
                        "  See docs/MIRO_AUTH.md § Troubleshooting."
                    )
                if status == 403:
                    raise MiroAuthError(
                        "Permission denied (HTTP 403).\n"
                        "  • Token scope may not include boards:write.\n"
                        "  • If using --team-id, verify you are a member of that team.\n"
                        f"  API response: {rbody[:200]}"
                    )
                if status == 429:
                    retry_after = int(exc.headers.get("Retry-After", "5"))
                    if attempt < _API_MAX_RETRIES - 1:
                        time.sleep(retry_after)
                        continue
                    raise MiroRateLimitError(status, rbody)
                if status in _API_RETRY_ON and attempt < _API_MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                    continue
                raise MiroAPIError(status, rbody)
        raise MiroAPIError(0, "Max retries exceeded")

    def get(self, path: str) -> Dict[str, Any]:
        return self.request("GET", path)

    def post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        return self.request("POST", path, body)


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 8 — Miro REST API uploader
# ═════════════════════════════════════════════════════════════════════════════

# Lucidchart arrow token → Miro connector stroke cap
_CONNECTOR_CAPS: Dict[str, str] = {
    "none":            "none",
    "arrow":           "arrow",
    "open_arrow":      "open_arrow",
    "filled_triangle": "filled_arrow",
    "filled_diamond":  "filled_diamond",
    "open_diamond":    "open_diamond",
    "circle":          "circle",
}

_UPLOAD_CONTAINER_FILLS = ["#EEF4FB", "#F0F9EE", "#FEF9EC", "#F9EEFF"]


def _load_icon_map(path: Optional[str]) -> Dict[str, str]:
    """Load an icon-map JSON file.  Returns {} when path is None."""
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        raise ValueError(f"--icon-map file not found: {p}")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"--icon-map is not valid JSON: {exc}") from exc
    result: Dict[str, str] = {}
    result.update(raw.get("by_id",   {}))
    result.update(raw.get("by_name", {}))
    if "default" in raw:
        result["__default__"] = raw["default"]
    return result


def _resolve_icon_url(item: Item, icon_map: Dict[str, str]) -> Optional[str]:
    if item.id   and item.id   in icon_map: return icon_map[item.id]
    if item.name and item.name in icon_map: return icon_map[item.name]
    return icon_map.get("__default__")


def _upload_label(item: Item) -> str:
    parts = [_sanitise(item.text)]
    for t in item.extra_text:
        s = _sanitise(t)
        if s:
            parts.append(s)
    return "\n".join(p for p in parts if p)


def _upload_frame_payload(page: Page, board_cx: float, fw: float, fh: float,
                          prefix: str, suffix: str) -> Dict[str, Any]:
    title = f"{prefix}{page.title}{suffix}".strip()
    return {
        "data":     {"format": "custom", "title": title, "type": "freeform"},
        "style":    {"fillColor": "#f5f5f5"},
        "position": {"x": board_cx, "y": fh / 2, "origin": "center"},
        "geometry": {"width": fw, "height": fh},
    }


def _upload_shape_payload(item: Item, frame_id: str, depth: int) -> Dict[str, Any]:
    fill = _UPLOAD_CONTAINER_FILLS[depth % len(_UPLOAD_CONTAINER_FILLS)] \
           if item.is_container else "#ffffff"
    return {
        "data": {"content": _upload_label(item), "shape": _to_miro_shape(item.name)},
        "style": {
            "fillColor":         fill,
            "borderColor":       "#555555" if item.is_container else "#000000",
            "borderWidth":       "2"       if item.is_container else "1",
            "borderStyle":       "normal",
            "fillOpacity":       "1",
            "fontSize":          "13"      if item.is_container else "14",
            "color":             "#333333" if item.is_container else "#000000",
            "textAlign":         "left"    if item.is_container else "center",
            "textAlignVertical": "top"     if item.is_container else "middle",
            "fontFamily":        "open_sans",
        },
        # Miro expects CENTER coordinates; layout engine uses top-left
        "position": {"x": item.x + item.width / 2, "y": item.y + item.height / 2,
                     "origin": "center"},
        "geometry": {"width": item.width, "height": item.height},
        "parent":   {"id": frame_id},
    }


def _upload_text_payload(item: Item, frame_id: str) -> Dict[str, Any]:
    return {
        "data":     {"content": _upload_label(item)},
        "style":    {"color": "#000000", "fillColor": "transparent",
                     "fontSize": "14", "fontFamily": "open_sans"},
        "position": {"x": item.x + item.width / 2, "y": item.y + item.height / 2,
                     "origin": "center"},
        "geometry": {"width": item.width, "height": item.height},
        "parent":   {"id": frame_id},
    }


def _upload_image_payload(item: Item, frame_id: str, url: str) -> Dict[str, Any]:
    return {
        "data":     {"imageUrl": url, "title": _upload_label(item)},
        "position": {"x": item.x + item.width / 2, "y": item.y + item.height / 2,
                     "origin": "center"},
        "geometry": {"width": item.width, "height": item.height},
        "parent":   {"id": frame_id},
    }


def _upload_connector_payload(line: Line,
                              lucid_to_miro: Dict[str, str]) -> Optional[Dict[str, Any]]:
    src_mid = lucid_to_miro.get(line.source_id) if line.source_id else None
    tgt_mid = lucid_to_miro.get(line.target_id) if line.target_id else None
    if src_mid is None and tgt_mid is None:
        return None
    payload: Dict[str, Any] = {
        "style": {
            "strokeColor":    "#444444",
            "strokeWidth":    "2",
            "strokeStyle":    "normal",
            "startStrokeCap": _CONNECTOR_CAPS.get(line.source_arrow, "none"),
            "endStrokeCap":   _CONNECTOR_CAPS.get(line.target_arrow, "arrow"),
        },
        "shape": "elbowed",
    }
    if src_mid: payload["startItem"] = {"id": src_mid, "snapTo": "auto"}
    if tgt_mid: payload["endItem"]   = {"id": tgt_mid, "snapTo": "auto"}
    label = _sanitise(line.text)
    if label:
        payload["captions"] = [{"content": label, "position": "50"}]
    return payload


def _api_log(verbose: bool, msg: str) -> None:
    if verbose:
        print(msg)


def upload_document(
    doc: Document,
    client: MiroClient,
    has_containment: bool,
    scale: float = 1.0,
    board_id: Optional[str] = None,
    team_id: Optional[str] = None,
    board_name: Optional[str] = None,
    frame_prefix: str = "",
    frame_suffix: str = "",
    icon_map: Optional[Dict[str, str]] = None,
    access: str = "private",
    dry_run: bool = False,
    verbose: bool = False,
) -> Dict[str, Any]:
    """
    Upload *doc* to Miro via the REST API.

    Returns a stats dict with keys:
      board_id, board_url, frames, shapes, texts, images, lines,
      skipped_icons, skipped_lines
    """
    if icon_map is None:
        icon_map = {}

    title   = board_name or doc.title
    result: Dict[str, Any] = {
        "board_id": "", "board_url": "",
        "frames": 0, "shapes": 0, "texts": 0, "images": 0, "lines": 0,
        "skipped_icons": 0, "skipped_lines": 0,
    }

    # ── 1. Create or validate board ──────────────────────────────────────────
    if dry_run:
        result["board_id"]  = board_id or "dry-run-board-id"
        result["board_url"] = f"https://miro.com/app/board/{result['board_id']}/"
        _api_log(verbose, f"[dry-run] Would create board: {title!r}")
    elif board_id:
        info = client.get(f"/v2/boards/{board_id}")
        result["board_id"]  = board_id
        result["board_url"] = info.get("viewLink",
                                       f"https://miro.com/app/board/{board_id}/")
        _api_log(verbose, f"Using existing board: {result['board_url']}")
    else:
        bp: Dict[str, Any] = {
            "name": title,
            "policy": {
                "permissionsPolicy": {
                    "collaborationToolsStartAccess": "all_editors",
                    "copyAccess": "anyone",
                },
                "sharingPolicy": {
                    "access":             access,
                    "organizationAccess": "private" if access == "private" else "view",
                    "teamAccess":         "private" if access == "private" else "view",
                },
            },
        }
        if team_id:
            bp["teamId"] = team_id
        info = client.post("/v2/boards", bp)
        result["board_id"]  = info["id"]
        result["board_url"] = info.get("viewLink",
                                       f"https://miro.com/app/board/{info['id']}/")
        _api_log(verbose, f"Created board: {result['board_url']}")

    board_x = 0.0

    for page in doc.pages:
        if not page.items and not page.lines:
            continue

        # ── 2. Layout ────────────────────────────────────────────────────────
        # VSDX: coordinates pre-set — compute frame from bounding box.
        if doc.has_coordinates:
            frame_w, frame_h = _frame_from_items(page)
        else:
            frame_w, frame_h = _layout_page(page, has_containment)
        if scale != 1.0:
            frame_w *= scale; frame_h *= scale
            for item in page.items:
                item.x *= scale; item.y *= scale
                item.width *= scale; item.height *= scale

        # ── 3. Create frame ──────────────────────────────────────────────────
        fp = _upload_frame_payload(page, board_x + frame_w / 2, frame_w, frame_h,
                                   frame_prefix, frame_suffix)
        if dry_run:
            mfid = f"dry-run-frame-{page.id}"
            _api_log(verbose,
                     f"  [dry-run] Frame: {fp['data']['title']!r} "
                     f"({frame_w:.0f}×{frame_h:.0f})")
        else:
            fr   = client.post(f"/v2/boards/{result['board_id']}/frames", fp)
            mfid = fr["id"]
            _api_log(verbose, f"  Frame: {fp['data']['title']!r} → {mfid}")
        result["frames"] += 1

        # nesting depth helper
        imap: Dict[str, Item] = {it.id: it for it in page.items}
        def _depth(it: Item) -> int:
            d, cur = 0, it.parent_id
            while cur and cur in imap:
                d += 1; cur = imap[cur].parent_id
            return d

        lucid_to_miro: Dict[str, str] = {}

        # ── 4. Shapes / texts / images ───────────────────────────────────────
        for item in page.items:
            if _is_icon_shape(item.name):
                url = _resolve_icon_url(item, icon_map)
                if url is None:
                    result["skipped_icons"] += 1
                    _api_log(verbose,
                             f"    [icon skipped — no URL] {item.id} ({item.name})")
                    continue
                payload  = _upload_image_payload(item, mfid, url)
                endpoint = f"/v2/boards/{result['board_id']}/images"
                wtype    = "images"
            elif _is_text_only(item.name):
                payload  = _upload_text_payload(item, mfid)
                endpoint = f"/v2/boards/{result['board_id']}/texts"
                wtype    = "texts"
            else:
                payload  = _upload_shape_payload(item, mfid, _depth(item))
                endpoint = f"/v2/boards/{result['board_id']}/shapes"
                wtype    = "shapes"

            if dry_run:
                mid = f"dry-run-{item.id}"
                _api_log(verbose,
                         f"    [dry-run] {wtype[:-1]}: {item.text!r} ({item.name})")
            else:
                resp = client.post(endpoint, payload)
                mid  = resp.get("id", "")
                _api_log(verbose, f"    {wtype[:-1]}: {item.text!r} → {mid}")

            lucid_to_miro[item.id] = mid
            result[wtype] += 1

        # ── 5. Connectors ────────────────────────────────────────────────────
        for line in page.lines:
            cp = _upload_connector_payload(line, lucid_to_miro)
            if cp is None:
                result["skipped_lines"] += 1
                continue
            if dry_run:
                _api_log(verbose, f"    [dry-run] connector: {line.text!r}")
            else:
                resp = client.post(
                    f"/v2/boards/{result['board_id']}/connectors", cp
                )
                _api_log(verbose, f"    connector → {resp.get('id', '')}")
            result["lines"] += 1

        board_x += frame_w + FRAME_GAP

    return result


# ═════════════════════════════════════════════════════════════════════════════
# SECTION 9 — CLI
# ═════════════════════════════════════════════════════════════════════════════

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lucid2miro",
        description=(
            "Convert Lucidchart .json or .csv exports to Miro JSON, "
            "or upload directly to Miro via the REST API."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Offline JSON output (default):
  python lucid2miro.py diagram.csv
  python lucid2miro.py diagram.json -o board.json --pretty --summary
  python lucid2miro.py diagram.csv -t "My Board" --scale 1.5 --pages "HA,VPC"

Batch JSON output:
  python lucid2miro.py ./exports/ --format csv --output-dir ./miro/
  python lucid2miro.py ./exports/ --format json --output-dir ./miro/ --summary

REST API upload (direct to Miro):
  export MIRO_TOKEN=<your_token>
  python lucid2miro.py diagram.csv --upload
  python lucid2miro.py diagram.csv --upload --board-name "Q3 Infra" --summary
  python lucid2miro.py diagram.csv --upload --frame-prefix "Sprint 3: "
  python lucid2miro.py diagram.csv --upload --dry-run --summary
  python lucid2miro.py ./exports/ --format csv --upload   # batch upload

See docs/MIRO_AUTH.md for authentication setup.
See docs/LUCIDCHART_FORMATS.md for format guidance.
""",
    )
    p.add_argument("input",
                   help="Path to a .json/.csv file  OR  a directory for batch mode")
    p.add_argument("--format", choices=["csv", "json", "vsdx"],
                   help="(Batch) Input format to look for: csv, json, or vsdx")
    p.add_argument("--output-dir", metavar="DIR",
                   help="(Batch, offline) Directory to write converted files into")
    p.add_argument("-o", "--output", metavar="FILE",
                   help="(Single, offline) Output file path (default: <input>.miro.json)")
    p.add_argument("-t", "--title", metavar="TITLE",
                   help="Miro board title (default: document title from source)")
    p.add_argument("-s", "--scale", metavar="N", type=float, default=1.0,
                   help="Uniform scale factor for all coordinates (default: 1.0)")
    p.add_argument("--pretty",  action="store_true",
                   help="(Offline) Pretty-print the output JSON")
    p.add_argument("--summary", action="store_true",
                   help="Print a conversion / upload summary (per file in batch mode)")
    p.add_argument("--pages", metavar="N[,N]",
                   help="Comma-separated page titles or 1-based indices to include")
    p.add_argument("--clean-names", action="store_true",
                   help="(Offline) Use source stem + .json instead of stem + .miro.json. "
                        "In batch mode requires --output-dir to differ from input directory.")
    # ── Upload mode flags ────────────────────────────────────────────────────
    p.add_argument("--upload", action="store_true",
                   help="Upload directly to Miro via REST API instead of writing local JSON")
    p.add_argument("--token", metavar="TOKEN",
                   help="Miro Personal Access Token (default: MIRO_TOKEN env var). "
                        "See docs/MIRO_AUTH.md")
    p.add_argument("--team-id", metavar="TEAM_ID",
                   help="(Upload) Miro team/workspace ID to create the board in")
    p.add_argument("--board-id", metavar="BOARD_ID",
                   help="(Upload) Upload into an existing board (default: create new board)")
    p.add_argument("--board-name", metavar="NAME",
                   help="(Upload) Override board title (overrides --title in upload mode)")
    p.add_argument("--frame-prefix", metavar="PREFIX", default="",
                   help="(Upload) Text prepended to each frame name, e.g. 'Sprint 3: '")
    p.add_argument("--frame-suffix", metavar="SUFFIX", default="",
                   help="(Upload) Text appended to each frame name")
    p.add_argument("--icon-map", metavar="FILE",
                   help="(Upload) JSON file mapping shape IDs/names to image URLs. "
                        "See docs/MIRO_AUTH.md § Custom icons")
    p.add_argument("--access", choices=["private", "view", "comment", "edit"],
                   default="private",
                   help="(Upload) Board sharing policy for new boards (default: private)")
    p.add_argument("--dry-run", action="store_true",
                   help="(Upload) Simulate upload — print what would be created, "
                        "no API calls made")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _filter_pages(doc: Document, spec: str) -> None:
    wanted = {s.strip() for s in spec.split(",")}
    doc.pages = [p for i, p in enumerate(doc.pages, 1)
                 if str(i) in wanted or p.title in wanted]


def _parse_file(path: Path):
    """Return (Document, has_containment) for any supported input format."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return parse_csv(path), True
    if suffix == ".json":
        return parse_json(path), False
    if suffix == ".vsdx":
        return parse_vsdx(path), True   # has_containment=True; layout skipped via has_coordinates
    raise ValueError(f"Unsupported file type '{suffix}'. Use .csv, .json, or .vsdx.")


def _convert_file(input_path: Path, output_path: Path, args) -> Dict[str, Any]:
    doc, has_containment = _parse_file(input_path)
    if getattr(args, "title", None):
        doc.title = args.title
    if getattr(args, "pages", None):
        _filter_pages(doc, args.pages)
        if not doc.pages:
            raise ValueError("--pages filter matched no pages")
    board = convert(doc, has_containment=has_containment, scale=args.scale)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(board, indent=2 if args.pretty else None, ensure_ascii=False),
        encoding="utf-8",
    )
    widgets = board["board"]["widgets"]

    # VSDX: extract embedded icons to a sibling directory
    icon_stats = _maybe_extract_icons(doc, input_path)

    return {
        "doc": doc, "board": board,
        "frames":  sum(1 for w in widgets if w["type"] == "frame"),
        "shapes":  sum(1 for w in widgets if w["type"] == "shape"),
        "texts":   sum(1 for w in widgets if w["type"] == "text"),
        "images":  sum(1 for w in widgets if w["type"] == "image"),
        "lines":   sum(1 for w in widgets if w["type"] == "line"),
        "icon_stats": icon_stats,
    }


def _maybe_extract_icons(doc: Document, input_path: Path) -> Optional[Dict[str, Any]]:
    """
    If *doc* contains VSDX icon items with embedded image data, write them
    to <input_stem>_icons/ and generate an icon-map template JSON.
    Returns a stats dict, or None if nothing was extracted.
    """
    if not doc.has_coordinates:
        return None
    icon_items = [item for page in doc.pages for item in page.items
                  if item.is_icon and item.image_data]
    if not icon_items:
        return None

    icons_dir = input_path.parent / f"{input_path.stem}_icons"
    written   = _vextract_media(doc, icons_dir)

    icon_map_path = input_path.parent / f"{input_path.stem}_icon_map.json"
    icon_map = {
        "by_id": {iid: f"<HOST_URL>/{p.name}" for iid, p in written.items()},
        "default": "",
        "_instructions": (
            "Replace <HOST_URL> with the base URL where you host the extracted "
            f"icons from {icons_dir.name}/, then pass: --icon-map {icon_map_path.name}"
        ),
    }
    icon_map_path.write_text(json.dumps(icon_map, indent=2), encoding="utf-8")

    return {"icons_dir": icons_dir, "icon_map": icon_map_path, "count": len(written)}


def _print_summary(input_path: Path, output_path: Path, fmt: str, stats: Dict) -> None:
    doc     = stats["doc"]
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
    if stats.get("icon_stats"):
        ic = stats["icon_stats"]
        print(f"  Icons extracted : {ic['count']} → {ic['icons_dir'].name}/")
        print(f"  Icon map template → {ic['icon_map'].name}")
        print(f"  Host the icons and update the map, then use:")
        print(f"    --icon-map {ic['icon_map'].name}")
    print()


def _run_single(args) -> None:
    input_path = Path(args.input)
    suffix     = input_path.suffix.lower()
    if suffix not in (".json", ".csv", ".vsdx"):
        sys.exit(f"Error: unsupported file type '{suffix}'. Use .csv, .json, or .vsdx.")

    # Resolve to an absolute path so symlink traversal and ".." segments are
    # made explicit before the file is written.
    if args.output:
        output_path = Path(args.output).resolve()
    elif args.clean_names:
        output_path = input_path.with_suffix(".json").resolve()
        if output_path == input_path.resolve():
            sys.exit(
                "Error: --clean-names would overwrite the source file.\n"
                "       Use -o to specify a different output path."
            )
    else:
        output_path = input_path.with_suffix(".miro.json").resolve()

    try:
        stats = _convert_file(input_path, output_path, args)
    except Exception as exc:
        sys.exit(f"Error: {exc}")

    if args.summary:
        _print_summary(input_path, output_path, suffix.lstrip("."), stats)
    else:
        print(f"Written → {output_path}")
        if stats.get("icon_stats"):
            ic = stats["icon_stats"]
            print(f"  Icons   → {ic['icons_dir']}/ ({ic['count']} files)")
            print(f"  Icon map template → {ic['icon_map']}")


def _run_batch(args) -> None:
    input_dir = Path(args.input)

    if not args.format:
        sys.exit("Error: --format csv|json is required in batch mode.")

    output_dir = Path(args.output_dir).resolve() if args.output_dir else input_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # --clean-names is only safe when outputs land in a different directory,
    # otherwise .json source files would be silently overwritten.
    if args.clean_names and output_dir == input_dir.resolve():
        sys.exit(
            "Error: --clean-names requires --output-dir to be a different directory "
            "from the input directory to avoid overwriting source files."
        )

    input_files = sorted(input_dir.glob(f"*.{args.format}"))
    if not input_files:
        sys.exit(f"Error: no .{args.format} files found in {input_dir}")

    ok, fail, failures = 0, 0, []
    col_w = max(len(f.name) for f in input_files)

    print(f"\nBatch converting {len(input_files)} .{args.format} file(s)")
    print(f"  Input dir  : {input_dir.resolve()}")
    print(f"  Output dir : {output_dir}\n")

    out_suffix = ".json" if args.clean_names else ".miro.json"

    for input_path in input_files:
        output_path = (output_dir / input_path.stem).with_suffix(out_suffix).resolve()
        try:
            output_path.relative_to(output_dir)   # raises ValueError if outside
        except ValueError:
            print(f"  ✗  {input_path.name.ljust(col_w)}  —  SKIPPED: output path escapes output dir")
            fail += 1
            failures.append((input_path.name, "output path escapes output_dir"))
            continue
        try:
            stats = _convert_file(input_path, output_path, args)
            ok += 1
            if args.summary:
                _print_summary(input_path, output_path, args.format, stats)
            else:
                print(f"  ✓  {input_path.name.ljust(col_w)}  →  {output_path.name}")
        except Exception as exc:
            fail += 1
            failures.append((input_path.name, str(exc)))
            print(f"  ✗  {input_path.name.ljust(col_w)}  —  ERROR: {exc}")

    print(f"\nDone — {ok} succeeded, {fail} failed out of {len(input_files)} file(s)")
    if failures:
        print("\nFailed files:")
        for name, err in failures:
            print(f"  {name}: {err}")
        print()
        sys.exit(1)


def _print_upload_summary(input_path: Path, stats: Dict[str, Any]) -> None:
    print()
    print("Lucidchart → Miro upload summary")
    print("──────────────────────────────────")
    print(f"  Source  : {input_path}")
    print(f"  Board   : {stats['board_url']}")
    print(f"  Frames  : {stats['frames']}")
    print(f"  Shapes  : {stats['shapes']}")
    print(f"  Text    : {stats['texts']}")
    print(f"  Images  : {stats['images']}")
    print(f"  Lines   : {stats['lines']}")
    if stats.get("skipped_icons"):
        print(f"  Skipped icons : {stats['skipped_icons']}  (no URL — use --icon-map)")
    if stats.get("skipped_lines"):
        print(f"  Skipped lines : {stats['skipped_lines']}  (both endpoints unresolved)")
    print()


def _run_upload(args) -> None:
    """Upload a single file or batch directory directly to Miro via REST API."""
    token = getattr(args, "token", None) or os.environ.get("MIRO_TOKEN", "")
    dry_run = getattr(args, "dry_run", False)

    if not dry_run:
        try:
            client = MiroClient(token)
        except MiroAuthError as exc:
            sys.exit(f"Auth error: {exc}")
    else:
        # Dry-run does not validate the token — create a dummy client
        class _DryClient:  # type: ignore[no-redef]
            def get(self, *a, **kw):  return {}
            def post(self, *a, **kw): return {}
        client = _DryClient()  # type: ignore[assignment]

    icon_map: Dict[str, str] = {}
    if getattr(args, "icon_map", None):
        try:
            icon_map = _load_icon_map(args.icon_map)
        except (ValueError, OSError) as exc:
            sys.exit(f"Error loading --icon-map: {exc}")

    frame_prefix = getattr(args, "frame_prefix", "") or ""
    frame_suffix = getattr(args, "frame_suffix", "") or ""
    access       = getattr(args, "access", "private") or "private"
    board_id     = getattr(args, "board_id", None)
    team_id      = getattr(args, "team_id", None)
    board_name   = getattr(args, "board_name", None) or getattr(args, "title", None)
    verbose      = getattr(args, "summary", False) or dry_run

    input_path = Path(args.input)
    is_batch   = input_path.is_dir()

    def _upload_one(fpath: Path) -> Dict[str, Any]:
        doc, has_cont = _parse_file(fpath)
        if board_name:
            doc.title = board_name
        if getattr(args, "pages", None):
            _filter_pages(doc, args.pages)
            if not doc.pages:
                raise ValueError("--pages filter matched no pages")
        return upload_document(
            doc, client, has_cont,
            scale=args.scale,
            board_id=board_id,
            team_id=team_id,
            board_name=doc.title,
            frame_prefix=frame_prefix,
            frame_suffix=frame_suffix,
            icon_map=icon_map,
            access=access,
            dry_run=dry_run,
            verbose=verbose,
        )

    if is_batch:
        if not args.format:
            sys.exit("Error: --format csv|json is required in batch mode.")
        files = sorted(input_path.glob(f"*.{args.format}"))
        if not files:
            sys.exit(f"Error: no .{args.format} files found in {input_path}")

        label = "Dry-run simulating" if dry_run else "Uploading"
        print(f"\n{label} {len(files)} .{args.format} file(s) to Miro")
        if dry_run:
            print("  [dry-run mode — no API calls will be made]\n")

        ok = fail = 0
        col_w = max(len(f.name) for f in files)
        for fpath in files:
            try:
                stats = _upload_one(fpath)
                ok += 1
                if args.summary:
                    _print_upload_summary(fpath, stats)
                else:
                    dest = "[dry-run]" if dry_run else stats["board_url"]
                    print(f"  ✓  {fpath.name.ljust(col_w)}  →  {dest}")
            except (MiroAuthError, MiroAPIError) as exc:
                fail += 1
                print(f"  ✗  {fpath.name.ljust(col_w)}  —  Miro API error: {exc}")
            except Exception as exc:
                fail += 1
                print(f"  ✗  {fpath.name.ljust(col_w)}  —  ERROR: {exc}")

        print(f"\nDone — {ok} succeeded, {fail} failed out of {len(files)} file(s)")
        if fail:
            sys.exit(1)

    else:
        suffix = input_path.suffix.lower()
        if suffix not in (".json", ".csv", ".vsdx"):
            sys.exit(f"Error: unsupported file type '{suffix}'. Use .csv, .json, or .vsdx.")
        if dry_run:
            print(f"[dry-run] Simulating upload of: {input_path}")
        try:
            stats = _upload_one(input_path)
        except (MiroAuthError, MiroAPIError) as exc:
            sys.exit(f"Miro API error: {exc}")
        except Exception as exc:
            sys.exit(f"Error: {exc}")

        if args.summary:
            _print_upload_summary(input_path, stats)
        else:
            dest = "[dry-run — no board created]" if dry_run else stats["board_url"]
            label = "Would upload to" if dry_run else "Uploaded to"
            print(f"{label}: {dest}")


def main(argv=None) -> None:
    args       = _build_parser().parse_args(argv)
    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"Error: path not found — {input_path}")
    if getattr(args, "upload", False) or getattr(args, "dry_run", False):
        _run_upload(args)
    elif input_path.is_dir():
        _run_batch(args)
    else:
        _run_single(args)


if __name__ == "__main__":
    main()
