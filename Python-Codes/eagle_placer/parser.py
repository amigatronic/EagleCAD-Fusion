# parser.py
import xml.etree.ElementTree as ET
import os
import math
from typing import List, Tuple, Dict
from geometry import Segment, ViaData, BoardData, ComponentData, NetConnection, NetSignal, interpolate_arc
from dru_parser import DesignRules

class EagleBoardParser:
    def __init__(self, brd_path: str):
        if not os.path.exists(brd_path):
            raise FileNotFoundError(f"Impossibile trovare il file: {brd_path}")
        self.brd_path = brd_path
        
        try:
            with open(brd_path, "r", encoding="utf-8-sig") as f:
                xml_content = f.read()
            self.root = ET.fromstring(xml_content)
        except Exception:
            try:
                with open(brd_path, "r", encoding="latin-1") as f:
                    xml_content = f.read()
                self.root = ET.fromstring(xml_content)
            except Exception as e:
                raise RuntimeError(f"Errore di decodifica XML: {e}")
        self.design_rules = DesignRules()
        
        
    def parse_design_rules(self) -> DesignRules:
        """Estrae le regole di design e le Net Classes definite nell'XML del .brd."""
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
        """Ruota, specchia e trasla un punto locale di un package nelle coordinate globali della board."""
        if mirror:
            x = -x  # Specchiamento rispetto all'asse Y locale del componente
        
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
                
                # Tracciamo se ci sono elementi SMD o solo Pad passanti
                has_smd = False
                has_pad = False

                # --- NUOVO DIZIONARIO PER I PAD LOCALI ---
                pads_map = {}

                # Salviamo le geometrie sul Layer 20 interne al package
                layer_20_elements = []

                # Estrazione wire (Linee/Archi) sul Layer 20 nel package
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

                # Se ci sono wire concatenati sul layer 20, li ricostruiamo in loop chiusi locali
                if pkg_boundary_wires:
                    loops = self._reconstruct_closed_loops(pkg_boundary_wires)
                    for loop in loops:
                        layer_20_elements.append({"type": "polygon", "points": loop})

                # Estrazione Cerchi sul Layer 20 nel package (es. fori centrali dei toroidi)
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

                # Estrazione Rettangoli sul Layer 20 nel package
                for rect in pkg.findall("rectangle"):
                    layer = int(rect.get("layer", 0))
                    if layer == 20:
                        rect_pts = self._parse_rect(rect)
                        layer_20_elements.append({"type": "polygon", "points": rect_pts})

                # Estrazione Poligoni sul Layer 20 nel package
                for poly in pkg.findall("polygon"):
                    layer = int(poly.get("layer", 0))
                    if layer == 20:
                        poly_pts = self._parse_polygon_vertices(poly)
                        if len(poly_pts) >= 3:
                            layer_20_elements.append({"type": "polygon", "points": poly_pts})

                # SMD e Pad per calcolo ingombro
                for smd in pkg.findall("smd"):
                    has_smd = True
                    smd_name = smd.get("name", "")  # Prende il nome del pin (es: "1", "2", "GND")
                    sx, sy = float(smd.get("x", 0)), float(smd.get("y", 0))
                    dx, dy = float(smd.get("dx", 0)), float(smd.get("dy", 0))
                    pts_x.extend([sx - dx/2, sx + dx/2])
                    pts_y.extend([sy - dy/2, sy + dy/2])
                    
                    # Salva le coordinate del pad smd
                    if smd_name:
                        pads_map[smd_name] = (sx, sy)

                for pad in pkg.findall("pad"):
                    has_pad = True
                    pad_name = pad.get("name", "")  # Prende il nome del pin
                    px, py = float(pad.get("x", 0)), float(pad.get("y", 0))
                    drill = float(pad.get("drill", 0))
                    diam_str = pad.get("diameter")
                    diam = float(diam_str) if diam_str else drill * 1.8
                    pts_x.extend([px - diam/2, px + diam/2])
                    pts_y.extend([py - diam/2, py + diam/2])
                    
                    # Salva le coordinate del pad passante
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

                libs_data[lib_name][pkg_name] = {
                    "width": width,
                    "height": height,
                    "offset_x": offset_x,
                    "offset_y": offset_y,
                    "is_tht": is_tht,
                    "layer_20_elements": layer_20_elements,
                    "pads": pads_map  # <--- AGGIUNTO QUI! Mappa fissa locale di ogni Pad
                }
        return libs_data

    def extract_data(self) -> BoardData:
        self.parse_design_rules()
        
        board = BoardData()
        
        board.design_rules = self.design_rules
        
        # 1. Profilo globale, Keepout, Fori
        plain_node = self.root.find(".//board/plain")
        if plain_node is not None:
            keepout_39_wires = []
            keepout_40_wires = []
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
            
            if boundary_wires:
                board.boundary_polygons = self._reconstruct_closed_loops(boundary_wires)
            if keepout_39_wires:
                board.keepouts_top.extend(self._reconstruct_closed_loops(keepout_39_wires))
            if keepout_40_wires:
                board.keepouts_bottom.extend(self._reconstruct_closed_loops(keepout_40_wires))

            for circle in plain_node.findall("circle"):
                layer = int(circle.get("layer", 0))
                if layer in (20, 39, 40):
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

            for poly in plain_node.findall("polygon"):
                layer = int(poly.get("layer", 0))
                if layer in (39, 40):
                    pts = self._parse_polygon_vertices(poly)
                    if len(pts) >= 3:
                        if layer == 39:
                            board.keepouts_top.append(pts)
                        else:
                            board.keepouts_bottom.append(pts)

            for rect in plain_node.findall("rectangle"):
                layer = int(rect.get("layer", 0))
                if layer in (39, 40):
                    pts = self._parse_rect(rect)
                    if len(pts) >= 3:
                        if layer == 39:
                            board.keepouts_top.append(pts)
                        else:
                            board.keepouts_bottom.append(pts)

            for hole in plain_node.findall("hole"):
                x, y = float(hole.get("x")), float(hole.get("y"))
                drill = float(hole.get("drill", 0))
                board.holes.append((x, y, drill))

        # 2. Componenti Fisici e Integrazione dei Fori Interni dei Componenti nel Profilo
        packages_geom = self._parse_libraries_packages()
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

                width, height, offset_x, offset_y, is_tht = 3.0, 3.0, 0.0, 0.0, False
                pkg_layer_20_elms = []

                if lib_name in packages_geom and pkg_name in packages_geom[lib_name]:
                    geom = packages_geom[lib_name][pkg_name]
                    width = geom["width"]
                    height = geom["height"]
                    offset_x = geom["offset_x"]
                    offset_y = geom["offset_y"]
                    is_tht = geom.get("is_tht", False)
                    pkg_layer_20_elms = geom.get("layer_20_elements", [])

                # Rototrasliamo le geometrie del Layer 20 del package e inseriamole nei boundary_polygons globali
                for geom_item in pkg_layer_20_elms:
                    if geom_item["type"] == "polygon":
                        transformed_loop = []
                        for px, py in geom_item["points"]:
                            tx, ty = self._apply_transform(px, py, x, y, angle_deg, mirror)
                            transformed_loop.append((tx, ty))
                        
                        if len(transformed_loop) >= 3:
                            board.boundary_polygons.append(transformed_loop)

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
                    is_tht=is_tht
                )

        # 3. Segnali e Vias (e compilazione delle connessioni di rete)
        signals_node = self.root.find(".//board/signals")
        if signals_node is not None:
            for signal in signals_node.findall("signal"):
                sig_name = signal.get("name", "UNNAMED")
                net_connections = []
                
                # Mappiamo i contatti tra pin (Mantenuta la tua rototraslazione reale)
                contacts = signal.findall("contactref")
                for contact in contacts:
                    el_name = contact.get("element", "")
                    pad_name = contact.get("pad", "")
                    
                    comp = board.components.get(el_name)
                    
                    # Logica di correzione: Rototranslazione reale del pin
                    if comp and comp.library in packages_geom and comp.package in packages_geom[comp.library]:
                        pkg_pads = packages_geom[comp.library][comp.package].get("pads", {})
                        pad_key = str(pad_name).strip().upper()
                        
                        # Cerchiamo il pad (case-insensitive) nella mappa locale del package
                        matched_pad = next((pkg_pads[k] for k in pkg_pads if k.upper() == pad_key), None)
                        
                        if matched_pad:
                            lx, ly = matched_pad
                            # Applichiamo la stessa identica trasformazione geometrica del parser
                            px, py = self._apply_transform(lx, ly, comp.x, comp.y, comp.rot, comp.mirror)
                        else:
                            # Fallback sul centro del componente se il pad non esiste nel package
                            px, py = comp.x, comp.y
                    else:
                        # Fallback se il componente o la libreria non sono censiti
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

                # INSERITO: Gestione Vias Isolate Estetiche (Segnali senza contactref)
                if len(contacts) == 0:
                    for via in signal.findall("via"):
                        vx = float(via.get("x", 0.0))
                        vy = float(via.get("y", 0.0))
                        v_drill = float(via.get("drill", 0.0))
                        v_diam_str = via.get("diameter")
                        v_diam = float(v_diam_str) if v_diam_str else v_drill * 1.8

                        board.isolated_vias.append(
                            ViaData(
                                x=vx,
                                y=vy,
                                drill=v_drill,
                                diameter=v_diam,
                                signal_name=sig_name
                            )
                        )

        return board