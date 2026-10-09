# Center Tracks

An EAGLE ULP that re-centers already routed tracks in the corridors between pads, vias, holes and tracks of other nets, while keeping the clearances defined in the board's Design Rules (DRU).

```
Before                         After
 ┌─────┐                        ┌─────┐
 │ pad │                        │ pad │
 └─────┘                        └─────┘
 ═══════ track  (tight)                      (even gaps)
                                ═══════ track
 ─ ─ ─ ─ other net              ─ ─ ─ ─ other net
```

The ULP **does not modify the board**. It generates an EAGLE script (`.scr`) made of `MOVE` commands, together with a plan file describing the expected result. The script can be reviewed, executed on a copy of the board, and checked with a built-in verifier.

> **Always work on a copy of the board** (or be ready to close it without saving). Finish with the EAGLE DRC.

## Features

- Centers straight track segments between obstacles on both sides, never going below the DRU limits.
- Obstacles: pads, SMD pads (rotation and rounded corners included), vias, holes, tracks of other nets, board outline, copper rectangles/circles/texts and copper inside packages.
- Reads wire/pad/via/copper-to-dimension distances from the DRU and the clearances of the net classes.
- Repeats the calculation in several passes, so that multiple tracks in the same corridor end up evenly spaced.
- Works on all copper layers, with the units of the current grid handled automatically.
- Automated workflow: baseline check, script generation, execution, second check and comparison with the plan.
- Detailed reports: why each segment was (or was not) moved, new violations, segments not where planned.

## Requirements

- EAGLE 6.00 or later (the ULP uses `#require 6.00.00`).
- A **saved** board: the design rules are read from the `.brd` file.
- Only the layers 1-16 (copper) are handled.

## Installation

1. Copy `center_tracks.ulp` to your EAGLE `ulp` folder, or to any folder listed in *Options > Directories > User Language Programs*.
2. Open a board and run it with `File > Run ULP...` or from the command line: `RUN center_tracks.ulp`

## Quick start (recommended)

1. Open a **copy** of the board and save it.
2. Run the ULP, leave **Automate** checked, and choose an output script file name.
3. The ULP verifies the board first (baseline). The original board should have 0 violations; otherwise you get a warning.
4. A summary of the script is shown. Confirm to execute it.
5. When the script ends, the ULP starts again by itself, verifies the board, and compares the result with the baseline and the plan. The final verdict is `OK` or `ATTENTION`.
6. Run the EAGLE DRC as the final check.

Tip: try a single net first (type its name in *Nets to move*), then the whole board.

## Manual workflow

For step by step use:

1. Save the board. Run the ULP with **Verify only** on the untouched board: this is the baseline (ideally 0 violations).
2. Run it again with **Verify only** off and **Run the script when done** off: it writes the script and the plan.
3. Execute the script (`File > Execute Script...`).
4. Run **Verify only** again with the **same output file name** (so that it finds the plan). Expected: 0 violations and 0 differing segments.
5. Run the EAGLE DRC.

## Parameters

| Parameter | Default | Description |
|---|---|---|
| Nets to move | `*` | Exact net names, comma separated, `*` = all. Other tracks stay in place but are still obstacles. |
| Safety margin | 0.02 mm | Extra room kept above the DRU requirement. 0 = the track may reach the DRU limit. |
| Max side gap | 1.5 mm | A segment is processed only if it has an obstacle on both sides within this distance (edge to edge). 0.8 = only tight corridors, 3 = also wide ones. |
| Min shift | 0.02 mm | Smaller moves are skipped. 0.1 = shorter script, only worthwhile moves. |
| Min segment length | 0.5 mm | Shorter segments (small bends) are skipped. |
| Max passes | 10 | Number of calculation passes. 2 = quick test, 20-30 = dense bus. It stops early when nothing moves any more. |
| Zoom half-size | 0.05 mm | Before each `MOVE` the view is zoomed on the vertex so that EAGLE picks the right wire. 0 = no zoom (faster, but it may pick the wrong object). Do not go above about 0.2. |

### Options

| Option | Description |
|---|---|
| Automate | Whole workflow described in [Quick start](#quick-start-recommended). When on, *Run the script when done* and *Verify only* are ignored. |
| Run the script when done | Off = only the `.scr` file is written, so you can read it and run it yourself. On = it is executed immediately and the board is modified. |
| SMD pads: bounding circle | Off (default) = SMDs are real rectangles with rotation and rounded corners. On = each SMD is modeled as the circle that contains it: safer on odd rotations, but it blocks many corridors on fine-pitch parts. The verifier always uses the real shapes. |
| Verify only | No script is generated. The current board is checked and a report is written. If a plan file exists, the board is also compared with it. |

### Obstacle mode

EAGLE can push or walk around tracks while something is moved. The script sets the obstacle mode to **Ignore** at the start, so that only the planned vertices move, and sets it again at the end. The radio buttons select the mode you want to find **after** the script:

- **Ignore**: you are left in Ignore.
- **Walkaround** / **Push**: the mode is restored to that one. Pick the one you normally route with.
- **Do not touch**: no `SET` command at all. The current mode stays active during the moves. This is not validated: with Push active other tracks may be pushed.

Validated runs used Ignore during the script.

## Output files

All files are written next to the script, using its name as base:

| File | Content |
|---|---|
| `name.scr` | The `MOVE` commands (zoom, then `MOVE`), grouped per layer. |
| `name_plan.txt` | Every signal segment as it should be after the script. |
| `name_skipped.txt` | For each segment that was not moved, the reason and its coordinates. Select a single net to read it easily. |
| `name_verify.txt` | Report of *Verify only*. |
| `name_verify_before.txt`, `name_baseline.txt`, `name_verify_after.txt` | Reports of the automated workflow. |

## Reading the verify report

```
L1 net X vs pad/smd of net Y gap=0.1275 required=0.1524 at (6.8, -15.8)
```

On layer 1, a segment of net `X` is closer than the DRU allows to a pad of net `Y`, near that point. `OVERLAP` means gap below 0: copper touching.

```
Plan check: 376 matching, 7 differing
```

Segments that are not where the plan expects them. `UNPLANNED CHANGE` marks a segment that moved although the script did not mean to move it.

If the EAGLE DRC is clean on the original board but the verifier reports violations there, the model is stricter than the DRC for those pads (typically SMD pads with rounded corners): they are not caused by the script.

## Which segments are moved

A segment is moved when:

- it is straight, and both its ends are plain bends with exactly one straight neighbor (no pad, via, junction or free end);
- it is not drawn with the `ShortDash` style (that style protects a wire);
- it has an obstacle on both sides within *Max side gap*;
- the shift is at least *Min shift* and keeps every clearance of the DRU.

Neighbor segments keep their angles: their ends slide along their own lines.

### Why a track may stay where it is

- One end is on a pad or via of its own net: that end cannot move, and moving only the other end would change the angle of the track.
- The ends are not plain bends (free end, junction, loop), or a neighbor is an arc.
- A long straight segment is moved as a whole, so the tightest spot along its entire length limits the shift. Splitting a track into jogs is not done.
- Less than *Min shift* to gain, or no obstacle on both sides within *Max side gap*.

Use `name_skipped.txt` to see the exact reason for every segment.

## Limitations

- Polygons (copper pours) are not considered: EAGLE recalculates them. The script ends with `RATSNEST;`.
- Arcs are used as obstacles only; they are never moved.
- Segments are shifted as a whole; no jogs are added.
- The model can be stricter than the EAGLE DRC on some pads, so the verifier may report violations that the DRC does not.
- Use of the Walkaround/Push obstacle mode during the moves is not validated.
- The result is not guaranteed to be perfect: always review the reports and run the DRC.

## How it works

1. Reads the board: wires, pads, SMDs, vias, holes, outline, net classes and the DRU.
2. Finds the candidate segments and the obstacles near each of them.
3. For each candidate, computes the free space on both sides and the shift that equalizes the two gaps, limited by the tightest obstacle along the segment.
4. Checks that the new positions of the segment and of its two neighbors keep every required clearance.
5. Repeats for several passes, updating the simulated positions after every move.
6. Writes the `MOVE` commands, preceded by the grid and obstacle mode setup, and the expected result.

## Contributing

Issues and pull requests are welcome. When reporting a problem, please attach the `.scr`, `_plan.txt` and `_verify*.txt` files, and describe the DRC error that you see.
