"""
Parser for Lucidchart Visio (.vsdx) exports.

A .vsdx file is a ZIP archive following the Open Packaging Convention (OPC).
Relevant paths inside the archive:

    visio/document.xml              — document title
    visio/pages/pages.xml           — ordered page list
    visio/pages/_rels/pages.xml.rels — page XML paths
    visio/pages/page{n}.xml         — shapes, groups, connectors per page
    visio/pages/_rels/page{n}.xml.rels — image relationship targets
    visio/masters/masters.xml       — master shape name lookup
    visio/media/                    — embedded PNG/SVG icon files

Coordinate conversion
---------------------
Visio measures from the bottom-left of the page in inches (Y increases up).
This parser converts to top-left pixels at 96 dpi (Y increases down):

    tl_x_inches          = PinX - LocPinX
    tl_y_from_bot_inches = PinY - LocPinY
    miro_x  = tl_x_inches * 96
    miro_y  = (page_height - tl_y_from_bot_inches - height) * 96
    miro_w  = width  * 96
    miro_h  = height * 96

For nested shapes (inside groups/containers) the same conversion is applied
locally, then the parent's absolute pixel offset is added.

Embedded images
---------------
Shapes with Type="Foreign" carry embedded image data.  The raw bytes are
stored in item.image_data.  Call extract_media() to write them to disk
and obtain a {item_id → Path} mapping for use with --icon-map.
"""
from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

from lucid_to_miro.model import Document, Item, Line, Page, Style

# ── XML namespaces ─────────────────────────────────────────────────────────────
_VISIO_NS = "http://schemas.microsoft.com/office/visio/2012/main"
_REL_NS   = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

DPI = 96  # pixels per inch

# ── Arrow value (Visio integer) → internal token ──────────────────────────────
_ARROW_MAP: Dict[int, str] = {
    0:  "none",
    1:  "arrow",            # open triangle
    2:  "filled_triangle",  # filled triangle
    3:  "arrow",            # open bent arrow
    4:  "arrow",
    5:  "circle",
    13: "open_diamond",
    14: "filled_diamond",
    45: "open_arrow",
}

# ── Container detection ───────────────────────────────────────────────────────
_CONTAINER_MASTER_KEYS: Set[str] = {
    "region", "vpc", "subnet", "vnet", "availabilityzone",
    "resourcegroup", "instancegroup", "swimlane", "lane", "pool",
    "logicalgroupsofservices/instances",
}

# ── Icon detection ────────────────────────────────────────────────────────────
_ICON_MASTER_KEYS: Set[str] = {
    "svgpathblock2", "svgpathblock", "imageblock", "icon", "customicon",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _vtag(local: str) -> str:
    """Return a namespaced tag string for the Visio namespace."""
    return f"{{{_VISIO_NS}}}{local}"


def _find_float(parent: ET.Element, local: str, default: float = 0.0) -> float:
    """Return the float value of the first matching child element."""
    child = parent.find(_vtag(local))
    if child is None:
        return default
    # Formula cells: prefer V attribute (computed value) over text
    raw = child.get("V") or (child.text or "")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _extract_text(text_elem: Optional[ET.Element]) -> str:
    """
    Extract plain text from a Visio <Text> element.

    The element may contain <cp>, <pp>, <tp> formatting markers; the actual
    content is in the .text and .tail of those children.
    """
    if text_elem is None:
        return ""
    parts: List[str] = []
    if text_elem.text:
        parts.append(text_elem.text)
    for child in text_elem:
        if child.tail:
            parts.append(child.tail)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _cell_value(shape: ET.Element, cell_name: str) -> Optional[str]:
    """Return the V attribute (or text) of the first <Cell N="cell_name"> anywhere under shape."""
    for cell in shape.iter(_vtag("Cell")):
        if cell.get("N") == cell_name:
            return cell.get("V") or cell.text or None
    return None


def _normalise_color(raw: Optional[str]) -> str:
    """Convert any Visio color representation to a lowercase #rrggbb string."""
    if not raw:
        return "#ffffff"
    raw = raw.strip()
    # Already hex
    if re.match(r"^#[0-9a-fA-F]{6}$", raw):
        return raw.lower()
    # THEMEVAL(...) — theme reference, return neutral default
    if "THEMEVAL" in raw or "Theme" in raw:
        return "#ffffff"
    # RGB(r,g,b)
    m = re.match(r"RGB\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", raw, re.I)
    if m:
        return "#{:02x}{:02x}{:02x}".format(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # Decimal BGR integer (Visio internal format)
    try:
        val = int(raw)
        r = val & 0xFF
        g = (val >> 8)  & 0xFF
        b = (val >> 16) & 0xFF
        return "#{:02x}{:02x}{:02x}".format(r, g, b)
    except (TypeError, ValueError):
        return "#ffffff"


def _arrow_token(raw: Optional[str]) -> str:
    """Convert a Visio arrow integer string to an internal arrow token."""
    if not raw:
        return "none"
    try:
        return _ARROW_MAP.get(int(float(raw)), "arrow")
    except (TypeError, ValueError):
        return "none"


def _master_key(name: str) -> str:
    """Normalise a master name to a lookup key."""
    return name.lower().replace(" ", "").replace("-", "").replace("/", "")


def _infer_ext(data: bytes) -> str:
    """Infer a file extension from image magic bytes."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"GIF8":
        return ".gif"
    if data[:4] in (b"<svg", b"<?xm") or b"<svg" in data[:64]:
        return ".svg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".bin"


# ── ZIP / relationship helpers ─────────────────────────────────────────────────

def _try_read(zf: zipfile.ZipFile, *paths: str) -> Optional[bytes]:
    """Try reading each path in turn; return None if none succeed."""
    for p in paths:
        try:
            return zf.read(p)
        except KeyError:
            continue
    return None


def _parse_rels(zf: zipfile.ZipFile, rels_path: str) -> Dict[str, str]:
    """
    Parse an OPC .rels file and return {Id: Target} for all relationships.
    Returns {} if the file is absent.
    """
    data = _try_read(zf, rels_path)
    if not data:
        return {}
    root = ET.fromstring(data)
    return {
        rel.get("Id", ""): rel.get("Target", "")
        for rel in root
        if rel.get("Id")
    }


def _page_rels_path(page_xml_path: str) -> str:
    """Derive the .rels path from a page XML path."""
    # "visio/pages/page1.xml"  →  "visio/pages/_rels/page1.xml.rels"
    parts = page_xml_path.rsplit("/", 1)
    if len(parts) == 2:
        return f"{parts[0]}/_rels/{parts[1]}.rels"
    return f"_rels/{page_xml_path}.rels"


def _resolve_media_path(rel_target: str, page_xml_path: str) -> str:
    """
    Resolve a relationship target relative to the page XML to an archive path.

    e.g. Target="../media/image1.png" from "visio/pages/page1.xml"
         → "visio/media/image1.png"
    """
    base_dir = page_xml_path.rsplit("/", 1)[0]  # "visio/pages"
    # Simple relative path resolution (no symlinks in ZIP)
    parts = (base_dir + "/" + rel_target).split("/")
    resolved: List[str] = []
    for part in parts:
        if part == "..":
            if resolved:
                resolved.pop()
        elif part and part != ".":
            resolved.append(part)
    return "/".join(resolved)


# ── Master shapes ──────────────────────────────────────────────────────────────

def _parse_masters(zf: zipfile.ZipFile) -> Dict[str, str]:
    """
    Return {master_id: master_name_u} from masters.xml.
    Returns {} if masters.xml is absent.
    """
    data = _try_read(zf, "visio/masters/masters.xml")
    if not data:
        return {}
    root = ET.fromstring(data)
    result: Dict[str, str] = {}
    for master in root.iter(_vtag("Master")):
        mid  = master.get("ID", "")
        name = master.get("NameU") or master.get("Name") or ""
        if mid:
            result[mid] = name
    return result


# ── Shape geometry ─────────────────────────────────────────────────────────────

def _shape_coords(
    shape: ET.Element,
    container_height: float,
    parent_x: float,
    parent_y: float,
) -> Tuple[float, float, float, float]:
    """
    Return (x, y, w, h) in absolute Miro pixels for a Visio shape element.

    container_height: height of the containing space in inches
                      (page height for top-level, parent height for nested).
    parent_x, parent_y: absolute Miro top-left of the parent (0,0 for page).
    """
    xform = shape.find(_vtag("XForm"))
    if xform is None:
        return parent_x, parent_y, 1.0, 1.0

    w   = _find_float(xform, "Width",   1.0)
    h   = _find_float(xform, "Height",  1.0)
    px  = _find_float(xform, "PinX",    w / 2)
    py  = _find_float(xform, "PinY",    h / 2)
    lpx = _find_float(xform, "LocPinX", w / 2)
    lpy = _find_float(xform, "LocPinY", h / 2)

    # Top-left in container-local coords (Visio: origin at bottom-left, Y up)
    tl_x = px - lpx
    tl_y_from_bot = py - lpy

    # Convert Y to top-down within container, then to pixels
    tl_y = container_height - tl_y_from_bot - h

    return (
        parent_x + tl_x * DPI,
        parent_y + tl_y * DPI,
        max(1.0, w * DPI),
        max(1.0, h * DPI),
    )


# ── Page parsing ───────────────────────────────────────────────────────────────

def _collect_connector_ids(root: ET.Element, page_id: str) -> Set[str]:
    """
    Scan the <Connects> section and return the set of connector shape IDs
    (raw IDs from the XML, before page_id prefixing).
    """
    connector_ids: Set[str] = set()
    connects = root.find(_vtag("Connects"))
    if connects is not None:
        connector_ids.update(
            c.get("FromSheet", "") for c in connects.findall(_vtag("Connect"))
            if c.get("FromSheet")
        )
    shapes_root = root.find(_vtag("Shapes"))
    if shapes_root is not None:
        for shape in shapes_root.iter(_vtag("Shape")):
            sid = shape.get("ID", "")
            if sid and (_cell_value(shape, "BeginX") or _cell_value(shape, "EndX")):
                connector_ids.add(sid)
    return connector_ids


def _parse_shapes_recursive(
    shapes_elem: ET.Element,
    page_id: str,
    masters: Dict[str, str],
    page_rels: Dict[str, str],       # rel_id → archive path
    zf: zipfile.ZipFile,
    container_height: float,          # inches
    parent_x: float,
    parent_y: float,
    connector_ids: Set[str],
    parent_item_id: Optional[str] = None,
) -> List[Item]:
    """
    Recursively parse <Shape> elements into Item objects.

    Connector shapes (their IDs are in connector_ids) are skipped here;
    they are parsed separately as Line objects.
    """
    items: List[Item] = []

    for shape in shapes_elem.findall(_vtag("Shape")):
        raw_id     = shape.get("ID", "")
        shape_type = shape.get("Type", "Shape")   # Shape | Group | Foreign
        master_id  = shape.get("Master", "")

        if not raw_id or raw_id in connector_ids:
            continue

        master_name = masters.get(master_id, "")
        mkey        = _master_key(master_name)

        # ── Geometry ───────────────────────────────────────────────────────
        # For group shapes, container_height for children is this shape's height
        xform = shape.find(_vtag("XForm"))
        shape_h_inches = _find_float(xform, "Height", 1.0) if xform is not None else 1.0

        ax, ay, aw, ah = _shape_coords(shape, container_height, parent_x, parent_y)

        # ── Text ───────────────────────────────────────────────────────────
        label = _extract_text(shape.find(_vtag("Text")))

        # ── Style ──────────────────────────────────────────────────────────
        fill_raw   = _cell_value(shape, "FillForegnd")
        border_raw = _cell_value(shape, "LineColor")
        style = Style(
            fill_color=_normalise_color(fill_raw),
            stroke_color=_normalise_color(border_raw),
        )

        # ── Icon / image detection ─────────────────────────────────────────
        is_icon_shape = shape_type == "Foreign" or mkey in _ICON_MASTER_KEYS

        # Extract embedded image bytes if present
        image_data: Optional[bytes] = None
        if is_icon_shape:
            foreign = shape.find(_vtag("ForeignData"))
            if foreign is not None:
                rel_elem = foreign.find(_vtag("Rel"))
                if rel_elem is not None:
                    rel_id = rel_elem.get(f"{{{_REL_NS}}}id", "")
                    if rel_id and rel_id in page_rels:
                        image_data = _try_read(zf, page_rels[rel_id])

        # ── Container detection ────────────────────────────────────────────
        child_shapes_elem = shape.find(_vtag("Shapes"))
        has_children = child_shapes_elem is not None and len(child_shapes_elem) > 0
        is_container_shape = (
            (shape_type == "Group" and has_children)
            or mkey in _CONTAINER_MASTER_KEYS
        )

        item_id = f"{page_id}_{raw_id}"

        item = Item(
            id=item_id,
            name=master_name or _fallback_name(shape_type),
            text=label,
            page_id=page_id,
            parent_id=parent_item_id,
            is_container=is_container_shape,
            is_icon=is_icon_shape,
            style=style,
            x=round(ax, 1),
            y=round(ay, 1),
            width=round(aw, 1),
            height=round(ah, 1),
            image_data=image_data,
        )
        items.append(item)

        # ── Recurse into group / container children ────────────────────────
        if child_shapes_elem is not None and has_children:
            child_items = _parse_shapes_recursive(
                child_shapes_elem,
                page_id,
                masters,
                page_rels,
                zf,
                container_height=shape_h_inches,
                parent_x=ax,
                parent_y=ay,
                connector_ids=connector_ids,
                parent_item_id=item_id,
            )
            items.extend(child_items)

    return items


def _parse_connectors(
    root: ET.Element,
    page_id: str,
    connector_ids: Set[str],
    page_height: float,
) -> List[Line]:
    """
    Parse the <Connects> section into Line objects.

    Visio stores connector topology in <Connects>:
        <Connect FromSheet="10" FromCell="BeginX" ToSheet="1" ToCell="PinX"/>
        <Connect FromSheet="10" FromCell="EndX"   ToSheet="2" ToCell="PinX"/>
    FromSheet=connector ID, BeginX=start endpoint, EndX=end endpoint.
    """
    conn_map: Dict[str, Dict[str, str]] = {}
    connects = root.find(_vtag("Connects"))
    if connects is not None:
        for c in connects.findall(_vtag("Connect")):
            from_id   = c.get("FromSheet", "")
            from_cell = c.get("FromCell",  "")
            to_sheet  = c.get("ToSheet",   "")
            if from_id and from_cell and to_sheet:
                conn_map.setdefault(from_id, {})[from_cell] = to_sheet

    # Build a shape lookup for extracting arrow style and label from the connector
    shape_by_id: Dict[str, ET.Element] = {}
    shapes_root = root.find(_vtag("Shapes"))
    if shapes_root is not None:
        for s in shapes_root.iter(_vtag("Shape")):
            sid = s.get("ID", "")
            if sid:
                shape_by_id[sid] = s

    lines: List[Line] = []
    for conn_id, cells in conn_map.items():
        # BeginX → source shape, EndX → target shape
        src_raw = cells.get("BeginX") or cells.get("FromBeginX")
        tgt_raw = cells.get("EndX")   or cells.get("FromEndX")

        if src_raw is None and tgt_raw is None:
            continue

        conn_shape  = shape_by_id.get(conn_id)
        start_arrow = _cell_value(conn_shape, "BeginArrow") if conn_shape is not None else None
        end_arrow   = _cell_value(conn_shape, "EndArrow")   if conn_shape is not None else None
        label       = _extract_text(conn_shape.find(_vtag("Text"))) if conn_shape is not None else ""

        # Prefix IDs with page_id to match Item IDs
        src = f"{page_id}_{src_raw}" if src_raw else None
        tgt = f"{page_id}_{tgt_raw}" if tgt_raw else None

        lines.append(Line(
            id=f"{page_id}_{conn_id}",
            source_id=src,
            target_id=tgt,
            source_arrow=_arrow_token(start_arrow),
            target_arrow=_arrow_token(end_arrow),
            text=label,
        ))

    # Lucid VSDX often encodes connectors as ordinary Shape elements carrying
    # BeginX/BeginY/EndX/EndY cells rather than <Connects> topology.
    shapes_root = root.find(_vtag("Shapes"))
    if shapes_root is not None:
        for shape in shapes_root.iter(_vtag("Shape")):
            shape_id = shape.get("ID", "")
            if not shape_id or shape_id in conn_map:
                continue
            begin_x = _cell_value(shape, "BeginX")
            begin_y = _cell_value(shape, "BeginY")
            end_x   = _cell_value(shape, "EndX")
            end_y   = _cell_value(shape, "EndY")
            if not ((begin_x and begin_y) or (end_x and end_y)):
                continue
            try:
                bx = float(begin_x) * DPI if begin_x else None
                by = (page_height - float(begin_y)) * DPI if begin_y else None
                ex = float(end_x) * DPI if end_x else None
                ey = (page_height - float(end_y)) * DPI if end_y else None
            except (TypeError, ValueError):
                continue
            label = _extract_text(shape.find(_vtag("Text")))
            lines.append(Line(
                id=f"{page_id}_{shape_id}",
                source_id=None,
                target_id=None,
                start_x=bx,
                start_y=by,
                end_x=ex,
                end_y=ey,
                source_arrow=_arrow_token(_cell_value(shape, "BeginArrow")),
                target_arrow=_arrow_token(_cell_value(shape, "EndArrow")),
                text=label,
                style=Style(stroke_color=_normalise_color(_cell_value(shape, "LineColor"))),
            ))

    return lines


def _parse_page(
    zf: zipfile.ZipFile,
    page_xml_path: str,
    page_id: str,
    page_title: str,
    masters: Dict[str, str],
) -> Page:
    """Parse a single page XML file and return a Page object."""
    data = _try_read(zf, page_xml_path)
    if not data:
        return Page(id=page_id, title=page_title)

    root = ET.fromstring(data)

    # Page dimensions
    page_height = 8.5   # default (letter landscape)
    page_sheet  = root.find(_vtag("PageSheet"))
    if page_sheet is not None:
        page_props = page_sheet.find(_vtag("PageProps"))
        if page_props is not None:
            page_height = _find_float(page_props, "PageHeight", page_height)

    # Image relationships: rel_id → archive path
    rels_raw = _parse_rels(zf, _page_rels_path(page_xml_path))
    page_rels: Dict[str, str] = {
        rel_id: _resolve_media_path(target, page_xml_path)
        for rel_id, target in rels_raw.items()
    }

    shapes_root = root.find(_vtag("Shapes"))
    if shapes_root is None:
        return Page(id=page_id, title=page_title)

    # First pass: identify connector shape IDs so they are excluded from items
    connector_ids = _collect_connector_ids(root, page_id)

    # Second pass: parse shapes into Items
    items = _parse_shapes_recursive(
        shapes_root,
        page_id=page_id,
        masters=masters,
        page_rels=page_rels,
        zf=zf,
        container_height=page_height,
        parent_x=0.0,
        parent_y=0.0,
        connector_ids=connector_ids,
    )

    # Third pass: parse connectors into Lines
    lines = _parse_connectors(root, page_id, connector_ids, page_height)

    return Page(id=page_id, title=page_title, items=items, lines=lines)


def _fallback_name(visio_type: str) -> str:
    """Shape name when no master is available."""
    return {"Group": "Region", "Foreign": "ImageBlock"}.get(visio_type, "Block")


# ── Document title ─────────────────────────────────────────────────────────────

def _read_doc_title(zf: zipfile.ZipFile) -> str:
    """Try to extract the document title from visio/document.xml."""
    data = _try_read(zf, "visio/document.xml")
    if not data:
        return ""
    root = ET.fromstring(data)
    for tag_name in ("Title", "title"):
        for elem in root.iter():
            if elem.tag.endswith(tag_name) and elem.text and elem.text.strip():
                return elem.text.strip()
    return ""


# ── Public API ─────────────────────────────────────────────────────────────────

def parse_vsdx(source: Union[str, Path, bytes]) -> Document:
    """
    Parse a Lucidchart Visio (.vsdx) export into a normalised Document.

    Shape coordinates are taken directly from the Visio geometry (converted
    from inches to pixels at 96 dpi).  The auto-layout engine is not run;
    doc.has_coordinates is set to True to signal this to the converter.

    Icon shapes (Type="Foreign") have their raw image bytes stored in
    item.image_data.  Call extract_media() to write them to disk before
    uploading to Miro (the REST API requires HTTP URLs, not raw bytes).

    Args:
        source: Path to a .vsdx file (str or Path), or raw bytes.

    Returns:
        Document with has_coordinates=True and item x/y/width/height pre-set.

    Raises:
        zipfile.BadZipFile: If the file is not a valid ZIP / .vsdx.
        ValueError:         If the file structure is unrecognisable.
    """
    if isinstance(source, (str, Path)):
        raw = Path(source).read_bytes()
    else:
        raw = bytes(source)

    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        masters = _parse_masters(zf)

        # ── Document title ─────────────────────────────────────────────────
        title = _read_doc_title(zf) or "Visio Import"

        # ── Page list ──────────────────────────────────────────────────────
        pages_xml = _try_read(zf, "visio/pages/pages.xml")
        if not pages_xml:
            return Document(title=title, has_coordinates=True)

        pages_root = ET.fromstring(pages_xml)

        # Resolve page XML paths via the pages .rels file
        pages_rels = _parse_rels(zf, "visio/pages/_rels/pages.xml.rels")

        pages: List[Page] = []
        for idx, page_elem in enumerate(pages_root.findall(_vtag("Page")), start=1):
            page_id    = page_elem.get("ID",   str(idx))
            page_title = page_elem.get("Name") or page_elem.get("NameU") or f"Page {idx}"

            # Resolve the page XML path via its Rel element
            rel_elem = page_elem.find(_vtag("Rel"))
            page_xml_path = f"visio/pages/page{idx}.xml"  # sensible default
            if rel_elem is not None:
                rel_id = rel_elem.get(f"{{{_REL_NS}}}id", "")
                if rel_id and rel_id in pages_rels:
                    target = pages_rels[rel_id]
                    page_xml_path = f"visio/pages/{target.lstrip('./')}"

            page = _parse_page(zf, page_xml_path, page_id, page_title, masters)
            if page.items or page.lines:
                pages.append(page)

    return Document(title=title, pages=pages, has_coordinates=True)


def extract_media(doc: Document, output_dir: Union[str, Path]) -> Dict[str, Path]:
    """
    Write all embedded icon images from *doc* to *output_dir*.

    Returns a dict mapping item.id → output Path for each icon written.
    Use the returned mapping to build an --icon-map JSON file for the
    REST API uploader.

    Example::

        written = extract_media(doc, "./icons")
        icon_map = {
            "by_id": {item_id: str(path) for item_id, path in written.items()}
        }
        Path("icon_map.json").write_text(json.dumps(icon_map, indent=2))
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    written: Dict[str, Path] = {}
    for page in doc.pages:
        for item in page.items:
            if item.is_icon and item.image_data:
                ext       = _infer_ext(item.image_data)
                # Sanitise item.id before using as a filename to prevent path
                # traversal if a malicious VSDX encodes "../" in a shape ID.
                safe_name = re.sub(r"[^\w\-]", "_", item.id)
                dest      = out / f"{safe_name}{ext}"
                dest.write_bytes(item.image_data)
                written[item.id] = dest
    return written
