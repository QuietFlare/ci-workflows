"""Tests for tools/spec_tool.py against test-fixtures/spec-project."""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
FIXTURE = ROOT / "test-fixtures" / "spec-project"
sys.path.insert(0, str(ROOT / "tools"))

import spec_tool as st  # noqa: E402


def run_lint(root, spec_dir="spec"):
    out = io.StringIO()
    env = dict(os.environ)
    env.pop("GITHUB_ACTIONS", None)
    env.pop("GITHUB_STEP_SUMMARY", None)
    with unittest.mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(out):
        code = st.lint(root, spec_dir)
    return code, out.getvalue()


class FixtureCopy(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.root = self.tmp / "project"
        shutil.copytree(FIXTURE, self.root)
        self.diagram = self.root / "spec" / "timer.excalidraw"

    def tearDown(self):
        shutil.rmtree(self.tmp)


class LintTests(FixtureCopy):
    def test_fixture_passes_with_known_warnings(self):
        code, out = run_lint(self.root)
        self.assertEqual(code, 0, out)
        self.assertIn("1 arrow(s) without a label", out)
        self.assertIn("Timer engine -> Timer view", out)
        self.assertNotIn("no rendered PNG", out)
        self.assertNotIn("holds code", out)
        self.assertIn("0 error(s), 1 warning(s)", out)

    def test_missing_png_is_a_warning(self):
        (self.root / "spec" / "timer.png").unlink()
        code, out = run_lint(self.root)
        self.assertEqual(code, 0)
        self.assertIn("no rendered PNG", out)

    def test_missing_spec_dir_is_an_error(self):
        shutil.rmtree(self.root / "spec")
        code, out = run_lint(self.root)
        self.assertEqual(code, 1)
        self.assertIn("no spec/ folder", out)

    def test_empty_rules_is_an_error(self):
        (self.root / "spec" / "rules.md").write_text("# Rules\n")
        code, out = run_lint(self.root)
        self.assertEqual(code, 1)
        self.assertIn("rules.md is missing or empty", out)

    def test_module_without_diagram_is_an_error(self):
        (self.root / "spec" / "map.yml").write_text("timer:\n  - src/timer/\nsettings:\n  - app/\n")
        code, out = run_lint(self.root)
        self.assertEqual(code, 1)
        self.assertIn("module 'settings' has no spec/settings.excalidraw", out)

    def test_missing_path_is_an_error(self):
        (self.root / "spec" / "map.yml").write_text("timer:\n  - src/timer/\n  - nowhere/\n")
        code, out = run_lint(self.root)
        self.assertEqual(code, 1)
        self.assertIn("'nowhere/' does not exist", out)

    def test_unnamed_frame_is_an_error(self):
        doc = st.load(self.diagram)
        st.frames(doc)[0]["name"] = ""
        st.save(self.diagram, doc)
        code, out = run_lint(self.root)
        self.assertEqual(code, 1)
        self.assertIn("a frame has no name", out)

    def test_unmapped_code_folder_is_a_warning(self):
        (self.root / "widgets").mkdir()
        (self.root / "widgets" / "w.py").write_text("x = 1\n")
        code, out = run_lint(self.root)
        self.assertEqual(code, 0)
        self.assertIn("widgets/ holds code but belongs to no module", out)

    def test_red_element_is_a_warning(self):
        doc = st.load(self.diagram)
        st.mark(doc, "Settings store")
        st.save(self.diagram, doc)
        code, out = run_lint(self.root)
        self.assertEqual(code, 0)
        self.assertIn("still marked red", out)

    def test_custom_spec_dir(self):
        (self.root / "spec").rename(self.root / "docs")
        code, out = run_lint(self.root, "docs")
        self.assertEqual(code, 0, out)


class MapTests(unittest.TestCase):
    def test_block_and_inline_lists(self):
        text = "# c\na:\n  - x/\n  - 'y/**'\nb: [p/, q.py]\nc: single/\n"
        self.assertEqual(st.parse_map(text), {"a": ["x/", "y/**"], "b": ["p/", "q.py"], "c": ["single/"]})

    def test_bad_shape(self):
        with self.assertRaises(ValueError):
            st.parse_map("- orphan\n")

    def test_path_matching(self):
        self.assertTrue(st.path_matches("src/timer/engine.py", "src/timer/"))
        self.assertTrue(st.path_matches("src/timer/engine.py", "src/timer"))
        self.assertTrue(st.path_matches("src/timer/engine.py", "src/**/*.py"))
        self.assertFalse(st.path_matches("src/timer2/engine.py", "src/timer/"))
        self.assertTrue(st.path_matches("app/view.py", "app/view.py"))


class TouchedTests(unittest.TestCase):
    def test_modules_unmapped_and_spec(self):
        result = st.touched(FIXTURE, "spec", [
            "src/timer/engine.py", "README.md", "lib/other.py", "spec/timer.excalidraw", "app/view.py",
        ])
        self.assertEqual(result["modules"], ["timer"])
        self.assertEqual(result["unmapped"], ["lib/other.py"])
        self.assertEqual(result["spec_changed"], ["spec/timer.excalidraw"])


class DescribeTests(unittest.TestCase):
    def test_describe_reads_frames_labels_and_notes(self):
        text = st.describe(st.load(FIXTURE / "spec" / "timer.excalidraw"), "timer.excalidraw")
        self.assertIn("## Countdown  [frame]", text)
        self.assertIn("- Timer engine | owns the clock  (fill #b2f2bb)", text)
        self.assertIn("- Timer view -> Timer engine : start / stop", text)
        self.assertIn("- Timer engine -> Timer view : (no label)", text)
        self.assertIn("## (top level)", text)
        self.assertIn("- Settings store | UserDefaults", text)
        self.assertIn("- Timer: the agreed design", text)

    def test_describe_reads_hand_drawn_sections_and_nearby_labels(self):
        doc = st.load(FIXTURE / "spec" / "timer.excalidraw")
        # A big unlabelled rectangle around the settings box, titled by a free text inside it.
        sec = st.base(doc, "rectangle", 0, 340, 400, 200)
        doc["elements"].append(sec)
        doc["elements"].append(st.make_text(doc, "Persistence", 10, 345, font_size=24, align="left"))
        # A free text sitting on the unlabelled arrow's midpoint.
        doc["elements"].append(st.make_text(doc, "ticks", 290, 150, font_size=14))
        text = st.describe(doc, "t")
        self.assertIn("## Persistence  [section]", text)
        self.assertIn("- Settings store | UserDefaults", text.split("## Persistence")[1])
        self.assertIn("- Timer engine -> Timer view : ticks", text)
        self.assertNotIn("- ticks", text)


class EditTests(FixtureCopy):
    def test_add_box_and_arrow_are_readable_and_lint_clean(self):
        doc = st.load(self.diagram)
        st.add_box(doc, "Haptics\nplays the end chime", "Timer engine", "below")
        st.add_arrow(doc, "Timer engine", "Haptics", "finished")
        st.save(self.diagram, doc)
        text = st.describe(st.load(self.diagram), "t")
        self.assertIn("- Haptics | plays the end chime", text.split("## Countdown")[1])
        self.assertIn("- Timer engine -> Haptics : finished", text)
        code, out = run_lint(self.root)
        self.assertEqual(code, 0, out)
        new_box = st.find(st.load(self.diagram), "Haptics", ("rectangle",))
        self.assertEqual(new_box["frameId"], "fr1")
        engine = st.find(st.load(self.diagram), "Timer engine", ("rectangle",))
        self.assertFalse(st.overlaps(new_box["x"], new_box["y"], new_box["width"], new_box["height"], engine, pad=0))

    def test_wide_label_on_a_short_arrow_becomes_free_text_above_the_boxes(self):
        doc = st.load(self.diagram)
        st.add_box(doc, "Haptics", "Timer engine", "right")
        a = st.add_arrow(doc, "Timer engine", "Haptics", "a label far wider than the gap between these boxes")
        self.assertEqual(a.get("boundElements"), [])
        text = st.describe(doc, "t")
        self.assertIn("Timer engine -> Haptics : a label far wider than the gap between these boxes", text)
        label = st.find(doc, "far wider", ("text",))
        engine = st.find(doc, "Timer engine", ("rectangle",))
        self.assertLess(label["y"] + label["height"], engine["y"])

    def test_add_box_avoids_existing_boxes(self):
        doc = st.load(self.diagram)
        st.add_box(doc, "Haptics", "Timer engine", "right")
        box = st.find(doc, "Haptics", ("rectangle",))
        view = st.find(doc, "Timer view", ("rectangle",))
        self.assertFalse(st.overlaps(box["x"], box["y"], box["width"], box["height"], view, pad=0))

    def test_relabel_keeps_the_box_and_grows_it_if_needed(self):
        doc = st.load(self.diagram)
        before = st.find(doc, "Timer engine", ("rectangle",))
        w0, h0 = before["width"], before["height"]
        st.relabel(doc, "Timer engine", "Timer engine\nowns the clock\nand the end chime")
        after = st.find(doc, "Timer engine", ("rectangle",))
        self.assertIs(after, before)
        self.assertGreaterEqual(after["width"], w0)
        self.assertGreater(after["height"], h0)
        self.assertIn("and the end chime", st.label_of(doc, after))

    def test_note_and_mark(self):
        doc = st.load(self.diagram)
        st.mark(doc, "Timer view", "Redraw: the view now owns a timer")
        view = st.find(doc, "Timer view", ("rectangle",))
        self.assertEqual(view["strokeColor"], st.RED)
        text = st.describe(doc, "t")
        self.assertIn("Timer view | SwiftUI, no timing logic  (fill #e9ecef, RED, dashed)", text)
        self.assertIn("- Redraw: the view now owns a timer (RED)", text)

    def test_ambiguous_and_missing_names_fail_loudly(self):
        doc = st.load(self.diagram)
        with self.assertRaises(SystemExit) as cm:
            st.find(doc, "Timer")
        self.assertIn("matches", str(cm.exception))
        with self.assertRaises(SystemExit) as cm:
            st.find(doc, "Nothing here")
        self.assertIn("no element", str(cm.exception))

    def test_cli_round_trip(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            st.main(["add-box", str(self.diagram), "--label", "Haptics", "--near", "Timer engine", "--side", "below"])
            st.main(["add-arrow", str(self.diagram), "--from", "Timer engine", "--to", "Haptics", "--label", "finished"])
            st.main(["relabel", str(self.diagram), "--element", "Settings store", "--text", "Settings store\nJSON file"])
            st.main(["note", str(self.diagram), "--near", "Settings", "--text", "Redraw: moved to JSON"])
            st.main(["describe", str(self.diagram)])
        text = out.getvalue()
        self.assertIn("Timer engine -> Haptics : finished", text)
        self.assertIn("Settings store | JSON file", text)
        self.assertIn("Redraw: moved to JSON (RED)", text)
        json.loads(self.diagram.read_text())

    def test_new_elements_get_a_fractional_index_only_when_the_file_uses_them(self):
        doc = st.load(self.diagram)
        box = st.add_box(doc, "Haptics", "Timer engine", "right")
        self.assertNotIn("index", box)
        for e in doc["elements"]:
            e["index"] = "a5"
        box2 = st.add_box(doc, "Sound", "Timer engine", "right")
        self.assertEqual(box2["index"], "a5V")


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
