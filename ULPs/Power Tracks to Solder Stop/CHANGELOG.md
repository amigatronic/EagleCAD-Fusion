# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-11-01

### Added
- Interactive dialog listing every signal routed on Top/Bottom copper, with wire counts, polygon count
  and minimum/maximum wire width.
- Per-signal checkboxes, paging, sorting by any column, and bulk selection (all, none, invert,
  by minimum width, by name).
- Copy of the wires of the selected signals to tStop (29) / bStop (30), with arcs, optional width
  margin and skipping of wires that already exist on the stop layer.
- Copy of pours (polygons) following the real poured copper, including isolation cutouts and
  islands, with fallback to the polygon outline when the pour is not calculated.
- Automatic opening grow derived from the clearance of each pour (pour isolate value, else net class
  clearance), plus an optional manual extra grow.
- Adaptive arc approximation controlled by an arc tolerance.
- Five-page built-in help and a PDF user manual.

