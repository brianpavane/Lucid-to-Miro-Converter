"""
Miro REST API uploader.

Converts a parsed Document into live Miro board content by calling the
Miro REST API v2.  Each Lucidchart page becomes a Miro Frame; each shape,
text block, icon, and connector is created via its own API call.

Coordinate notes
----------------
The layout engine (layout.py) assigns top-left origin coordinates.
The Miro REST API v2 uses CENTER coordinates for item positioning.
This module converts:
    center_x = item.x + item.width  / 2
    center_y = item.y + item.height / 2

When a child item has a parent frame, its position is relative to the
frame's top-left corner (not the board's origin).

Custom icons
------------
Lucidchart exports do not embed image data.  To restore custom icons,
supply an icon map JSON file (see docs/LUCIDCHART_FORMATS.md § Icons):

    {
      "by_id":   { "<lucid_shape_id>": "https://cdn.example.com/icon.png" },
      "by_name": { "AmazonEC2": "https://cdn.example.com/ec2.png" },
      "default": "https://cdn.example.com/placeholder.png"
    }

Icons without a resolved URL are counted in skipped_icons and omitted
from the Miro board.  Pass --summary to see per-upload counts.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from lucid_to_miro.api.miro_client import MiroClient
from lucid_to_miro.converter.layout import layout_page, frame_from_items, FRAME_GAP
from lucid_to_miro.converter.shape_map import to_miro_shape, is_text_only, is_icon
from lucid_to_miro.model import Document, Item, Line, Page

# ── Container fill colours (cycled per nesting depth) ─────────────────────────
_CONTAINER_FILLS = ["#EEF4FB", "#F0F9EE", "#FEF9EC", "#F9EEFF"]

# ── Lucidchart arrow token → Miro connector stroke cap ───────────────────────
_CONNECTOR_CAPS: Dict[str, str] = {
    "none":            "none",
    "arrow":           "arrow",
    "open_arrow":      "open_arrow",
    "filled_triangle": "filled_arrow",
    "filled_diamond":  "filled_diamond",
    "open_diamond":    "open_diamond",
    "circle":          "circle",
}


# ── Result type ───────────────────────────────────────────────────────────────

class UploadResult:
    """Summary returned by upload_document()."""
    __slots__ = (
        "board_id", "board_url",
        "frames", "shapes", "texts", "images", "lines",
        "skipped_icons", "skipped_lines",
    )

    def __init__(self) -> None:
        self.board_id:      str = ""
        self.board_url:     str = ""
        self.frames:        int = 0
        self.shapes:        int = 0
        self.texts:         int = 0
        self.images:        int = 0
        self.lines:         int = 0
        self.skipped_icons: int = 0
        self.skipped_lines: int = 0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sanitise(text: str) -> str:
    """Strip HTML tags that Lucidchart sometimes injects into text areas."""
    return re.sub(r"<[^>]*>", "", text or "").strip()


def _label(item: Item) -> str:
    """Build a full text label from primary + extra text areas."""
    parts = [_sanitise(item.text)]
    for t in item.extra_text:
        s = _sanitise(t)
        if s:
            parts.append(s)
    return "\n".join(p for p in parts if p)


def _container_fill(depth: int) -> str:
    return _CONTAINER_FILLS[depth % len(_CONTAINER_FILLS)]


def load_icon_map(path: Optional[str]) -> Dict[str, str]:
    """
    Load an icon map JSON file and return a flat {key: url} dict.

    The file format is::

        {
            "by_id":   {"<lucid_shape_id>": "https://..."},
            "by_name": {"AmazonEC2": "https://..."},
            "default": "https://..."
        }

    Returns an empty dict if *path* is None.
    Raises ValueError if the file does not exist or cannot be parsed.
    """
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
    """Return an image URL for *item*, or None if no mapping exists."""
    if item.id   and item.id   in icon_map:
        return icon_map[item.id]
    if item.name and item.name in icon_map:
        return icon_map[item.name]
    return icon_map.get("__default__")


# ── API payload builders ───────────────────────────────────────────────────────

def _frame_payload(
    page: Page,
    board_center_x: float,
    frame_w: float,
    frame_h: float,
    prefix: str,
    suffix: str,
) -> Dict[str, Any]:
    title = f"{prefix}{page.title}{suffix}".strip()
    return {
        "data": {"format": "custom", "title": title, "type": "freeform"},
        "style": {"fillColor": "#f5f5f5"},
        # Miro frame position is its CENTER on the board
        "position": {"x": board_center_x, "y": frame_h / 2, "origin": "center"},
        "geometry": {"width": frame_w, "height": frame_h},
    }


def _shape_payload(
    item: Item,
    miro_frame_id: str,
    depth: int,
) -> Dict[str, Any]:
    fill = _container_fill(depth) if item.is_container else "#ffffff"
    return {
        "data": {
            "content": _label(item),
            "shape":   to_miro_shape(item.name),
        },
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
        # Position is CENTER, relative to parent frame's top-left
        "position": {
            "x":      item.x + item.width  / 2,
            "y":      item.y + item.height / 2,
            "origin": "center",
        },
        "geometry": {"width": item.width, "height": item.height},
        "parent":   {"id": miro_frame_id},
    }


def _text_payload(item: Item, miro_frame_id: str) -> Dict[str, Any]:
    return {
        "data": {"content": _label(item)},
        "style": {
            "color":      "#000000",
            "fillColor":  "transparent",
            "fontSize":   "14",
            "fontFamily": "open_sans",
        },
        "position": {
            "x":      item.x + item.width  / 2,
            "y":      item.y + item.height / 2,
            "origin": "center",
        },
        "geometry": {"width": item.width, "height": item.height},
        "parent":   {"id": miro_frame_id},
    }


def _image_payload(item: Item, miro_frame_id: str, image_url: str) -> Dict[str, Any]:
    return {
        "data": {"imageUrl": image_url, "title": _label(item)},
        "position": {
            "x":      item.x + item.width  / 2,
            "y":      item.y + item.height / 2,
            "origin": "center",
        },
        "geometry": {"width": item.width, "height": item.height},
        "parent":   {"id": miro_frame_id},
    }


def _connector_payload(
    line: Line,
    lucid_to_miro: Dict[str, str],
) -> Optional[Dict[str, Any]]:
    """
    Build a Miro connector payload.

    Returns None if neither endpoint can be resolved to a Miro item ID
    (both endpoints unresolvable → line is dropped).
    """
    src_miro = lucid_to_miro.get(line.source_id) if line.source_id else None
    tgt_miro = lucid_to_miro.get(line.target_id) if line.target_id else None
    if src_miro is None and tgt_miro is None:
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
    if src_miro:
        payload["startItem"] = {"id": src_miro, "snapTo": "auto"}
    if tgt_miro:
        payload["endItem"]   = {"id": tgt_miro, "snapTo": "auto"}
    label = _sanitise(line.text)
    if label:
        payload["captions"] = [{"content": label, "position": "50"}]
    return payload


# ── Main upload entry point ───────────────────────────────────────────────────

def upload_document(
    doc: Document,
    client: MiroClient,
    has_containment: bool,
    *,
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
) -> UploadResult:
    """
    Upload *doc* to a Miro board and return an UploadResult.

    Parameters
    ----------
    doc:
        Parsed Document (output of parse_csv / parse_json).
    client:
        Authenticated MiroClient instance.
    has_containment:
        True for CSV-parsed documents (parent_id populated);
        False for JSON-parsed documents.
    scale:
        Uniform coordinate scale factor (default 1.0).
    board_id:
        Upload into this existing board.  If omitted, a new board is created.
    team_id:
        Miro team / workspace ID for new board creation.  If omitted, the
        token's default workspace is used.
    board_name:
        Override the board title (default: doc.title).
    frame_prefix:
        Text prepended to every frame title, e.g. ``"Sprint 3: "``.
    frame_suffix:
        Text appended to every frame title.
    icon_map:
        Flat ``{id_or_name: url}`` dict (from load_icon_map()).  Icons
        without a URL are skipped and counted in result.skipped_icons.
    access:
        Board sharing policy for new boards:
        ``"private"`` | ``"view"`` | ``"comment"`` | ``"edit"``.
    dry_run:
        If True, lay out the document and print what would be created
        but make no API calls.
    verbose:
        Print per-item progress lines.

    Returns
    -------
    UploadResult
        Contains board_url and per-type item counts.
    """
    if icon_map is None:
        icon_map = {}

    result = UploadResult()
    title  = board_name or doc.title

    # ── 1. Create or validate board ───────────────────────────────────────────
    if dry_run:
        result.board_id  = board_id or "dry-run-board-id"
        result.board_url = f"https://miro.com/app/board/{result.board_id}/"
        _log(verbose, f"[dry-run] Would create board: {title!r}")
    elif board_id:
        info = client.get(f"/v2/boards/{board_id}")
        result.board_id  = board_id
        result.board_url = info.get("viewLink", f"https://miro.com/app/board/{board_id}/")
        _log(verbose, f"Using existing board: {result.board_url}")
    else:
        board_policy: Dict[str, Any] = {
            "permissionsPolicy": {
                "collaborationToolsStartAccess": "all_editors",
                "copyAccess": "anyone",
            },
            "sharingPolicy": {
                "access":               access,
                "organizationAccess":   "private" if access == "private" else "view",
                "teamAccess":           "private" if access == "private" else "view",
            },
        }
        board_payload: Dict[str, Any] = {"name": title, "policy": board_policy}
        if team_id:
            board_payload["teamId"] = team_id

        board_info       = client.post("/v2/boards", board_payload)
        result.board_id  = board_info["id"]
        result.board_url = board_info.get(
            "viewLink", f"https://miro.com/app/board/{result.board_id}/"
        )
        _log(verbose, f"Created board: {result.board_url}")

    board_x = 0.0  # running horizontal offset for successive frames

    for page in doc.pages:
        if not page.items and not page.lines:
            continue

        # ── 2. Layout ─────────────────────────────────────────────────────────
        # VSDX: coordinates already set — compute frame size from bounding box.
        # CSV / JSON: run the auto-layout engine.
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

        # ── 3. Create frame ───────────────────────────────────────────────────
        center_x = board_x + frame_w / 2
        fpayload = _frame_payload(
            page, center_x, frame_w, frame_h, frame_prefix, frame_suffix
        )

        if dry_run:
            miro_frame_id = f"dry-run-frame-{page.id}"
            _log(
                verbose,
                f"  [dry-run] Frame: {fpayload['data']['title']!r} "
                f"({frame_w:.0f} × {frame_h:.0f})",
            )
        else:
            frame_resp    = client.post(f"/v2/boards/{result.board_id}/frames", fpayload)
            miro_frame_id = frame_resp["id"]
            _log(verbose, f"  Frame: {fpayload['data']['title']!r} → {miro_frame_id}")

        result.frames += 1

        # ── 4. Nesting depth helper ───────────────────────────────────────────
        item_by_id: Dict[str, Item] = {it.id: it for it in page.items}

        def _depth(it: Item) -> int:
            d, cursor = 0, it.parent_id
            while cursor and cursor in item_by_id:
                d     += 1
                cursor = item_by_id[cursor].parent_id
            return d

        # lucid_id → miro_id — built during shape creation for connector routing
        lucid_to_miro: Dict[str, str] = {}

        # ── 5. Create shapes / texts / images ─────────────────────────────────
        for item in page.items:
            if is_icon(item.name):
                url = _resolve_icon_url(item, icon_map)
                if url is None:
                    result.skipped_icons += 1
                    _log(verbose, f"    [icon skipped — no URL] {item.id} ({item.name})")
                    continue
                payload  = _image_payload(item, miro_frame_id, url)
                endpoint = f"/v2/boards/{result.board_id}/images"
                wtype    = "images"

            elif is_text_only(item.name):
                payload  = _text_payload(item, miro_frame_id)
                endpoint = f"/v2/boards/{result.board_id}/texts"
                wtype    = "texts"

            else:
                payload  = _shape_payload(item, miro_frame_id, _depth(item))
                endpoint = f"/v2/boards/{result.board_id}/shapes"
                wtype    = "shapes"

            if dry_run:
                miro_item_id = f"dry-run-{item.id}"
                _log(verbose, f"    [dry-run] {wtype[:-1]}: {item.text!r} ({item.name})")
            else:
                resp         = client.post(endpoint, payload)
                miro_item_id = resp.get("id", "")
                _log(verbose, f"    {wtype[:-1]}: {item.text!r} → {miro_item_id}")

            lucid_to_miro[item.id] = miro_item_id
            setattr(result, wtype, getattr(result, wtype) + 1)

        # ── 6. Create connectors ──────────────────────────────────────────────
        for line in page.lines:
            cpayload = _connector_payload(line, lucid_to_miro)
            if cpayload is None:
                result.skipped_lines += 1
                continue

            if dry_run:
                _log(verbose, f"    [dry-run] connector: {line.text!r}")
            else:
                resp = client.post(
                    f"/v2/boards/{result.board_id}/connectors", cpayload
                )
                _log(verbose, f"    connector: {line.text!r} → {resp.get('id', '')}")

            result.lines += 1

        board_x += frame_w + FRAME_GAP

    return result


def _log(verbose: bool, msg: str) -> None:
    if verbose:
        print(msg)
