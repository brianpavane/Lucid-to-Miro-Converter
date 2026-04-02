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


# ─── Batch mode ───────────────────────────────────────────────────────────────

class TestBatch(unittest.TestCase):
    """Tests for batch/bulk conversion mode (directory input)."""

    def setUp(self):
        from lucid2miro import main
        self.main = main

    def _make_input_dir(self, tmp: str, fmt: str, count: int = 3) -> Path:
        """Copy the sample fixture into a temp directory <count> times."""
        import shutil
        src = CSV_FILE if fmt == "csv" else JSON_FILE
        d = Path(tmp) / "inputs"
        d.mkdir()
        for i in range(count):
            shutil.copy(src, d / f"diagram_{i}.{fmt}")
        return d

    # ── CSV batch ─────────────────────────────────────────────────────────────

    def test_batch_csv_creates_output_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            in_dir  = self._make_input_dir(tmp, "csv", count=3)
            out_dir = Path(tmp) / "outputs"
            self.main([str(in_dir), "--format", "csv", "--output-dir", str(out_dir)])
            out_files = list(out_dir.glob("*.miro.json"))
            self.assertEqual(len(out_files), 3)

    def test_batch_csv_output_filenames_match_input(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            in_dir  = self._make_input_dir(tmp, "csv", count=2)
            out_dir = Path(tmp) / "outputs"
            self.main([str(in_dir), "--format", "csv", "--output-dir", str(out_dir)])
            stems = {f.stem.replace(".miro", "") for f in out_dir.glob("*.miro.json")}
            self.assertIn("diagram_0", stems)
            self.assertIn("diagram_1", stems)

    def test_batch_csv_output_is_valid_miro_json(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            in_dir  = self._make_input_dir(tmp, "csv", count=1)
            out_dir = Path(tmp) / "outputs"
            self.main([str(in_dir), "--format", "csv", "--output-dir", str(out_dir)])
            out_file = next(out_dir.glob("*.miro.json"))
            data = json.loads(out_file.read_text())
            self.assertEqual(data["version"], "1")
            self.assertIn("board", data)
            self.assertIsInstance(data["board"]["widgets"], list)

    # ── JSON batch ────────────────────────────────────────────────────────────

    def test_batch_json_creates_output_files(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            in_dir  = self._make_input_dir(tmp, "json", count=2)
            out_dir = Path(tmp) / "outputs"
            self.main([str(in_dir), "--format", "json", "--output-dir", str(out_dir)])
            out_files = list(out_dir.glob("*.miro.json"))
            self.assertEqual(len(out_files), 2)

    def test_batch_json_output_is_valid_miro_json(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            in_dir  = self._make_input_dir(tmp, "json", count=1)
            out_dir = Path(tmp) / "outputs"
            self.main([str(in_dir), "--format", "json", "--output-dir", str(out_dir)])
            out_file = next(out_dir.glob("*.miro.json"))
            data = json.loads(out_file.read_text())
            self.assertEqual(data["version"], "1")

    # ── Output directory creation ─────────────────────────────────────────────

    def test_batch_creates_output_dir_if_missing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            in_dir  = self._make_input_dir(tmp, "csv", count=1)
            out_dir = Path(tmp) / "nested" / "new_dir"
            self.assertFalse(out_dir.exists())
            self.main([str(in_dir), "--format", "csv", "--output-dir", str(out_dir)])
            self.assertTrue(out_dir.exists())
            self.assertEqual(len(list(out_dir.glob("*.miro.json"))), 1)

    def test_batch_defaults_output_to_input_dir(self):
        """When --output-dir is omitted, outputs land alongside the inputs."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            in_dir = self._make_input_dir(tmp, "csv", count=2)
            self.main([str(in_dir), "--format", "csv"])
            out_files = list(in_dir.glob("*.miro.json"))
            self.assertEqual(len(out_files), 2)

    # ── Error handling ────────────────────────────────────────────────────────

    def test_batch_missing_format_exits(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            in_dir = self._make_input_dir(tmp, "csv", count=1)
            with self.assertRaises(SystemExit) as cm:
                self.main([str(in_dir)])   # no --format
            self.assertNotEqual(cm.exception.code, 0)

    def test_batch_no_matching_files_exits(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            in_dir  = self._make_input_dir(tmp, "csv", count=1)
            out_dir = Path(tmp) / "out"
            with self.assertRaises(SystemExit) as cm:
                # Ask for json but only csv files exist
                self.main([str(in_dir), "--format", "json", "--output-dir", str(out_dir)])
            self.assertNotEqual(cm.exception.code, 0)

    def test_batch_pretty_output_is_indented(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            in_dir  = self._make_input_dir(tmp, "csv", count=1)
            out_dir = Path(tmp) / "out"
            self.main([str(in_dir), "--format", "csv",
                       "--output-dir", str(out_dir), "--pretty"])
            out_file = next(out_dir.glob("*.miro.json"))
            raw = out_file.read_text()
            self.assertIn("\n", raw)   # pretty-printed has newlines

    def test_batch_scale_applied(self):
        """Scaling in batch mode produces larger frame geometries."""
        import tempfile, shutil
        with tempfile.TemporaryDirectory() as tmp:
            in_dir   = self._make_input_dir(tmp, "csv", count=1)
            out1_dir = Path(tmp) / "out1x"
            out2_dir = Path(tmp) / "out2x"
            self.main([str(in_dir), "--format", "csv", "--output-dir", str(out1_dir)])
            self.main([str(in_dir), "--format", "csv", "--output-dir", str(out2_dir),
                       "--scale", "2.0"])
            d1 = json.loads(next(out1_dir.glob("*.miro.json")).read_text())
            d2 = json.loads(next(out2_dir.glob("*.miro.json")).read_text())
            f1 = next(w for w in d1["board"]["widgets"] if w["type"] == "frame")
            f2 = next(w for w in d2["board"]["widgets"] if w["type"] == "frame")
            self.assertGreater(f2["geometry"]["width"], f1["geometry"]["width"])


# ─── --clean-names flag ───────────────────────────────────────────────────────

class TestCleanNames(unittest.TestCase):
    """Tests for the --clean-names output-naming option."""

    def setUp(self):
        from lucid2miro import main
        self.main = main

    def _make_input_dir(self, tmp, fmt, count=2):
        import shutil
        src = CSV_FILE if fmt == "csv" else JSON_FILE
        d = Path(tmp) / "inputs"
        d.mkdir()
        for i in range(count):
            shutil.copy(src, d / f"diagram_{i}.{fmt}")
        return d

    # ── Batch: different output dir ───────────────────────────────────────────

    def test_batch_clean_names_produces_dot_json(self):
        """--clean-names batch → outputs are <stem>.json, not <stem>.miro.json"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            in_dir  = self._make_input_dir(tmp, "csv", count=2)
            out_dir = Path(tmp) / "out"
            self.main([str(in_dir), "--format", "csv",
                       "--output-dir", str(out_dir), "--clean-names"])
            out_files = list(out_dir.glob("*.json"))
            self.assertEqual(len(out_files), 2)
            for f in out_files:
                self.assertFalse(f.name.endswith(".miro.json"),
                                 f"{f.name} should not contain .miro")

    def test_batch_clean_names_stems_match_input(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            in_dir  = self._make_input_dir(tmp, "csv", count=2)
            out_dir = Path(tmp) / "out"
            self.main([str(in_dir), "--format", "csv",
                       "--output-dir", str(out_dir), "--clean-names"])
            stems = {f.stem for f in out_dir.glob("*.json")}
            self.assertIn("diagram_0", stems)
            self.assertIn("diagram_1", stems)

    def test_batch_clean_names_output_is_valid(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            in_dir  = self._make_input_dir(tmp, "csv", count=1)
            out_dir = Path(tmp) / "out"
            self.main([str(in_dir), "--format", "csv",
                       "--output-dir", str(out_dir), "--clean-names"])
            out_file = next(out_dir.glob("*.json"))
            data = json.loads(out_file.read_text())
            self.assertEqual(data["version"], "1")

    def test_batch_clean_names_json_format(self):
        """Works for JSON input format too."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            in_dir  = self._make_input_dir(tmp, "json", count=2)
            out_dir = Path(tmp) / "out"
            self.main([str(in_dir), "--format", "json",
                       "--output-dir", str(out_dir), "--clean-names"])
            out_files = list(out_dir.glob("*.json"))
            self.assertEqual(len(out_files), 2)
            for f in out_files:
                self.assertFalse(f.name.endswith(".miro.json"))

    # ── Batch: same dir is rejected ───────────────────────────────────────────

    def test_batch_clean_names_same_dir_exits(self):
        """--clean-names with output == input dir must be rejected (would overwrite sources)."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            in_dir = self._make_input_dir(tmp, "csv", count=1)
            with self.assertRaises(SystemExit) as cm:
                self.main([str(in_dir), "--format", "csv", "--clean-names"])
            self.assertNotEqual(cm.exception.code, 0)

    def test_batch_clean_names_explicit_same_dir_exits(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            in_dir = self._make_input_dir(tmp, "csv", count=1)
            with self.assertRaises(SystemExit) as cm:
                # --output-dir explicitly set to the same path
                self.main([str(in_dir), "--format", "csv",
                           "--output-dir", str(in_dir), "--clean-names"])
            self.assertNotEqual(cm.exception.code, 0)

    # ── Single-file mode ──────────────────────────────────────────────────────

    def test_single_clean_names_csv_input(self):
        """CSV input + --clean-names → <stem>.json (no .miro)"""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "diagram_0.json"
            self.main([str(CSV_FILE), "-o", str(out), "--clean-names"])
            self.assertTrue(out.exists())
            data = json.loads(out.read_text())
            self.assertEqual(data["version"], "1")

    def test_single_clean_names_would_overwrite_json_exits(self):
        """JSON input + --clean-names with no -o must be rejected (would overwrite source)."""
        import tempfile, shutil
        with tempfile.TemporaryDirectory() as tmp:
            # Copy fixture so we don't touch the real file
            src = Path(tmp) / "diagram.json"
            shutil.copy(JSON_FILE, src)
            with self.assertRaises(SystemExit) as cm:
                self.main([str(src), "--clean-names"])
            self.assertNotEqual(cm.exception.code, 0)

    def test_single_clean_names_json_explicit_output_ok(self):
        """JSON input + --clean-names is fine when -o points elsewhere."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "board.json"
            self.main([str(JSON_FILE), "-o", str(out), "--clean-names"])
            self.assertTrue(out.exists())
            data = json.loads(out.read_text())
            self.assertEqual(data["version"], "1")

    # ── Default still works ───────────────────────────────────────────────────

    def test_default_naming_unchanged(self):
        """Without --clean-names, .miro.json suffix is still used."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            in_dir  = self._make_input_dir(tmp, "csv", count=1)
            out_dir = Path(tmp) / "out"
            self.main([str(in_dir), "--format", "csv", "--output-dir", str(out_dir)])
            out_files = list(out_dir.glob("*.miro.json"))
            self.assertEqual(len(out_files), 1)


if __name__ == "__main__":
    unittest.main()
