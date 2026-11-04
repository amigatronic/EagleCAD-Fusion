"""Safe EAGLE XML placement export helpers."""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Mapping, Sequence


def _rotation_token(angle: float, mirror: bool, original: str = "R0") -> str:
    """Build an EAGLE rotation token and preserve the original spin flag."""
    spin = "S" if (original or "").startswith("S") else ""
    return f"{spin}{'M' if mirror else ''}R{float(angle):g}"


def export_placement_pair(
    source_brd: str | os.PathLike,
    source_sch: str | os.PathLike,
    output_brd: str | os.PathLike,
    output_sch: str | os.PathLike,
    placements: Mapping[str, Sequence],
) -> int:
    """Write optimized element placements to a BRD copy and copy its SCH unchanged.

    The operation intentionally does not perform logical gate/pin swaps. Both
    output files are staged before replacing their destinations.
    """
    source_brd = Path(source_brd)
    source_sch = Path(source_sch)
    output_brd = Path(output_brd)
    output_sch = Path(output_sch)

    if not source_brd.is_file():
        raise FileNotFoundError(f"Source BRD file not found: {source_brd}")
    if not source_sch.is_file():
        raise FileNotFoundError(f"Source SCH file not found: {source_sch}")
    if output_brd.resolve() == source_brd.resolve() or output_sch.resolve() == source_sch.resolve():
        raise ValueError("The export must not overwrite either source Eagle file.")
    if output_brd.resolve().parent != output_sch.resolve().parent:
        raise ValueError("The exported BRD and SCH must be saved in the same folder.")
    if output_brd.suffix.lower() != ".brd" or output_sch.suffix.lower() != ".sch":
        raise ValueError("Output filenames must use .brd and .sch extensions.")
    if output_brd.stem.casefold() != output_sch.stem.casefold():
        raise ValueError("The exported BRD and SCH must have the same filename stem.")

    raw_brd = source_brd.read_bytes()
    doctype_match = re.search(rb"<!DOCTYPE[^>]*>", raw_brd, flags=re.IGNORECASE)
    doctype = doctype_match.group(0) if doctype_match else None

    parser = ET.XMLParser()
    root = ET.fromstring(raw_brd, parser=parser)
    elements = root.find(".//board/elements")
    if elements is None:
        raise ValueError("The source BRD does not contain a board/elements section.")

    # EAGLE stores unrouted airwires as zero-width wires on layer 19.
    # Polygon pours are separate <polygon> elements and are not routed tracks.
    # Only positive-width copper wires on copper layers 1-16 and actual vias
    # indicate that the board has already been routed.
    routed_wires = []
    for wire in root.findall(".//board/signals/signal/wire"):
        try:
            layer = int(wire.get("layer", "0"))
            width = float(wire.get("width", "0"))
        except (TypeError, ValueError):
            continue
        if 1 <= layer <= 16 and width > 0:
            routed_wires.append(wire)

    routed_vias = root.findall(".//board/signals/signal/via")
    

    source_elements = {element.get("name"): element for element in elements.findall("element")}
    if len(source_elements) != len(elements.findall("element")):
        raise ValueError("The source BRD contains duplicate element names.")
    missing = sorted(set(placements) - set(source_elements))
    if missing:
        raise ValueError("Optimized components are missing from the source BRD: " + ", ".join(missing[:20]))

    for name, state in placements.items():
        if len(state) < 4:
            raise ValueError(f"Placement for {name} must contain X, Y, rotation, and mirror state.")
        x, y, angle, mirror = state[:4]
        element = source_elements[name]
        element.set("x", f"{float(x):.6f}".rstrip("0").rstrip("."))
        element.set("y", f"{float(y):.6f}".rstrip("0").rstrip("."))
        element.set("rot", _rotation_token(angle, bool(mirror), element.get("rot", "R0")))

    brd_payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if doctype:
        declaration_end = brd_payload.find(b"?>")
        if declaration_end >= 0:
            brd_payload = brd_payload[:declaration_end + 2] + b"\n" + doctype + brd_payload[declaration_end + 2:]

    output_brd.parent.mkdir(parents=True, exist_ok=True)
    output_sch.parent.mkdir(parents=True, exist_ok=True)
    temp_paths = []
    try:
        with tempfile.NamedTemporaryFile("wb", dir=output_brd.parent, suffix=".brd.tmp", delete=False) as handle:
            handle.write(brd_payload)
            temp_brd = Path(handle.name)
            temp_paths.append(temp_brd)
        with tempfile.NamedTemporaryFile("wb", dir=output_sch.parent, suffix=".sch.tmp", delete=False) as handle:
            with source_sch.open("rb") as source:
                shutil.copyfileobj(source, handle)
            temp_sch = Path(handle.name)
            temp_paths.append(temp_sch)

        # Validate both staged XML files and the unchanged component inventory.
        check_root = ET.parse(temp_brd).getroot()
        check_elements = check_root.findall(".//board/elements/element")
        if {element.get("name") for element in check_elements} != set(source_elements):
            raise ValueError("Export validation failed: the BRD component inventory changed.")
        ET.parse(temp_sch)

        os.replace(temp_brd, output_brd)
        temp_paths.remove(temp_brd)
        os.replace(temp_sch, output_sch)
        temp_paths.remove(temp_sch)
    finally:
        for temp_path in temp_paths:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    return len(placements)
