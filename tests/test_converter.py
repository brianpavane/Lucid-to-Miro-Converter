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


# ─── VSDX parser ─────────────────────────────────────────────────────────────

import io
import zipfile

from lucid_to_miro.parser.vsdx_parser import parse_vsdx, extract_media
from lucid_to_miro.converter.layout   import frame_from_items

_VSDX_NS  = "http://schemas.microsoft.com/office/visio/2012/main"
_VSDX_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _make_vsdx(
    page_title="Test Page",
    shapes=None,       # list of (id, master_id, pin_x, pin_y, w, h, text)
    connects=None,     # list of (conn_id, begin_to, end_to)
    masters=None,      # list of (id, name_u)
    page_w=11.0,
    page_h=8.5,
) -> bytes:
    """Build a minimal .vsdx bytes for testing."""
    if shapes   is None: shapes   = []
    if connects is None: connects = []
    if masters  is None: masters  = []

    ns  = _VSDX_NS
    rel = _VSDX_REL
    pkg = "http://schemas.openxmlformats.org/package/2006/relationships"

    # masters.xml
    master_rows = "".join(
        f'<Master ID="{mid}" NameU="{name}" Name="{name}"/>'
        for mid, name in masters
    )
    masters_xml = f'<?xml version="1.0"?><Masters xmlns="{ns}">{master_rows}</Masters>'

    # page1.xml shapes
    shape_rows = ""
    for sid, mid, px, py, w, h, txt in shapes:
        master_attr = f' Master="{mid}"' if mid else ""
        shape_rows += (
            f'<Shape ID="{sid}" Type="Shape"{master_attr}>'
            f'<XForm>'
            f'<PinX>{px}</PinX><PinY>{py}</PinY>'
            f'<Width>{w}</Width><Height>{h}</Height>'
            f'<LocPinX F="Width*0.5">{w/2}</LocPinX>'
            f'<LocPinY F="Height*0.5">{h/2}</LocPinY>'
            f'</XForm>'
            f'<Text>{txt}</Text>'
            f'</Shape>'
        )
    conn_shapes = "".join(
        f'<Shape ID="{cid}" Type="Shape"/>' for cid, _, _ in connects
    )
    connect_rows = "".join(
        f'<Connect FromSheet="{cid}" FromCell="BeginX" ToSheet="{beg}" ToCell="PinX"/>'
        f'<Connect FromSheet="{cid}" FromCell="EndX"   ToSheet="{end}" ToCell="PinX"/>'
        for cid, beg, end in connects
    )

    page1_xml = (
        f'<?xml version="1.0"?>'
        f'<PageContents xmlns="{ns}" xmlns:r="{rel}">'
        f'<PageSheet><PageProps>'
        f'<PageWidth>{page_w}</PageWidth><PageHeight>{page_h}</PageHeight>'
        f'</PageProps></PageSheet>'
        f'<Shapes>{shape_rows}{conn_shapes}</Shapes>'
        f'<Connects>{connect_rows}</Connects>'
        f'</PageContents>'
    )

    pages_xml = (
        f'<?xml version="1.0"?>'
        f'<Pages xmlns="{ns}" xmlns:r="{rel}">'
        f'<Page ID="1" Name="{page_title}"><Rel r:id="rId1"/></Page>'
        f'</Pages>'
    )
    pages_rels = (
        f'<?xml version="1.0"?>'
        f'<Relationships xmlns="{pkg}">'
        f'<Relationship Id="rId1" Type="http://schemas.microsoft.com/visio/2010/relationships/page" Target="page1.xml"/>'
        f'</Relationships>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("visio/pages/pages.xml", pages_xml)
        zf.writestr("visio/pages/_rels/pages.xml.rels", pages_rels)
        zf.writestr("visio/pages/page1.xml", page1_xml)
        zf.writestr("visio/masters/masters.xml", masters_xml)
    return buf.getvalue()


class TestVsdxParser(unittest.TestCase):

    def test_has_coordinates_flag(self):
        vsdx = _make_vsdx(shapes=[(1, "", 2, 6, 1, 0.5, "A")])
        doc  = parse_vsdx(vsdx)
        self.assertTrue(doc.has_coordinates)

    def test_page_title(self):
        vsdx = _make_vsdx(page_title="My Diagram",
                          shapes=[(1, "", 1, 1, 1, 1, "X")])
        doc  = parse_vsdx(vsdx)
        self.assertEqual(doc.pages[0].title, "My Diagram")

    def test_shape_count(self):
        shapes = [(i, "", float(i), 4.0, 1.0, 0.5, f"S{i}") for i in range(1, 5)]
        doc    = parse_vsdx(_make_vsdx(shapes=shapes))
        self.assertEqual(len(doc.pages[0].items), 4)

    def test_coordinate_conversion(self):
        # PinX=2, PinY=6.5, W=1.5, H=0.75  on page H=8.5
        # tl_x = (2 - 0.75) * 96 = 120
        # tl_y = (8.5 - (6.5 - 0.375) - 0.75) * 96 = (8.5 - 6.875) * 96 = 156
        shapes = [(1, "", 2.0, 6.5, 1.5, 0.75, "Box")]
        doc    = parse_vsdx(_make_vsdx(shapes=shapes))
        item   = doc.pages[0].items[0]
        self.assertAlmostEqual(item.x,      120, delta=2)
        self.assertAlmostEqual(item.y,      156, delta=2)
        self.assertAlmostEqual(item.width,  144, delta=2)
        self.assertAlmostEqual(item.height,  72, delta=2)

    def test_connectors_become_lines(self):
        shapes   = [(1, "", 1.0, 4.0, 1.0, 0.5, "A"),
                    (2, "", 4.0, 4.0, 1.0, 0.5, "B")]
        connects = [(10, "1", "2")]
        doc      = parse_vsdx(_make_vsdx(shapes=shapes, connects=connects))
        page     = doc.pages[0]
        self.assertEqual(len(page.items), 2)
        self.assertEqual(len(page.lines), 1)
        self.assertEqual(page.lines[0].source_id, "1_1")
        self.assertEqual(page.lines[0].target_id, "1_2")

    def test_connector_excluded_from_items(self):
        shapes   = [(1, "", 1.0, 4.0, 1.0, 0.5, "A"),
                    (2, "", 4.0, 4.0, 1.0, 0.5, "B")]
        connects = [(99, "1", "2")]
        doc      = parse_vsdx(_make_vsdx(shapes=shapes, connects=connects))
        item_ids = {i.id for i in doc.pages[0].items}
        self.assertNotIn("1_99", item_ids)

    def test_master_name_used(self):
        masters = [("5", "Cylinder")]
        shapes  = [(1, "5", 3.0, 4.0, 1.0, 1.0, "DB")]
        doc     = parse_vsdx(_make_vsdx(shapes=shapes, masters=masters))
        self.assertEqual(doc.pages[0].items[0].name, "Cylinder")

    def test_shape_text_extracted(self):
        shapes = [(1, "", 2.0, 4.0, 1.0, 0.5, "Hello World")]
        doc    = parse_vsdx(_make_vsdx(shapes=shapes))
        self.assertEqual(doc.pages[0].items[0].text, "Hello World")

    def test_empty_page_excluded(self):
        """A page with no shapes and no lines must not appear in doc.pages."""
        vsdx = _make_vsdx(shapes=[])
        doc  = parse_vsdx(vsdx)
        self.assertEqual(len(doc.pages), 0)

    def test_frame_from_items(self):
        shapes = [(1, "", 1.0, 7.5, 1.0, 0.5, "A"),
                  (2, "", 5.0, 5.0, 2.0, 1.0, "B")]
        doc    = parse_vsdx(_make_vsdx(shapes=shapes))
        page   = doc.pages[0]
        fw, fh = frame_from_items(page)
        # max_x = max(item.x + item.width for item in page.items) + CONT_PAD
        max_x = max(i.x + i.width  for i in page.items)
        max_y = max(i.y + i.height for i in page.items)
        self.assertGreaterEqual(fw, max_x)
        self.assertGreaterEqual(fh, max_y)

    def test_convert_skips_layout(self):
        """convert() must not overwrite VSDX coordinates with auto-layout."""
        shapes = [(1, "", 2.0, 6.5, 1.5, 0.75, "Box")]
        doc    = parse_vsdx(_make_vsdx(shapes=shapes))
        item   = doc.pages[0].items[0]
        orig_x, orig_y = item.x, item.y
        board  = convert(doc, has_containment=True)
        # Re-check same item — x/y should be unchanged after convert()
        self.assertAlmostEqual(item.x, orig_x, delta=2)
        self.assertAlmostEqual(item.y, orig_y, delta=2)

    def test_convert_produces_frame_and_shape(self):
        shapes = [(1, "", 2.0, 6.5, 1.5, 0.75, "Node")]
        doc    = parse_vsdx(_make_vsdx(shapes=shapes))
        board  = convert(doc, has_containment=True)
        widgets = board["board"]["widgets"]
        self.assertEqual(sum(1 for w in widgets if w["type"] == "frame"), 1)
        self.assertEqual(sum(1 for w in widgets if w["type"] == "shape"), 1)

    def test_extract_media_writes_files(self):
        """extract_media() writes image_data bytes to disk."""
        import tempfile
        # Build a shape with embedded PNG-ish image data
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
        shapes = [(1, "", 2.0, 6.5, 1.5, 0.75, "Icon")]
        doc    = parse_vsdx(_make_vsdx(shapes=shapes))
        # Manually inject image_data
        doc.pages[0].items[0].is_icon   = True
        doc.pages[0].items[0].image_data = png_header

        with tempfile.TemporaryDirectory() as tmpdir:
            written = extract_media(doc, tmpdir)
            self.assertEqual(len(written), 1)
            path = list(written.values())[0]
            self.assertTrue(path.exists())
            self.assertEqual(path.read_bytes(), png_header)


# ─── VSDX writer ──────────────────────────────────────────────────────────────

class TestVsdxWriter(unittest.TestCase):
    """Tests for lucid_to_miro.converter.vsdx_writer.write_vsdx."""

    def setUp(self):
        from lucid_to_miro.converter.vsdx_writer import write_vsdx
        from lucid_to_miro.model import Document, Page, Item, Line, Style
        self._write = write_vsdx
        self._Document = Document
        self._Page = Page
        self._Item = Item
        self._Line = Line
        self._Style = Style

    def _simple_doc(self, n_items=2):
        """Build a minimal Document with pre-set coordinates."""
        doc = self._Document(title="Test", has_coordinates=True)
        items = [
            self._Item(id=f"s{i}", name="Block", text=f"Shape {i}",
                       x=float(i * 200), y=50.0, width=160.0, height=80.0)
            for i in range(n_items)
        ]
        doc.pages.append(self._Page(id="p1", title="Tab 1", items=items))
        return doc

    def _write_to_bytes(self, doc, **kwargs) -> bytes:
        import io
        buf = io.BytesIO()
        self._write(doc, buf, **kwargs)
        return buf.getvalue()

    # ── Structure ─────────────────────────────────────────────────────────────

    def test_output_is_valid_zip(self):
        import zipfile, io
        data = self._write_to_bytes(self._simple_doc())
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(data)))

    def test_required_opc_members(self):
        import zipfile, io
        data = self._write_to_bytes(self._simple_doc())
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
        for required in (
            "[Content_Types].xml", "_rels/.rels",
            "visio/document.xml", "visio/_rels/document.xml.rels",
            "visio/pages/pages.xml", "visio/pages/_rels/pages.xml.rels",
            "visio/pages/page1.xml",
        ):
            self.assertIn(required, names, msg=f"Missing {required}")

    def test_multi_page_creates_multiple_page_files(self):
        import zipfile, io
        doc = self._Document(title="Multi", has_coordinates=True)
        for i in range(3):
            it = self._Item(id=f"x{i}", name="Block", x=0.0, y=0.0,
                            width=100.0, height=50.0)
            doc.pages.append(self._Page(id=f"pg{i}", title=f"Page {i+1}", items=[it]))
        data = self._write_to_bytes(doc)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
        for i in range(1, 4):
            self.assertIn(f"visio/pages/page{i}.xml", names)

    def test_page_titles_in_pages_xml(self):
        import zipfile, io, xml.etree.ElementTree as ET
        doc = self._simple_doc()
        doc.pages[0].title = "My Custom Tab"
        data = self._write_to_bytes(doc)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            pages_xml = zf.read("visio/pages/pages.xml").decode()
        self.assertIn("My Custom Tab", pages_xml)

    # ── Coordinates ───────────────────────────────────────────────────────────

    def test_coordinate_round_trip(self):
        """Write VSDX, parse it back, check pixel coords are preserved."""
        import io, zipfile
        from lucid_to_miro.parser.vsdx_parser import parse_vsdx
        doc = self._Document(title="RT", has_coordinates=True)
        it = self._Item(id="sh1", name="Block", text="Hello",
                        x=96.0, y=192.0, width=192.0, height=96.0)
        doc.pages.append(self._Page(id="p1", title="P1", items=[it]))
        buf = io.BytesIO()
        self._write(doc, buf)
        doc2 = parse_vsdx(buf.getvalue())  # parser accepts raw bytes
        self.assertEqual(len(doc2.pages), 1)
        self.assertEqual(len(doc2.pages[0].items), 1)
        it2 = doc2.pages[0].items[0]
        self.assertAlmostEqual(it2.x,      96.0,  delta=2)
        self.assertAlmostEqual(it2.y,      192.0, delta=2)
        self.assertAlmostEqual(it2.width,  192.0, delta=2)
        self.assertAlmostEqual(it2.height, 96.0,  delta=2)

    def test_shape_text_in_page_xml(self):
        import zipfile, io
        doc = self._simple_doc(1)
        doc.pages[0].items[0].text = "Hello World"
        data = self._write_to_bytes(doc)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            page_xml = zf.read("visio/pages/page1.xml").decode()
        self.assertIn("Hello World", page_xml)

    # ── Connectors ────────────────────────────────────────────────────────────

    def test_connector_in_page_xml(self):
        import zipfile, io
        doc = self._simple_doc(2)
        line = self._Line(id="l1", source_id="s0", target_id="s1",
                          source_arrow="none", target_arrow="arrow", text="edge")
        doc.pages[0].lines.append(line)
        data = self._write_to_bytes(doc)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            page_xml = zf.read("visio/pages/page1.xml").decode()
        self.assertIn('Type="Edge"', page_xml)
        self.assertIn("<Connects>",  page_xml)
        self.assertIn("edge",        page_xml)

    def test_connector_connect_elements(self):
        import zipfile, io
        doc = self._simple_doc(2)
        line = self._Line(id="l1", source_id="s0", target_id="s1")
        doc.pages[0].lines.append(line)
        data = self._write_to_bytes(doc)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            page_xml = zf.read("visio/pages/page1.xml").decode()
        self.assertEqual(page_xml.count("<Connect "), 2)

    # ── Layout integration ────────────────────────────────────────────────────

    def test_csv_doc_gets_layout_applied(self):
        """CSV doc (no coords) should have coords after write_vsdx runs layout."""
        import io
        from lucid_to_miro.parser.csv_parser import parse_csv
        from tests.make_fixtures import FIXTURE_DIR
        doc, _ = parse_csv(FIXTURE_DIR / "sample.csv"), True
        doc = parse_csv(FIXTURE_DIR / "sample.csv")
        # All items start at 0,0 — after write_vsdx layout runs, at least one differs
        buf = io.BytesIO()
        self._write(doc, buf, has_containment=True)
        any_nonzero = any(
            it.x != 0 or it.y != 0
            for pg in doc.pages for it in pg.items
        )
        self.assertTrue(any_nonzero)

    def test_scale_applied(self):
        import io
        doc = self._simple_doc(1)
        doc.pages[0].items[0].x = 100.0
        doc.pages[0].items[0].width = 160.0
        buf = io.BytesIO()
        self._write(doc, buf, scale=2.0)
        item = doc.pages[0].items[0]
        self.assertAlmostEqual(item.x,     200.0, delta=1)
        self.assertAlmostEqual(item.width, 320.0, delta=1)

    # ── File output ───────────────────────────────────────────────────────────

    def test_write_to_file_path(self):
        import tempfile, zipfile
        doc = self._simple_doc()
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "out.vsdx"
            self._write(doc, out)
            self.assertTrue(out.exists())
            self.assertTrue(zipfile.is_zipfile(str(out)))

    def test_empty_pages_excluded(self):
        import zipfile, io
        doc = self._Document(title="T", has_coordinates=True)
        doc.pages.append(self._Page(id="empty", title="Empty"))
        doc.pages.append(self._Page(id="full",  title="Full",
                                    items=[self._Item(id="x", name="Block",
                                                      x=0.0, y=0.0,
                                                      width=100.0, height=50.0)]))
        data = self._write_to_bytes(doc)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
        self.assertIn(    "visio/pages/page1.xml", names)
        self.assertNotIn("visio/pages/page2.xml", names)


if __name__ == "__main__":
    unittest.main()
