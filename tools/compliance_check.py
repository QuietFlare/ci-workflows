#!/usr/bin/env python3
"""The hard compliance checks, as a tool. Standard library only.

Each check is a plain file check that cannot be argued with, so a failure
blocks the change. Judgement calls belong to the AI review in
compliance-review.yml, which advises and never blocks.

    rules       the rules file exists and is not empty
    permissions no AndroidManifest.xml in the repo requests a forbidden
                permission (source manifests only: a permission a library
                adds through manifest merging is not visible here)
    files       every required file or folder exists
    data        every file under a data path is named in the data register,
                by its own path or by a folder above it inside the data path

Exit 1 on any error. On GitHub Actions errors become annotations and the
step summary lists them.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"
TOOLS_NS = "{http://schemas.android.com/tools}"
PERMISSION_TAGS = {"uses-permission", "uses-permission-sdk-23"}
SKIP_DIRS = {".git", ".gradle", ".kotlin", ".venv", "build", "node_modules", "__pycache__"}
# Housekeeping files a data folder may hold without a register entry.
DATA_EXEMPT = {"README.md", ".gitkeep", ".gitattributes", ".gitignore"}


class Report:
    def __init__(self):
        self.errors = []

    def error(self, msg, file=None):
        self.errors.append((msg, file))

    def emit(self):
        gha = bool(os.environ.get("GITHUB_ACTIONS"))
        for msg, file in self.errors:
            if gha:
                loc = f" file={file}" if file else ""
                print(f"::error{loc}::{msg}")
            else:
                where = f"{file}: " if file else ""
                print(f"error: {where}{msg}")
        summary = f"compliance checks: {len(self.errors)} error(s)"
        print(summary)
        step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if step_summary:
            with open(step_summary, "a", encoding="utf-8") as f:
                f.write(f"### {summary}\n\n")
                for msg, file in self.errors:
                    f.write(f"- :x: {file + ': ' if file else ''}{msg}\n")
        return 1 if self.errors else 0


def list_files(root: Path) -> list[str]:
    """Tracked files when root is a git checkout, otherwise every file on disk."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True, check=True, text=True,
        ).stdout
        files = [f for f in out.split("\0") if f]
        if files:
            return sorted(files)
    except (OSError, subprocess.CalledProcessError):
        pass
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            found.append(Path(dirpath, name).relative_to(root).as_posix())
    return sorted(found)


def check_rules(root: Path, rules: str, report: Report):
    path = root / rules
    if not path.is_file():
        report.error(f"No rules file at {rules}. The AI review has nothing to review against.")
    elif not path.read_text(encoding="utf-8").strip():
        report.error("The rules file is empty.", rules)


def check_permissions(root: Path, files: list[str], forbidden: list[str], report: Report):
    if not forbidden:
        return
    for rel in files:
        if Path(rel).name != "AndroidManifest.xml":
            continue
        try:
            tree = ET.parse(root / rel)
        except (ET.ParseError, OSError) as e:
            report.error(f"Cannot read the manifest: {e}", rel)
            continue
        for el in tree.getroot():
            if el.tag not in PERMISSION_TAGS:
                continue
            name = el.get(f"{ANDROID_NS}name")
            # tools:node="remove" strips a permission a library merged in: allowed.
            if name in forbidden and el.get(f"{TOOLS_NS}node") != "remove":
                report.error(f"Requests the forbidden permission {name}.", rel)


def check_required(root: Path, required: list[str], report: Report):
    for rel in required:
        if not (root / rel).exists():
            report.error(f"Required file or folder {rel} is missing.")


def register_names(rel: str, data_path: str) -> list[str]:
    """The path itself, then each folder above it that lies inside the data path."""
    names = [rel]
    parent = Path(rel).parent
    while parent.as_posix() != data_path and parent.as_posix() not in (".", ""):
        names.append(parent.as_posix() + "/")
        parent = parent.parent
    return names


def check_data(root: Path, files: list[str], data_paths: list[str], register: str,
               report: Report):
    if not data_paths:
        return
    if not register:
        report.error("Data paths are set but no data register is named.")
        return
    reg = root / register
    if not reg.is_file():
        report.error(f"No data register at {register}.")
        return
    text = reg.read_text(encoding="utf-8")
    for data_path in (p.rstrip("/") for p in data_paths):
        for rel in files:
            if not rel.startswith(data_path + "/") or Path(rel).name in DATA_EXEMPT:
                continue
            if not any(name in text for name in register_names(rel, data_path)):
                report.error(
                    f"Not in the data register {register}. Add its source, licence and date.",
                    rel,
                )


def run(root, rules, forbidden=(), required=(), data_paths=(), register=""):
    root = Path(root)
    report = Report()
    files = list_files(root)
    check_rules(root, rules, report)
    check_permissions(root, files, list(forbidden), report)
    check_required(root, list(required), report)
    check_data(root, files, list(data_paths), register, report)
    return report.emit()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--root", default=".")
    p.add_argument("--rules", default="compliance/rules.md")
    p.add_argument("--forbid-android-permission", action="append", default=[],
                   help="e.g. android.permission.INTERNET; repeat for more")
    p.add_argument("--require-file", action="append", default=[])
    p.add_argument("--data-path", action="append", default=[])
    p.add_argument("--data-register", default="")
    a = p.parse_args(argv)
    return run(a.root, a.rules, a.forbid_android_permission, a.require_file,
               a.data_path, a.data_register)


if __name__ == "__main__":
    sys.exit(main())
