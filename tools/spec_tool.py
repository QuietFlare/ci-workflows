#!/usr/bin/env python3
"""The spec contract, as a tool. Standard library only.

A project's agreed design lives in one folder (spec/ by default):

    spec/<module>.excalidraw   one diagram per module; frames inside name features
    spec/rules.md              the non-negotiables a diagram cannot express
    spec/map.yml               which source paths belong to which module

Subcommands:

    lint       check a project against the contract; exit 1 on an error
    describe   print a diagram as text: frames, boxes, labelled arrows, notes
    touched    map changed paths to the modules whose design they fall under
    relabel    change the label of a box
    add-box    add a box beside an existing one
    add-arrow  add a labelled arrow between two boxes
    note       add a red note beside an element
    mark       colour an element red, with an optional note

Elements are addressed by a case-insensitive substring of their label, which
must match exactly one element. The editing commands never move or delete
anything that is already drawn.
"""

from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import math
import os
import random
import sys
import time
from pathlib import Path

CODE_SUFFIXES = {
    ".py", ".swift", ".kt", ".kts", ".java", ".ts", ".tsx", ".js", ".jsx",
    ".go", ".rs", ".rb", ".c", ".cc", ".cpp", ".h", ".cs", ".m", ".mm",
}
SKIP_DIRS = {
    "tests", "test", "docs", "doc", "examples", "example", "build", "dist",
    "node_modules", "venv", "vendor", "scripts", "tools", "instances", "work",
    "trail", "evals", "hackathon", "skills",
}
RED = "#e03131"
BLACK = "#1e1e1e"
LABEL_REACH = 90  # px: a free text this close to an arrow's midpoint labels it


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------

def load(path):
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    if doc.get("type") != "excalidraw" or not isinstance(doc.get("elements"), list):
        raise ValueError(f"{path}: not an Excalidraw file")
    return doc


def save(path, doc):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")


def live(doc):
    return [e for e in doc["elements"] if not e.get("isDeleted")]


def by_id(doc):
    return {e["id"]: e for e in live(doc)}


def label_of(doc, element):
    """The text shown on a container (box or arrow), or None."""
    ids = by_id(doc)
    for b in element.get("boundElements") or []:
        if b.get("type") == "text" and b["id"] in ids:
            return (ids[b["id"]].get("text") or "").strip()
    if element["type"] == "text":
        return (element.get("text") or "").strip()
    if element["type"] == "frame":
        return (element.get("name") or "").strip()
    return None


def center(e):
    return e["x"] + e["width"] / 2, e["y"] + e["height"] / 2


def arrow_midpoint(a):
    pts = a.get("points") or [[0, 0]]
    total = 0.0
    segs = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        d = math.hypot(x1 - x0, y1 - y0)
        segs.append((x0, y0, x1, y1, d))
        total += d
    half = total / 2
    run = 0.0
    for x0, y0, x1, y1, d in segs:
        if run + d >= half and d:
            t = (half - run) / d
            return a["x"] + x0 + (x1 - x0) * t, a["y"] + y0 + (y1 - y0) * t
        run += d
    return a["x"], a["y"]


def free_texts(doc):
    return [e for e in live(doc) if e["type"] == "text" and not e.get("containerId")]


def arrow_labels(doc, claimed):
    """arrow id -> label. A bound text wins; otherwise the nearest free text
    to the arrow's midpoint, each text given to one arrow only, closest pairs
    first. Texts used as labels are added to `claimed`."""
    labels = {}
    pairs = []
    for a in arrows(doc):
        bound = label_of(doc, a)
        if bound:
            labels[a["id"]] = bound
            continue
        mx, my = arrow_midpoint(a)
        for t in free_texts(doc):
            if t["id"] in claimed or t.get("fontSize", 16) > 20:
                continue
            cx, cy = center(t)
            d = math.hypot(cx - mx, cy - my)
            if d < LABEL_REACH:
                pairs.append((d, a["id"], t))
    pairs.sort(key=lambda p: p[0])
    for _, aid, t in pairs:
        if aid in labels or t["id"] in claimed:
            continue
        labels[aid] = (t.get("text") or "").strip()
        claimed.add(t["id"])
    return labels


def boxes(doc):
    return [e for e in live(doc) if e["type"] in ("rectangle", "ellipse", "diamond")]


def arrows(doc):
    return [e for e in live(doc) if e["type"] == "arrow"]


def frames(doc):
    return [e for e in live(doc) if e["type"] == "frame"]


def find(doc, needle, kinds=("rectangle", "ellipse", "diamond", "frame", "text", "arrow")):
    needle_l = needle.lower()
    hits = []
    for e in live(doc):
        if e["type"] not in kinds:
            continue
        if e["type"] == "text" and e.get("containerId"):
            continue
        lab = label_of(doc, e)
        if lab and needle_l in lab.lower():
            hits.append(e)
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise SystemExit(f"no element labelled like {needle!r}")
    names = ", ".join(repr(label_of(doc, h)) for h in hits)
    raise SystemExit(f"{needle!r} matches {len(hits)} elements: {names}. Be more specific.")


# --------------------------------------------------------------------------
# describe
# --------------------------------------------------------------------------

def area(e):
    return abs(e["width"] * e["height"])


def contains(outer, inner):
    cx, cy = center(inner)
    return (outer["x"] <= cx <= outer["x"] + outer["width"] and
            outer["y"] <= cy <= outer["y"] + outer["height"])


def is_swatch(e):
    """A legend colour chip, not a component."""
    return e["width"] < 50 and e["height"] < 50


def sections(doc, claimed):
    """Hand-drawn groupings: an unlabelled rectangle that encloses other boxes.

    Its title is the first free text inside it, read top to bottom. Returns
    [(rect, title)], largest first.
    """
    real = [b for b in boxes(doc) if not is_swatch(b)]
    found = []
    for r in real:
        if label_of(doc, r):
            continue
        if not any(b is not r and area(b) < area(r) and contains(r, b) for b in real):
            continue
        title = None
        cands = [t for t in free_texts(doc) if t["id"] not in claimed and contains(r, t)]
        if cands:
            t = min(cands, key=lambda t: (-t.get("fontSize", 16), t["y"], t["x"]))
            claimed.add(t["id"])
            title = first_line(t.get("text"))
        found.append((r, title or "(unnamed section)"))
    found.sort(key=lambda s: -area(s[0]))
    return found


def group_of(e, secs):
    """('frame', id) | ('section', id) | ('top', None): the smallest thing enclosing e."""
    if e.get("frameId"):
        return ("frame", e["frameId"])
    enclosing = [r for r, _ in secs if r is not e and area(r) > area(e) and contains(r, e)]
    if enclosing:
        return ("section", min(enclosing, key=area)["id"])
    return ("top", None)


def describe(doc, name):
    ids = by_id(doc)
    out = [f"# {name}"]
    claimed = set()
    labels = arrow_labels(doc, claimed)
    secs = sections(doc, claimed)
    section_ids = {r["id"] for r, _ in secs}

    arrow_lines = {}
    for a in arrows(doc):
        lab = labels.get(a["id"])
        sb = (a.get("startBinding") or {}).get("elementId")
        eb = (a.get("endBinding") or {}).get("elementId")
        src = first_line(label_of(doc, ids[sb])) if sb in ids else ""
        dst = first_line(label_of(doc, ids[eb])) if eb in ids else ""
        text = f"{src or '(unbound)'} -> {dst or '(unbound)'}"
        text += f" : {lab}" if lab else " : (no label)"
        if a.get("startArrowhead") and a.get("endArrowhead"):
            text += "  [both ways]"
        key = group_of(ids[sb], secs) if sb in ids else group_of(a, secs)
        arrow_lines.setdefault(key, []).append(text)

    groups = [(("top", None), "(top level)")]
    groups += [(("frame", f["id"]), f"{f.get('name') or '(unnamed frame)'}  [frame]") for f in frames(doc)]
    for r, title in secs:
        parent = group_of(r, secs)
        where = ""
        if parent[0] == "section":
            where = f", inside {dict((r2['id'], t2) for r2, t2 in secs)[parent[1]]}"
        elif parent[0] == "frame":
            where = f", inside frame {ids[parent[1]].get('name')}"
        groups.append((("section", r["id"]), f"{title}  [section{where}]"))

    for key, heading in groups:
        bx = [b for b in boxes(doc) if not is_swatch(b) and b["id"] not in section_ids and group_of(b, secs) == key]
        ar = arrow_lines.get(key, [])
        notes = [t for t in free_texts(doc) if t["id"] not in claimed and group_of(t, secs) == key]
        if not (bx or ar or notes):
            continue
        out.append("")
        out.append(f"## {heading}")
        if bx:
            out.append("Boxes:")
            for b in bx:
                lab = label_of(doc, b) or "(no label)"
                fill = b.get("backgroundColor")
                style = []
                if fill and fill != "transparent":
                    style.append(f"fill {fill}")
                if b.get("strokeColor") == RED:
                    style.append("RED")
                if b.get("strokeStyle") == "dashed":
                    style.append("dashed")
                suffix = f"  ({', '.join(style)})" if style else ""
                out.append(f"- {one_line(lab)}{suffix}")
        if ar:
            out.append("Arrows:")
            for t in ar:
                out.append(f"- {t}")
        if notes:
            out.append("Text:")
            for t in notes:
                tag = " (RED)" if t.get("strokeColor") == RED else ""
                out.append(f"- {one_line(t.get('text') or '')}{tag}")
    return "\n".join(out)


def first_line(s):
    return (s or "").strip().splitlines()[0].strip() if (s or "").strip() else ""


def one_line(s):
    return " | ".join(line.strip() for line in s.strip().splitlines() if line.strip())


# --------------------------------------------------------------------------
# map.yml (a deliberately small subset of YAML)
# --------------------------------------------------------------------------

def parse_map(text):
    """module:\\n  - path\\n  - path   or   module: [path, path]"""
    result = {}
    current = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith((" ", "\t", "-")):
            key, sep, rest = line.partition(":")
            if not sep:
                raise ValueError(f"map.yml: expected 'module:' but got {raw!r}")
            current = key.strip().strip("'\"")
            rest = rest.strip()
            if rest.startswith("["):
                items = [i.strip().strip("'\"") for i in rest.strip("[]").split(",") if i.strip()]
                result[current] = items
            elif rest:
                result[current] = [rest.strip("'\"")]
            else:
                result[current] = []
        else:
            item = line.strip()
            if not item.startswith("-") or current is None:
                raise ValueError(f"map.yml: expected '- path' under a module but got {raw!r}")
            result[current].append(item[1:].strip().strip("'\""))
    return result


def path_matches(path, pattern):
    pattern = pattern.replace("\\", "/")
    path = path.replace("\\", "/")
    if pattern.endswith("/"):
        return path.startswith(pattern) or path == pattern.rstrip("/")
    if any(ch in pattern for ch in "*?["):
        if fnmatch.fnmatch(path, pattern):
            return True
        if "**" in pattern:
            return fnmatch.fnmatch(path, pattern.replace("**/", "")) or fnmatch.fnmatch(path, pattern.replace("**", "*"))
        return False
    return path == pattern or path.startswith(pattern.rstrip("/") + "/")


# --------------------------------------------------------------------------
# lint
# --------------------------------------------------------------------------

class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, msg, file=None):
        self.errors.append((msg, file))

    def warn(self, msg, file=None):
        self.warnings.append((msg, file))

    def emit(self):
        gha = bool(os.environ.get("GITHUB_ACTIONS"))
        for kind, items in (("error", self.errors), ("warning", self.warnings)):
            for msg, file in items:
                if gha:
                    loc = f" file={file}" if file else ""
                    print(f"::{kind}{loc}::{msg}")
                else:
                    where = f"{file}: " if file else ""
                    print(f"{kind}: {where}{msg}")
        summary = f"spec lint: {len(self.errors)} error(s), {len(self.warnings)} warning(s)"
        print(summary)
        step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if step_summary:
            with open(step_summary, "a", encoding="utf-8") as f:
                f.write(f"### {summary}\n\n")
                for msg, file in self.errors:
                    f.write(f"- :x: {file + ': ' if file else ''}{msg}\n")
                for msg, file in self.warnings:
                    f.write(f"- :warning: {file + ': ' if file else ''}{msg}\n")
        return 1 if self.errors else 0


def lint(root, spec_dir):
    rep = Report()
    root = Path(root)
    spec = root / spec_dir
    if not spec.is_dir():
        rep.error(f"no {spec_dir}/ folder: the agreed design must exist before code is reviewed against it")
        return rep.emit()

    rules = spec / "rules.md"
    if not rules.is_file() or len(rules.read_text(encoding="utf-8").strip()) < 40:
        rep.error("rules.md is missing or empty: write the non-negotiables a diagram cannot express", str(rules))

    diagrams = sorted(spec.glob("*.excalidraw"))
    if not diagrams:
        rep.error(f"no .excalidraw diagram in {spec_dir}/", str(spec))

    mapping = {}
    map_file = spec / "map.yml"
    if not map_file.is_file():
        rep.error("map.yml is missing: list which source paths belong to which module", str(map_file))
    else:
        try:
            mapping = parse_map(map_file.read_text(encoding="utf-8"))
        except ValueError as e:
            rep.error(str(e), str(map_file))
        if not mapping:
            rep.error("map.yml maps nothing", str(map_file))
        for module, paths in mapping.items():
            if not (spec / f"{module}.excalidraw").is_file():
                rep.error(f"module '{module}' has no {spec_dir}/{module}.excalidraw", str(map_file))
            if not paths:
                rep.error(f"module '{module}' lists no paths", str(map_file))
            for p in paths:
                if any(ch in p for ch in "*?["):
                    if not glob.glob(str(root / p), recursive=True):
                        rep.error(f"module '{module}': nothing matches {p!r}", str(map_file))
                elif not (root / p).exists():
                    rep.error(f"module '{module}': path {p!r} does not exist", str(map_file))

    for d in diagrams:
        rel = str(d.relative_to(root))
        try:
            doc = load(d)
        except (ValueError, json.JSONDecodeError) as e:
            rep.error(f"cannot read diagram: {e}", rel)
            continue
        if d.stem not in mapping and mapping:
            rep.warn(f"diagram is not a module in map.yml, so no code is reviewed against it", rel)
        if not d.with_suffix(".png").is_file():
            rep.warn("no rendered PNG beside the diagram; the excalidraw-render workflow makes one", rel)
        for f in frames(doc):
            if not (f.get("name") or "").strip():
                rep.error("a frame has no name; name it after the feature it scopes", rel)
        if not boxes(doc):
            rep.error("diagram has no boxes", rel)
        ids = by_id(doc)
        labels = arrow_labels(doc, set())
        unlabelled, dangling = [], 0
        for a in arrows(doc):
            sb = (a.get("startBinding") or {}).get("elementId")
            eb = (a.get("endBinding") or {}).get("elementId")
            if sb not in ids or eb not in ids:
                dangling += 1
                continue
            if not labels.get(a["id"]):
                unlabelled.append(f"{first_line(label_of(doc, ids[sb]))} -> {first_line(label_of(doc, ids[eb]))}")
        if dangling:
            rep.warn(f"{dangling} arrow(s) not attached to a box at both ends", rel)
        if unlabelled:
            shown = "; ".join(unlabelled[:6]) + (" ..." if len(unlabelled) > 6 else "")
            rep.warn(f"{len(unlabelled)} arrow(s) without a label, so the reviewer must guess what flows: {shown}", rel)
        red = [first_line(label_of(doc, e) or e["type"]) for e in live(doc)
               if e.get("strokeColor") == RED and e["type"] != "text"]
        if red:
            rep.warn(f"{len(red)} element(s) still marked red (unresolved review note): {', '.join(red[:6])}", rel)

    if mapping:
        for child in sorted(root.iterdir()):
            if not child.is_dir() or child.name.startswith(".") or child.name in SKIP_DIRS or child == spec:
                continue
            if not any(p.suffix in CODE_SUFFIXES for p in child.rglob("*") if p.is_file()):
                continue
            rel = child.name + "/"
            if not any(path_matches(rel + "x", p) or path_matches(child.name, p)
                       for paths in mapping.values() for p in paths):
                rep.warn(f"{rel} holds code but belongs to no module in map.yml", str(map_file))

    return rep.emit()


# --------------------------------------------------------------------------
# touched
# --------------------------------------------------------------------------

def touched(root, spec_dir, files):
    spec = Path(root) / spec_dir
    mapping = parse_map((spec / "map.yml").read_text(encoding="utf-8"))
    modules, unmapped, spec_changed = [], [], []
    for f in files:
        f = f.strip().replace("\\", "/")
        if not f:
            continue
        if f.startswith(spec_dir.rstrip("/") + "/"):
            spec_changed.append(f)
            continue
        hit = [m for m, paths in mapping.items() if any(path_matches(f, p) for p in paths)]
        if hit:
            for m in hit:
                if m not in modules:
                    modules.append(m)
        elif Path(f).suffix in CODE_SUFFIXES:
            unmapped.append(f)
    return {"modules": modules, "unmapped": unmapped, "spec_changed": spec_changed}


# --------------------------------------------------------------------------
# Editing
# --------------------------------------------------------------------------

def new_id():
    return "spec" + "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(16))


def next_index(doc):
    existing = [e.get("index") for e in doc["elements"] if isinstance(e.get("index"), str)]
    if not existing:
        return None
    return max(existing) + "V"


def base(doc, kind, x, y, w, h, frame_id=None):
    e = {
        "id": new_id(), "type": kind, "x": x, "y": y, "width": w, "height": h,
        "angle": 0, "strokeColor": BLACK, "backgroundColor": "transparent",
        "fillStyle": "solid", "strokeWidth": 2, "strokeStyle": "solid",
        "roughness": 1, "opacity": 100, "groupIds": [], "frameId": frame_id,
        "roundness": None, "seed": random.randint(1, 2**31 - 1), "version": 1,
        "versionNonce": random.randint(1, 2**31 - 1), "isDeleted": False,
        "boundElements": [], "updated": int(time.time() * 1000), "link": None,
        "locked": False,
    }
    idx = next_index(doc)
    if idx is not None:
        e["index"] = idx
    return e


def font_family(doc):
    fams = [t.get("fontFamily") for t in live(doc) if t["type"] == "text" and t.get("fontFamily")]
    return max(set(fams), key=fams.count) if fams else 1


def text_size(text, font_size):
    lines = text.splitlines() or [""]
    w = max(len(line) for line in lines) * font_size * 0.6
    h = len(lines) * font_size * 1.25
    return w, h


def make_text(doc, text, x, y, font_size=16, container=None, color=BLACK, frame_id=None, align="center"):
    w, h = text_size(text, font_size)
    t = base(doc, "text", x, y, w, h, frame_id)
    t.update({
        "strokeColor": color, "text": text, "originalText": text, "fontSize": font_size,
        "fontFamily": font_family(doc), "textAlign": align,
        "verticalAlign": "middle" if container else "top",
        "containerId": container, "lineHeight": 1.25, "autoResize": True,
        "boundElements": None,
    })
    return t


def overlaps(x, y, w, h, e, pad=20):
    return not (x + w + pad < e["x"] or e["x"] + e["width"] + pad < x or
                y + h + pad < e["y"] or e["y"] + e["height"] + pad < y)


def add_box(doc, label, near, side, fill=None):
    anchor = find(doc, near, ("rectangle", "ellipse", "diamond"))
    tw, th = text_size(label, 16)
    w, h = max(160, tw + 40), max(60, th + 30)
    gap = 60
    x, y = (anchor["x"] + anchor["width"] + gap, anchor["y"]) if side == "right" else (anchor["x"], anchor["y"] + anchor["height"] + gap)
    others = boxes(doc) + free_texts(doc)
    for _ in range(12):
        if not any(overlaps(x, y, w, h, o) for o in others):
            break
        if side == "right":
            x += w + gap
        else:
            y += h + gap
    box = base(doc, "rectangle", x, y, w, h, anchor.get("frameId"))
    box["roundness"] = {"type": 3}
    box["backgroundColor"] = fill or anchor.get("backgroundColor") or "transparent"
    doc["elements"].append(box)
    t = make_text(doc, label, x + (w - tw) / 2, y + (h - th) / 2, container=box["id"], frame_id=anchor.get("frameId"))
    box["boundElements"] = [{"type": "text", "id": t["id"]}]
    doc["elements"].append(t)
    return box


def edge_point(e, towards):
    """Where a line from e's centre towards a point leaves e's rectangle."""
    cx, cy = center(e)
    dx, dy = towards[0] - cx, towards[1] - cy
    if dx == 0 and dy == 0:
        return cx, cy
    sx = (e["width"] / 2) / abs(dx) if dx else math.inf
    sy = (e["height"] / 2) / abs(dy) if dy else math.inf
    s = min(sx, sy)
    return cx + dx * s, cy + dy * s


def add_arrow(doc, src_needle, dst_needle, label):
    src = find(doc, src_needle, ("rectangle", "ellipse", "diamond"))
    dst = find(doc, dst_needle, ("rectangle", "ellipse", "diamond"))
    gap = 6
    sx, sy = edge_point(src, center(dst))
    ex, ey = edge_point(dst, center(src))
    ux, uy = ex - sx, ey - sy
    d = math.hypot(ux, uy) or 1
    sx, sy = sx + ux / d * gap, sy + uy / d * gap
    ex, ey = ex - ux / d * gap, ey - uy / d * gap
    a = base(doc, "arrow", sx, sy, ex - sx, ey - sy, src.get("frameId"))
    a.update({
        "roundness": {"type": 2}, "points": [[0, 0], [ex - sx, ey - sy]],
        "lastCommittedPoint": None,
        "startBinding": {"elementId": src["id"], "focus": 0, "gap": gap},
        "endBinding": {"elementId": dst["id"], "focus": 0, "gap": gap},
        "startArrowhead": None, "endArrowhead": "arrow", "elbowed": False,
    })
    doc["elements"].append(a)
    for e in (src, dst):
        e.setdefault("boundElements", [])
        if e["boundElements"] is None:
            e["boundElements"] = []
        e["boundElements"].append({"type": "arrow", "id": a["id"]})
    if label:
        tw, th = text_size(label, 14)
        mx, my = (sx + ex) / 2, (sy + ey) / 2
        t = make_text(doc, label, mx - tw / 2, my - th / 2, font_size=14, container=a["id"], frame_id=src.get("frameId"))
        a["boundElements"] = [{"type": "text", "id": t["id"]}]
        doc["elements"].append(t)
    return a


def relabel(doc, needle, text):
    e = find(doc, needle, ("rectangle", "ellipse", "diamond", "arrow", "text"))
    ids = by_id(doc)
    target = None
    if e["type"] == "text":
        target = e
    else:
        for b in e.get("boundElements") or []:
            if b.get("type") == "text" and b["id"] in ids:
                target = ids[b["id"]]
    if target is None:
        t = make_text(doc, text, e["x"], e["y"], container=e["id"], frame_id=e.get("frameId"))
        e["boundElements"] = (e.get("boundElements") or []) + [{"type": "text", "id": t["id"]}]
        doc["elements"].append(t)
        target = t
    old_w, old_h = target["width"], target["height"]
    target["text"] = text
    target["originalText"] = text
    w, h = text_size(text, target.get("fontSize", 16))
    if e["type"] in ("rectangle", "ellipse", "diamond"):
        e["width"] = max(e["width"], w + 40)
        e["height"] = max(e["height"], h + 30)
        target["x"] = e["x"] + (e["width"] - w) / 2
        target["y"] = e["y"] + (e["height"] - h) / 2
    else:
        target["x"] += (old_w - w) / 2
        target["y"] += (old_h - h) / 2
    target["width"], target["height"] = w, h
    bump(target)
    bump(e)
    return target


def note(doc, near, text):
    e = find(doc, near)
    x, y = e["x"], e["y"] + e["height"] + 12
    t = make_text(doc, text, x, y, font_size=14, color=RED, frame_id=e.get("frameId"), align="left")
    doc["elements"].append(t)
    return t


def mark(doc, needle, text=None):
    e = find(doc, needle, ("rectangle", "ellipse", "diamond", "arrow"))
    e["strokeColor"] = RED
    e["strokeStyle"] = "dashed"
    bump(e)
    if text:
        note(doc, needle, text)
    return e


def bump(e):
    e["version"] = int(e.get("version", 1)) + 1
    e["versionNonce"] = random.randint(1, 2**31 - 1)
    e["updated"] = int(time.time() * 1000)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("lint", help="check a project against the contract")
    s.add_argument("--root", default=".")
    s.add_argument("--spec-dir", default="spec")

    s = sub.add_parser("describe", help="print diagrams as text")
    s.add_argument("diagram", nargs="+")

    s = sub.add_parser("touched", help="map changed paths to modules; reads paths from stdin or --files")
    s.add_argument("--root", default=".")
    s.add_argument("--spec-dir", default="spec")
    s.add_argument("--files", nargs="*")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("relabel", help="change a box or arrow label")
    s.add_argument("diagram")
    s.add_argument("--element", required=True)
    s.add_argument("--text", required=True)

    s = sub.add_parser("add-box", help="add a box beside an existing one")
    s.add_argument("diagram")
    s.add_argument("--label", required=True)
    s.add_argument("--near", required=True)
    s.add_argument("--side", choices=["right", "below"], default="right")
    s.add_argument("--fill")

    s = sub.add_parser("add-arrow", help="add a labelled arrow between two boxes")
    s.add_argument("diagram")
    s.add_argument("--from", dest="src", required=True)
    s.add_argument("--to", dest="dst", required=True)
    s.add_argument("--label", required=True)

    s = sub.add_parser("note", help="add a red note under an element")
    s.add_argument("diagram")
    s.add_argument("--near", required=True)
    s.add_argument("--text", required=True)

    s = sub.add_parser("mark", help="colour an element red, with an optional note")
    s.add_argument("diagram")
    s.add_argument("--element", required=True)
    s.add_argument("--note")

    args = p.parse_args(argv)

    if args.cmd == "lint":
        return lint(args.root, args.spec_dir)

    if args.cmd == "describe":
        parts = []
        for d in args.diagram:
            parts.append(describe(load(d), Path(d).name))
        print("\n\n".join(parts))
        return 0

    if args.cmd == "touched":
        files = args.files if args.files is not None else sys.stdin.read().splitlines()
        result = touched(args.root, args.spec_dir, files)
        if args.json:
            print(json.dumps(result))
        else:
            print("modules: " + (", ".join(result["modules"]) or "(none)"))
            print("unmapped code: " + (", ".join(result["unmapped"]) or "(none)"))
            print("spec changed: " + (", ".join(result["spec_changed"]) or "(none)"))
        return 0

    doc = load(args.diagram)
    if args.cmd == "relabel":
        relabel(doc, args.element, args.text)
    elif args.cmd == "add-box":
        add_box(doc, args.label, args.near, args.side, args.fill)
    elif args.cmd == "add-arrow":
        add_arrow(doc, args.src, args.dst, args.label)
    elif args.cmd == "note":
        note(doc, args.near, args.text)
    elif args.cmd == "mark":
        mark(doc, args.element, args.note)
    save(args.diagram, doc)
    print(f"{args.cmd}: {args.diagram} updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
