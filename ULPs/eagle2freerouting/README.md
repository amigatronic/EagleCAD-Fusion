# Eagle2FreeRouter

**EAGLE CAD ULP for exporting EAGLE board files to Specctra DSN format for use with FreeRouting.**

Eagle2FreeRouter converts an EAGLE CAD board into a DSN file that can be imported into FreeRouting for automatic PCB routing.

## Features

- Export EAGLE boards to Specctra DSN format.
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

## Unroute all

The **Unroute all existing wires and vias** option allows an already routed EAGLE board to be exported as if it were unrouted.

When enabled, existing routing information is omitted from the DSN export so that FreeRouting can route the board again from the original netlist.

This is useful when:

- The board already contains existing routing.
- The existing routing should be discarded.
- The board needs to be completely re-routed with FreeRouting.
- Existing tracks or vias should not influence the automatic router.

When the option is disabled, the original export behavior is preserved.

## Circular polygon optimization

Some EAGLE boards can contain circular copper polygons represented internally as polygons with a very large number of vertices.

For example, a circular copper area may be represented by a polygon containing **3600 vertices**.

Although geometrically valid, such a representation can produce unnecessarily large DSN files and can significantly increase the processing required by FreeRouting.

Eagle2FreeRouter detects polygons that are geometrically circular and rebuilds their contour using an optimized number of vertices.

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

A circular EAGLE polygon is **not** converted into a DSN `circle`.

An EAGLE polygon represents a **filled copper area**, so the DSN output remains a filled polygon:

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

The original EAGLE `.brd` file is not modified.

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

The exporter keeps the original EAGLE routing information unless an option such as **Unroute all** explicitly disables it.

## Installation

Copy:

```text
eagle2freerouter.ulp
```

into the EAGLE ULP directory or another directory accessible from EAGLE.

In EAGLE, run the ULP from:

```text
File → Run ULP
```

## Usage

1. Open the desired board in EAGLE.
2. Run `eagle2freerouter.ulp`.
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

The circular polygon optimization only changes the representation written to the DSN file. It does not modify the original EAGLE board.

### Board outline

The board outline is exported from the EAGLE board data and is used by FreeRouting as the routing boundary.

### FreeRouting compatibility

The generated DSN files are intended primarily for use with FreeRouting.

Very complex EAGLE boards may still contain geometry that requires additional investigation if FreeRouting reports errors while loading the DSN.

## Version history

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

- Added recognition of geometrically circular EAGLE polygons.
- Circular polygons could be represented using DSN circular geometry to avoid extremely large polygon descriptions.
- Improved FreeRouting compatibility with boards containing very large circular polygon geometries.

### Version 7.1.2

- Extended **Unroute all** handling to remove existing routing-related polygon geometry from the DSN when requested.
- Preserved the board structure, netlist, components, pads and outline.

### Version 7.1.1

- Added the initial **Unroute all existing wires and vias** option.
- Existing tracks and vias can be omitted from the DSN so FreeRouting can route the board from scratch.

## License

See the license information included with the project.

## Disclaimer

This ULP modifies the way EAGLE board data is represented in the exported DSN file.

Always keep a backup of the original EAGLE `.brd` file before experimenting with routing or automated export workflows.

The generated DSN should be checked in FreeRouting before manufacturing.

## Project

**Eagle2FreeRouter**

EAGLE CAD → Specctra DSN → FreeRouting

Developed for PCB routing workflows where an existing EAGLE board needs to be exported and optionally re-routed using FreeRouting.
