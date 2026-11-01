# Documentation sources

These scripts regenerate the figures and the PDF manual.

```bat
pip install matplotlib reportlab pillow
cd docs\src
python make_figures.py
python build_manual.py
```

- `make_figures.py` writes the PNG files in `docs/images`.
- `build_manual.py` reads those images and writes `docs/power_tracks_to_stop_manual.pdf`.

The figures are schematic drawings, not screenshots of EAGLE.
