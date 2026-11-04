# parser.py
import xml.etree.ElementTree as ET
import os
import math
from typing import List, Tuple, Dict
from geometry import Segment, TrackSegment, ViaData, BoardData, ComponentData, NetConnection, NetSignal, interpolate_arc
from dru_parser import DesignRules

class EagleBoardParser:
    def __init__(self, brd_path: str):
        if not os.path.exists(brd_path):
            raise FileNotFoundError(f"Board file not found: {brd_path}")
        self.brd_path = brd_path
        
        try:
            with open(brd_path, "r", encoding="utf-8-sig") as f:
                xml_content = f.read()
            self.root = ET.fromstring(xml_content)
            if self.root.find(".//board") is None:
                raise ValueError("The XML file does not contain an Eagle board element.")
        except Exception:
            try:
                with open(brd_path, "r", encoding="latin-1") as f:
                    xml_content = f.read()
                self.root = ET.fromstring(xml_content)
                if self.root.find(".//board") is None:
                    raise ValueError("The XML file does not contain an Eagle board element.")
            except Exception as e:
                raise RuntimeError(f"Unable to decode or validate Eagle board XML: {e}")
        self.design_rules = DesignRules()
        
        
    def parse_design_rules(self) -> DesignRules:
        """Extract design rules and net classes defined in the .brd XML."""
        self.design_rules.parse_from_brd_xml(self.root)
        return self.design_rules
        
    def _reconstruct_closed_loops(self, segments: List[Segment]) -> List[List[Tuple[float, float]]]:
        loops = []
        remaining = list(segments)
        tolerance = 0.05

        while remaining:
            curr_seg = remaining.pop(0)
            loop_points = []
            
            p_start = curr_seg.p1
            p_end = curr_seg.p2
            
            pts = interpolate_arc(p_start[0], p_start[1], p_end[0], p_end[1], curr_seg.curve)
            loop_points.extend(pts[:-1])
            last_pt = p_end

            while True:
                found_next = False
                for i, seg in enumerate(remaining):
                    if math.hypot(seg.p1[0] - last_pt[0], seg.p1[1] - last_pt[1]) < tolerance:
                        pts = interpolate_arc(seg.p1[0], seg.p1[1], seg.p2[0], seg.p2[1], seg.curve)
                        loop_points.extend(pts[:-1])
                        last_pt = seg.p2
                        remaining.pop(i)
                        found_next = True
                        break
                    elif math.hypot(seg.p2[0] - last_pt[0], seg.p2[1] - last_pt[1]) < tolerance:
                        pts = interpolate_arc(seg.p2[0], seg.p2[1], seg.p1[0], seg.p1[1], -seg.curve)
                        loop_points.extend(pts[:-1])
                        last_pt = seg.p1
                        remaining.pop(i)
                        found_next = True
                        break
                
                if not found_next:
                    if math.hypot(last_pt[0] - p_start[0], last_pt[1] - p_start[1]) < tolerance:
                        loop_points.append(p_start)
                    else:
                        loop_points.append(last_pt)
                    loops.append(loop_points)
                    break
                    
        return loops

    def _parse_polygon_vertices(self, poly_node: ET.Element) -> List[Tuple[float, float]]:
        vertices = poly_node.findall("vertex")
        if len(vertices) < 2:
            return []

        pts = []
        for i in range(len(vertices)):
            v_curr = vertices[i]
            v_next = vertices[(i + 1) % len(vertices)]
            
            x1, y1 = float(v_curr.get("x")), float(v_curr.get("y"))
            x2, y2 = float(v_next.get("x")), float(v_next.get("y"))
            curve_val = float(v_curr.get("curve", 0.0))
            
            if abs(curve_val) > 0.01:
                arc_pts = interpolate_arc(x1, y1, x2, y2, curve_val)
                pts.extend(arc_pts[:-1])
            else:
                pts.append((x1, y1))
                
        if pts:
            pts.append(pts[0])
        return pts

    def _parse_rect(self, rect_node: ET.Element) -> List[Tuple[float, float]]:
        x1 = float(rect_node.get("x1", 0))
        y1 = float(rect_node.get("y1", 0))
        x2 = float(rect_node.get("x2", 0))
        y2 = float(rect_node.get("y2", 0))
        
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        
        w_half = abs(x2 - x1) / 2.0
        h_half = abs(y2 - y1) / 2.0
        
        local_pts = [
            (-w_half, -h_half),
            (w_half, -h_half),
            (w_half, h_half),
            (-w_half, h_half)
        ]
        
        rot_str = rect_node.get("rot", "")
        angle_deg = 0.0
        if rot_str:
            num_part = "".join([c for c in rot_str if c.isdigit() or c == '.'])
            if num_part:
                angle_deg = float(num_part)
                
        rad = math.radians(angle_deg)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        
        rotated_pts = []
        for lx, ly in local_pts:
            rx = cx + (lx * cos_a - ly * sin_a)
            ry = cy + (lx * sin_a + ly * cos_a)
            rotated_pts.append((rx, ry))
            
        rotated_pts.append(rotated_pts[0])
        return rotated_pts

    def _apply_transform(self, x: float, y: float, tx: float, ty: float, rot_deg: float, mirror: bool) -> Tuple[float, float]:
        """Rotate, mirror, and translate a package-local point into board coordinates."""
        if mirror:
            x = -x  # Mirror across the component-local Y axis
        
        rad = math.radians(rot_deg)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        
        rx = tx + (x * cos_a - y * sin_a)
        ry = ty + (x * sin_a + y * cos_a)
        return rx, ry

    def _parse_libraries_packages(self) -> Dict[str, Dict[str, dict]]:
        libs_data = {}
        libraries_node = self.root.find(".//board/libraries")
        if libraries_node is None:
            return libs_data

        for lib in libraries_node.findall("library"):
            lib_name = lib.get("name", "")
            libs_data[lib_name] = {}
            packages_node = lib.find("packages")
            if packages_node is None:
                continue

            for pkg in packages_node.findall("package"):
                pkg_name = pkg.get("name", "")
                
                pts_x = []
                pts_y = []
                
                # Determine whether the package contains SMD elements or only through-hole pads
                has_smd = False
                has_pad = False

                # Local pad-coordinate map
                pads_map = {}

                # Store package-internal geometry from layer 20
                layer_20_elements = []

                # Extract wires (lines/arcs) on package layer 20
                pkg_boundary_wires = []
                for wire in pkg.findall("wire"):
                    wx1, wy1 = float(wire.get("x1", 0)), float(wire.get("y1", 0))
                    wx2, wy2 = float(wire.get("x2", 0)), float(wire.get("y2", 0))
                    layer = int(wire.get("layer", 0))
                    
                    pts_x.extend([wx1, wx2])
                    pts_y.extend([wy1, wy2])

                    if layer == 20:
                        curve_val = float(wire.get("curve", 0.0))
                        pkg_boundary_wires.append(Segment(p1=(wx1, wy1), p2=(wx2, wy2), curve=curve_val))

                # Reconstruct connected wires on layer 20 as closed local loops
                if pkg_boundary_wires:
                    loops = self._reconstruct_closed_loops(pkg_boundary_wires)
                    for loop in loops:
                        layer_20_elements.append({"type": "polygon", "points": loop})

                # Extract circles on package layer 20 (e.g. central holes in toroidal components)
                for circle in pkg.findall("circle"):
                    layer = int(circle.get("layer", 0))
                    cx, cy = float(circle.get("x", 0)), float(circle.get("y", 0))
                    radius = float(circle.get("radius", 0))
                    
                    if layer == 20:
                        num_points = 32
                        circle_pts = [
                            (cx + radius * math.cos(2 * math.pi * i / num_points),
                             cy + radius * math.sin(2 * math.pi * i / num_points))
                            for i in range(num_points)
                        ]
                        circle_pts.append(circle_pts[0])
                        layer_20_elements.append({"type": "polygon", "points": circle_pts})

                # Extract rectangles on package layer 20
                for rect in pkg.findall("rectangle"):
                    layer = int(rect.get("layer", 0))
                    if layer == 20:
                        rect_pts = self._parse_rect(rect)
                        layer_20_elements.append({"type": "polygon", "points": rect_pts})

                # Extract polygons on package layer 20
                for poly in pkg.findall("polygon"):
                    layer = int(poly.get("layer", 0))
                    if layer == 20:
                        poly_pts = self._parse_polygon_vertices(poly)
                        if len(poly_pts) >= 3:
                            layer_20_elements.append({"type": "polygon", "points": poly_pts})

                # SMDs and pads used to calculate the package bounds
                for smd in pkg.findall("smd"):
                    has_smd = True
                    smd_name = smd.get("name", "")  # Get the pin name (e.g. "1", "2", "GND")
                    sx, sy = float(smd.get("x", 0)), float(smd.get("y", 0))
                    dx, dy = float(smd.get("dx", 0)), float(smd.get("dy", 0))
                    pts_x.extend([sx - dx/2, sx + dx/2])
                    pts_y.extend([sy - dy/2, sy + dy/2])
                    
                    # Store the SMD pad coordinates
                    if smd_name:
                        pads_map[smd_name] = (sx, sy)

                for pad in pkg.findall("pad"):
                    has_pad = True
                    pad_name = pad.get("name", "")  # Get the pin name
                    px, py = float(pad.get("x", 0)), float(pad.get("y", 0))
                    drill = float(pad.get("drill", 0))
                    diam_str = pad.get("diameter")
                    diam = float(diam_str) if diam_str else drill * 1.8
                    pts_x.extend([px - diam/2, px + diam/2])
                    pts_y.extend([py - diam/2, py + diam/2])
                    
                    # Store the through-hole pad coordinates
                    if pad_name:
                        pads_map[pad_name] = (px, py)

                if not pts_x or not pts_y:
                    width = 2.0
                    height = 2.0
                    offset_x = 0.0
                    offset_y = 0.0
                else:
                    min_x, max_x = min(pts_x), max(pts_x)
                    min_y, max_y = min(pts_y), max(pts_y)
                    
                    width = max_x - min_x
                    height = max_y - min_y
                    offset_x = (min_x + max_x) / 2.0
                    offset_y = (min_y + max_y) / 2.0

                is_tht = has_pad and not has_smd
                is_smd = has_smd and not has_pad

                libs_data[lib_name][pkg_name] = {
                    "width": width,
                    "height": height,
                    "offset_x": offset_x,
                    "offset_y": offset_y,
                    "is_tht": is_tht,
                    "is_smd": is_smd,
                    "layer_20_elements": layer_20_elements,
                    "pads": pads_map  # Fixed package-local coordinate map for each pad
                }
        return libs_data

    def extract_data(self) -> BoardData:
        self.parse_design_rules()
        
        board = BoardData()
        
        board.design_rules = self.design_rules
        board.net_classes = dict(self.design_rules.net_classes)

        grid_node = self.root.find(".//grid")
        if grid_node is not None:
            try:
                grid_distance = float(grid_node.get("distance", "0"))
                grid_unit = (grid_node.get("unitdist") or grid_node.get("unit") or "mm").lower()
                display_unit = (grid_node.get("unit") or grid_unit or "mm").lower()
                unit_aliases = {"inch": "in", "inches": "in", "mic": "um", "micron": "um", "microns": "um"}
                display_unit = unit_aliases.get(display_unit, display_unit)
                board.display_unit = display_unit if display_unit in {"mm", "mil", "in", "um"} else "mm"
                unit_to_mm = {"mm": 1.0, "mil": 0.0254, "inch": 25.4, "in": 25.4, "mic": 0.001, "um": 0.001}
                spacing = grid_distance * unit_to_mm.get(grid_unit, 1.0)
                if math.isfinite(spacing) and spacing > 0:
                    board.grid_spacing_mm = spacing
            except (TypeError, ValueError):
                board.grid_spacing_mm = None

        # 1. Board outline, keepouts, restrictions, and holes
        plain_node = self.root.find(".//board/plain")
        if plain_node is not None:
            keepout_39_wires = []
            keepout_40_wires = []
            restrict_41_wires = []
            restrict_42_wires = []
            boundary_wires = []
            
            for wire in plain_node.findall("wire"):
                layer = int(wire.get("layer", 0))
                x1, y1 = float(wire.get("x1")), float(wire.get("y1"))
                x2, y2 = float(wire.get("x2")), float(wire.get("y2"))
                curve_val = float(wire.get("curve", 0.0))
                seg = Segment(p1=(x1, y1), p2=(x2, y2), curve=curve_val)
                
                if layer == 20:
                    boundary_wires.append(seg)
                elif layer == 39:
                    keepout_39_wires.append(seg)
                elif layer == 40:
                    keepout_40_wires.append(seg)
                elif layer == 41:
                    restrict_41_wires.append(seg)
                elif layer == 42:
                    restrict_42_wires.append(seg)

            if boundary_wires:
                board.boundary_polygons = self._reconstruct_closed_loops(boundary_wires)
            if keepout_39_wires:
                board.keepouts_top.extend(self._reconstruct_closed_loops(keepout_39_wires))
            if keepout_40_wires:
                board.keepouts_bottom.extend(self._reconstruct_closed_loops(keepout_40_wires))
            if restrict_41_wires:
                board.restrict_top.extend(self._reconstruct_closed_loops(restrict_41_wires))
            if restrict_42_wires:
                board.restrict_bottom.extend(self._reconstruct_closed_loops(restrict_42_wires))

            for circle in plain_node.findall("circle"):
                layer = int(circle.get("layer", 0))
                if layer in (20, 39, 40, 41, 42):
                    cx, cy = float(circle.get("x")), float(circle.get("y"))
                    radius = float(circle.get("radius"))
                    num_points = 64
                    circle_pts = [
                        (cx + radius * math.cos(2 * math.pi * i / num_points),
                         cy + radius * math.sin(2 * math.pi * i / num_points))
                        for i in range(num_points)
                    ]
                    circle_pts.append(circle_pts[0])
                    
                    if layer == 20:
                        board.boundary_polygons.append(circle_pts)
                    elif layer == 39:
                        board.keepouts_top.append(circle_pts)
                    elif layer == 40:
                        board.keepouts_bottom.append(circle_pts)
                    elif layer == 41:
                        board.restrict_top.append(circle_pts)
                    elif layer == 42:
                        board.restrict_bottom.append(circle_pts)

            for poly in plain_node.findall("polygon"):
                layer = int(poly.get("layer", 0))
                if layer in (20, 39, 40, 41, 42):
                    pts = self._parse_polygon_vertices(poly)
                    if len(pts) >= 3:
                        if layer == 20:
                            board.boundary_polygons.append(pts)
                        elif layer == 39:
                            board.keepouts_top.append(pts)
                        elif layer == 40:
                            board.keepouts_bottom.append(pts)
                        elif layer == 41:
                            board.restrict_top.append(pts)
                        else:
                            board.restrict_bottom.append(pts)

            for rect in plain_node.findall("rectangle"):
                layer = int(rect.get("layer", 0))
                if layer in (20, 39, 40, 41, 42):
                    pts = self._parse_rect(rect)
                    if len(pts) >= 3:
                        if layer == 20:
                            board.boundary_polygons.append(pts)
                        elif layer == 39:
                            board.keepouts_top.append(pts)
                        elif layer == 40:
                            board.keepouts_bottom.append(pts)
                        elif layer == 41:
                            board.restrict_top.append(pts)
                        else:
                            board.restrict_bottom.append(pts)

            for hole in plain_node.findall("hole"):
                x, y = float(hole.get("x")), float(hole.get("y"))
                drill = float(hole.get("drill", 0))
                board.holes.append((x, y, drill))
                if drill > 0:
                    num_points = 48
                    hole_loop = [
                        (x + (drill / 2.0) * math.cos(2 * math.pi * i / num_points),
                         y + (drill / 2.0) * math.sin(2 * math.pi * i / num_points))
                        for i in range(num_points)
                    ]
                    hole_loop.append(hole_loop[0])
                    board.boundary_polygons.append(hole_loop)

        # 2. Physical components and internal component holes
        packages_geom = self._parse_libraries_packages()
        board.packages = packages_geom
        elements_node = self.root.find(".//board/elements")
        if elements_node is not None:
            for el in elements_node.findall("element"):
                name = el.get("name", "")
                lib_name = el.get("library", "")
                pkg_name = el.get("package", "")
                x = float(el.get("x", 0))
                y = float(el.get("y", 0))
                
                is_locked = el.get("locked", "no") == "yes"
                rot_str = el.get("rot", "R0")
                mirror = "M" in rot_str
                
                angle_deg = 0.0
                num_part = "".join([c for c in rot_str if c.isdigit() or c == '.'])
                if num_part:
                    angle_deg = float(num_part)

                width, height, offset_x, offset_y, is_tht, is_smd = 3.0, 3.0, 0.0, 0.0, False, False
                pkg_layer_20_elms = []

                if lib_name in packages_geom and pkg_name in packages_geom[lib_name]:
                    geom = packages_geom[lib_name][pkg_name]
                    width = geom["width"]
                    height = geom["height"]
                    offset_x = geom["offset_x"]
                    offset_y = geom["offset_y"]
                    is_tht = geom.get("is_tht", False)
                    is_smd = geom.get("is_smd", False)
                    pkg_layer_20_elms = geom.get("layer_20_elements", [])

                # Keep package outlines separate from the actual PCB outline.
                # Mixing these polygons into boundary_polygons causes the GUI to
                # interpret component bodies as board cutouts.
                component_outlines = []
                for geom_item in pkg_layer_20_elms:
                    if geom_item["type"] == "polygon":
                        transformed_loop = []
                        for px, py in geom_item["points"]:
                            tx, ty = self._apply_transform(px, py, x, y, angle_deg, mirror)
                            transformed_loop.append((tx, ty))
                        if len(transformed_loop) >= 3:
                            component_outlines.append(transformed_loop)
                if component_outlines:
                    board.component_outlines[name] = component_outlines

                board.components[name] = ComponentData(
                    name=name,
                    library=lib_name,
                    package=pkg_name,
                    x=x,
                    y=y,
                    rot=angle_deg,
                    mirror=mirror,
                    width=width,
                    height=height,
                    offset_x=offset_x,
                    offset_y=offset_y,
                    locked=is_locked,
                    is_tht=is_tht,
                    is_smd=is_smd,
                    package_outlines=[
                        list(item["points"])
                        for item in pkg_layer_20_elms
                        if item.get("type") == "polygon" and len(item.get("points", [])) >= 3
                    ]
                )

        # 3. Signals and vias (build net connections)
        signals_node = self.root.find(".//board/signals")
        if signals_node is not None:
            for signal in signals_node.findall("signal"):
                sig_name = signal.get("name", "UNNAMED")
                net_connections = []

                # Preserve routed copper even when the board has no component references.
                # Zero-width wires are commonly present as non-renderable helper geometry.
                for wire in signal.findall("wire"):
                    width = float(wire.get("width", 0.0))
                    if width <= 0.0:
                        continue
                    board.tracks.append(TrackSegment(
                        p1=(float(wire.get("x1", 0.0)), float(wire.get("y1", 0.0))),
                        p2=(float(wire.get("x2", 0.0)), float(wire.get("y2", 0.0))),
                        width=width,
                        layer=int(wire.get("layer", 0)),
                        curve=float(wire.get("curve", 0.0)),
                        signal_name=sig_name,
                    ))

                # Map physical pad references to absolute board coordinates.
                contacts = signal.findall("contactref")
                for contact in contacts:
                    el_name = contact.get("element", "")
                    pad_name = contact.get("pad", "")
                    
                    comp = board.components.get(el_name)
                    
                    # Correction logic: apply the actual pin rotation and translation
                    if comp and comp.library in packages_geom and comp.package in packages_geom[comp.library]:
                        pkg_pads = packages_geom[comp.library][comp.package].get("pads", {})
                        pad_key = str(pad_name).strip().upper()
                        
                        # Find the pad (case-insensitive) in the package-local map
                        matched_pad = next((pkg_pads[k] for k in pkg_pads if k.upper() == pad_key), None)
                        
                        if matched_pad:
                            lx, ly = matched_pad
                            # Apply the same geometric transform used by the parser
                            px, py = self._apply_transform(lx, ly, comp.x, comp.y, comp.rot, comp.mirror)
                        else:
                            # Fall back to the component center if the pad is missing from the package
                            px, py = comp.x, comp.y
                    else:
                        # Fall back if the component or library is not defined
                        px, py = (comp.x, comp.y) if comp else (0.0, 0.0)
                    
                    net_connections.append(NetConnection(
                        element=el_name,
                        pad=pad_name,
                        x=px,
                        y=py
                    ))
                
                if net_connections:
                    board.signals[sig_name] = NetSignal(
                        name=sig_name,
                        connections=net_connections
                    )

                # Preserve vias for display regardless of whether the signal has pad references.
                for via in signal.findall("via"):
                    vx = float(via.get("x", 0.0))
                    vy = float(via.get("y", 0.0))
                    v_drill = float(via.get("drill", 0.0))
                    v_diam_str = via.get("diameter")
                    v_diam = float(v_diam_str) if v_diam_str else v_drill * 1.8
                    board.isolated_vias.append(ViaData(
                        x=vx, y=vy, drill=v_drill, diameter=v_diam,
                        signal_name=sig_name
                    ))

        return board