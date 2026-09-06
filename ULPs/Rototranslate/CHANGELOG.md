# Changelog

All notable changes to this project will be documented in this file.

## [1.0] - Initial release

- Move and/or rotate the current GROUP, with live preview on layer 51.
- Rotation reference point: bbox center or custom X/Y.
- Selectable positive-angle convention (CCW / CW).
- Snap dX/dY to the midpoint between two named components, with optional
  type-prefix filtering for boards with many components.
- Move and Copy output modes (Copy: move-only, see README limitations).
- Settings persisted between runs via `cfgget`/`cfgset`.
- Non-interactive command-line mode: `RUN rototranslate <dx> <dy>`.
