"""
Writes a normalised Document as a Visio (.vsdx) file.

A .vsdx file is an Open Packaging Convention (OPC) ZIP archive.  This writer
produces the minimal structure that Miro's "Import from Visio" feature (and
Microsoft Visio itself) can read:

    [Content_Types].xml
    _rels/.rels
    visio/document.xml
    visio/_rels/document.xml.rels
    visio/pages/pages.xml
    visio/pages/_rels/pages.xml.rels
    visio/pages/page{n}.xml          — one per non-empty Document page

Coordinate conversion
---------------------
The internal model uses top-left origin, Y increases downward, pixels at 96 dpi.
Visio uses bottom-left origin, Y increases upward, inches.  This writer converts
at 96 dpi (the same constant used by the VSDX parser):

    PinX    = (item.x + item.width  / 2) / 96
    PinY    = page_height_in - (item.y + item.height / 2) / 96
    Width   = item.width  / 96
    Height  = item.height / 96
    LocPinX = Width  / 2   (shape's own local origin = its centre)
    LocPinY = Height / 2

Connector coordinates use the centre of the connected shape.  Unresolvable
endpoints are placed at default positions so the file remains valid.
"""
from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path
from typing import Dict, IO, List, Tuple, Union

from lucid_to_miro.model import Document, Item, Line, Page
from lucid_to_miro.converter.layout import layout_page, CONT_PAD

DPI = 96  # pixels per inch (matches vsdx_parser.py)

# Internal arrow token → Visio BeginArrow/EndArrow integer
_ARROW_OUT: Dict[str, int] = {
    "none":            0,
    "arrow":           1,
    "filled_triangle": 2,
    "open_arrow":      3,
    "circle":          5,
    "open_diamond":    13,
    "filled_diamond":  14,
}

# OPC / Visio content-type and relationship type URIs
_CT_RELS   = "application/vnd.openxmlformats-package.relationships+xml"
_CT_DOC    = "application/vnd.ms-visio.drawing.main+xml"
_CT_PAGES  = "application/vnd.ms-visio.pages+xml"
_CT_PAGE   = "application/vnd.ms-visio.page+xml"
_CT_APP    = "application/vnd.openxmlformats-officedocument.extended-properties+xml"
_CT_CORE   = "application/vnd.openxmlformats-package.core-properties+xml"
_NS_VISIO  = "http://schemas.microsoft.com/office/visio/2012/main"
_NS_REL    = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PKG    = "http://schemas.openxmlformats.org/package/2006/relationships"
_RT_DOC    = "http://schemas.microsoft.com/visio/2010/relationships/document"
_RT_PAGES  = "http://schemas.microsoft.com/visio/2010/relationships/pages"
_RT_PAGE   = "http://schemas.microsoft.com/visio/2010/relationships/page"
_RT_WINDOWS = "http://schemas.microsoft.com/visio/2010/relationships/windows"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    """Minimal XML text / attribute value escaping."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _colour(raw: str) -> str:
    """Return a valid #rrggbb string; fall back to white."""
    if raw and re.match(r"^#[0-9a-fA-F]{6}$", raw):
        return raw.lower()
    return "#ffffff"


# ── OPC envelope ─────────────────────────────────────────────────────────────

def _content_types(n_pages: int) -> str:
    overrides = "\n".join(
        f'  <Override PartName="/visio/pages/page{i + 1}.xml"'
        f' ContentType="{_CT_PAGE}"/>'
        for i in range(n_pages)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        f'  <Default Extension="rels" ContentType="{_CT_RELS}"/>\n'
        '  <Default Extension="xml" ContentType="application/xml"/>\n'
        f'  <Override PartName="/docProps/app.xml" ContentType="{_CT_APP}"/>\n'
        f'  <Override PartName="/docProps/core.xml" ContentType="{_CT_CORE}"/>\n'
        f'  <Override PartName="/visio/document.xml" ContentType="{_CT_DOC}"/>\n'
        f'  <Override PartName="/visio/pages/pages.xml" ContentType="{_CT_PAGES}"/>\n'
        f'{overrides}\n'
        '</Types>'
    )


def _root_rels() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="{_NS_PKG}">\n'
        f'  <Relationship Id="rId1" Type="{_RT_DOC}"'
        ' Target="visio/document.xml"/>\n'
        '</Relationships>'
    )


def _document_xml() -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<VisioDocument xmlns="{_NS_VISIO}" xmlns:r="{_NS_REL}" xml:space="preserve">\n'
        '  <DocumentSettings TopPage="0" DefaultTextStyle="3" DefaultLineStyle="3" DefaultFillStyle="3" DefaultGuideStyle="4">\n'
        '    <GlueSettings>9</GlueSettings>\n'
        '    <SnapSettings>295</SnapSettings>\n'
        '    <SnapExtensions>34</SnapExtensions>\n'
        '    <SnapAngles/>\n'
        '    <DynamicGridEnabled>0</DynamicGridEnabled>\n'
        '    <ProtectStyles>0</ProtectStyles>\n'
        '    <ProtectShapes>0</ProtectShapes>\n'
        '    <ProtectMasters>0</ProtectMasters>\n'
        '    <ProtectBkgnds>0</ProtectBkgnds>\n'
        '  </DocumentSettings>\n'
        '</VisioDocument>'
    )


def _document_rels() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="{_NS_PKG}">\n'
        f'  <Relationship Id="rId1" Type="{_RT_PAGES}"'
        ' Target="pages/pages.xml"/>\n'
        f'  <Relationship Id="rId2" Type="{_RT_WINDOWS}"'
        ' Target="windows.xml"/>\n'
        '</Relationships>'
    )


def _pages_xml(pages: List[Page], page_sizes: List[tuple[float, float]]) -> str:
    entries = []
    for i, page in enumerate(pages):
        name = _esc(page.title or f"Page-{i + 1}")
        page_w_in, page_h_in = page_sizes[i]
        entries.append(
            f'  <Page ID="{i}" NameU="{name}" IsCustomNameU="1"'
            f' Name="{name}" IsCustomName="1" ViewScale="-1"'
            f' ViewCenterX="{page_w_in / 2:.6f}" ViewCenterY="{page_h_in / 2:.6f}">\n'
            '    <PageSheet LineStyle="0" FillStyle="0" TextStyle="0">\n'
            f'      <Cell N="PageWidth" V="{page_w_in:.6f}"/>\n'
            f'      <Cell N="PageHeight" V="{page_h_in:.6f}"/>\n'
            '      <Cell N="ShdwOffsetX" V="0.125"/>\n'
            '      <Cell N="ShdwOffsetY" V="-0.125"/>\n'
            '      <Cell N="PageScale" V="1" U="IN_F"/>\n'
            '      <Cell N="DrawingScale" V="1" U="IN_F"/>\n'
            '      <Cell N="DrawingSizeType" V="0"/>\n'
            '      <Cell N="DrawingScaleType" V="3"/>\n'
            '      <Cell N="InhibitSnap" V="0"/>\n'
            '      <Cell N="PageLockReplace" V="0" U="BOOL"/>\n'
            '      <Cell N="PageLockDuplicate" V="0" U="BOOL"/>\n'
            '      <Cell N="UIVisibility" V="0"/>\n'
            '      <Cell N="ShdwType" V="0"/>\n'
            '      <Cell N="ShdwObliqueAngle" V="0"/>\n'
            '      <Cell N="ShdwScaleFactor" V="1"/>\n'
            '      <Cell N="DrawingResizeType" V="1"/>\n'
            '      <Cell N="PageShapeSplit" V="1"/>\n'
            '      <Cell N="PageLeftMargin" V="0.2"/>\n'
            '      <Cell N="PageRightMargin" V="0.2"/>\n'
            '      <Cell N="PageTopMargin" V="0.2"/>\n'
            '      <Cell N="PageBottomMargin" V="0.2"/>\n'
            '      <Cell N="PrintPageOrientation" V="2"/>\n'
            '      <Cell N="LineJumpCode" V="0"/>\n'
            '      <Cell N="LineJumpStyle" V="1"/>\n'
            '    </PageSheet>\n'
            f'    <Rel r:id="rId{i + 1}"'
            f' xmlns:r="{_NS_REL}"/>\n'
            f'  </Page>'
        )
    body = "\n".join(entries)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<Pages xmlns="{_NS_VISIO}">\n'
        f'{body}\n'
        '</Pages>'
    )


def _pages_rels(pages: List[Page]) -> str:
    entries = "\n".join(
        f'  <Relationship Id="rId{i + 1}" Type="{_RT_PAGE}"'
        f' Target="page{i + 1}.xml"/>'
        for i in range(len(pages))
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="{_NS_PKG}">\n'
        f'{entries}\n'
        '</Relationships>'
    )


def _windows_xml(page_sizes: List[tuple[float, float]]) -> str:
    page_w_in, page_h_in = page_sizes[0] if page_sizes else (11.0, 8.5)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<Windows ClientWidth="1920" ClientHeight="977" xmlns="{_NS_VISIO}" xmlns:r="{_NS_REL}" xml:space="preserve">'
        f'<Window ID="0" WindowType="Drawing" WindowState="1073741824" WindowLeft="-8" WindowTop="-31" WindowWidth="1936" WindowHeight="1016" ContainerType="Page" Page="0" ViewScale="-1" ViewCenterX="{page_w_in / 2:.6f}" ViewCenterY="{page_h_in / 2:.6f}">'
        '<ShowRulers>1</ShowRulers><ShowGrid>0</ShowGrid><ShowPageBreaks>1</ShowPageBreaks><ShowGuides>1</ShowGuides><ShowConnectionPoints>1</ShowConnectionPoints><GlueSettings>9</GlueSettings><SnapSettings>65847</SnapSettings><SnapExtensions>34</SnapExtensions><SnapAngles/><DynamicGridEnabled>1</DynamicGridEnabled><TabSplitterPos>0.5</TabSplitterPos></Window></Windows>'
    )


def _app_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"></Properties>'
    )


def _core_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"></cp:coreProperties>'
    )


# ── Per-page XML ──────────────────────────────────────────────────────────────

def _shape_xml(int_id: int, item: Item, page_h_in: float) -> str:
    """Render one Item as a Visio <Shape Type="Shape"> element.

    Geometry is written inside an <XForm> child element using element-name
    tags (e.g. <Width V="..."/>) because the parser's _find_float() looks for
    namespace-qualified element names inside XForm, not Cell/@N attributes.
    Colour cells use Cell/@N because _cell_value() expects that pattern.
    """
    w_in  = max(item.width,  1.0) / DPI
    h_in  = max(item.height, 1.0) / DPI
    pin_x = (item.x + item.width  / 2.0) / DPI
    pin_y = page_h_in - (item.y + item.height / 2.0) / DPI
    loc_x = w_in / 2.0
    loc_y = h_in / 2.0

    fill  = _colour(item.style.fill_color)
    line  = _colour(item.style.stroke_color)
    label = _esc(item.text or "")
    text_elem = f"\n  <Text>{label}</Text>" if label else ""
    # Include a simple rectangle path so Visio consumers have visible geometry,
    # not just transform cells.
    geom = (
        '\n  <Section N="Geometry" IX="0">\n'
        '    <Row T="MoveTo" IX="0">\n'
        '      <Cell N="X" V="0" F="Width*0">0</Cell>\n'
        '      <Cell N="Y" V="0" F="Height*0">0</Cell>\n'
        '    </Row>\n'
        '    <Row T="LineTo" IX="1">\n'
        '      <Cell N="X" V="1" F="Width*1">1</Cell>\n'
        '      <Cell N="Y" V="0" F="Height*0">0</Cell>\n'
        '    </Row>\n'
        '    <Row T="LineTo" IX="2">\n'
        '      <Cell N="X" V="1" F="Width*1">1</Cell>\n'
        '      <Cell N="Y" V="1" F="Height*1">1</Cell>\n'
        '    </Row>\n'
        '    <Row T="LineTo" IX="3">\n'
        '      <Cell N="X" V="0" F="Width*0">0</Cell>\n'
        '      <Cell N="Y" V="1" F="Height*1">1</Cell>\n'
        '    </Row>\n'
        '    <Row T="LineTo" IX="4">\n'
        '      <Cell N="X" V="0" F="Width*0">0</Cell>\n'
        '      <Cell N="Y" V="0" F="Height*0">0</Cell>\n'
        '    </Row>\n'
        '  </Section>'
    )

    ns = _NS_VISIO
    return (
        f'<Shape ID="{int_id}" Type="Shape"'
        ' LineStyle="0" FillStyle="0" TextStyle="0">\n'
        f'  <Cell N="PinX" V="{pin_x:.6f}">{pin_x:.6f}</Cell>\n'
        f'  <Cell N="PinY" V="{pin_y:.6f}">{pin_y:.6f}</Cell>\n'
        f'  <Cell N="Width" V="{w_in:.6f}">{w_in:.6f}</Cell>\n'
        f'  <Cell N="Height" V="{h_in:.6f}">{h_in:.6f}</Cell>\n'
        f'  <Cell N="LocPinX" V="{loc_x:.6f}" F="Width*0.5">{loc_x:.6f}</Cell>\n'
        f'  <Cell N="LocPinY" V="{loc_y:.6f}" F="Height*0.5">{loc_y:.6f}</Cell>\n'
        f'  <XForm xmlns="{ns}">\n'
        f'    <PinX V="{pin_x:.6f}">{pin_x:.6f}</PinX>\n'
        f'    <PinY V="{pin_y:.6f}">{pin_y:.6f}</PinY>\n'
        f'    <Width V="{w_in:.6f}">{w_in:.6f}</Width>\n'
        f'    <Height V="{h_in:.6f}">{h_in:.6f}</Height>\n'
        f'    <LocPinX V="{loc_x:.6f}" F="Width*0.5">{loc_x:.6f}</LocPinX>\n'
        f'    <LocPinY V="{loc_y:.6f}" F="Height*0.5">{loc_y:.6f}</LocPinY>\n'
        f'  </XForm>\n'
        f'  <Cell N="FillForegnd" V="{fill}">{fill}</Cell>\n'
        f'  <Cell N="LineColor"   V="{line}">{line}</Cell>'
        f'{geom}'
        f'{text_elem}\n'
        '</Shape>'
    )


def _connector_xml(
    conn_id: int,
    line: Line,
    id_map: Dict[str, int],
    item_map: Dict[str, Item],
    page_h_in: float,
) -> Tuple[str, List[str]]:
    """
    Render a Line as a Visio <Shape Type="Edge"> element.

    Returns (shape_xml_string, [connect_xml_string, ...]).
    """
    def _ctr(item: Item) -> Tuple[float, float]:
        cx = (item.x + item.width  / 2.0) / DPI
        cy = page_h_in - (item.y + item.height / 2.0) / DPI
        return cx, cy

    src = item_map.get(line.source_id) if line.source_id else None
    tgt = item_map.get(line.target_id) if line.target_id else None

    if src is not None:
        bx, by = _ctr(src)
    elif line.start_x is not None and line.start_y is not None:
        bx, by = line.start_x / DPI, page_h_in - (line.start_y / DPI)
    else:
        bx, by = (1.0, page_h_in / 2.0)

    if tgt is not None:
        ex, ey = _ctr(tgt)
    elif line.end_x is not None and line.end_y is not None:
        ex, ey = line.end_x / DPI, page_h_in - (line.end_y / DPI)
    else:
        ex, ey = (2.0, page_h_in / 2.0)

    b_arrow = _ARROW_OUT.get(line.source_arrow, 0)
    e_arrow = _ARROW_OUT.get(line.target_arrow, 1)
    label   = _esc(line.text or "")
    text_elem = f"\n  <Text>{label}</Text>" if label else ""

    shape = (
        f'<Shape ID="{conn_id}" Type="Edge"'
        ' LineStyle="0" FillStyle="0" TextStyle="0">\n'
        f'  <Cell N="BeginX"    V="{bx:.6f}">{bx:.6f}</Cell>\n'
        f'  <Cell N="BeginY"    V="{by:.6f}">{by:.6f}</Cell>\n'
        f'  <Cell N="EndX"      V="{ex:.6f}">{ex:.6f}</Cell>\n'
        f'  <Cell N="EndY"      V="{ey:.6f}">{ey:.6f}</Cell>\n'
        f'  <Cell N="BeginArrow" V="{b_arrow}">{b_arrow}</Cell>\n'
        f'  <Cell N="EndArrow"   V="{e_arrow}">{e_arrow}</Cell>'
        f'{text_elem}\n'
        '</Shape>'
    )

    connects: List[str] = []
    if src and line.source_id in id_map:
        connects.append(
            f'<Connect FromSheet="{conn_id}" ToSheet="{id_map[line.source_id]}"'
            ' FromCell="BeginX" ToCell="PinX"/>'
        )
    if tgt and line.target_id in id_map:
        connects.append(
            f'<Connect FromSheet="{conn_id}" ToSheet="{id_map[line.target_id]}"'
            ' FromCell="EndX" ToCell="PinX"/>'
        )
    return shape, connects


def _page_xml(page: Page, page_w_in: float, page_h_in: float) -> str:
    """Render a full page{n}.xml for one Page.

    A <PageSheet><PageProps> block is included so consumers can read the page
    bounds directly, and the parser can still invert Y coordinates properly.
    """
    # Integer ID map: item.id (str) → sequential int starting at 1
    id_map: Dict[str, int] = {it.id: i + 1 for i, it in enumerate(page.items)}
    item_map: Dict[str, Item] = {it.id: it for it in page.items}

    shape_parts: List[str] = []
    connect_parts: List[str] = []
    next_id = len(page.items) + 1

    for item in page.items:
        shape_parts.append(_shape_xml(id_map[item.id], item, page_h_in))

    for line in page.lines:
        s_xml, c_xmls = _connector_xml(next_id, line, id_map, item_map, page_h_in)
        shape_parts.append(s_xml)
        connect_parts.extend(c_xmls)
        next_id += 1

    indent = "  "
    shapes_inner = "\n".join(f"{indent}{s}" for s in shape_parts)
    connects_block = ""
    if connect_parts:
        c_inner = "\n".join(f"{indent}{c}" for c in connect_parts)
        connects_block = f"\n<Connects>\n{c_inner}\n</Connects>"

    ns = _NS_VISIO
    page_sheet = (
        f'<PageSheet xmlns="{ns}" LineStyle="0" FillStyle="0" TextStyle="0">\n'
        f'  <PageProps>\n'
        f'    <PageWidth V="{page_w_in:.6f}">{page_w_in:.6f}</PageWidth>\n'
        f'    <PageHeight V="{page_h_in:.6f}">{page_h_in:.6f}</PageHeight>\n'
        f'  </PageProps>\n'
        f'</PageSheet>'
    )

    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<PageContents xmlns="{_NS_VISIO}"\n'
        f'              xmlns:r="{_NS_REL}">\n'
        f'{page_sheet}\n'
        f'<Shapes>\n'
        f'{shapes_inner}\n'
        f'</Shapes>'
        f'{connects_block}\n'
        '</PageContents>'
    )


# ── Public API ────────────────────────────────────────────────────────────────

def write_vsdx(
    doc: Document,
    dest: Union[str, Path, IO[bytes]],
    has_containment: bool = True,
    scale: float = 1.0,
) -> None:
    """
    Convert a normalised Document to a .vsdx file.

    Accepts any Document produced by the CSV, JSON, or VSDX parsers.
    If the document does not already carry coordinates (CSV / JSON input),
    the auto-layout engine is run first.

    Args:
        doc:             Parsed document.
        dest:            Output file path (str / Path) or a writable binary
                         file-like object (e.g. io.BytesIO for testing).
        has_containment: True for CSV input (parent_id populated); False for JSON.
                         Ignored when doc.has_coordinates is True (VSDX input).
        scale:           Uniform scale factor applied after layout.
    """
    # Layout CSV / JSON input (VSDX already has coordinates)
    if not doc.has_coordinates:
        for page in doc.pages:
            if page.items or page.lines:
                layout_page(page, has_containment)

    # Apply optional scale
    if scale != 1.0:
        for page in doc.pages:
            for item in page.items:
                item.x      *= scale
                item.y      *= scale
                item.width  *= scale
                item.height *= scale

    # Only include pages that have content
    pages = [p for p in doc.pages if p.items or p.lines]
    page_sizes: List[tuple[float, float]] = []
    for page in pages:
        max_x_px = max((it.x + it.width for it in page.items), default=800.0)
        max_y_px = max((it.y + it.height for it in page.items), default=600.0)
        page_sizes.append(((max_x_px + CONT_PAD) / DPI, (max_y_px + CONT_PAD) / DPI))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml",               _content_types(len(pages)))
        zf.writestr("_rels/.rels",                        _root_rels())
        zf.writestr("docProps/app.xml",                   _app_xml())
        zf.writestr("docProps/core.xml",                  _core_xml())
        zf.writestr("visio/document.xml",                 _document_xml())
        zf.writestr("visio/_rels/document.xml.rels",      _document_rels())
        zf.writestr("visio/windows.xml",                  _windows_xml(page_sizes))
        zf.writestr("visio/pages/pages.xml",              _pages_xml(pages, page_sizes))
        zf.writestr("visio/pages/_rels/pages.xml.rels",   _pages_rels(pages))

        for idx, page in enumerate(pages):
            page_w_in, page_h_in = page_sizes[idx]
            zf.writestr(
                f"visio/pages/page{idx + 1}.xml",
                _page_xml(page, page_w_in, page_h_in),
            )

    data = buf.getvalue()

    if isinstance(dest, (str, Path)):
        out = Path(dest)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
    else:
        dest.write(data)
