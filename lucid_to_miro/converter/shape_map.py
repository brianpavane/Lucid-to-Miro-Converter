"""
Maps Lucidchart shape names / class identifiers to Miro REST API v2 shape types.
"""
from __future__ import annotations

# Lucidchart "Name" (CSV) or "class" (JSON) → Miro shape type
_MAP: dict[str, str] = {
    # ── Basic shapes ──────────────────────────────────────────────────────────
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

    # ── Arrows ────────────────────────────────────────────────────────────────
    "arrow":                "arrow",
    "rightarrow":           "arrow",
    "right arrow":          "arrow",
    "leftarrow":            "left_arrow",
    "doublearrow":          "left_right_arrow",
    "uparrow":              "up_arrow",
    "downarrow":            "down_arrow",

    # ── Flowchart ─────────────────────────────────────────────────────────────
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

    # ── Callouts ──────────────────────────────────────────────────────────────
    "callout":              "wedge_round_rectangle_callout",
    "cloudcallout":         "cloud_callout",

    # ── Cloud / infra ─────────────────────────────────────────────────────────
    "cloud":                "cloud",
    "cylinder":             "can",
    "database":             "can",
    "can":                  "can",

    # ── Cloud provider containers → styled rectangles ─────────────────────────
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

    # ── AWS shapes (common names) ─────────────────────────────────────────────
    "autoscaling":          "rectangle",
    "loadbalancer":         "rectangle",
    "elasticnetworkinterface": "rectangle",
    "elasticloadbalancing": "rectangle",

    # ── Text / label ──────────────────────────────────────────────────────────
    "minimaltextblock":     "rectangle",   # handled as text widget by converter
    "text":                 "rectangle",
    "label":                "rectangle",
}


def to_miro_shape(lucid_name: str) -> str:
    """
    Return the Miro shape type for a given Lucidchart shape name.
    Case-insensitive; strips spaces and hyphens.  Defaults to "rectangle".
    """
    if not lucid_name:
        return "rectangle"
    key = lucid_name.lower().replace("-", "").replace(" ", "").replace("_", "")
    return _MAP.get(key, "rectangle")


def is_text_only(lucid_name: str) -> bool:
    """True when the shape should become a Miro text widget instead of a shape."""
    key = lucid_name.lower().replace(" ", "")
    return key in {"minimaltextblock", "text", "label", "textbox"}


def is_icon(lucid_name: str) -> bool:
    """True when the shape is an SVG icon / image block."""
    key = lucid_name.lower()
    return "svgpathblock" in key or key in {"imageblock", "icon", "customicon"}
