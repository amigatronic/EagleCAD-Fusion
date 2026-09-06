# rototranslate.ulp

A ULP (User Language Program) for **Autodesk EAGLE / Fusion 360 Electronics**
that moves and/or rotates the currently defined board `GROUP` by a
user-entered displacement (dX, dY) and/or rotation angle, with a live
preview drawn on the board before the transform is actually applied.

![EAGLE](https://img.shields.io/badge/EAGLE-ULP-blue) ![Version](https://img.shields.io/badge/version-1.0-informational) ![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **Move** a group by dX/dY, **Rotate** it around a reference point, or both.
- **Live preview**: before applying anything, the script draws the resulting
  bounding box as a rectangle on layer `51 (tDocu)` and asks for confirmation.
- **Two rotation reference modes**:
  - Group bounding-box center (computed automatically).
  - A custom point you type in.
- **Two rotation direction conventions**, selectable in the dialog:
  - Counter-clockwise (math / EAGLE default).
  - Clockwise (clock convention) — the script inverts the sign for you.
- **Snap dX/dY to the midpoint between two components**: pick component A
  and B (optionally filtered by name-prefix/type, e.g. `IC`, `R`, `RN`) and
  the script computes the offset needed to land the group's bbox center on
  their midpoint.
- **Move or Copy mode**. Copy mode duplicates the group by translation only
  (see [Known limitations](#known-limitations)).
- **Settings persistence** between runs via `cfgget`/`cfgset`, in the
  script's own namespace (`rototranslate.value.*`), so it never touches
  another ULP's stored values.
- **Non-interactive command-line mode** for scripting: `RUN rototranslate <dx> <dy>`
  applies a move immediately, with no dialog and no preview.

## Requirements

- Autodesk EAGLE (or Fusion 360 Electronics / Fusion Electronics), any
  reasonably recent version with standard ULP/`dlg*` dialog support.
- A **board** (`.brd`) editor window. The script has no effect in the
  schematic editor.

## Installation

1. Download [`rototranslate.ulp`](./rototranslate.ulp).
2. Copy it into your EAGLE `ulp` folder, e.g.:
   - Windows: `C:\EAGLE\ulp\` or `%APPDATA%\EAGLE\ulp\`
   - Or any folder already listed in **Options → Directories → User language programs**.
3. In the board editor, run it from **File → Run ULP…**, or type:
   ```
   RUN rototranslate
   ```

## Usage

### Interactive mode

1. Select the objects you want to transform and issue EAGLE's own
   `GROUP` command (or select + right-click → Group).
2. `RUN rototranslate`
3. In the dialog:
   - Tick **Move** and/or **Rotate**, enter the values.
   - Choose the rotation **reference point** (bbox center or custom X/Y).
   - Choose the positive-angle **convention** (CCW or CW).
   - Optionally enable **snap to midpoint** between two named components.
   - Choose **Move** or **Copy** as the output mode.
   - Press **Preview & Apply**.
4. A preview rectangle appears on layer 51. Confirm in the follow-up dialog
   to actually apply the transform, or discard to undo the preview only.

Values typed in the dX/dY/reference fields are forwarded to EAGLE as-is:
a bare number is interpreted in the board's current grid unit (shown next
to each field), or you can type an explicit unit suffix yourself
(e.g. `0.1in`, `500mil`).

### Non-interactive / scripted mode

```
RUN rototranslate <dx> <dy>
```

Applies a plain move of `(dx, dy)` to the current group immediately —
no dialog, no preview. Useful for chaining from other scripts.

## Known limitations (v1.0)

- **Approximate bounding box for elements.** The bbox for placed elements
  is built from pad/SMD contact positions (plus a fixed margin as fallback
  when neither is found); it does not walk the package's courtyard/outline.
  The preview rectangle for element-heavy groups is therefore an
  approximation, not an exact silhouette.
- **Copy mode supports Move only.** Combining Copy + Rotate is not
  implemented: EAGLE blocks `CUT` on schematic-linked parts to protect
  board/schematic sync (backannotation), and after a `COPY` there is no
  reliable script-level way to reselect just the new copy in order to
  rotate it afterwards. Contributions welcome — see below.
- **Locked elements** are excluded when computing the bounding box in
  copy-mode filtering, but are not otherwise excluded from the
  `MOVE`/`COPY` command itself — EAGLE will simply refuse to move a locked
  element on its own.

## How it works (short version)

The script never mutates the board directly by walking objects itself;
instead it computes the required transform and **emits an EAGLE script
string** (`MOVE`, `ROTATE`, `COPY`, `UNDO`, plus `LAYER`/`RECT` for the
preview) via `exit(script)`, which EAGLE then executes as if typed on the
command line. This is why the flow is split into three phases: a first
`RUN` builds the preview + queues a `--confirm` re-run, the `--confirm`
re-run shows a small Apply/Discard dialog, and the final commands are
only emitted if you accept.

## License

MIT — see [LICENSE](./LICENSE).

This project is an independent implementation. It reuses EAGLE's own
script command syntax (`MOVE`, `ROTATE`, `GROUP`, `UNDO`, `RECT`, `LAYER`),
which is part of the EAGLE application's interface and not the creative
expression of any third-party ULP author.

## Contributing

Issues and pull requests are welcome, in particular for the Copy+Rotate
limitation described above and for a more accurate (courtyard-based)
bounding box.
