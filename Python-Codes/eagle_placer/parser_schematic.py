import xml.etree.ElementTree as ET
import os
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Set, Optional
from dru_parser import DesignRules

@dataclass
class NetClassData:
    number: int        
    name: str          
    width: float       
    clearance: float   

@dataclass
class GateInstance:
    gate_name: str     
    sheet_index: int  
    x: float          
    y: float          
    rot: str          
    swaplevel: int = 0 

@dataclass
class PinData:
    name: str          
    swaplevel: int = 0 

@dataclass
class PartData:
    name: str                   
    deviceset: str              
    device: str                 
    library: str                
    value: str                  
    gates: Dict[str, GateInstance] = field(default_factory=dict) 
    pin_to_pad_map: Dict[str, str] = field(default_factory=dict) # "Gate.Pin" -> "Pad"
    pad_to_pin_map: Dict[str, str] = field(default_factory=dict) # "Pad" -> "Gate.Pin"
    gate_pin_definitions: Dict[str, Dict[str, PinData]] = field(default_factory=dict)
    net_by_pin: Dict[str, str] = field(default_factory=dict)

class EagleSchematicParser:
    def __init__(self, sch_path: str):
        if not os.path.exists(sch_path):
            raise FileNotFoundError(f"Schematic file not found: {sch_path}")
        self.root = ET.parse(sch_path).getroot()
        self.parts: Dict[str, PartData] = {}
        self.net_classes: Dict[int, NetClassData] = {}

    def _find_lib_data(self, library: str, deviceset: str, device: str, lib_cache: dict) -> Optional[dict]:
        """Find library data while tolerating None, empty strings, and case differences."""
        lib_l = (library or "").lower()
        dset_l = (deviceset or "").lower()
        dev_l = (device or "").lower()

        # 1. Exact match (case-insensitive)
        for (c_lib, c_dset, c_dev), data in lib_cache.items():
            if c_lib.lower() == lib_l and c_dset.lower() == dset_l and c_dev.lower() == dev_l:
                return data

        # 2. Fallback: match an empty device name
        for (c_lib, c_dset, c_dev), data in lib_cache.items():
            if c_lib.lower() == lib_l and c_dset.lower() == dset_l and c_dev == "":
                return data

        # 3. Fallback: use the only device available for this device set
        matches = [data for (c_lib, c_dset, c_dev), data in lib_cache.items() 
                   if c_lib.lower() == lib_l and c_dset.lower() == dset_l]
        if len(matches) == 1:
            return matches[0]

        return None

    def extract_schematic_data(self) -> Dict[str, PartData]:
        # 0. Net Classes
        classes_node = self.root.find(".//schematic/classes")
        if classes_node is not None:
            for cl in classes_node.findall("class"):
                num = int(cl.get("number", 0))
                name = cl.get("name", "default")
                width = DesignRules._parse_unit(cl.get("width", "0"))
                clearance = DesignRules._parse_unit(cl.get("clearance", "0"))
                if width is None or clearance is None:
                    continue
                self.net_classes[num] = NetClassData(
                    number=num, name=name, width=width, clearance=clearance
                )

        # 1. Extract parts (safely handle empty device names)
        parts_node = self.root.find(".//schematic/parts")
        if parts_node is not None:
            for part_elm in parts_node.findall("part"):
                name = part_elm.get("name")
                self.parts[name] = PartData(
                    name=name,
                    deviceset=part_elm.get("deviceset", ""),
                    device=part_elm.get("device") or "", # Prevent None values
                    library=part_elm.get("library", ""),
                    value=part_elm.get("value", "")
                )

        lib_cache = {}

        # 2. Parse schematic libraries
        for lib in self.root.findall(".//schematic/libraries/library"):
            lib_name = lib.get("name", "")
            
            symbols_pins: Dict[str, Dict[str, int]] = {}
            for sym in lib.findall(".//symbols/symbol"):
                sym_name = sym.get("name")
                symbols_pins[sym_name] = {}
                for pin in sym.findall("pin"):
                    p_name = pin.get("name")
                    p_swap = int(pin.get("swaplevel", 0))
                    symbols_pins[sym_name][p_name] = p_swap

            for dset in lib.findall(".//devicesets/deviceset"):
                dset_name = dset.get("name", "")
                
                gates_swap: Dict[str, int] = {}
                gate_to_symbol: Dict[str, str] = {}
                for gate_elm in dset.findall(".//gates/gate"):
                    g_name = gate_elm.get("name")
                    g_swap = int(gate_elm.get("swaplevel", 0))
                    gates_swap[g_name] = g_swap
                    gate_to_symbol[g_name] = gate_elm.get("symbol")

                pins_definition: Dict[str, Dict[str, PinData]] = {}
                for g_name, sym_name in gate_to_symbol.items():
                    pins_definition[g_name] = {}
                    if sym_name in symbols_pins:
                        for p_name, p_swap in symbols_pins[sym_name].items():
                            pins_definition[g_name][p_name] = PinData(name=p_name, swaplevel=p_swap)

                for dev in dset.findall(".//devices/device"):
                    dev_name = dev.get("name", "")
                    
                    connects = []
                    connects_node = dev.find("connects")
                    if connects_node is not None:
                        for conn in connects_node.findall("connect"):
                            connects.append({
                                "gate": conn.get("gate", ""),
                                "pin": conn.get("pin", ""),
                                "pad": conn.get("pad", "")
                            })

                    lib_cache[(lib_name, dset_name, dev_name)] = {
                        "gates_swap": gates_swap,
                        "pins_definition": pins_definition,
                        "connects": connects
                    }

        # 3. Associate data using intelligent fallbacks
        for part in self.parts.values():
            data = self._find_lib_data(part.library, part.deviceset, part.device, lib_cache)
            if data:
                part.gate_pin_definitions = data["pins_definition"]
                
                for conn in data["connects"]:
                    g = conn["gate"]
                    p = conn["pin"]
                    pad_str = conn["pad"]
                    full_pin = f"{g}.{p}" if g else p
                    
                    # Handle multiple pads (e.g. pad="1 2" or "P1,P2")
                    pads = pad_str.replace(",", " ").split()
                    for pad in pads:
                        part.pin_to_pad_map[full_pin] = pad
                        part.pad_to_pin_map[pad] = full_pin

        # 4. Extract schematic net membership for board/schematic consistency checks.
        sheets_node = self.root.find(".//schematic/sheets")
        if sheets_node is not None:
            for sheet in sheets_node.findall("sheet"):
                for net in sheet.findall(".//nets/net"):
                    net_name = net.get("name", "")
                    for pinref in net.findall(".//pinref"):
                        part_name = pinref.get("part", "")
                        gate_name = pinref.get("gate", "")
                        pin_name = pinref.get("pin", "")
                        part = self.parts.get(part_name)
                        if part is not None and pin_name:
                            full_pin = f"{gate_name}.{pin_name}" if gate_name else pin_name
                            part.net_by_pin[full_pin] = net_name

        # 5. Extract graphical instances and gate swap levels.
        sheets_node = self.root.find(".//schematic/sheets")
        if sheets_node is not None:
            for idx, sheet in enumerate(sheets_node.findall("sheet")):
                for inst in sheet.findall(".//instance"):
                    part_name = inst.get("part")
                    g_name = inst.get("gate")
                    if part_name in self.parts:
                        part = self.parts[part_name]
                        data = self._find_lib_data(part.library, part.deviceset, part.device, lib_cache)
                        g_swap = 0
                        if data and g_name in data["gates_swap"]:
                            g_swap = data["gates_swap"][g_name]

                        part.gates[g_name] = GateInstance(
                            gate_name=g_name,
                            sheet_index=idx + 1,
                            x=float(inst.get("x", 0)),
                            y=float(inst.get("y", 0)),
                            rot=inst.get("rot", "R0"),
                            swaplevel=g_swap
                        )
                        
        return self.parts