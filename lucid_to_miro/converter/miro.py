"""
Converts a normalised Document into Miro-importable JSON.

Output structure (Miro REST API v2 style):
{
  "version": "1",
  "board": {
    "title": "...",
    "widgets": [ <MiroWidget>, ... ]
  }
}

One Miro Frame is created per Lucidchart page/tab.
Frames are placed side-by-side horizontally with FRAME_GAP px spacing.
All child widgets carry a parentId referencing their frame.
"""
from __future__ import annotations

import re
from typing import Any

from lucid_to_miro.model import Document, Page, Item, Line
from lucid_to_miro.converter.layout import layout_page, frame_from_items, FRAME_GAP
from lucid_to_miro.converter.shape_map import to_miro_shape, is_text_only, is_icon

# Colours for auto-generated container fills (cycled per nesting depth)
_CONTAINER_FILLS = [
    "#EEF4FB",   # very light blue
    "#F0F9EE",   # very light green
    "#FEF9EC",   # very light amber
    "#F9EEFF",   # very light purple
]

# Arrow head token → Miro lineEndType
_ARROW_MAP = {
    "none":           "none",
    "arrow":          "arrow",
    "open_arrow":     "open_arrow",
    "filled_triangle":"filled_triangle",
    "filled_diamond": "filled_diamond",
    "open_diamond":   "open_diamond",
    "circle":         "circle",
}


def _sanitise(text: str) -> str:
    """Strip HTML tags that Lucidchart sometimes injects into text areas."""
    return re.sub(r"<[^>]*>", "", text or "").strip()


def _container_fill(depth: int) -> str:
    return _CONTAINER_FILLS[depth % len(_CONTAINER_FILLS)]


def _build_item_widget(item: Item, frame_id: str, board_offset_x: float,
                       depth: int = 0) -> dict[str, Any]:
    """Build a single Miro widget dict for a shape/icon/text Item."""
    abs_x = round(item.x + board_offset_x)
    abs_y = round(item.y)
    w     = max(1, round(item.width))
    h     = max(1, round(item.height))
    label = _sanitise(item.text)

    # Extra text lines appended with line breaks
    if item.extra_text:
        extra = "\n".join(_sanitise(t) for t in item.extra_text if t.strip())
        if extra:
            label = f"{label}\n{extra}".strip()

    if is_icon(item.name):
        return {
            "type":     "image",
            "id":       item.id or None,
            "parentId": frame_id,
            "data":     {"title": label},
            "style":    {"backgroundColor": "#ffffff"},
            "position": {"x": abs_x, "y": abs_y},
            "geometry": {"width": w, "height": h},
        }

    if is_text_only(item.name):
        return {
            "type":     "text",
            "id":       item.id or None,
            "parentId": frame_id,
            "data":     {"content": label},
            "style":    {
                "color":      "#000000",
                "fontSize":   14,
                "textAlign":  "left",
                "fontFamily": "arial",
            },
            "position": {"x": abs_x, "y": abs_y},
            "geometry": {"width": w, "height": h},
        }

    shape_type = to_miro_shape(item.name)
    fill_color = _container_fill(depth) if item.is_container else "#ffffff"

    return {
        "type":     "shape",
        "id":       item.id or None,
        "parentId": frame_id,
        "data":     {"shape": shape_type, "content": label},
        "style":    {
            "fillColor":    fill_color,
            "borderColor":  "#555555" if item.is_container else "#000000",
            "borderWidth":  2 if item.is_container else 1,
            "borderStyle":  "normal",
            "fillOpacity":  1,
            "fontSize":     13 if item.is_container else 14,
            "color":        "#333333" if item.is_container else "#000000",
            "textAlign":    "left" if item.is_container else "center",
            "textAlignVertical": "top" if item.is_container else "middle",
            "fontFamily":   "arial",
        },
        "position": {"x": abs_x, "y": abs_y},
        "geometry": {"width": w, "height": h},
    }


def _build_line_widget(line: Line, frame_id: str,
                       item_lookup: dict[str, Item],
                       board_offset_x: float) -> dict[str, Any] | None:
    """Build a Miro line widget.  Returns None if both endpoints are unresolvable."""

    def _centre(item: Item) -> tuple[float, float]:
        return (
            round(item.x + item.width / 2 + board_offset_x),
            round(item.y + item.height / 2),
        )

    src = item_lookup.get(line.source_id) if line.source_id else None
    tgt = item_lookup.get(line.target_id) if line.target_id else None

    if src is None and tgt is None:
        if line.start_x is None or line.start_y is None or line.end_x is None or line.end_y is None:
            return None
        sx, sy = (round(line.start_x + board_offset_x), round(line.start_y))
        ex, ey = (round(line.end_x + board_offset_x), round(line.end_y))
    else:
        if src is not None:
            sx, sy = _centre(src)
        else:
            sx, sy = (round((line.start_x or 100) + board_offset_x), round(line.start_y or 100))

        if tgt is not None:
            ex, ey = _centre(tgt)
        else:
            ex, ey = (round((line.end_x or 200) + board_offset_x), round(line.end_y or 200))

    return {
        "type":     "line",
        "id":       line.id or None,
        "parentId": frame_id,
        "data": {
            "content":    _sanitise(line.text),
            "startShapeId": line.source_id,
            "endShapeId":   line.target_id,
        },
        "style": {
            "lineColor":     "#444444",
            "lineThickness": 1,
            "lineStyle":     "normal",
            "lineStartType": _ARROW_MAP.get(line.source_arrow, "none"),
            "lineEndType":   _ARROW_MAP.get(line.target_arrow, "arrow"),
        },
        "startPosition": {"x": sx, "y": sy},
        "endPosition":   {"x": ex, "y": ey},
    }


def convert(doc: Document, has_containment: bool = True,
            scale: float = 1.0) -> dict[str, Any]:
    """
    Convert a normalised Document to a Miro board JSON dict.

    Args:
        doc:             Parsed document (from CSV or JSON parser).
        has_containment: True for CSV (parent_id populated), False for JSON.
        scale:           Optional uniform scale factor.

    Returns:
        Dict ready for json.dumps().
    """
    widgets: list[dict[str, Any]] = []
    board_x = 0.0   # running horizontal offset for successive frames

    for page in doc.pages:
        # Skip empty pages
        if not page.items and not page.lines:
            continue

        # ── Layout ──────────────────────────────────────────────────────────
        # VSDX input: coordinates already set by parser — just compute frame size.
        # CSV / JSON input: run the auto-layout engine.
        if doc.has_coordinates:
            frame_w, frame_h = frame_from_items(page)
        else:
            frame_w, frame_h = layout_page(page, has_containment)

        if scale != 1.0:
            frame_w *= scale
            frame_h *= scale
            for item in page.items:
                item.x      *= scale
                item.y      *= scale
                item.width  *= scale
                item.height *= scale

        frame_id = f"frame_{page.id}"

        # ── Frame widget ─────────────────────────────────────────────────────
        widgets.append({
            "type":     "frame",
            "id":       frame_id,
            "title":    page.title,
            "style":    {"fillColor": "#f5f5f5"},
            "position": {"x": round(board_x), "y": 0},
            "geometry": {"width": round(frame_w), "height": round(frame_h)},
        })

        # Build item lookup for line endpoint resolution
        item_lookup: dict[str, Item] = {it.id: it for it in page.items}

        # ── Shape / icon / text widgets ──────────────────────────────────────
        for item in page.items:
            # Determine nesting depth for container fill colour
            depth  = 0
            cursor = item.parent_id
            while cursor and cursor in item_lookup:
                depth += 1
                cursor = item_lookup[cursor].parent_id

            widgets.append(_build_item_widget(item, frame_id, board_x, depth))

        # ── Line / connector widgets ─────────────────────────────────────────
        for line in page.lines:
            w = _build_line_widget(line, frame_id, item_lookup, board_x)
            if w:
                widgets.append(w)

        board_x += frame_w + FRAME_GAP

    return {
        "version": "1",
        "board":   {"title": doc.title, "widgets": widgets},
    }
