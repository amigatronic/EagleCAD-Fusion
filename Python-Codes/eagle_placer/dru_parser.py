import xml.etree.ElementTree as ET
from typing import Dict, Optional

class DesignRules:
    def __init__(self):
        # Valori di fallback di sicurezza (in mm)
        self.clearance_comp_to_comp: float = 0.25
        self.clearance_board_edge: float = 0.50
        self.clearance_track_to_track: float = 0.15
        
        self.net_classes: Dict[int, dict] = {}
        self.source_type: str = "BRD_EMBEDDED"  # BRD_EMBEDDED, FILE_DRU, MANUAL

    def parse_from_brd_xml(self, board_root: ET.Element):
        # 1. Estrae le regole incorporate nel tag designrules del .brd
        dr_node = board_root.find("drawing/board/designrules")
        if dr_node is None:
            return

        for param in dr_node.findall("param"):
            name = param.get("name", "")
            val = param.get("value", "")

            if name in ("mdSmdSmd", "mdPadPad", "mdWirePad"):
                parsed = self._parse_unit(val)
                if parsed > 0:
                    self.clearance_comp_to_comp = parsed
            elif name == "mdCopperDimension":
                self.clearance_board_edge = self._parse_unit(val)
            elif name == "mdWireWire":
                self.clearance_track_to_track = self._parse_unit(val)

        # Estrae anche le Net Classes presenti nello stesso XML
        self._parse_net_classes(board_root)

    def load_from_dru_file(self, file_path: str) -> bool:
        # 2. Sovrascrive le regole leggendo un file .dru esterno
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, val = line.split("=", 1)
                    key, val = key.strip(), val.strip()

                    if key in ("mdSmdSmd", "mdPadPad", "mdWirePad"):
                        parsed = self._parse_unit(val)
                        if parsed > 0:
                            self.clearance_comp_to_comp = parsed
                    elif key == "mdCopperDimension":
                        self.clearance_board_edge = self._parse_unit(val)
                    elif key == "mdWireWire":
                        self.clearance_track_to_track = self._parse_unit(val)

            self.source_type = "FILE_DRU"
            return True
        except Exception as e:
            print(f"[DRU Error] {e}")
            return False

    def load_from_manual_inputs(self, comp_c: float, edge_c: float, track_c: float):
        # 3. Sovrascrive le regole usando i campi manuali della GUI
        self.clearance_comp_to_comp = max(0.0, comp_c)
        self.clearance_board_edge = max(0.0, edge_c)
        self.clearance_track_to_track = max(0.0, track_c)
        self.source_type = "MANUAL"

    def _parse_net_classes(self, board_root: ET.Element):
        # Estrae le Net Classes dall'XML classes
        self.net_classes.clear()
        self.net_classes[0] = {
            "name": "default",
            "clearance": self.clearance_track_to_track,
            "width": 0.0
        }
        
        classes_node = board_root.find("drawing/board/classes")
        if classes_node is None:
            return

        for elem in classes_node.findall("class"):
            try:
                c_num = int(elem.get("number", 0))
                c_name = elem.get("name", f"class_{c_num}")
                c_width = self._parse_unit(elem.get("width", "0 mm"))
                c_clear = self._parse_unit(elem.get("clearance", "0 mm"))
                
                self.net_classes[c_num] = {
                    "name": c_name,
                    "width": c_width,
                    "clearance": max(c_clear, self.clearance_track_to_track)
                }
            except ValueError:
                continue

    def _parse_unit(self, val_str: str) -> float:
        val_str = val_str.lower().strip()
        if val_str.endswith("mil"):
            return float(val_str.replace("mil", "")) * 0.0254
        elif val_str.endswith("mm"):
            return float(val_str.replace("mm", ""))
        elif val_str.endswith("inch"):
            return float(val_str.replace("inch", "")) * 25.4
        elif val_str.endswith("in"):
            return float(val_str.replace("in", "")) * 25.4
        try:
            return float(val_str)
        except ValueError:
            return 0.0