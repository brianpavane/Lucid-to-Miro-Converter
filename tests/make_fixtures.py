"""
Creates minimal synthetic fixture files used by the test suite.
Run once:  python tests/make_fixtures.py
"""
import json
import textwrap
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures"
FIXTURE_DIR.mkdir(exist_ok=True)

# ── Minimal CSV ───────────────────────────────────────────────────────────────
CSV_CONTENT = textwrap.dedent("""\
    Id,Name,Shape Library,Page ID,Contained By,Group,Line Source,Line Destination,Source Arrow,Destination Arrow,Status,Text Area 1,Text Area 2,Comments
    1,Document,,,,,,,,,Draft,Test Diagram,,
    2,Page,,,,,,,,,,Architecture,,
    3,Page,,,,,,,,,,Sequence,,
    4,Region,AWS 2021,2,,,,,,,, AWS Region 1,,
    5,Availability Zone,AWS 2019,2,4,,,,,,, AZ 1,,
    6,Block,Standard,2,4|5,,,,,,, Web Server,,
    7,Block,Standard,2,4|5,,,,,,, Database,,
    8,MinimalTextBlock,Standard,2,,,,,,,,Legend text,,
    9,SVGPathBlock2,,2,,,,,,,,,,,
    10,Line,,2,,,6,7,None,Arrow,,queries,,
    11,Line,,2,,,6,,None,Arrow,,internet,,
    12,Group 1,,2,,,,,,,,,,,
    13,Circle,Geometric Shapes,3,,,,,,,,Start,,
    14,Rectangle,Geometric Shapes,3,,,,,,,,Process Data,,
    15,Rectangle,Geometric Shapes,3,,,,,,,,End,,
    16,Line,,3,,,13,14,None,Arrow,,,,,
    17,Line,,3,,,14,15,None,Arrow,,,,,
""")

# ── Minimal JSON ──────────────────────────────────────────────────────────────
JSON_CONTENT = {
    "id": "doc-1",
    "title": "Test Diagram",
    "product": "lucidchart",
    "accountId": "acct-1",
    "data": {},
    "pages": [
        {
            "id": "page-arch",
            "title": "Architecture",
            "index": 0,
            "customData": [],
            "linkedData": [],
            "items": {
                "shapes": [
                    {"id": "s1", "class": "DefaultSquareBlock",
                     "textAreas": [{"label": "Text", "text": "Web Server"}],
                     "customData": [], "linkedData": []},
                    {"id": "s2", "class": "DefaultSquareBlock",
                     "textAreas": [{"label": "Text", "text": "Database"}],
                     "customData": [], "linkedData": []},
                    {"id": "s3", "class": "SVGPathBlock2",
                     "textAreas": [],
                     "customData": [], "linkedData": []},
                    {"id": "s4", "class": "MinimalTextBlock",
                     "textAreas": [{"label": "Text", "text": "Legend"}],
                     "customData": [], "linkedData": []},
                ],
                "lines": [
                    {"id": "l1",
                     "endpoint1": {"style": "None", "connectedTo": "s1"},
                     "endpoint2": {"style": "Arrow", "connectedTo": "s2"},
                     "textAreas": [{"label": "t0", "text": "queries"}],
                     "customData": [], "linkedData": []},
                    {"id": "l2",
                     "endpoint1": {"style": "None", "connectedTo": "s1"},
                     "endpoint2": {"style": "Arrow", "connectedTo": None},
                     "textAreas": [],
                     "customData": [], "linkedData": []},
                ],
                "groups": [
                    {"id": "g1", "members": ["s1", "s3"],
                     "customData": [], "linkedData": []},
                ],
                "layers": [],
            },
        },
        {
            "id": "page-seq",
            "title": "Sequence",
            "index": 1,
            "customData": [],
            "linkedData": [],
            "items": {
                "shapes": [
                    {"id": "p2s1", "class": "DefaultSquareBlock",
                     "textAreas": [{"label": "Text", "text": "Start"}],
                     "customData": [], "linkedData": []},
                    {"id": "p2s2", "class": "DefaultSquareBlock",
                     "textAreas": [{"label": "Text", "text": "End"}],
                     "customData": [], "linkedData": []},
                ],
                "lines": [
                    {"id": "p2l1",
                     "endpoint1": {"style": "None",  "connectedTo": "p2s1"},
                     "endpoint2": {"style": "Arrow", "connectedTo": "p2s2"},
                     "textAreas": [],
                     "customData": [], "linkedData": []},
                ],
                "groups": [],
                "layers": [],
            },
        },
        # Empty page — should be skipped in output
        {
            "id": "page-empty",
            "title": "Empty Page",
            "index": 2,
            "customData": [],
            "linkedData": [],
            "items": {"shapes": [], "lines": [], "groups": [], "layers": []},
        },
    ],
}

(FIXTURE_DIR / "sample.csv").write_text(CSV_CONTENT, encoding="utf-8")
(FIXTURE_DIR / "sample.json").write_text(
    json.dumps(JSON_CONTENT, indent=2), encoding="utf-8"
)
print(f"Fixtures written to {FIXTURE_DIR}")
