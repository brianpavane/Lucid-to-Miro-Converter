"""
Internal normalised data model.

Both the CSV and JSON parsers produce a Document containing Pages.
A Page holds flat lists of Items and Lines; the containment tree is
encoded via Item.parent_id so the layout engine can reconstruct it.

Neither Lucidchart export format (CSV or JSON) carries pixel coordinates,
so x/y/width/height are left at 0 and filled in by the layout engine.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Style:
    fill_color: str = "#ffffff"
    stroke_color: str = "#000000"
    stroke_width: int = 1
    font_size: int = 14
    font_color: str = "#000000"
    text_align: str = "center"
    bold: bool = False
    italic: bool = False


@dataclass
class Item:
    id: str
    name: str                    # Shape Library name / Lucid class
    text: str = ""               # Primary label (Text Area 1 / first textArea)
    extra_text: List[str] = field(default_factory=list)  # Text Area 2-N
    page_id: str = ""
    parent_id: Optional[str] = None   # Direct containing shape (innermost)
    group_id: Optional[str] = None    # Group membership
    is_container: bool = False        # True for region/VPC/swimlane shapes
    is_icon: bool = False             # SVGPathBlock2 / image shapes
    style: Style = field(default_factory=Style)
    # Filled by layout engine (CSV/JSON) or VSDX parser (actual coordinates):
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0
    # VSDX only — raw embedded image bytes (None for CSV/JSON):
    image_data: Optional[bytes] = field(default=None, repr=False)


@dataclass
class Line:
    id: str
    source_id: Optional[str]    # ID of connected source shape (may be None)
    target_id: Optional[str]    # ID of connected target shape (may be None)
    start_x: Optional[float] = None
    start_y: Optional[float] = None
    end_x: Optional[float] = None
    end_y: Optional[float] = None
    source_arrow: str = "none"  # e.g. "None", "Arrow", "OpenArrow"
    target_arrow: str = "arrow"
    text: str = ""
    style: Style = field(default_factory=Style)


@dataclass
class Page:
    id: str
    title: str
    items: List[Item] = field(default_factory=list)
    lines: List[Line] = field(default_factory=list)


@dataclass
class Document:
    title: str
    pages: List[Page] = field(default_factory=list)
    # True when a parser has already set item x/y/width/height (e.g. VSDX).
    # When True, the layout engine is skipped and coordinates are used as-is.
    has_coordinates: bool = False
