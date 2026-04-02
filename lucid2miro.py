#!/usr/bin/env python3
"""
lucid2miro — Convert Lucidchart exports to Miro-importable JSON.

Self-contained single file. No third-party packages required.
Works on macOS, Windows, and Linux (Python 3.8+).

Supported input formats:
  .csv    Lucidchart CSV export   (File → Export → CSV)
  .json   Lucidchart JSON export  (File → Export → JSON)

Single-file usage:
  python lucid2miro.py diagram.csv
  python lucid2miro.py diagram.json -o board.json --pretty --summary

Batch usage (pass a directory):
  python lucid2miro.py ./exports/ --format csv --output-dir ./miro/
  python lucid2miro.py ./exports/ --format json --output-dir ./miro/ --summary
"""
from __future__ import annotations

# ── Standard-library imports (only) ──────────────────────────────────────────
import argparse
import csv
import io
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

__version__ = "1.3.0"

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
    # Set by layout engine:
    x:      float = 0
    y:      float = 0
    width:  float = 0
    height: float = 0


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
# SECTION 7 — CLI
# ═════════════════════════════════════════════════════════════════════════════

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

Batch examples (pass a directory as input):
  python lucid2miro.py ./exports/ --format csv --output-dir ./miro/
  python lucid2miro.py ./exports/ --format json --output-dir ./miro/ --summary
""",
    )
    p.add_argument("input",
                   help="Path to a .json/.csv file  OR  a directory for batch mode")
    p.add_argument("--format", choices=["csv", "json"],
                   help="(Batch) Input format to look for: csv or json")
    p.add_argument("--output-dir", metavar="DIR",
                   help="(Batch) Directory to write converted files into")
    p.add_argument("-o", "--output", metavar="FILE",
                   help="(Single) Output file path (default: <input>.miro.json)")
    p.add_argument("-t", "--title", metavar="TITLE",
                   help="Miro board title (default: document title from source)")
    p.add_argument("-s", "--scale", metavar="N", type=float, default=1.0,
                   help="Uniform scale factor for all coordinates (default: 1.0)")
    p.add_argument("--pretty",  action="store_true", help="Pretty-print the output JSON")
    p.add_argument("--summary", action="store_true",
                   help="Print a conversion summary (per file in batch mode)")
    p.add_argument("--pages", metavar="N[,N]",
                   help="(Single) Comma-separated page titles or 1-based indices to include")
    p.add_argument("--clean-names", action="store_true",
                   help="Use source stem + .json as output name instead of stem + .miro.json. "
                        "In batch mode requires --output-dir to differ from input directory "
                        "to avoid overwriting source files.")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def _filter_pages(doc: Document, spec: str) -> None:
    wanted = {s.strip() for s in spec.split(",")}
    doc.pages = [p for i, p in enumerate(doc.pages, 1)
                 if str(i) in wanted or p.title in wanted]


def _parse_file(path: Path):
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return parse_csv(path), True
    if suffix == ".json":
        return parse_json(path), False
    raise ValueError(f"Unsupported file type '{suffix}'. Use .json or .csv.")


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
    return {
        "doc": doc, "board": board,
        "frames": sum(1 for w in widgets if w["type"] == "frame"),
        "shapes": sum(1 for w in widgets if w["type"] == "shape"),
        "texts":  sum(1 for w in widgets if w["type"] == "text"),
        "images": sum(1 for w in widgets if w["type"] == "image"),
        "lines":  sum(1 for w in widgets if w["type"] == "line"),
    }


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
    print()


def _run_single(args) -> None:
    input_path = Path(args.input)
    suffix     = input_path.suffix.lower()
    if suffix not in (".json", ".csv"):
        sys.exit(f"Error: unsupported file type '{suffix}'. Use .json or .csv.")

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


def main(argv=None) -> None:
    args       = _build_parser().parse_args(argv)
    input_path = Path(args.input)
    if not input_path.exists():
        sys.exit(f"Error: path not found — {input_path}")
    if input_path.is_dir():
        _run_batch(args)
    else:
        _run_single(args)


if __name__ == "__main__":
    main()
