# geometry.py
import math
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Any, Optional

@dataclass
class Segment:
    p1: Tuple[float, float]
    p2: Tuple[float, float]
    curve: float = 0.0

@dataclass
class ViaData:
    x: float
    y: float
    drill: float
    diameter: float
    signal_name: str

@dataclass
class TrackSegment:
    """A routed copper segment extracted from an Eagle signal wire."""
    p1: Tuple[float, float]
    p2: Tuple[float, float]
    width: float
    layer: int
    curve: float = 0.0
    signal_name: str = ""

@dataclass
class NetConnection:
    element: str  # Component name (e.g. "R1")
    pad: str      # Pin/pad name (e.g. "1", "A")
    x: float      # Absolute X coordinate (mm)
    y: float      # Absolute Y coordinate (mm)

@dataclass
class NetSignal:
    name: str
    connections: List[NetConnection] = field(default_factory=list)

@dataclass
class ComponentData:
    name: str          
    library: str       
    package: str       
    x: float           
    y: float           
    rot: float         
    mirror: bool       
    width: float       
    height: float      
    offset_x: float    
    offset_y: float    
    locked: bool = False
    is_tht: bool = False  # True when the package has only through-hole pads (THT)
    is_smd: bool = False  # True only when the package has SMD pads and no through-hole pads
    
    # Fields synchronized from the schematic (.SCH)
    value: str = ""
    deviceset: str = ""
    swap_enabled: bool = True
    pin_to_pad_map: Dict[str, str] = field(default_factory=dict)         # "Gate.Pin" -> "Pad"
    pad_to_pin_map: Dict[str, str] = field(default_factory=dict)         # "Pad" -> "Gate.Pin"
    gate_pin_definitions: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    gates: Dict[str, Any] = field(default_factory=dict)
    package_outlines: List[List[Tuple[float, float]]] = field(default_factory=list)

@dataclass
class BoardData:
    # Board outline and cutout polygons only; component/package geometry is stored separately.
    boundary_polygons: List[List[Tuple[float, float]]] = field(default_factory=list)
    component_outlines: Dict[str, List[List[Tuple[float, float]]]] = field(default_factory=dict)
    packages: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    keepouts_top: List[List[Tuple[float, float]]] = field(default_factory=list)
    keepouts_bottom: List[List[Tuple[float, float]]] = field(default_factory=list)
    restrict_top: List[List[Tuple[float, float]]] = field(default_factory=list)
    restrict_bottom: List[List[Tuple[float, float]]] = field(default_factory=list)
    grid_spacing_mm: Optional[float] = None
    display_unit: str = "mm"
    holes: List[Tuple[float, float, float]] = field(default_factory=list)
    isolated_vias: List[ViaData] = field(default_factory=list)
    tracks: List[TrackSegment] = field(default_factory=list)
    components: Dict[str, ComponentData] = field(default_factory=dict)
    signals: Dict[str, NetSignal] = field(default_factory=dict)
    net_classes: Dict[int, Any] = field(default_factory=dict)
    passive_equivalence_groups: Dict[str, List[str]] = field(default_factory=dict)
    design_rules: Optional[Any] = None
    # Board-only objects are fixed obstacles when a usable schematic is available.
    orphan_components: set = field(default_factory=set)
    schematic_only_components: set = field(default_factory=set)

    def merge_schematic_data(self, schematic_parts: Dict[str, Any]):
        """Merge data extracted from the .SCH file into board components."""
        for comp_name, comp in self.components.items():
            if comp_name in schematic_parts:
                part = schematic_parts[comp_name]
                comp.value = getattr(part, 'value', '')  # Copy the value (e.g. 10k, 100nF)
                comp.pin_to_pad_map = getattr(part, 'pin_to_pad_map', {})
                comp.pad_to_pin_map = getattr(part, 'pad_to_pin_map', {})
                comp.gate_pin_definitions = getattr(part, 'gate_pin_definitions', {})
                comp.gates = getattr(part, 'gates', {})
                comp.deviceset = getattr(part, 'deviceset', "")

    def build_passive_equivalence_groups(self):
        """Identify identical passive components (R, C, L) by library, package, and value."""
        temp_groups = {}
        
        for name, comp in self.components.items():
            if comp.locked:
                continue  # Skip locked components
            
            # Identify passives from their name prefix (R, C, L)
            prefix = "".join([c for c in name if c.isalpha()]).upper()
            if prefix not in ["R", "C", "L"] or not comp.value:
                continue

            # Unique key: library + footprint + value
            key = (comp.library.lower(), comp.package.lower(), comp.value.strip().lower())
            temp_groups.setdefault(key, []).append(name)

        # Keep only groups with at least two interchangeable components
        self.passive_equivalence_groups = {}
        idx = 1
        for (lib, pkg, val), members in temp_groups.items():
            if len(members) >= 2:
                grp_label = f"{prefix_type(members[0])} {val} ({pkg})"
                self.passive_equivalence_groups[grp_label] = members
                idx += 1

def prefix_type(name: str) -> str:
    p = "".join([c for c in name if c.isalpha()]).upper()
    return "Resistors" if p == "R" else ("Capacitors" if p == "C" else "Inductors")

def interpolate_arc(x1: float, y1: float, x2: float, y2: float, curve_deg: float) -> List[Tuple[float, float]]:
    if abs(curve_deg) < 0.01:
        return [(x1, y1), (x2, y2)]

    theta = math.radians(curve_deg)
    abs_theta = abs(theta)
    
    dx = x2 - x1
    dy = y2 - y1
    d = math.hypot(dx, dy)
    if d < 1e-6:
        return [(x1, y1)]

    r = d / (2.0 * math.sin(abs_theta / 2.0))
    h = math.sqrt(max(0.0, r**2 - (d / 2.0)**2))
    
    mx = (x1 + x2) / 2.0
    my = (y1 + y2) / 2.0
    
    nx = -dy / d
    ny = dx / d
    
    if theta > 0:
        cx = mx + h * nx
        cy = my + h * ny
    else:
        cx = mx - h * nx
        cy = my - h * ny

    a1 = math.atan2(y1 - cy, x1 - cx)
    a2 = a1 + theta
        
    num_steps = max(12, int(abs(curve_deg) / 2.5))
    
    points = []
    for i in range(num_steps + 1):
        t = i / num_steps
        angle = a1 + (a2 - a1) * t
        px_arc = cx + r * math.cos(angle)
        py_arc = cy + r * math.sin(angle)
        points.append((px_arc, py_arc))
        
    return points