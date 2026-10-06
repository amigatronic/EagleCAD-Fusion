# Eagle and Fusion to FreeRouting

**ULP scripts for exporting EAGLE and Fusion 360 Electronics board files to Specctra DSN format for use with FreeRouting.**

Eagle2FreeRouter converts a board into a DSN file that can be imported into FreeRouting for automatic PCB routing.

## Available versions

| File | Target |
|---|---|
| `eagle2freerouting.ulp` | EAGLE CAD |
| `fusion2freerouting.ulp` | **Fusion 360 Electronics** (optimized for Fusion 360) |

Both versions share the same features, export options and DSN output. Use `fusion2freerouting.ulp` when working in Fusion 360 Electronics and `eagle2freerouter.ulp` when working in EAGLE CAD.

## Features

- Export EAGLE / Fusion 360 Electronics boards to Specctra DSN format.
- Export of:
  - Board outline
  - Components and footprints
  - Pads
  - Nets and connections
  - Existing tracks
  - Vias
  - Polygons
  - Keepouts
- Optional protection of existing tracks and vias.
- Optional exclusion of selected nets.
- Configurable routing layers.
- Polygon protection and polygon handling options.
- **Unroute all** option to export the board as effectively unrouted.
- Automatic recognition of circular polygons.
- Adaptive reduction of excessively detailed circular polygons.
- Circular polygons remain **filled polygons** in the DSN and are not converted to empty circles.
- Built-in **Help** window with clickable links and credits.

## Fusion 360 Electronics version

`fusion2freerouting.ulp` is the version optimized for **Fusion 360 Electronics**.

Fusion 360 Electronics replaced the classic EAGLE `polygons` loop (now reported as deprecated) with new polygon objects. The Fusion version uses them natively:

| Purpose | EAGLE version | Fusion 360 version |
|---|---|---|
| Copper pours inside signals | `polygons` loop | `polyPours` loop (`UL_POLYPOUR`) |
| Restrict areas on the board | `polygons` loop | `polyShapes` loop (`UL_POLYSHAPE`) |
| Restrict areas inside packages | `polygons` loop | `polyShapes` loop (`UL_POLYSHAPE`) |

Notes:

- A `UL_POLYPOUR` exposes its contour directly; there is no intermediate `polyShapes` level for copper pours.
- `UL_POLYSHAPE` has no `width` member, so restrict areas on the board are written to the DSN with a width of `0`.
- All other features (Unroute all, net exclusion, circular polygon optimization, DSN output selector) behave the same as in the EAGLE version.
- The Help button opens links in the default web browser (Windows).


## Unroute all

The **Unroute all existing wires and vias** option allows an already routed board to be exported as if it were unrouted.

When enabled, existing routing information is omitted from the DSN export so that FreeRouting can route the board again from the original netlist.

This is useful when:

- The board already contains existing routing.
- The existing routing should be discarded.
- The board needs to be completely re-routed with FreeRouting.
- Existing tracks or vias should not influence the automatic router.

When the option is disabled, the original export behavior is preserved.

## Circular polygon optimization

Some boards can contain circular copper polygons represented internally as polygons with a very large number of vertices.

For example, a circular copper area may be represented by a polygon containing **3600 vertices**.

Although geometrically valid, such a representation can produce unnecessarily large DSN files and can significantly increase the processing required by FreeRouting.

Eagle2FreeRouting detects polygons that are geometrically circular and rebuilds their contour using an optimized number of vertices.

### Adaptive resolution

The number of vertices is calculated from the actual radius of the circular polygon rather than using a fixed number of segments.

The principle is:

```text
Small circular polygon
        ↓
fewer vertices required

Large circular polygon
        ↓
more vertices required

Very large circular polygon
        ↓
may require many vertices
```

If the original polygon already contains fewer vertices than the calculated optimal resolution, the original level of detail is preserved.

The exporter therefore avoids increasing the number of vertices unnecessarily.

### Filled polygon preservation

A circular polygon is **not** converted into a DSN `circle`.

A polygon represents a **filled copper area**, so the DSN output remains a filled polygon:

```text
(poly layer width
    x1 y1
    x2 y2
    ...
    xn yn
    x1 y1)
```

The first vertex is repeated at the end of the coordinate chain to properly close the polygon.

## Why circular polygon optimization is necessary

Large circular polygons can contain thousands of vertices even when their geometry does not require such a high resolution.

For example:

```text
Original:
3600 vertices

Optimized:
only the number of vertices actually required
```

This reduces the amount of geometry passed to FreeRouting while maintaining the shape of the copper area.

The optimization is performed **during DSN export only**.

The original `.brd` file is not modified.

## DSN output

The generated file uses the Specctra DSN format expected by FreeRouting.

The output includes:

- Structure/layers
- Boundary
- Components
- Padstacks
- Nets
- Wiring
- Tracks and vias when enabled
- Keepouts
- Copper polygons

The exporter keeps the original routing information unless an option such as **Unroute all** explicitly disables it.

## Installation

### EAGLE CAD

Copy:

```text
eagle2freerouting.ulp
```

into the EAGLE ULP directory or another directory accessible from EAGLE.

In EAGLE, run the ULP from:

```text
File → Run ULP
```

### Fusion 360 Electronics

Copy:

```text
fusion2freerouting.ulp
```

into a directory accessible from Fusion 360 Electronics and run it from the board editor with the **Run ULP** command.

## Usage

1. Open the desired board in EAGLE or in the Fusion 360 Electronics board editor.
2. Run the ULP for your application (`eagle2freerouting.ulp` or `fusion2freerouting.ulp`).
3. Configure the export options.
4. Select the desired output file.
5. Export the board to DSN.
6. Open the generated DSN in FreeRouting.

For a board that should be completely re-routed, enable:

```text
Unroute all existing wires and vias
```

For a board where existing routing should be retained, leave it disabled.

## Important notes

### Existing routing

The exporter preserves existing tracks and vias unless the corresponding protection/exclusion options or **Unroute all** are enabled.

### Polygons

Polygon handling is particularly important for boards containing large copper pours or circular copper areas.

The circular polygon optimization only changes the representation written to the DSN file. It does not modify the original board.

### Board outline

The board outline is exported from the board data and is used by FreeRouting as the routing boundary.

### FreeRouting compatibility

The generated DSN files are intended primarily for use with FreeRouting.

Very complex boards may still contain geometry that requires additional investigation if FreeRouting reports errors while loading the DSN.

## Version history

### Version 7.1.5 (for Fusion)

- First release of `fusion2freerouting.ulp`, optimized for Fusion 360 Electronics.
- Uses the Fusion polygon objects: `polyPours` / `UL_POLYPOUR` for signal copper and `polyShapes` for board and package restrict areas, instead of the deprecated `polygons` loop.
- Fixed string literals that contained raw line breaks (`unterminated string` error).
- Added clickable links and a Credits section to the Help window.
- Based on version 7.1.5 of the EAGLE version.

### Version 7.1.5

- Fixed circular polygon DSN generation.
- Corrected polygon closure so that the first vertex is repeated as the final vertex.
- Removed incorrect extra coordinate pairs from generated circular polygons.
- Fixed negative zero values such as `-0.000000` in generated coordinates.
- Circular polygons are exported as properly closed filled polygons.
- Added adaptive circular polygon resolution based on polygon size.
- Avoids increasing the number of vertices when the original polygon already has sufficient resolution.
- Preserves large circular polygons when their existing resolution is already appropriate.
- Existing track/via export behavior retained from the known working 7.1.3 implementation.
- `Unroute all` behavior preserved.

### Version 7.1.4

- Added reconstruction of circular polygons as reduced filled polygon contours.
- Circular polygons were no longer exported as native DSN circles.
- Added support for reducing extremely high vertex-count circular polygons while preserving their filled-copper semantics.

### Version 7.1.3

- Added recognition of geometrically circular polygons.
- Circular polygons could be represented using DSN circular geometry to avoid extremely large polygon descriptions.
- Improved FreeRouting compatibility with boards containing very large circular polygon geometries.

### Version 7.1.2

- Extended **Unroute all** handling to remove existing routing-related polygon geometry from the DSN when requested.
- Preserved the board structure, netlist, components, pads and outline.

### Version 7.1.1

- Added the initial **Unroute all existing wires and vias** option.
- Existing tracks and vias can be omitted from the DSN so FreeRouting can route the board from scratch.

## Credits

- EAGLE version 7.x by Arky - [amigatronic.com](https://amigatronic.com) - [github.com/amigatronic](https://github.com/amigatronic).
- Based on an earlier design by Thomas Kaeubler and Alfons Wirtz.
- Thanks to David Varley for finding the right Resolution settings.
- Original version optimized for Freerouter, started in summer 2012.
- [Freerouting](https://github.com/freerouting/freerouting): autorouter by Alfons Wirtz, now developed at [github.com/freerouting/freerouting](https://github.com/freerouting/freerouting). Documentation and software: [www.freerouting.app](https://www.freerouting.app).

All original copyrights and credits remain with their respective authors.

## License

See the license information included with the project.

## Disclaimer

These ULPs modify the way board data is represented in the exported DSN file.

Always keep a backup of the original `.brd` file before experimenting with routing or automated export workflows.

The generated DSN should be checked in FreeRouting before manufacturing.

## Project

**Eagle2FreeRouting**

EAGLE CAD / Fusion 360 Electronics → Specctra DSN → FreeRouting

Developed for PCB routing workflows where an existing board needs to be exported and optionally re-routed using FreeRouting.
