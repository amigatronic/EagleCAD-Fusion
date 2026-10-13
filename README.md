# EagleCAD-Fusion

A collection of tools for **Autodesk EAGLE** and **Fusion 360 Electronics**: User Language Programs (ULPs) that automate PCB editing tasks, and standalone Python/PHP utilities for inspecting EAGLE board and schematic files.

> by **Arky** - [amigatronic.com](https://www.amigatronic.com)

## Repository layout

```
EagleCAD-Fusion/
├── ULPs/              EAGLE / Fusion 360 Electronics User Language Programs
├── Python-Codes/      Standalone tools that read EAGLE .brd / .sch files
├── Projects/          Reserved for future projects
└── LICENSE
```

## ULPs

Each ULP has its own folder with a dedicated README, installation notes and usage instructions.

| Tool | Description |
|---|---|
| [`center_tracks`](ULPs/center_tracks) | Re-centers routed tracks in the corridors between pads, vias, holes and other tracks, respecting the board's DRU clearances. It generates a reviewable `.scr` script instead of modifying the board directly, and includes a built-in verifier. |
| [`cmd-draw`](ULPs/cmd-draw) | Generates and runs a script that places wires, polygons, pads, vias, SMDs, holes, existing elements or groups along a circle, ellipse or quarter ellipse. Adapted from the CadSoft/Autodesk `cmd-draw` ULP for EAGLE 9.6.2, with bug fixes and new features. |
| [`eagle2freerouting`](ULPs/eagle2freerouting) | Exports a board to Specctra DSN for use with FreeRouting. Two versions: `eagle2freerouting.ulp` (EAGLE) and `fusion2freerouting.ulp` (Fusion 360 Electronics). |
| [`Remove-Wire-Stubs`](ULPs/Remove-Wire-Stubs) | Detects and removes dead-end copper trace stubs (including multi-segment chains), with optional autoroute-and-repeat mode. |
| [`Rototranslate`](ULPs/Rototranslate) | Moves and/or rotates the current `GROUP` by a given displacement and angle, with a live bounding-box preview. |

### Installing a ULP

1. Copy the `.ulp` file into your EAGLE `ulp` folder (or any folder listed in *Options > Directories > User Language Programs*). In Fusion 360, any accessible folder works.
2. Open a board (`.brd`) and run it with `File > Run ULP...` or from the command line:

   ```
   RUN <name>.ulp
   ```

> **Tip:** always work on a copy of the board and finish with the EAGLE DRC.

## Python / PHP tools

| Tool | Description |
|---|---|
| [`eagle-viewers`](Python-Codes/eagle-viewers) | **EaglePCBView3D** - offline renderer for EAGLE `.brd` / `.sch` files. Produces a static SVG and a standalone interactive `.htm` viewer with per-layer toggles and a 3D view. Python standard library only (GUI via `tkinter`). A PHP web version (`eagle_pcb_view_3d.php`) is also included. |
| [`eagle_brd_analyzer`](Python-Codes/eagle_brd_analyzer) | Read-only analyzer for `.brd` XML files: element counts, polygon vertex counts, bounding boxes, area/perimeter, circle detection and reports on suspiciously large polygons. |

### Quick usage

```
# EaglePCBView3D: GUI
python eagle_pcb_view_3d.py

# EaglePCBView3D: command line
python eagle_pcb_view_3d.py board.brd -o OUTDIR --open

# Board analyzer
python eagle_brd_analyzer.py board.brd
```

Python 3.8 or newer is required.

## Compatibility

- **EAGLE**: 6.00 or later for most ULPs; `cmd-draw` targets EAGLE 9.6.2.
- **Fusion 360 Electronics**: supported by `eagle2freerouting` (dedicated version), `Remove-Wire-Stubs` and `Rototranslate`.

See each tool's README for exact requirements.

## License

Released under the **Apache License 2.0**. See [`LICENSE`](LICENSE) for details. Individual tools may carry additional credits or notices in their own folders.

## Contributing

Issues and pull requests are welcome.
