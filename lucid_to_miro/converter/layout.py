"""
Auto-layout engine.

Since neither the CSV nor the JSON Lucidchart export carries pixel coordinates,
this module assigns x/y/width/height to every Item on a Page before the Miro
converter serialises them.

Strategy
--------
For CSV exports the "Contained By" field gives us a containment tree.  We
perform a bottom-up layout: leaf items get default dimensions, containers are
sized to fit their children, then the top-level items are arranged in a grid.

For JSON exports there is no containment information, so all shapes on a page
are peers.  Items that share a group_id are clustered together before the
global grid is applied.

Coordinate system: top-left origin, Y increases downward.
All dimensions are in Miro "device pixels" (1 dp ≈ 1 CSS px at 100 % zoom).
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

from lucid_to_miro.model import Item, Page

# ── Default dimensions ────────────────────────────────────────────────────────
SHAPE_W   = 160     # default shape width
SHAPE_H   =  80     # default shape height
ICON_W    =  80     # SVG icon / custom icon
ICON_H    =  80
TEXT_W    = 200     # text-only block
TEXT_H    =  40
ITEM_GAP  =  20     # gap between sibling items
CONT_PAD  =  40     # padding inside a container (sides + bottom)
LABEL_H   =  30     # space reserved for a container's own label at the top
FRAME_GAP = 150     # horizontal gap between page frames on the board


def _default_size(item: Item) -> tuple[float, float]:
    if item.is_icon:
        return ICON_W, ICON_H
    if item.name.lower() in ("minimaltextblock", "text", "label"):
        return TEXT_W, TEXT_H
    return SHAPE_W, SHAPE_H


# ── Grid packing ──────────────────────────────────────────────────────────────

def _grid_layout(items: List[Item], origin_x: float = 0, origin_y: float = 0) -> tuple[float, float]:
    """
    Arrange *items* (already sized) in a left-to-right, top-to-bottom grid
    starting at (origin_x, origin_y).  Returns (total_width, total_height).
    Mutates item.x / item.y in place.
    """
    if not items:
        return 0, 0

    n    = len(items)
    cols = max(1, math.ceil(math.sqrt(n)))

    x = origin_x
    y = origin_y
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
            col  = 0
            x    = origin_x
            y   += row_h + ITEM_GAP
            row_h = 0

    # Total bounding box
    total_w = max_x - origin_x
    total_h = (y + row_h) - origin_y  # last row height
    return total_w, total_h


# ── Containment-tree layout (for CSV, which has parent_id) ───────────────────

def _build_tree(items: List[Item]) -> tuple[Dict[str, Item], Dict[str, List[Item]]]:
    """
    Build:
    - item_by_id: id → Item
    - children:   parent_id → [child Items]  ('' key = top-level)
    """
    item_by_id: Dict[str, Item] = {it.id: it for it in items}
    children:   Dict[str, List[Item]] = {}

    for item in items:
        pid = item.parent_id if (item.parent_id and item.parent_id in item_by_id) else ""
        children.setdefault(pid, []).append(item)

    return item_by_id, children


def _layout_subtree(item: Item, children_map: Dict[str, List[Item]]) -> None:
    """
    Recursively size *item* and arrange its children.
    After this call item.width / item.height are set.
    """
    kids = children_map.get(item.id, [])

    if not kids:
        # Leaf node: assign default size
        w, h = _default_size(item)
        item.width, item.height = w, h
        return

    # Recurse first so children are sized
    for kid in kids:
        _layout_subtree(kid, children_map)

    # Lay out children inside this container
    inner_w, inner_h = _grid_layout(kids, origin_x=CONT_PAD, origin_y=CONT_PAD + LABEL_H)

    # Size the container to wrap its content
    item.is_container = True
    item.width  = inner_w + CONT_PAD * 2
    item.height = inner_h + CONT_PAD + LABEL_H


def layout_csv_page(page: Page) -> tuple[float, float]:
    """
    Assign positions to all items on a CSV-parsed page using the containment tree.
    Returns (frame_width, frame_height).
    """
    if not page.items:
        return 800, 600

    item_by_id, children_map = _build_tree(page.items)

    # Size every item bottom-up
    top_level = children_map.get("", [])
    for item in top_level:
        _layout_subtree(item, children_map)

    # Arrange top-level items in a grid
    total_w, total_h = _grid_layout(top_level, origin_x=CONT_PAD, origin_y=CONT_PAD)

    # Propagate absolute positions down the tree
    _propagate_positions(top_level, children_map)

    frame_w = total_w + CONT_PAD * 2
    frame_h = total_h + CONT_PAD * 2
    return max(frame_w, 400), max(frame_h, 300)


def _propagate_positions(items: List[Item], children_map: Dict[str, List[Item]]) -> None:
    """Convert relative child positions to absolute by adding parent offsets."""
    for item in items:
        kids = children_map.get(item.id, [])
        for kid in kids:
            kid.x += item.x
            kid.y += item.y
        _propagate_positions(kids, children_map)


# ── Flat layout (for JSON, which has no containment) ─────────────────────────

def _cluster_by_group(items: List[Item]) -> List[List[Item]]:
    """
    Group items by group_id.  Items without a group form singleton clusters.
    Returns a list of clusters (each cluster is a list of Items).
    """
    groups: Dict[str, List[Item]] = {}
    singletons: List[Item] = []
    for item in items:
        if item.group_id:
            groups.setdefault(item.group_id, []).append(item)
        else:
            singletons.append(item)

    clusters = list(groups.values()) + [[s] for s in singletons]
    return clusters


def _layout_cluster(cluster: List[Item]) -> tuple[float, float]:
    """
    Lay out items within a cluster in a tight horizontal row.
    Returns (cluster_width, cluster_height).
    """
    for item in cluster:
        w, h = _default_size(item)
        item.width, item.height = w, h

    x = 0.0
    max_h = 0.0
    for item in cluster:
        item.x = x
        item.y = 0.0
        x    += item.width + ITEM_GAP
        max_h = max(max_h, item.height)

    return x - ITEM_GAP, max_h   # subtract last gap


def layout_json_page(page: Page) -> tuple[float, float]:
    """
    Assign positions to all items on a JSON-parsed page using group clustering.
    Returns (frame_width, frame_height).
    """
    if not page.items:
        return 800, 600

    clusters = _cluster_by_group(page.items)

    # Build proxy items representing each cluster for the outer grid
    cluster_sizes: List[tuple[float, float]] = []
    cluster_origins: List[tuple[float, float]] = []

    for cluster in clusters:
        cw, ch = _layout_cluster(cluster)
        cluster_sizes.append((cw, ch))

    # Arrange clusters in a grid
    n    = len(clusters)
    cols = max(1, math.ceil(math.sqrt(n)))

    x = float(CONT_PAD)
    y = float(CONT_PAD)
    row_h = 0.0
    col   = 0
    max_x = x

    for i, (cluster, (cw, ch)) in enumerate(zip(clusters, cluster_sizes)):
        # Offset each item in the cluster by the cluster's grid position
        for item in cluster:
            item.x += x
            item.y += y
        max_x = max(max_x, x + cw)
        row_h = max(row_h, ch)
        col  += 1
        x    += cw + ITEM_GAP * 3   # wider gap between clusters
        if col >= cols:
            col  = 0
            x    = float(CONT_PAD)
            y   += row_h + ITEM_GAP * 3
            row_h = 0.0

    frame_w = max_x - CONT_PAD + CONT_PAD
    frame_h = y + row_h + CONT_PAD
    return max(frame_w, 400), max(frame_h, 300)


# ── Public entry point ────────────────────────────────────────────────────────

def layout_page(page: Page, has_containment: bool) -> tuple[float, float]:
    """
    Lay out a page and return (frame_width, frame_height).

    Args:
        page:            The Page whose items will be mutated in place.
        has_containment: True for CSV-parsed pages (parent_id is populated);
                         False for JSON-parsed pages.
    """
    if has_containment:
        return layout_csv_page(page)
    return layout_json_page(page)
