# cmd-draw — EAGLE ULP

`cmd-draw` is an EAGLE User Language Program that **generates and runs a script** to place objects along a circle, an ellipse or a quarter ellipse:

- wires and **polygons** (circles / ellipses drawn as wire or polygon outlines)
- pads, vias, SMDs and holes
- existing board elements (**MOVE** by name, e.g. `R1`, `R2`, …)
- whole **groups** (CUT / PASTE of rotated copies)

It works from a dialog (run it without parameters) or from the command line with compact parameters (`RUN cmd-draw ...`). A *Test* dialog always shows the generated script before it is executed.

> This repository is an adaptation of the CadSoft/Autodesk ULP `cmd-draw` (v2.01) for **EAGLE 9.6.2**, with bug fixes and one new feature (polygon by number of sides). See [Credits](#credits-and-license).

---

## Table of contents

- [What is new in this edition](#what-is-new-in-this-edition)
- [Requirements and installation](#requirements-and-installation)
- [Usage](#usage)
- [Parameter reference](#parameter-reference)
- [Examples](#examples)
- [Polygon by number of sides](#polygon-by-number-of-sides)
- [Behaviour notes](#behaviour-notes)
- [Status and known issues](#status-and-known-issues)
- [Changelog](#changelog)
- [Credits and license](#credits-and-license)

---

## What is new in this edition

### New feature

| Feature | Details |
|---|---|
| **Polygon by number of sides** | New dialog field *Polygon sides* and new parameter `K<n>`. Gives exactly *n* vertices on a full 360° circle (or ellipse) instead of start/end angle + step. Vertex count is immune to floating-point rounding (no duplicated closing vertex). See [Polygon by number of sides](#polygon-by-number-of-sides). |

### Bugs fixed

| # | Problem | Fix |
|---|---|---|
| 1 | The polygon option generated the command `ppour` (a Fusion Electronics command) instead of the EAGLE `POLYGON` command, so polygons did not work in EAGLE 9.6.2. | All 8 occurrences restored to `POLYGON`. |
| 2 | Polygon with an angle step and no form selected did not terminate the command with `;`. | `;` added. |
| 3 | **SMD**, clockwise (negative step): the "add 360° to start" condition was inverted compared with MOVE, PAD, HOLE and the help text. | Condition fixed (`StartAngle < EndAngle`). |
| 4 | **Rotate offset** was applied only to MOVE with a negative step; it was ignored for MOVE with a positive step, single MOVE and all SMD placements, although the field is shown for SMD. | Offset now applied everywhere (shared `smdRotation()` helper for SMD). |
| 5 | Via/Pad with the blank entry selected in the shape combo box emitted an empty `CHANGE SHAPE  ;`. | Blank entry is skipped. |
| 6 | Dialog label in HOLE mode showed `%+ distance`. | Fixed to `&+ distance`. |
| 7 | `error()` for GROUP contained a duplicated test (`!AngleStep` twice), a misleading message (it mentioned *Angle start*, which may legitimately be 0) and an unreachable branch. | Test and message corrected, dead branch removed. |
| 8 | The help examples use `#` and `.` as step symbols, but the parser only knew `°` and `/` (anything else ended in *unknown parameter*). | `#` is accepted as `°` (step in degrees) and `.` as `/` (number of steps). |
| 9 | The file is UTF-8 but the parser compared the first character with `0xB0` (Latin-1 `°`) only. | The UTF-8 `°` is now accepted as well. |
| 10 | Menu pictures were loaded from remote URLs inside HTML strings (not reliable in the ULP dialog). | Back to local `.bmp` files referenced with `<img src=...>` in a `dlgLabel`. |

### Inherited from upstream v2.01 (CadSoft)

These come from the upstream version this edition is based on:

- coordinates printed with **9 decimals** (`%.9f`) instead of 4 — important for polygons with many vertices
- GROUP: radius no longer required, new *Use selected group* check box, copies pasted with `PASTE R<angle>`
- new **rotate offset** field, start angle range up to 720° (clockwise placement with an end angle larger than 0)
- HOLE generation corrected (no stray semicolons)
- shape is also output for vias
- coordinate limits expressed in absolute units
- extended German help

### Help improvements

The English help now also documents: `W` before `O` for polygons, `R` before `P`/`V`/`S` (last one wins), the defaults (start 0°, end 360°), that the end angle is excluded except for wire/polygon, the `#` / `.` aliases, the `K` parameter, and a `K` example.

---

## Requirements and installation

- EAGLE **6.4 or newer** (`#require 6.0400`). Developed and checked on **EAGLE 9.6.2**.
- Autodesk Fusion Electronics is **not** targeted (the polygon command was reverted to the EAGLE `POLYGON`).

Installation:

1. Copy the `.ulp` file into one of your ULP directories (*Options → Directories → User Language Programs*).
2. Copy the **68 menu pictures** (`cmd-draw-*.bmp`, the same set shipped with the original `cmd-draw`) **into the same folder as the `.ulp`**. A ULP cannot embed images, so without them the menu works but the picture area stays empty.
3. Name the file `cmd-draw.ulp` to use the examples below as they are. If you keep another name (for example `cmd-draw_e962.ulp`), use it in the `RUN` command.

The file is **UTF-8 with CRLF line endings**. Keep this encoding when you edit it.

---

## Usage

- **Dialog**: `RUN cmd-draw` (from a Board, Package, Symbol or Schematic editor). Libraries must be in Package or Symbol mode. Pick the object type on the left, set position, radius and angles, then press **OK**. The generated script is shown in a *Test* dialog; confirm to execute it.
- **Command line**: `RUN cmd-draw <parameters>`. Parameters can be given **in any order** (with two exceptions, see [Behaviour notes](#behaviour-notes)) and are not case sensitive.

Units are those of the current grid. If `MARK` is set in the editor, coordinates are relative to the mark.

---

## Parameter reference

| Parameter | Meaning |
|---|---|
| `+<n>` | Radius (wire, polygon, MOVE) or distance (pad, via, SMD, hole, group) |
| `A<n>` | Angle start (degrees) |
| `N<n>` | Angle step in degrees (with `°` / `#`) **or** number of steps (with `/` / `.`) |
| `E<n>` | Angle end (degrees) |
| `°` or `#` | `N` is an angle step in degrees |
| `/` or `.` | `N` is a number of steps: step = (end − start) / n |
| `X<n>` `Y<n>` | Centre coordinates |
| `L<layer>` | Layer (number or name). In MOVE, layer `16` mirrors the elements |
| `W<n>` | Wire with width `n` (selects the WIRE function) |
| `O` | Polygon instead of wire (put it **after** `W`) |
| `K<n>` | **Polygon by number of sides** (with `O`), see below |
| `P` / `V` / `S` | Pad (package) / Via (board) / SMD (package) |
| `I<n>` `T<n>` | SMD width and height (dx, dy) |
| `D<n>` | Pad / via diameter |
| `R<n>` | Drill diameter; selects HOLE (put it **before** `P`/`V`/`S` if combined) |
| `-<name>` | Signal / net name, first pad or SMD name, or first element name for MOVE |
| `MOVE` | Place existing elements in a Board by name order (`R1`, `R2`, …) |
| `M` | Rotate placed items to match their angle |
| `G` | Group: CUT, then PASTE rotated copies |
| `C` | Circle |
| `0` | Full ellipse |
| `F<n>` | Ellipse factor: height = radius × `n` |
| `4` | Quarter ellipse (first quadrant, 0°–90°) |

---

## Examples

```text
# Wire arc from 115° to 180°, 75° step, on layer Top
RUN cmd-draw w0.4 -gnd x1.3 y2.56 +17.45 a115 n75 e180 # lTop

# Polygon arc, 9° step, on layer 1
RUN cmd-draw a0 e150.0 x30 y4 w0.2 n9 # o +2.27 -gnd l1

# Full ellipse as polygon, factor 1.7
RUN cmd-draw a0 e50.0 x30 y4 w0.2 n9 o 0 f1.7 +2.27 -gnd l1

# Circular polygon with exactly 60 sides (new)
RUN cmd-draw w0.2 -gnd x30 y4 +25.4 o c k60 l1

# SMDs around a circle, rotated to match, 7 steps
RUN cmd-draw s -1 +9 n7 #

# Holes, 7 steps between start and end angle
RUN cmd-draw r1.2 +9.5 n7 .

# Vias on an ellipse, 20° step
RUN cmd-draw r.8 d1.4 v -A +4.20 n20.0 x-2.54 y-5.08 l1 f1.75

# Rotated copies of the current group, 33.333° step
RUN cmd-draw g n33.333 # A0.0 e359.9

# Place R1, R2, ... on a circle (Board only), mirrored on layer 16
RUN cmd-draw +10 MOVE -R1 M a33 L16 N7 E322 .
```

---

## Polygon by number of sides

Drawing a polygon that approximates a circle used to require start angle, end angle and step (for example `a0 e359.9 n0.1`). With a **number of sides** you just say how many vertices you want:

```text
RUN cmd-draw w0.2 -gnd x0 y0 +50.8 o c k60 l1
```

- In the dialog, select **Polygon** and fill **Polygon sides** (0 = use the angles as before).
- `Angle start` stays available and is the position of the **first vertex** (useful to rotate the shape, e.g. 22.5° for an octagon with a flat side on top).
- Angle step and end are computed: step = 360° / sides.
- Works with circle and full ellipse (`0` + `f`). It cannot be combined with the quarter ellipse (`4`), and at least 3 sides are required.

### How many sides?

The polygon is inscribed in the circle, so the largest deviation (at the middle of a side) is `R · (1 − cos(π / N))`. For a radius of 50.8 mm:

| Sides | Step | Max. deviation |
|---:|---:|---:|
| 360 | 1° | 0.002 mm |
| 120 | 3° | 0.017 mm |
| 72 | 5° | 0.048 mm |
| 60 | 6° | 0.070 mm |
| 48 | 7.5° | 0.109 mm |
| 36 | 10° | 0.193 mm |
| 32 | 11.25° | 0.245 mm |

As a rule of thumb, keep the deviation below the polygon width you use (for example 0.2 mm).

---

## Behaviour notes

- **Order of parameters**: `W` must come before `O` (`W` selects WIRE and would override POLYGON); `R` (drill, selects HOLE) must come before `P`/`V`/`S`, because the last selection wins.
- **End angle**: wire and polygon include the end angle; all other objects stop before it. Defaults: start 0°, end 360°.
- **Clockwise placement**: use a negative step for MOVE, PAD, SMD and HOLE. If start is smaller than end with a negative step, 360° is added to the start angle.
- **MOVE** works only in a Board. Elements are taken by incrementing the number in the first name (`R1`, `R2`, …) and the sequence stops at the first missing element.
- **GROUP** needs angle step and end; the radius is not used. With *Use selected group* the group defined before starting the ULP is used, otherwise every visible object is grouped.
- The `K` parameter is used **only with `O`** (polygon).

---

## Status and known issues

**Checked**

- Polygon with many sides forming a circle was tested on EAGLE 9.6.2.
- The remaining changes were reviewed in the code (balanced blocks, every referenced picture defined, vertex-count logic simulated for 3 to 3600 sides) but not every mode has been exercised in EAGLE. Bug reports are welcome.

**Known issues / limitations (not changed)**

- The *Test* dialog is always shown (`test = 1`).
- Some dialog texts still contain typos (`Schape`, `Heigh&t`, `ponly`, `relativ`). The picture file names with typos (`cricle`, `degsetp`, `degstap`, `clac`) are kept on purpose because they match the original `.bmp` files.
- Angle loops accumulate floating-point steps (`a += step`); for wires, pads and similar objects the last point of a very fine step may be missed or duplicated. Polygons by number of sides are not affected.
- Wire/ellipse placement from the dialog is not covered by the new *sides* option (only polygons).
- A few unused variables and dead code lines of the original remain (for example the group-distance calculation that is overwritten by the coordinate limit).

---

## Changelog

| Version | Notes |
|---|---|
| 1.05 (2006–2008) | CadSoft original (alf@cadsoft.de): GROUP, SMD name fixes |
| 2.01 (up to 2013) | CadSoft update: rotate offset, group improvements, V6 resolution, hole and via shape fixes |
|  | `POLYGON` restored, local pictures, SMD/offset/shape/label/error fixes, `#` and `.` symbols, UTF-8 `°`, help additions, **polygon by number of sides (`K`)** |

---

## Credits and license

- Original program: **CadSoft Computer GmbH / alf@cadsoft.de**, later versions distributed with EAGLE by Autodesk.
- This edition: adaptation, bug fixes and the *sides* feature.
- The original ULP states: *"THIS PROGRAM IS PROVIDED AS IS AND WITHOUT WARRANTY OF ANY KIND, EXPRESSED OR IMPLIED"*. No other license is specified by the original author, so **no license is granted by this repository beyond what the original terms allow**. Check the terms of the original program before redistributing it, and add your own license text here once that is clear.
