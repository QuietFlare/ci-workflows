"""Tests for tools/compliance_check.py against throwaway project folders."""

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import compliance_check as cc  # noqa: E402

MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:tools="http://schemas.android.com/tools">
{permissions}
    <application android:label="App" />
</manifest>
"""


def run(root, **kwargs):
    out = io.StringIO()
    env = dict(os.environ)
    env.pop("GITHUB_ACTIONS", None)
    env.pop("GITHUB_STEP_SUMMARY", None)
    with unittest.mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stdout(out):
        code = cc.run(root, "compliance/rules.md", **kwargs)
    return code, out.getvalue()


class Project(unittest.TestCase):
    def setUp(self):
        # Not a git checkout, so list_files walks the disk.
        self.root = Path(tempfile.mkdtemp())
        self.write("compliance/rules.md", "# Rules\n\n1. No personal data.\n")

    def tearDown(self):
        shutil.rmtree(self.root)

    def write(self, rel, text=""):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def manifest(self, *lines):
        self.write("androidApp/src/main/AndroidManifest.xml",
                   MANIFEST.format(permissions="\n".join(lines)))


class RulesTests(Project):
    def test_a_project_with_rules_and_nothing_else_passes(self):
        code, out = run(self.root)
        self.assertEqual(code, 0, out)
        self.assertIn("0 error(s)", out)

    def test_a_missing_rules_file_fails(self):
        (self.root / "compliance" / "rules.md").unlink()
        code, out = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("No rules file at compliance/rules.md", out)

    def test_an_empty_rules_file_fails(self):
        self.write("compliance/rules.md", "  \n")
        code, out = run(self.root)
        self.assertEqual(code, 1)
        self.assertIn("rules file is empty", out)


class PermissionTests(Project):
    INTERNET = "android.permission.INTERNET"

    def test_a_forbidden_permission_fails(self):
        self.manifest(f'    <uses-permission android:name="{self.INTERNET}" />')
        code, out = run(self.root, forbidden=[self.INTERNET])
        self.assertEqual(code, 1)
        self.assertIn("androidApp/src/main/AndroidManifest.xml", out)
        self.assertIn(self.INTERNET, out)

    def test_a_permission_removed_with_tools_node_passes(self):
        self.manifest(f'    <uses-permission android:name="{self.INTERNET}" tools:node="remove" />')
        code, out = run(self.root, forbidden=[self.INTERNET])
        self.assertEqual(code, 0, out)

    def test_other_permissions_pass(self):
        self.manifest('    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />')
        code, out = run(self.root, forbidden=[self.INTERNET])
        self.assertEqual(code, 0, out)

    def test_the_sdk_23_tag_is_checked_too(self):
        self.manifest(f'    <uses-permission-sdk-23 android:name="{self.INTERNET}" />')
        code, _ = run(self.root, forbidden=[self.INTERNET])
        self.assertEqual(code, 1)

    def test_an_unreadable_manifest_fails(self):
        self.write("androidApp/src/main/AndroidManifest.xml", "<manifest>")
        code, out = run(self.root, forbidden=[self.INTERNET])
        self.assertEqual(code, 1)
        self.assertIn("Cannot read the manifest", out)


class RequiredFileTests(Project):
    def test_a_missing_required_file_fails(self):
        code, out = run(self.root, required=["MODEL_CARD.md"])
        self.assertEqual(code, 1)
        self.assertIn("MODEL_CARD.md is missing", out)

    def test_present_files_and_folders_pass(self):
        self.write("MODEL_CARD.md", "# Card\n")
        self.write("docs/evals/run1.json", "{}")
        code, out = run(self.root, required=["MODEL_CARD.md", "docs/evals"])
        self.assertEqual(code, 0, out)


class DataRegisterTests(Project):
    def setUp(self):
        super().setUp()
        self.write("data/anki/alltag.tsv", "a\tb\n")
        self.write("data/wiki/mitochondria.txt", "text")

    def test_every_data_file_named_passes(self):
        self.write("docs/data-sources.md",
                   "- data/anki/alltag.tsv: my own deck\n- data/wiki/mitochondria.txt: CC BY-SA\n")
        code, out = run(self.root, data_paths=["data"], register="docs/data-sources.md")
        self.assertEqual(code, 0, out)

    def test_a_folder_entry_covers_the_files_below_it(self):
        self.write("docs/data-sources.md", "- data/anki/: my own deck\n- data/wiki/: CC BY-SA\n")
        code, out = run(self.root, data_paths=["data/"], register="docs/data-sources.md")
        self.assertEqual(code, 0, out)

    def test_naming_the_data_path_itself_covers_nothing(self):
        self.write("docs/data-sources.md", "- data/: everything\n")
        code, out = run(self.root, data_paths=["data"], register="docs/data-sources.md")
        self.assertEqual(code, 1)
        self.assertIn("data/anki/alltag.tsv", out)
        self.assertIn("data/wiki/mitochondria.txt", out)

    def test_an_unregistered_file_fails_alone(self):
        self.write("docs/data-sources.md", "- data/anki/: my own deck\n")
        code, out = run(self.root, data_paths=["data"], register="docs/data-sources.md")
        self.assertEqual(code, 1)
        self.assertIn("data/wiki/mitochondria.txt", out)
        self.assertNotIn("data/anki/alltag.tsv", out)
        self.assertIn("1 error(s)", out)

    def test_housekeeping_files_need_no_entry(self):
        self.write("data/README.md", "What is in here.")
        self.write("data/raw/.gitkeep")
        self.write("docs/data-sources.md", "- data/anki/: mine\n- data/wiki/: CC BY-SA\n")
        code, out = run(self.root, data_paths=["data"], register="docs/data-sources.md")
        self.assertEqual(code, 0, out)

    def test_a_missing_register_fails(self):
        code, out = run(self.root, data_paths=["data"], register="docs/data-sources.md")
        self.assertEqual(code, 1)
        self.assertIn("No data register at docs/data-sources.md", out)

    def test_data_paths_without_a_register_fail(self):
        code, out = run(self.root, data_paths=["data"])
        self.assertEqual(code, 1)
        self.assertIn("no data register is named", out)


if __name__ == "__main__":
    unittest.main()
