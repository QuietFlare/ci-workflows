# The spec contract

Design and requirements exist before code. A pull request is reviewed
against them, and when the code departs from the drawing, the drawing
changes in the same pull request. A person approves both at once.

This file is the whole contract. Two workflows enforce it:
[`spec-lint.yml`](.github/workflows/spec-lint.yml) checks the shape with no
model involved, and [`design-review.yml`](.github/workflows/design-review.yml)
reads a pull request against the design and reports drift.

## What a project keeps

One folder, `spec/` by default:

```
spec/
  <module>.excalidraw   one diagram per module, drawn by a person
  <module>.png          its render, kept current by excalidraw-render.yml
  rules.md              the non-negotiables a diagram cannot express
  map.yml               which source paths belong to which module
```

**The diagram** is the design. Boxes are components. Arrows are labelled
with what flows or who depends on whom; an unlabelled arrow makes the
reviewer guess. A frame, or a large rectangle drawn around a group with a
title inside, scopes a feature. A legend is welcome and ignored.

**`rules.md`** is under a page. Layer boundaries, what must never happen,
who owns which decision. A pull request that breaks a rule is reported.
The reviewer never edits this file.

**`map.yml`** is a few lines:

```yaml
timer:            # spec/timer.excalidraw
  - src/timer/
  - app/
```

A path is a folder prefix or a glob. Code outside every module gets a
warning, not a review.

## Who writes what

| Artifact | Written by | Changed by |
|---|---|---|
| `spec/<module>.excalidraw` | a person, in the editor | the reviewer, small edits on a pull request; a person approves |
| `spec/rules.md` | a person | a person only |
| `spec/map.yml` | a person, once | a person; the reviewer points out unmapped code |
| `spec/*.png` | the render workflow | the render workflow |
| the review comment | the reviewer | |
| approval and merge | a person | |

Nothing in `spec/` reaches the default branch without a person approving
the pull request it rides on.

## What the reviewer does

On a pull request:

1. Lint. No `spec/`, no review: the job fails and says so.
2. Map the changed files to modules. Nothing mapped changed, nothing
   happens. Code changed that no module covers, one comment says so.
3. Read `rules.md`, the touched modules' diagrams as text, and the diff.
4. Decide. **No design impact**: one line, and stop. **Drift**: edit the
   diagram so it describes what the code now does, commit to the branch,
   and post one comment under 150 words saying what moved and what it
   changed. A broken rule is reported, never fixed by editing the rule.

The reviewer relabels, recolours, and adds a box or an arrow beside the
element it relates to. It never moves or deletes what a person drew. When
the change needs a redraw, it leaves a red note on the diagram and says so.
Red on a diagram means a person has something to resolve; the lint warns
while it stays.

## Limits, stated up front

- The reviewer holds you to what is written down. A design that lives in a
  conversation is invisible to it.
- It is judgment, not verification. It comments; it does not block.
  Mechanical rules belong in a script that does.
- It never decides whether the code or the design is wrong. That is the
  approval.

## Tooling

[`tools/spec_tool.py`](tools/spec_tool.py), standard library only:

```bash
python3 tools/spec_tool.py lint --spec-dir spec
python3 tools/spec_tool.py describe spec/timer.excalidraw
git diff --name-only main | python3 tools/spec_tool.py touched
python3 tools/spec_tool.py add-box spec/timer.excalidraw --label "Haptics" --near "Timer engine" --side below
python3 tools/spec_tool.py add-arrow spec/timer.excalidraw --from "Timer engine" --to "Haptics" --label "finished"
python3 tools/spec_tool.py relabel spec/timer.excalidraw --element "Settings store" --text "Settings store\nJSON file"
python3 tools/spec_tool.py note spec/timer.excalidraw --near "Timer view" --text "Redraw: the view now owns a clock"
python3 tools/spec_tool.py mark spec/timer.excalidraw --element "Timer view"
```

Elements are named by a substring of their label, which must match one
element. `describe` is what the reviewer reads instead of raw JSON.
