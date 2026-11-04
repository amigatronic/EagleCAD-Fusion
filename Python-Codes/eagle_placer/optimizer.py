"""Placement fitness and safe pair-exchange optimization for EAGLE boards."""
from __future__ import annotations

import math
import random
import time
from typing import Callable, Dict, Optional, Tuple

from geometry import BoardData, ComponentData

try:
    from shapely.affinity import rotate as shapely_rotate
    from shapely.geometry import Point, Polygon, box
    from shapely.ops import unary_union
except ImportError:  # pragma: no cover - the GUI already requires Shapely
    shapely_rotate = None
    Point = Polygon = box = unary_union = None


class PlacementOptimizer:
    """Greedy pair-exchange optimizer with strict locked-component protection.

    Phase 2 changes only component center coordinates in memory. It does not write
    EAGLE files or perform logical device/gate/pin swaps.
    """

    def __init__(self, board_data: BoardData):
        self.board_data = board_data
        self.last_result: Dict[str, float | int | str] = {}
        self.optimize_side = "BOTH"
        self.snap_to_grid = False
        self.allow_layer_swaps = False

    def _get_absolute_pad_coords(self, comp: ComponentData, conn) -> Tuple[float, float]:
        """Return parsed absolute pad coordinates without applying transforms twice."""
        x = getattr(conn, "x", None)
        y = getattr(conn, "y", None)
        try:
            if x is not None and y is not None:
                return float(x), float(y)
        except (TypeError, ValueError):
            pass
        return float(comp.x), float(comp.y)

    def _coordinates_for_positions(self, positions: Optional[Dict[str, Tuple[float, float]]] = None):
        positions = positions or {}
        result = {}
        orphan_names = set(getattr(self.board_data, "orphan_components", set()) or set())
        for signal_name, signal in self.board_data.signals.items():
            points = []
            for conn in signal.connections:
                if conn.element in orphan_names:
                    continue
                comp = self.board_data.components.get(conn.element)
                x, y = self._get_absolute_pad_coords(comp, conn) if comp else (float(conn.x), float(conn.y))
                if comp and comp.name in positions:
                    candidate = positions[comp.name]
                    nx, ny = float(candidate[0]), float(candidate[1])
                    new_angle = float(candidate[2]) if len(candidate) > 2 else float(comp.rot)
                    new_mirror = bool(candidate[3]) if len(candidate) > 3 else bool(comp.mirror)
                    # Recover package-local coordinates from the current absolute pad
                    # coordinates, undoing the current rotation and mirror first.
                    dx, dy = x - comp.x, y - comp.y
                    old_angle = math.radians(float(comp.rot))
                    local_x = dx * math.cos(old_angle) + dy * math.sin(old_angle)
                    local_y = -dx * math.sin(old_angle) + dy * math.cos(old_angle)
                    if comp.mirror:
                        local_x = -local_x
                    if new_mirror:
                        local_x = -local_x
                    new_angle_rad = math.radians(new_angle)
                    x = nx + local_x * math.cos(new_angle_rad) - local_y * math.sin(new_angle_rad)
                    y = ny + local_x * math.sin(new_angle_rad) + local_y * math.cos(new_angle_rad)
                points.append((x, y))
            result[signal_name] = points
        return result

    @staticmethod
    def _mst_length(points) -> float:
        """Euclidean minimum spanning tree length using Kruskal's algorithm."""
        n = len(points)
        if n < 2:
            return 0.0
        edges = []
        for i in range(n):
            for j in range(i + 1, n):
                edges.append((math.hypot(points[i][0] - points[j][0], points[i][1] - points[j][1]), i, j))
        edges.sort(key=lambda edge: edge[0])
        parent = list(range(n))

        def find(index):
            while parent[index] != index:
                parent[index] = parent[parent[index]]
                index = parent[index]
            return index

        total = 0.0
        count = 0
        for distance, first, second in edges:
            root_a, root_b = find(first), find(second)
            if root_a != root_b:
                parent[root_a] = root_b
                total += distance
                count += 1
                if count == n - 1:
                    break
        return total

    def _snap_coordinate(self, value: float) -> float:
        """Snap a coordinate to the board grid when grid snapping is enabled."""
        spacing = float(getattr(self.board_data, "grid_spacing_mm", 0.0) or 0.0)
        if not self.snap_to_grid or spacing <= 0:
            return float(value)
        return round(float(value) / spacing) * spacing

    def calculate_ratsnest_length(self) -> float:
        """Return the unweighted sum of per-net Euclidean MST lengths in mm."""
        return sum(self._mst_length(points) for points in self._coordinates_for_positions().values())

    def calculate_fitness(self, positions: Optional[Dict[str, Tuple[float, float]]] = None) -> float:
        """Return the current geometric fitness; lower values are better."""
        return sum(self._mst_length(points) for points in self._coordinates_for_positions(positions).values())

    def _component_polygon(self, comp: ComponentData, x: Optional[float] = None, y: Optional[float] = None,
                           rot: Optional[float] = None, mirror: Optional[bool] = None):
        """Build the transformed package-body footprint in board coordinates.

        Layer-20 package outlines are preferred. Pad-derived dimensions are only a
        fallback for packages without a closed body outline.
        """
        if Polygon is None or box is None:
            return None
        cx = comp.x if x is None else float(x)
        cy = comp.y if y is None else float(y)
        angle = math.radians(comp.rot if rot is None else float(rot))
        effective_mirror = comp.mirror if mirror is None else bool(mirror)
        cos_a, sin_a = math.cos(angle), math.sin(angle)

        def transform(point):
            px, py = float(point[0]), float(point[1])
            if effective_mirror:
                px = -px
            return (cx + px * cos_a - py * sin_a,
                    cy + px * sin_a + py * cos_a)

        outlines = getattr(comp, "package_outlines", None) or []
        polygons = []
        for outline in outlines:
            try:
                points = [transform(point) for point in outline]
                polygon = Polygon(points)
                if not polygon.is_valid:
                    polygon = polygon.buffer(0)
                if not polygon.is_empty and polygon.area > 1e-9:
                    polygons.append(polygon)
            except (TypeError, ValueError):
                continue
        if polygons:
            return unary_union(polygons)

        effective_offset_x = -comp.offset_x if effective_mirror else comp.offset_x
        left = cx + effective_offset_x - comp.width / 2.0
        bottom = cy + comp.offset_y - comp.height / 2.0
        fallback = box(left, bottom, left + max(comp.width, 0.01),
                       bottom + max(comp.height, 0.01))
        return shapely_rotate(fallback, math.degrees(angle), origin=(cx, cy), use_radians=False)

    def _board_allowed_area(self):
        """Build a conservative board area from parsed outline loops, if available."""
        if Polygon is None or not self.board_data.boundary_polygons:
            return None
        polygons = []
        for points in self.board_data.boundary_polygons:
            try:
                poly = Polygon(points)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if not poly.is_empty and poly.area > 1e-6:
                    polygons.append(poly)
            except Exception:
                continue
        if not polygons:
            return None
        # The largest closed loop is treated as the outer board outline; smaller
        # loops are subtracted as internal cutouts/holes.
        outer = max(polygons, key=lambda p: p.area)
        holes = [p for p in polygons if p is not outer and p.area < outer.area]
        allowed = outer
        if holes:
            allowed = allowed.difference(unary_union(holes))
        edge_clearance = 0.0
        rules = getattr(self.board_data, "design_rules", None)
        if rules is not None:
            try:
                edge_clearance = max(0.0, float(getattr(rules, "clearance_board_edge", 0.0) or 0.0))
            except (TypeError, ValueError):
                edge_clearance = 0.0
        if edge_clearance:
            allowed = allowed.buffer(-edge_clearance)
        return allowed

    def _keepout_polygons(self, mirror: bool):
        if mirror:
            source = list(self.board_data.keepouts_bottom) + list(getattr(self.board_data, "restrict_bottom", []))
        else:
            source = list(self.board_data.keepouts_top) + list(getattr(self.board_data, "restrict_top", []))
        polygons = []
        if Polygon is None:
            return polygons
        for points in source:
            try:
                poly = Polygon(points)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if not poly.is_empty:
                    polygons.append(poly)
            except Exception:
                continue
        return polygons

    def _candidate_is_valid(self, comp_a: ComponentData, pos_a, comp_b: ComponentData, pos_b) -> bool:
        """Check both proposed footprints against board, keepouts, restrictions, and all components."""
        if comp_a.locked or comp_b.locked:
            return False
        if comp_a.mirror != comp_b.mirror:
            return False  # Phase 2 does not change TOP/BOTTOM assignment.
        if box is None:
            # Without geometry support, refuse risky physical moves.
            return False

        proposed = {
            comp_a.name: self._component_polygon(comp_a, pos_a[0], pos_a[1],
                                                 pos_a[2] if len(pos_a) > 2 else None,
                                                 mirror=pos_a[3] if len(pos_a) > 3 else comp_a.mirror),
            comp_b.name: self._component_polygon(comp_b, pos_b[0], pos_b[1],
                                                 pos_b[2] if len(pos_b) > 2 else None,
                                                 mirror=pos_b[3] if len(pos_b) > 3 else comp_b.mirror),
        }
        if any(poly is None or poly.is_empty for poly in proposed.values()):
            return False
        allowed = self._board_allowed_area()
        for comp in (comp_a, comp_b):
            poly = proposed[comp.name]
            if allowed is not None and not allowed.covers(poly):
                return False
            if any(poly.intersects(keepout) for keepout in self._keepout_polygons(comp.mirror)):
                return False

        clearance = 0.0
        rules = getattr(self.board_data, "design_rules", None)
        if rules is not None:
            try:
                clearance = max(0.0, float(getattr(rules, "clearance_comp_to_comp", 0.0) or 0.0))
            except (TypeError, ValueError):
                clearance = 0.0
        if clearance:
            proposed = {name: poly.buffer(clearance / 2.0) for name, poly in proposed.items()}

        # Any overlap or clearance violation in the proposed placement is rejected.
        if proposed[comp_a.name].intersection(proposed[comp_b.name]).area > 1e-8:
            return False
        for moving in (comp_a, comp_b):
            new_poly = proposed[moving.name]
            for other in self.board_data.components.values():
                if other.name in proposed or other.mirror != moving.mirror:
                    continue
                other_poly = self._component_polygon(other)
                if other_poly is None:
                    continue
                if clearance:
                    other_poly = other_poly.buffer(clearance / 2.0)
                if new_poly.intersection(other_poly).area > 1e-8:
                    return False
        return True

    def _candidate_group_is_valid(self, candidates: Dict[str, Tuple[float, ...]]) -> bool:
        """Validate a compound move as one final configuration.

        Every candidate must remain on the board and outside side-specific restricted
        areas. Collisions are checked among the proposed components and against fixed
        components on the same side. The operation is transactional: this method does
        not mutate component positions or net coordinates.
        """
        if not candidates or box is None:
            return False
        moving = {}
        for name, position in candidates.items():
            comp = self.board_data.components.get(name)
            if comp is None or comp.locked or name in (getattr(self.board_data, "orphan_components", set()) or set()):
                return False
            mirror = bool(position[3]) if len(position) > 3 else bool(comp.mirror)
            if mirror != comp.mirror and (not self.allow_layer_swaps or comp.is_tht or not comp.is_smd):
                return False
            poly = self._component_polygon(comp, position[0], position[1],
                                           position[2] if len(position) > 2 else None,
                                           mirror=mirror)
            if poly is None or poly.is_empty:
                return False
            allowed = self._board_allowed_area()
            if allowed is not None and not allowed.covers(poly):
                return False
            if any(poly.intersects(area) for area in self._keepout_polygons(mirror)):
                return False
            moving[name] = (comp, poly, mirror)

        clearance = 0.0
        rules = getattr(self.board_data, "design_rules", None)
        if rules is not None:
            try:
                clearance = max(0.0, float(getattr(rules, "clearance_comp_to_comp", 0.0) or 0.0))
            except (TypeError, ValueError):
                clearance = 0.0
        tested = {name: (poly.buffer(clearance / 2.0) if clearance else poly)
                  for name, (_, poly, _) in moving.items()}
        for name, (comp, _, mirror) in moving.items():
            new_poly = tested[name]
            old_poly = self._component_polygon(comp)
            if clearance:
                old_poly = old_poly.buffer(clearance / 2.0)
            for other_name, (other, other_poly, other_mirror) in moving.items():
                if other_name <= name or mirror != other_mirror:
                    continue
                other_new = tested[other_name]
                overlap = new_poly.intersection(other_new).area
                if overlap > 1e-8:
                    return False
            for other in self.board_data.components.values():
                if other.name in moving or other.mirror != mirror:
                    continue
                other_poly = self._component_polygon(other)
                if clearance:
                    other_poly = other_poly.buffer(clearance / 2.0)
                overlap = new_poly.intersection(other_poly).area
                if overlap > 1e-8:
                    return False
        return True

    def _single_candidate_is_valid(self, comp: ComponentData, position: Tuple[float, ...]) -> bool:
        """Validate translation, rotation, and side changes against physical constraints."""
        if comp.locked or box is None:
            return False
        mirror = bool(position[3]) if len(position) > 3 else bool(comp.mirror)
        # Layer changes are opt-in and restricted to non-through-hole components.
        if mirror != comp.mirror and (not self.allow_layer_swaps or comp.is_tht or not comp.is_smd):
            return False
        candidate = self._component_polygon(comp, position[0], position[1],
                                            position[2] if len(position) > 2 else None,
                                            mirror=mirror)
        if candidate is None or candidate.is_empty:
            return False
        allowed = self._board_allowed_area()
        if allowed is not None and not allowed.covers(candidate):
            return False
        if any(candidate.intersects(p) for p in self._keepout_polygons(mirror)):
            return False
        clearance = 0.0
        rules = getattr(self.board_data, "design_rules", None)
        if rules is not None:
            try:
                clearance = max(0.0, float(getattr(rules, "clearance_comp_to_comp", 0.0) or 0.0))
            except (TypeError, ValueError):
                clearance = 0.0
        candidate_test = candidate.buffer(clearance / 2.0) if clearance else candidate
        current = self._component_polygon(comp)
        current_test = current.buffer(clearance / 2.0) if clearance else current
        for other in self.board_data.components.values():
            if other.name == comp.name:
                continue
            other_poly = self._component_polygon(other)
            if other_poly is None:
                continue
            other_test = other_poly.buffer(clearance / 2.0) if clearance else other_poly
            new_overlap = candidate_test.intersection(other_test).area
            if new_overlap > 1e-8:
                return False
        return True

    def is_placement_valid(self, comp: ComponentData, new_x: float, new_y: float, new_layer: str = "TOP") -> bool:
        """Validate a proposed single-component location without moving locked parts."""
        if comp.locked or (comp.is_tht and str(new_layer).upper() != "TOP"):
            return False
        if box is None:
            return False
        candidate = self._component_polygon(comp, new_x, new_y)
        allowed = self._board_allowed_area()
        if allowed is not None and not allowed.covers(candidate):
            return False
        if any(candidate.intersects(p) for p in self._keepout_polygons(comp.mirror)):
            return False
        for other in self.board_data.components.values():
            if other.name == comp.name:
                continue
            if candidate.intersects(self._component_polygon(other)):
                return False
        return True

    def optimize(self, max_iterations: int = 50000, max_evaluations: int = 50000,
                 progress_callback: Optional[Callable[[int, int, float], None]] = None,
                 cancel_callback: Optional[Callable[[], bool]] = None,
                 plateau_callback: Optional[Callable[[Dict[str, float | int]], str]] = None,
                 plateau_window: int = 1000, plateau_threshold_percent: float = 0.1,
                 plateau_patience: int = 3,
                 monitor_callback: Optional[Callable[[Dict[str, float | int | bool]], None]] = None,
                 seed: int = 7, optimize_side: str = "BOTH", snap_to_grid: bool = False,
                 allow_layer_swaps: bool = False, adaptive_strategy: bool = True,
                 auto_stop_enabled: bool = False, auto_stop_min_seconds: float = 1200.0,
                 auto_stop_patience: int = 20) -> Dict[str, float | int | str]:
        """Run Orbit Placement Engine: staged, multi-neighborhood simulated annealing.

        The virtual workspace stages eligible unlocked components outside the board
        without committing those staging coordinates. Search then evaluates legal
        on-board candidates and restores the best known configuration at the end.
        This is a placement heuristic, not an autorouter or full DRC engine.
        """
        # Always optimize eligible components on both sides. Layer swaps are an
        # explicit user option and remain restricted to non-THT components.
        self.optimize_side = "BOTH"
        self.allow_layer_swaps = bool(allow_layer_swaps)
        self.snap_to_grid = bool(snap_to_grid and getattr(self.board_data, "grid_spacing_mm", None))

        workspace = VirtualPlacementWorkspace(self.board_data)
        workspace.stage_unlocked_components()
        staged_names = set(workspace.staged_names)
        staging_positions = dict(workspace.positions)
        # The off-board coordinates are retained in this virtual staging map only;
        # the board model stays at its original legal placements during evaluation.
        workspace.restore()

        start = self.calculate_fitness()
        current = start
        evaluations = accepted_moves = accepted_swaps = accepted_rotations = accepted_layer_swaps = accepted_compound_moves = 0
        action_stats = {
            name: {"attempted": 0, "evaluated": 0, "valid": 0, "accepted": 0, "best_improvements": 0}
            for name in ("move", "target", "rotate", "swap", "layer", "compound", "chain")
        }
        chain_depth_stats = {
            depth: {"attempted": 0, "accepted": 0, "best_improvements": 0}
            for depth in (2, 3, 4)
        }
        benchmark_history = []
        started_at = time.monotonic()
        last_benchmark_evaluation = -1
        rng = random.Random(seed)
        orphan_names = set(getattr(self.board_data, "orphan_components", set()) or set())
        components = [c for c in self.board_data.components.values()
                      if c.name in staged_names and not c.locked and c.name not in orphan_names]
        if not components:
            result = {"initial_fitness": start, "final_fitness": start, "improvement_percent": 0.0,
                      "accepted_swaps": 0, "accepted_moves": 0, "accepted_rotations": 0,
                      "accepted_layer_swaps": 0, "accepted_compound_moves": 0,
                      "staged_components": len(staged_names),
                      "evaluations": 0, "plateau_checks": 0, "adaptive_stopping": bool(plateau_callback is not None or monitor_callback is not None),
                      "search_steps": 0, "max_search_steps": 1,
                      "status": "No eligible unlocked components available for placement optimization."}
            self.last_result = result
            if progress_callback:
                progress_callback(1, 1, current)
            return result

        # Keep a restorable best state while allowing the annealing walk to cross
        # temporary local-fitness barriers. Pad coordinates are included because
        # they are transformed whenever a move is accepted.
        def snapshot():
            return {name: (c.x, c.y, c.rot, c.mirror)
                    for name, c in self.board_data.components.items()}

        def restore(state):
            for name, values in state.items():
                comp = self.board_data.components[name]
                old = (comp.x, comp.y)
                old_rot, old_mirror = comp.rot, comp.mirror
                new_x, new_y, new_rot, new_mirror = values
                self._transform_connections(name, old, (new_x, new_y), old_rot, new_rot,
                                            old_mirror=old_mirror, new_mirror=new_mirror)
                comp.x, comp.y, comp.rot, comp.mirror = new_x, new_y, new_rot, new_mirror

        current_state = snapshot()
        best_state = snapshot()
        best_fitness = current
        xs = [p[0] for poly in self.board_data.boundary_polygons for p in poly]
        ys = [p[1] for poly in self.board_data.boundary_polygons for p in poly]
        board_span = max((max(xs) - min(xs)) if xs else 50.0,
                         (max(ys) - min(ys)) if ys else 50.0, 10.0)
        max_step = max(1.0, min(12.0, board_span * 0.12))
        def snap_coordinate(value):
            return self._snap_coordinate(value)
        max_evaluations = max(1, int(max_evaluations))
        max_iterations = max(1, int(max_iterations))
        plateau_window = max(1, int(plateau_window))
        plateau_threshold_percent = max(0.0, float(plateau_threshold_percent))
        plateau_patience = max(1, int(plateau_patience))
        auto_stop_min_seconds = max(0.0, float(auto_stop_min_seconds))
        auto_stop_patience = max(1, int(auto_stop_patience))
        window_start_fitness = best_fitness
        stale_windows = 0
        adaptive_stopping = auto_stop_enabled or plateau_callback is not None or monitor_callback is not None
        plateau_stop_requested = False
        plateau_checks = 0
        auto_stop_reason = ""
        base_strategy_weights = {
            "move": 36.0, "target": 18.0, "rotate": 14.0, "swap": 12.0,
            "layer": 6.0, "compound": 8.0, "chain": 6.0,
        }
        if not self.allow_layer_swaps:
            base_strategy_weights = {
                "move": 40.0, "target": 19.0, "rotate": 15.0,
                "swap": 12.0, "compound": 8.0, "chain": 6.0,
            }
        adaptive_weights = dict(base_strategy_weights)
        strategy_weight_history = []
        last_strategy_stats = {
            name: {key: 0 for key in ("attempted", "valid", "accepted", "best_improvements")}
            for name in action_stats
        }

        def update_strategy_weights():
            """Adapt proposal probabilities while preserving exploration of every strategy."""
            if not adaptive_strategy:
                return
            scores = {}
            for name, stats in action_stats.items():
                previous = last_strategy_stats[name]
                attempts_delta = max(0, stats["attempted"] - previous["attempted"])
                valid_delta = max(0, stats["valid"] - previous["valid"])
                accepted_delta = max(0, stats["accepted"] - previous["accepted"])
                records_delta = max(0, stats["best_improvements"] - previous["best_improvements"])
                attempts = max(1, attempts_delta)
                valid_rate = valid_delta / attempts
                accept_rate = accepted_delta / attempts
                record_rate = records_delta / attempts
                for key in previous:
                    previous[key] = stats[key]
                # Best-record discoveries dominate; valid/accepted rates provide
                # a modest signal when a strategy has not yet found a global record.
                scores[name] = 1.0 + min(2.0, record_rate * 120.0) + min(0.35, valid_rate * 0.20 + accept_rate * 0.15)
            mean_score = sum(scores.values()) / max(1, len(scores))
            for name, base in base_strategy_weights.items():
                relative = scores.get(name, 1.0) / max(mean_score, 1e-9)
                adaptive = base * max(0.65, min(1.65, relative))
                # Keep 65% of the original distribution as a stable exploration floor.
                adaptive_weights[name] = base * 0.65 + adaptive * 0.35
            strategy_weight_history.append({"evaluations": evaluations, "weights": adaptive_weights.copy()})

        def record_benchmark(force=False):
            nonlocal last_benchmark_evaluation
            if not force and evaluations - last_benchmark_evaluation < 100:
                return
            total_gain = ((start - best_fitness) / max(abs(start), 1e-12)) * 100.0
            benchmark_history.append({
                "evaluations": evaluations,
                "elapsed_seconds": round(time.monotonic() - started_at, 6),
                "best_fitness": float(best_fitness),
                "total_improvement_percent": float(total_gain),
                "action_stats": {name: values.copy() for name, values in action_stats.items()},
                "chain_depth_stats": {depth: values.copy() for depth, values in chain_depth_stats.items()},
                "strategy_weights": adaptive_weights.copy(),
            })
            last_benchmark_evaluation = evaluations
            if len(benchmark_history) > 5000:
                benchmark_history[:] = benchmark_history[::2]

        def check_plateau():
            nonlocal window_start_fitness, stale_windows, adaptive_stopping
            nonlocal plateau_stop_requested, plateau_checks, auto_stop_reason
            if evaluations == 0 or evaluations % plateau_window != 0:
                return
            record_benchmark(force=True)
            if not adaptive_stopping:
                return
            denominator = max(abs(window_start_fitness), 1e-12)
            improvement = max(0.0, (window_start_fitness - best_fitness) / denominator * 100.0)
            total_improvement = ((start - best_fitness) / max(abs(start), 1e-12)) * 100.0
            plateau_checks += 1
            update_strategy_weights()
            if improvement < plateau_threshold_percent:
                stale_windows += 1
            else:
                stale_windows = 0
            window_start_fitness = best_fitness
            target_patience = auto_stop_patience if auto_stop_enabled else plateau_patience
            details = {
                "evaluations": evaluations,
                "max_evaluations": max_evaluations,
                "best_fitness": best_fitness,
                "window_improvement_percent": improvement,
                "total_improvement_percent": total_improvement,
                "action_stats": {name: values.copy() for name, values in action_stats.items()},
                "chain_depth_stats": {depth: values.copy() for depth, values in chain_depth_stats.items()},
                "elapsed_seconds": round(time.monotonic() - started_at, 6),
                "stale_windows": stale_windows,
                "plateau_window": plateau_window,
                "threshold_percent": plateau_threshold_percent,
                "stop_recommended": stale_windows >= target_patience,
                "auto_stop_enabled": bool(auto_stop_enabled),
                "adaptive_strategy": bool(adaptive_strategy),
                "strategy_weights": adaptive_weights.copy(),
            }
            if monitor_callback is not None:
                # The monitor is informational and never blocks or stops the search.
                monitor_callback(details)
            if stale_windows < target_patience:
                return
            elapsed = time.monotonic() - started_at
            if auto_stop_enabled and elapsed >= auto_stop_min_seconds:
                plateau_stop_requested = True
                auto_stop_reason = (
                    f"Automatic stop: no improvement of at least {plateau_threshold_percent:.4f}% "
                    f"for {stale_windows} consecutive checkpoints after {elapsed / 60.0:.1f} minutes."
                )
                return
            if plateau_callback is not None:
                decision = plateau_callback(details) or "continue"
                if decision == "stop":
                    plateau_stop_requested = True
                elif decision == "max":
                    adaptive_stopping = False
            if not plateau_stop_requested:
                stale_windows = 0
                window_start_fitness = best_fitness
        record_benchmark(force=True)

        # Each iteration is a search round containing several candidate trials;
        # this preserves useful search depth for the GUI's existing iteration setting.
        # Count the budget in candidate evaluations, not raw loop attempts. Some
        # proposals (for example, an unavailable equivalent-device swap) are skipped
        # before geometry/fitness evaluation, so allow extra attempts to use the budget.
        search_attempts = max_evaluations + max_iterations
        total_steps = max(1, max_evaluations)
        temperature = max(0.15, start * 0.025)
        cooling = 0.992
        no_improvement = 0

        iterations_completed = 0
        for iteration in range(search_attempts):
            iterations_completed = iteration + 1
            if evaluations >= max_evaluations or (cancel_callback and cancel_callback()):
                break
            comp = rng.choice(components)
            if self.allow_layer_swaps:
                action = rng.choices(tuple(base_strategy_weights),
                                     weights=tuple(adaptive_weights[name] for name in base_strategy_weights), k=1)[0]
            else:
                names = tuple(base_strategy_weights)
                action = rng.choices(names,
                                     weights=tuple(adaptive_weights[name] for name in names), k=1)[0]
            proposal = None
            candidate_positions = {}
            other = None
            chain_depth = 0
            action_stats[action]["attempted"] += 1

            if action in ("move", "target"):
                if action == "target":
                    targets = self._strategic_translation_candidates(comp)
                    if targets:
                        tx, ty = rng.choice(targets)
                        # Blend the target with the current location to make the
                        # proposal scale controllable by the annealing temperature.
                        blend = rng.uniform(0.35, 1.0)
                        nx = comp.x + (tx - comp.x) * blend
                        ny = comp.y + (ty - comp.y) * blend
                    else:
                        action_stats["target"]["attempted"] -= 1
                        action = "move"
                        action_stats["move"]["attempted"] += 1
                if action == "move":
                    step = max_step * (0.15 + 0.85 * min(1.0, temperature / max(start * 0.025, 1e-9)))
                    angle = rng.uniform(0.0, math.tau)
                    distance = step * math.sqrt(rng.random())
                    nx, ny = comp.x + math.cos(angle) * distance, comp.y + math.sin(angle) * distance
                nx, ny = snap_coordinate(nx), snap_coordinate(ny)
                proposal = (nx, ny, float(comp.rot), bool(comp.mirror))
                candidate_positions[comp.name] = proposal
            elif action == "rotate":
                delta = rng.choice((-180.0, -90.0, 90.0, 180.0))
                proposal = (snap_coordinate(comp.x), snap_coordinate(comp.y), (float(comp.rot) + delta) % 360.0, bool(comp.mirror))
                candidate_positions[comp.name] = proposal
            elif action == "layer":
                # Layer swaps are opt-in and apply only to pure SMD/SMT packages.
                if not self.allow_layer_swaps or comp.is_tht or not comp.is_smd:
                    continue
                proposal = (comp.x, comp.y, float(comp.rot), not bool(comp.mirror))
                candidate_positions[comp.name] = proposal
            elif action == "compound":
                # A compound move models a pick-stage-place sequence: one component
                # is virtually staged off-board, another can use the released space,
                # and both final placements are evaluated together. Staging is never
                # committed as a final board coordinate.
                alternatives = [item for item in components if item.name != comp.name
                                and item.mirror == comp.mirror]
                if not alternatives:
                    continue
                other = rng.choice(alternatives)
                targets = self._strategic_translation_candidates(comp)
                if targets and rng.random() < 0.7:
                    tx, ty = rng.choice(targets)
                    nx = tx + rng.uniform(-max_step, max_step) * 0.25
                    ny = ty + rng.uniform(-max_step, max_step) * 0.25
                else:
                    angle = rng.uniform(0.0, math.tau)
                    distance = max_step * rng.uniform(0.2, 1.0)
                    nx, ny = comp.x + math.cos(angle) * distance, comp.y + math.sin(angle) * distance
                nx, ny = snap_coordinate(nx), snap_coordinate(ny)
                # Other component moves into the first component's former area;
                # the first is relocated elsewhere, forming one atomic proposal.
                candidate_positions[comp.name] = (nx, ny, float(comp.rot), bool(comp.mirror))
                candidate_positions[other.name] = (snap_coordinate(comp.x), snap_coordinate(comp.y),
                                                    float(other.rot), bool(other.mirror))
            elif action == "chain":
                # Variable-depth strategic relocation chain (2-4 components).
                # The first component is virtually staged, then each following
                # component takes the previous component's original position.
                # The entire final configuration is validated and scored atomically.
                alternatives = [item for item in components
                                if item.name != comp.name and item.mirror == comp.mirror]
                if not alternatives:
                    continue
                depth = min(len(components), rng.choices((2, 3, 4), weights=(50, 35, 15), k=1)[0])
                if len(alternatives) < depth - 1:
                    depth = len(alternatives) + 1
                if depth < 2:
                    continue
                chain_depth = depth
                chain_depth_stats[depth]["attempted"] += 1
                chain = [comp] + rng.sample(alternatives, depth - 1)
                targets = self._strategic_translation_candidates(comp)
                if targets:
                    tx, ty = rng.choice(targets)
                    nx = tx + rng.uniform(-max_step, max_step) * 0.2
                    ny = ty + rng.uniform(-max_step, max_step) * 0.2
                else:
                    angle = rng.uniform(0.0, math.tau)
                    distance = max_step * rng.uniform(0.25, 1.0)
                    nx, ny = comp.x + math.cos(angle) * distance, comp.y + math.sin(angle) * distance
                candidate_positions[comp.name] = (snap_coordinate(nx), snap_coordinate(ny),
                                                  float(comp.rot), bool(comp.mirror))
                for index in range(1, len(chain)):
                    item = chain[index]
                    predecessor = chain[index - 1]
                    candidate_positions[item.name] = (snap_coordinate(predecessor.x),
                                                       snap_coordinate(predecessor.y),
                                                       float(item.rot), bool(item.mirror))
            else:
                compatible = [c for c in components if c.name != comp.name
                              and c.mirror == comp.mirror and c.is_tht == comp.is_tht
                              and c.library.casefold() == comp.library.casefold()
                              and c.package.casefold() == comp.package.casefold()
                              and abs(c.width-comp.width) <= 0.05 and abs(c.height-comp.height) <= 0.05
                              and self._same_physical_interface(comp, c)]
                if not compatible:
                    continue
                other = rng.choice(compatible)
                candidate_positions[comp.name] = (snap_coordinate(other.x), snap_coordinate(other.y), float(comp.rot), bool(comp.mirror))
                candidate_positions[other.name] = (snap_coordinate(comp.x), snap_coordinate(comp.y), float(other.rot), bool(other.mirror))

            evaluations += 1
            action_stats[action]["evaluated"] += 1
            if action in ("compound", "chain"):
                valid = self._candidate_group_is_valid(candidate_positions)
            elif other is None:
                valid = self._single_candidate_is_valid(comp, proposal)
            else:
                valid = self._candidate_is_valid(comp, candidate_positions[comp.name],
                                                 other, candidate_positions[other.name])
            if not valid:
                temperature *= cooling
                check_plateau()
                if progress_callback and (iteration % max(1, search_attempts // 100) == 0):
                    progress_callback(min(evaluations, total_steps), total_steps, best_fitness)
                if plateau_stop_requested:
                    break
                continue

            action_stats[action]["valid"] += 1
            candidate_fitness = self.calculate_fitness(candidate_positions)
            delta_cost = candidate_fitness - current
            accept = delta_cost < -1e-9 or rng.random() < math.exp(-max(0.0, delta_cost) / max(temperature, 1e-9))
            if accept:
                action_stats[action]["accepted"] += 1
                if action == "chain" and chain_depth in chain_depth_stats:
                    chain_depth_stats[chain_depth]["accepted"] += 1
                if other is None and action not in ("compound", "chain"):
                    old = (comp.x, comp.y)
                    old_rot, old_mirror = comp.rot, comp.mirror
                    nx, ny, nr, nm = candidate_positions[comp.name]
                    self._transform_connections(comp.name, old, (nx, ny), old_rot, nr,
                                                old_mirror=old_mirror, new_mirror=nm)
                    comp.x, comp.y, comp.rot, comp.mirror = nx, ny, nr, nm
                    if action in ("move", "target"):
                        accepted_moves += 1
                    elif action == "rotate":
                        accepted_rotations += 1
                    elif action == "layer":
                        accepted_layer_swaps += 1
                else:
                    affected = [self.board_data.components[name] for name in candidate_positions]
                    for item in affected:
                        values = candidate_positions[item.name]
                        old = (item.x, item.y)
                        self._transform_connections(item.name, old, values[:2], item.rot, values[2],
                                                    old_mirror=item.mirror, new_mirror=values[3])
                        item.x, item.y, item.rot, item.mirror = values
                    if action in ("compound", "chain"):
                        accepted_compound_moves += 1
                    else:
                        accepted_swaps += 1
                current = candidate_fitness
                current_state = snapshot()
                if current + 1e-9 < best_fitness:
                    best_fitness = current
                    best_state = snapshot()
                    action_stats[action]["best_improvements"] += 1
                    if action == "chain" and chain_depth in chain_depth_stats:
                        chain_depth_stats[chain_depth]["best_improvements"] += 1
                    record_benchmark(force=True)
                    no_improvement = 0
                else:
                    no_improvement += 1
            else:
                no_improvement += 1

            temperature *= cooling
            check_plateau()
            if plateau_stop_requested:
                break
            if no_improvement > max(250, len(components) * 40):
                # Deterministic restart from the best solution, then reheat.
                restore(best_state)
                current_state = snapshot()
                current = best_fitness
                temperature = max(0.15, start * 0.012)
                no_improvement = 0
            if progress_callback and (iteration % max(1, search_attempts // 100) == 0):
                progress_callback(min(evaluations, total_steps), total_steps, best_fitness)

        restore(best_state)
        final = self.calculate_fitness()
        record_benchmark(force=True)
        improvement = ((start - final) / start * 100.0) if start > 1e-12 else 0.0
        if plateau_stop_requested:
            status = auto_stop_reason or "Stopped after negligible improvement; best valid placement restored."
        elif cancel_callback and cancel_callback():
            status = "Cancelled by user; best valid placement restored."
        elif evaluations >= max_evaluations:
            status = "Evaluation budget reached; best valid placement restored."
        else:
            status = "Search completed; best valid placement restored."
        result = {"initial_fitness": start, "final_fitness": final,
                  "improvement_percent": improvement, "accepted_swaps": accepted_swaps,
                  "accepted_moves": accepted_moves, "accepted_rotations": accepted_rotations,
                  "accepted_layer_swaps": accepted_layer_swaps,
                  "accepted_compound_moves": accepted_compound_moves,
                  "action_stats": {name: values.copy() for name, values in action_stats.items()},
                  "chain_depth_stats": {depth: values.copy() for depth, values in chain_depth_stats.items()},
                  "benchmark_history": benchmark_history,
                  "elapsed_seconds": round(time.monotonic() - started_at, 6),
                  "seed": seed,
                  "staged_components": len(staged_names), "evaluations": evaluations,
                  "plateau_checks": plateau_checks,
                  "adaptive_stopping": bool(auto_stop_enabled or plateau_callback is not None),
                  "auto_stop_enabled": bool(auto_stop_enabled),
                  "auto_stop_reason": auto_stop_reason,
                  "adaptive_strategy": bool(adaptive_strategy),
                  "strategy_weights": adaptive_weights.copy(),
                  "strategy_weight_history": strategy_weight_history,
                  "search_steps": evaluations,
                  "max_search_steps": total_steps,
                  "status": status}
        self.last_result = result
        if progress_callback:
            progress_callback(min(evaluations, total_steps), total_steps, final)
        return result

    def _strategic_translation_candidates(self, comp: ComponentData):
        """Suggest component centers that pull its connected pads toward net clusters."""
        orphan_names = set(getattr(self.board_data, "orphan_components", set()) or set())
        proposals = []
        for signal in self.board_data.signals.values():
            own = [c for c in signal.connections if c.element == comp.name]
            others = [c for c in signal.connections
                      if c.element != comp.name and c.element not in orphan_names]
            if not own or not others:
                continue
            target_x = sum(float(c.x) for c in others) / len(others)
            target_y = sum(float(c.y) for c in others) / len(others)
            # Preserve the current pad-to-origin offset for the first connected pad.
            anchor = own[0]
            rel_x, rel_y = float(anchor.x) - comp.x, float(anchor.y) - comp.y
            proposals.append((target_x - rel_x, target_y - rel_y))
        # Deduplicate near-identical proposals and avoid over-evaluating dense nets.
        unique = []
        for point in proposals:
            if all(math.hypot(point[0] - old[0], point[1] - old[1]) > 0.1 for old in unique):
                unique.append(point)
        return unique[:8]

    def _transform_connections(self, component_name: str, old_position, new_position,
                               old_angle: float = 0.0, new_angle: float = 0.0,
                               old_mirror: Optional[bool] = None,
                               new_mirror: Optional[bool] = None):
        """Transform absolute pad coordinates for translation, rotation, and mirroring."""
        comp = self.board_data.components.get(component_name)
        old_mirror = bool(comp.mirror) if old_mirror is None and comp else bool(old_mirror)
        new_mirror = old_mirror if new_mirror is None else bool(new_mirror)
        old_rad, new_rad = math.radians(old_angle), math.radians(new_angle)
        for signal in self.board_data.signals.values():
            for conn in signal.connections:
                if conn.element != component_name:
                    continue
                dx, dy = conn.x - old_position[0], conn.y - old_position[1]
                local_x = dx * math.cos(old_rad) + dy * math.sin(old_rad)
                local_y = -dx * math.sin(old_rad) + dy * math.cos(old_rad)
                if old_mirror:
                    local_x = -local_x
                if new_mirror:
                    local_x = -local_x
                conn.x = new_position[0] + local_x * math.cos(new_rad) - local_y * math.sin(new_rad)
                conn.y = new_position[1] + local_x * math.sin(new_rad) + local_y * math.cos(new_rad)

    def _translate_connections(self, component_name: str, old_position, new_position):
        """Backward-compatible translation helper."""
        self._transform_connections(component_name, old_position, new_position)

    @staticmethod
    def _same_physical_interface(first: ComponentData, second: ComponentData) -> bool:
        """Conservative equivalence check for physical device exchanges.

        Logical device/gate/pin swaps are deliberately not inferred from matching
        footprints; those require verified schematic pin-to-pad equivalence.
        """
        def normalized(mapping):
            return tuple(sorted((str(k).casefold(), str(v).casefold())
                                for k, v in (mapping or {}).items()))
        if first.pad_to_pin_map and second.pad_to_pin_map:
            return normalized(first.pad_to_pin_map) == normalized(second.pad_to_pin_map)
        if first.pin_to_pad_map and second.pin_to_pad_map:
            return normalized(first.pin_to_pad_map) == normalized(second.pin_to_pad_map)
        # Without schematic mappings, allow only exact library/package identity.
        same_library_package = (
            first.library.strip().casefold(), first.package.strip().casefold()
        ) == (second.library.strip().casefold(), second.package.strip().casefold())
        if not same_library_package:
            return False
        if first.deviceset.strip() and second.deviceset.strip():
            return first.deviceset.strip().casefold() == second.deviceset.strip().casefold()
        # Legacy board-only passive test data may lack schematic mappings and values.
        # In that case, only allow same-reference-family passives with matching values.
        def family(name):
            return "".join(ch for ch in name if ch.isalpha()).upper()
        passive_families = {"R", "C", "L"}
        return (family(first.name) == family(second.name) and family(first.name) in passive_families
                and str(first.value).strip().casefold() == str(second.value).strip().casefold())


class VirtualPlacementWorkspace:
    """Non-destructive staging model for SCH-linked, unlocked board components.

    Staging coordinates are kept in a separate map; the source BoardData and its
    connectivity are not modified until commit() is explicitly requested.
    Board-only objects and locked components remain fixed obstacles.
    """

    def __init__(self, board_data: BoardData, staging_gap: float = 10.0):
        self.board_data = board_data
        self.staging_gap = max(1.0, float(staging_gap))
        self.original_positions = {
            name: (float(comp.x), float(comp.y))
            for name, comp in board_data.components.items()
        }
        self.positions = dict(self.original_positions)
        self.staged_names = set()
        self.placed_names = {
            name for name, comp in board_data.components.items()
            if comp.locked or name in (getattr(board_data, "orphan_components", set()) or set())
        }
        self._committed = False

    def stage_unlocked_components(self) -> dict:
        """Assign movable components to a virtual off-board storage grid."""
        movable = [
            comp for comp in self.board_data.components.values()
            if not comp.locked
            and comp.name not in (getattr(self.board_data, "orphan_components", set()) or set())
        ]
        if not movable:
            self.staged_names.clear()
            return dict(self.positions)

        points = [pt for polygon in self.board_data.boundary_polygons for pt in polygon]
        if points:
            min_x = min(pt[0] for pt in points)
            max_x = max(pt[0] for pt in points)
            min_y = min(pt[1] for pt in points)
            max_y = max(pt[1] for pt in points)
        else:
            all_positions = list(self.original_positions.values())
            min_x = min((p[0] for p in all_positions), default=0.0)
            max_x = max((p[0] for p in all_positions), default=100.0)
            min_y = min((p[1] for p in all_positions), default=0.0)
            max_y = max((p[1] for p in all_positions), default=100.0)

        cell = max(3.0, max((max(c.width, c.height) for c in movable), default=3.0) + self.staging_gap)
        columns = max(1, int(math.ceil(math.sqrt(len(movable)))))
        start_x = max_x + self.staging_gap + cell
        start_y = max_y + self.staging_gap + cell
        self.staged_names = {comp.name for comp in movable}
        for index, comp in enumerate(sorted(movable, key=lambda item: item.name)):
            col, row = index % columns, index // columns
            self.positions[comp.name] = (start_x + col * cell, start_y + row * cell)
        self.placed_names.difference_update(self.staged_names)
        return dict(self.positions)

    def set_candidate(self, component_name: str, x: float, y: float) -> None:
        """Set a virtual candidate position without touching source board data."""
        if component_name not in self.staged_names and component_name not in self.positions:
            raise KeyError(f"Unknown component: {component_name}")
        comp = self.board_data.components.get(component_name)
        if comp is None:
            raise KeyError(f"Unknown component: {component_name}")
        if comp.locked or component_name in (getattr(self.board_data, "orphan_components", set()) or set()):
            raise ValueError(f"Component is fixed and cannot be repositioned: {component_name}")
        self.positions[component_name] = (float(x), float(y))
        self.staged_names.discard(component_name)
        self.placed_names.add(component_name)

    def restore(self) -> None:
        """Discard virtual changes and restore the initial virtual state."""
        self.positions = dict(self.original_positions)
        self.staged_names.clear()
        self.placed_names = {
            name for name, comp in self.board_data.components.items()
            if comp.locked or name in (getattr(self.board_data, "orphan_components", set()) or set())
        }
        self._committed = False

    def commit(self) -> None:
        """Apply virtual positions to movable components and translate connected pads."""
        # Never commit components that are still in virtual storage. Only components
        # explicitly assigned a candidate position are eligible for commit.
        for name in sorted(self.placed_names):
            new_position = self.positions.get(name)
            comp = self.board_data.components.get(name)
            if new_position is None or comp is None or comp.locked or name in (getattr(self.board_data, "orphan_components", set()) or set()):
                continue
            old_position = (comp.x, comp.y)
            dx, dy = new_position[0] - old_position[0], new_position[1] - old_position[1]
            if abs(dx) < 1e-12 and abs(dy) < 1e-12:
                continue
            comp.x, comp.y = new_position
            for signal in self.board_data.signals.values():
                for connection in signal.connections:
                    if connection.element == name:
                        connection.x += dx
                        connection.y += dy
        self._committed = True
