"""Parse EAGLE design rules and net classes."""

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Optional


class DesignRules:
    """Design-rule values normalized to millimeters."""

    def __init__(self):
        self.clearance_comp_to_comp: float = 0.25
        self.clearance_board_edge: float = 0.50
        self.clearance_track_to_track: float = 0.15
        self.clearance_component_to_hole: float = 0.25
        self.net_classes: Dict[int, dict] = {}
        self.source_type: str = "BRD_EMBEDDED"
        self.last_error: str = ""

    def parse_from_brd_xml(self, board_root: ET.Element) -> None:
        """Load design rules and net classes embedded in an EAGLE board XML tree."""
        board_node = board_root.find(".//board")
        if board_node is None:
            board_node = board_root

        dr_node = board_node.find("designrules")
        if dr_node is not None:
            self._apply_params(dr_node.findall("param"))

        self._parse_net_classes(board_node)
        self.source_type = "BRD_EMBEDDED"

    def load_from_dru_file(self, file_path: str) -> bool:
        """Load an EAGLE XML .dru file, with support for legacy key=value files."""
        self.last_error = ""
        try:
            text = Path(file_path).read_text(encoding="utf-8-sig", errors="replace")
        except OSError as exc:
            self.last_error = str(exc)
            return False

        params = []
        try:
            root = ET.fromstring(text)
            params = root.findall(".//param")
            if root.tag.lower() == "param":
                params = [root]
        except ET.ParseError:
            # Retain compatibility with simple legacy configuration files.
            for line_number, raw_line in enumerate(text.splitlines(), start=1):
                line = raw_line.strip()
                if not line or line.startswith(("#", ";")) or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                params.append(_ParamProxy(key.strip(), value.strip(), line_number))

        if not params:
            self.last_error = "No design-rule parameters were found in the selected file."
            return False

        applied = self._apply_params(params)
        if applied == 0:
            self.last_error = "The file contains no supported design-rule parameters."
            return False
        self.source_type = "FILE_DRU"
        return True

    def load_from_manual_inputs(self, comp_c: float, edge_c: float, track_c: float) -> None:
        """Apply non-negative clearance values entered in the GUI."""
        self.clearance_comp_to_comp = max(0.0, float(comp_c))
        self.clearance_board_edge = max(0.0, float(edge_c))
        self.clearance_track_to_track = max(0.0, float(track_c))
        self.source_type = "MANUAL"

    def _apply_params(self, params) -> int:
        """Apply supported EAGLE parameters and return the number of values applied."""
        component_clearances = []
        applied = 0
        for param in params:
            name = param.get("name", "")
            value = param.get("value", "")
            parsed = self._parse_unit(value)
            if parsed is None or parsed < 0:
                continue

            if name in ("mdSmdSmd", "mdPadPad", "mdWirePad", "mdSmdPad", "mdSmdVia", "mdPadVia"):
                if parsed > 0:
                    component_clearances.append(parsed)
                    applied += 1
            elif name == "mdCopperDimension":
                self.clearance_board_edge = parsed
                applied += 1
            elif name in ("mdWireWire", "mdWireVia", "mdViaVia"):
                if parsed > 0:
                    self.clearance_track_to_track = parsed
                    applied += 1
            elif name in ("mdDrill", "mdDrillStop"):
                if parsed > 0:
                    self.clearance_component_to_hole = parsed
                    applied += 1

        if component_clearances:
            self.clearance_comp_to_comp = max(component_clearances)
        return applied

    def _parse_net_classes(self, board_node: ET.Element) -> None:
        """Extract board net classes, preserving class zero as the default."""
        self.net_classes = {
            0: {
                "name": "default",
                "clearance": self.clearance_track_to_track,
                "width": 0.0,
            }
        }
        classes_node = board_node.find("classes")
        if classes_node is None:
            return

        for elem in classes_node.findall("class"):
            try:
                number = int(elem.get("number", "0"))
                name = elem.get("name", f"class_{number}")
                width = self._parse_unit(elem.get("width", "0 mm"))
                clearance = self._parse_unit(elem.get("clearance", "0 mm"))
                if width is None or clearance is None:
                    continue
                self.net_classes[number] = {
                    "name": name,
                    "width": width,
                    "clearance": max(clearance, self.clearance_track_to_track),
                }
            except (TypeError, ValueError):
                continue

    @staticmethod
    def _parse_unit(value: str) -> Optional[float]:
        """Convert a numeric value with an optional EAGLE unit suffix to millimeters."""
        if value is None:
            return None
        match = re.fullmatch(
            r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(mm|mil|inch|in)?\s*",
            str(value),
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        number = float(match.group(1))
        unit = (match.group(2) or "mm").lower()
        if unit == "mil":
            return number * 0.0254
        if unit in ("inch", "in"):
            return number * 25.4
        return number


class _ParamProxy:
    """Small adapter that exposes key=value entries like XML param elements."""

    def __init__(self, name: str, value: str, line_number: int):
        self._name = name
        self._value = value
        self.line_number = line_number

    def get(self, key: str, default=None):
        if key == "name":
            return self._name
        if key == "value":
            return self._value
        return default
