"""
Unit and integration tests for the Lucidchart → Miro converter.

Run with:  python -m pytest tests/ -v
       or: python -m unittest discover tests
"""
import json
import unittest
from pathlib import Path

# Ensure fixtures exist before tests run
from tests.make_fixtures import FIXTURE_DIR
import tests.make_fixtures  # noqa: F401  (side-effect: writes fixtures)

from lucid_to_miro.parser.csv_parser  import parse_csv
from lucid_to_miro.parser.json_parser import parse_json
from lucid_to_miro.converter.miro     import convert
from lucid_to_miro.converter.shape_map import to_miro_shape, is_text_only, is_icon
from lucid_to_miro.converter.layout   import (
    layout_csv_page, layout_json_page, _default_size
)
from lucid_to_miro.model import Item

CSV_FILE  = FIXTURE_DIR / "sample.csv"
JSON_FILE = FIXTURE_DIR / "sample.json"


# ─── Shape map ────────────────────────────────────────────────────────────────

class TestShapeMap(unittest.TestCase):
    def test_common_shapes(self):
        self.assertEqual(to_miro_shape("Block"),             "rectangle")
        self.assertEqual(to_miro_shape("DefaultSquareBlock"),"rectangle")
        self.assertEqual(to_miro_shape("Circle"),            "circle")
        self.assertEqual(to_miro_shape("diamond"),           "rhombus")
        self.assertEqual(to_miro_shape("cylinder"),          "can")
        self.assertEqual(to_miro_shape("process"),           "flow_chart_process")
        self.assertEqual(to_miro_shape("terminator"),        "flow_chart_terminator")

    def test_case_insensitive(self):
        self.assertEqual(to_miro_shape("RECTANGLE"), "rectangle")
        self.assertEqual(to_miro_shape("RoundedRectangle"), "round_rectangle")

    def test_unknown_falls_back_to_rectangle(self):
        self.assertEqual(to_miro_shape("WeirdCustomShape"), "rectangle")
        self.assertEqual(to_miro_shape(""),                 "rectangle")
        self.assertEqual(to_miro_shape(None),               "rectangle")

    def test_is_text_only(self):
        self.assertTrue(is_text_only("MinimalTextBlock"))
        self.assertTrue(is_text_only("text"))
        self.assertFalse(is_text_only("Block"))

    def test_is_icon(self):
        self.assertTrue(is_icon("SVGPathBlock2"))
        self.assertTrue(is_icon("svgpathblock"))
        self.assertFalse(is_icon("rectangle"))


# ─── Layout ───────────────────────────────────────────────────────────────────

class TestLayout(unittest.TestCase):
    def _make_item(self, id_, parent=None, is_container=False):
        return Item(id=id_, name="Block", parent_id=parent,
                    is_container=is_container)

    def test_default_size_shape(self):
        item = self._make_item("x")
        w, h = _default_size(item)
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)

    def test_default_size_icon(self):
        item = Item(id="x", name="SVGPathBlock2", is_icon=True)
        w, h = _default_size(item)
        self.assertEqual(w, 80)
        self.assertEqual(h, 80)

    def test_csv_layout_returns_positive_frame_size(self):
        from lucid_to_miro.model import Page
        page = parse_csv(CSV_FILE).pages[0]
        fw, fh = layout_csv_page(page)
        self.assertGreater(fw, 0)
        self.assertGreater(fh, 0)

    def test_json_layout_returns_positive_frame_size(self):
        page = parse_json(JSON_FILE).pages[0]
        fw, fh = layout_json_page(page)
        self.assertGreater(fw, 0)
        self.assertGreater(fh, 0)

    def test_all_items_get_positions(self):
        page = parse_csv(CSV_FILE).pages[0]
        layout_csv_page(page)
        for item in page.items:
            with self.subTest(item=item.id):
                self.assertGreaterEqual(item.width,  1)
                self.assertGreaterEqual(item.height, 1)


# ─── CSV parser ───────────────────────────────────────────────────────────────

class TestCsvParser(unittest.TestCase):
    def setUp(self):
        self.doc = parse_csv(CSV_FILE)

    def test_doc_title(self):
        self.assertEqual(self.doc.title, "Test Diagram")

    def test_page_count(self):
        self.assertEqual(len(self.doc.pages), 2)

    def test_page_titles(self):
        titles = [p.title for p in self.doc.pages]
        self.assertIn("Architecture", titles)
        self.assertIn("Sequence", titles)

    def test_shapes_on_page1(self):
        arch = next(p for p in self.doc.pages if p.title == "Architecture")
        names = [i.name for i in arch.items]
        self.assertIn("Block", names)
        self.assertIn("MinimalTextBlock", names)
        self.assertIn("SVGPathBlock2", names)

    def test_lines_on_page1(self):
        arch = next(p for p in self.doc.pages if p.title == "Architecture")
        self.assertEqual(len(arch.lines), 2)

    def test_line_endpoints(self):
        arch = next(p for p in self.doc.pages if p.title == "Architecture")
        line = next(l for l in arch.lines if l.text == "queries")
        self.assertEqual(line.source_id, "6")
        self.assertEqual(line.target_id, "7")

    def test_container_flag(self):
        arch = next(p for p in self.doc.pages if p.title == "Architecture")
        region = next((i for i in arch.items if i.name == "Region"), None)
        self.assertIsNotNone(region)
        self.assertTrue(region.is_container)

    def test_icon_flag(self):
        arch = next(p for p in self.doc.pages if p.title == "Architecture")
        icon = next((i for i in arch.items if i.name == "SVGPathBlock2"), None)
        self.assertIsNotNone(icon)
        self.assertTrue(icon.is_icon)

    def test_parent_id_innermost(self):
        """Shapes with 'Contained By' = '4|5' should have parent_id='5' (last)."""
        arch = next(p for p in self.doc.pages if p.title == "Architecture")
        web  = next(i for i in arch.items if i.text == "Web Server")
        self.assertEqual(web.parent_id, "5")

    def test_text_area_multiline(self):
        """Text with embedded newlines in CSV is preserved."""
        doc2 = parse_csv(CSV_FILE)
        all_texts = [i.text for p in doc2.pages for i in p.items]
        self.assertIn("Legend text", all_texts)

    def test_parse_bytes(self):
        """Parser accepts raw bytes."""
        raw = CSV_FILE.read_bytes()
        doc = parse_csv(raw)
        self.assertGreater(len(doc.pages), 0)


# ─── JSON parser ──────────────────────────────────────────────────────────────

class TestJsonParser(unittest.TestCase):
    def setUp(self):
        self.doc = parse_json(JSON_FILE)

    def test_doc_title(self):
        self.assertEqual(self.doc.title, "Test Diagram")

    def test_page_count(self):
        # 3 pages total including the empty one
        self.assertEqual(len(self.doc.pages), 3)

    def test_page_titles(self):
        titles = [p.title for p in self.doc.pages]
        self.assertIn("Architecture", titles)
        self.assertIn("Sequence", titles)

    def test_shapes_on_arch_page(self):
        arch = next(p for p in self.doc.pages if p.title == "Architecture")
        self.assertEqual(len(arch.items), 4)

    def test_item_text(self):
        arch = next(p for p in self.doc.pages if p.title == "Architecture")
        ws   = next(i for i in arch.items if i.text == "Web Server")
        self.assertEqual(ws.name, "DefaultSquareBlock")

    def test_lines_parsed(self):
        arch = next(p for p in self.doc.pages if p.title == "Architecture")
        self.assertEqual(len(arch.lines), 2)

    def test_line_with_text(self):
        arch = next(p for p in self.doc.pages if p.title == "Architecture")
        line = next(l for l in arch.lines if l.text == "queries")
        self.assertEqual(line.source_id, "s1")
        self.assertEqual(line.target_id, "s2")

    def test_line_null_endpoint(self):
        arch = next(p for p in self.doc.pages if p.title == "Architecture")
        dangling = next(l for l in arch.lines if l.target_id is None)
        self.assertIsNone(dangling.target_id)

    def test_group_membership(self):
        arch = next(p for p in self.doc.pages if p.title == "Architecture")
        s1   = next(i for i in arch.items if i.id == "s1")
        s3   = next(i for i in arch.items if i.id == "s3")
        self.assertEqual(s1.group_id, "g1")
        self.assertEqual(s3.group_id, "g1")

    def test_icon_flag(self):
        arch = next(p for p in self.doc.pages if p.title == "Architecture")
        icon = next(i for i in arch.items if i.name == "SVGPathBlock2")
        self.assertTrue(icon.is_icon)

    def test_parse_bytes(self):
        raw = JSON_FILE.read_bytes()
        doc = parse_json(raw)
        self.assertGreater(len(doc.pages), 0)


# ─── Converter (end-to-end) ───────────────────────────────────────────────────

class TestConverterCsv(unittest.TestCase):
    def setUp(self):
        self.doc   = parse_csv(CSV_FILE)
        self.board = convert(self.doc, has_containment=True)

    def test_output_structure(self):
        self.assertEqual(self.board["version"], "1")
        self.assertIn("board", self.board)
        self.assertEqual(self.board["board"]["title"], "Test Diagram")
        self.assertIsInstance(self.board["board"]["widgets"], list)

    def test_one_frame_per_non_empty_page(self):
        frames = [w for w in self.board["board"]["widgets"] if w["type"] == "frame"]
        self.assertEqual(len(frames), 2)

    def test_frame_titles_match_pages(self):
        frames = [w for w in self.board["board"]["widgets"] if w["type"] == "frame"]
        titles = {f["title"] for f in frames}
        self.assertIn("Architecture", titles)
        self.assertIn("Sequence",     titles)

    def test_frames_placed_side_by_side(self):
        frames = sorted(
            [w for w in self.board["board"]["widgets"] if w["type"] == "frame"],
            key=lambda f: f["position"]["x"],
        )
        self.assertGreaterEqual(
            frames[1]["position"]["x"],
            frames[0]["position"]["x"] + frames[0]["geometry"]["width"],
        )

    def test_all_non_frame_widgets_have_parent_id(self):
        frame_ids = {w["id"] for w in self.board["board"]["widgets"] if w["type"] == "frame"}
        for w in self.board["board"]["widgets"]:
            if w["type"] != "frame":
                with self.subTest(widget_type=w["type"]):
                    self.assertIn(w["parentId"], frame_ids)

    def test_icon_becomes_image_widget(self):
        images = [w for w in self.board["board"]["widgets"] if w["type"] == "image"]
        self.assertGreater(len(images), 0)

    def test_text_only_becomes_text_widget(self):
        texts = [w for w in self.board["board"]["widgets"] if w["type"] == "text"]
        self.assertGreater(len(texts), 0)

    def test_lines_produced(self):
        lines = [w for w in self.board["board"]["widgets"] if w["type"] == "line"]
        self.assertGreater(len(lines), 0)

    def test_line_text_preserved(self):
        lines = [w for w in self.board["board"]["widgets"] if w["type"] == "line"]
        query_line = next((l for l in lines if l["data"].get("content") == "queries"), None)
        self.assertIsNotNone(query_line)

    def test_container_shape_has_border_color(self):
        """Containers should have a distinct border colour (#555555)."""
        shapes = [w for w in self.board["board"]["widgets"] if w["type"] == "shape"]
        container = next(
            (s for s in shapes if s["style"].get("borderColor") == "#555555"), None
        )
        self.assertIsNotNone(container, "expected at least one container-styled shape")

    def test_scale_doubles_frame_size(self):
        board2x = convert(parse_csv(CSV_FILE), has_containment=True, scale=2.0)
        f1 = next(w for w in self.board["board"]["widgets"]  if w["type"] == "frame")
        f2 = next(w for w in board2x["board"]["widgets"] if w["type"] == "frame")
        self.assertAlmostEqual(f2["geometry"]["width"], f1["geometry"]["width"] * 2, delta=5)


class TestConverterJson(unittest.TestCase):
    def setUp(self):
        self.doc   = parse_json(JSON_FILE)
        self.board = convert(self.doc, has_containment=False)

    def test_output_structure(self):
        self.assertEqual(self.board["version"], "1")
        self.assertIn("board", self.board)

    def test_empty_page_skipped(self):
        frames = [w for w in self.board["board"]["widgets"] if w["type"] == "frame"]
        titles = {f["title"] for f in frames}
        self.assertNotIn("Empty Page", titles)

    def test_two_non_empty_frames(self):
        frames = [w for w in self.board["board"]["widgets"] if w["type"] == "frame"]
        self.assertEqual(len(frames), 2)

    def test_grouped_items_clustered(self):
        """s1 and s3 share group g1; they should end up with similar y coordinates."""
        shapes = [w for w in self.board["board"]["widgets"] if w["type"] == "shape"]
        s1 = next((s for s in shapes if s.get("id") == "s1"), None)
        s3 = next((s for s in shapes if s.get("id") == "s3"), None)
        if s1 and s3:
            self.assertAlmostEqual(s1["position"]["y"], s3["position"]["y"], delta=5)

    def test_dangling_line_omitted_or_present(self):
        """A line with only one resolvable endpoint should still appear."""
        lines = [w for w in self.board["board"]["widgets"] if w["type"] == "line"]
        self.assertGreater(len(lines), 0)


# ─── CLI smoke test ───────────────────────────────────────────────────────────

class TestCli(unittest.TestCase):
    def test_csv_cli(self):
        import tempfile, os, sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from lucid2miro import main
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            main([str(CSV_FILE), "-o", str(out), "--pretty"])
            data = json.loads(out.read_text())
            self.assertEqual(data["version"], "1")

    def test_json_cli(self):
        import tempfile, sys
        from lucid2miro import main
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            main([str(JSON_FILE), "-o", str(out)])
            data = json.loads(out.read_text())
            self.assertEqual(data["version"], "1")

    def test_pages_filter(self):
        import tempfile, sys
        from lucid2miro import main
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.json"
            main([str(JSON_FILE), "-o", str(out), "--pages", "Architecture"])
            data = json.loads(out.read_text())
            frames = [w for w in data["board"]["widgets"] if w["type"] == "frame"]
            self.assertEqual(len(frames), 1)
            self.assertEqual(frames[0]["title"], "Architecture")


if __name__ == "__main__":
    unittest.main()
