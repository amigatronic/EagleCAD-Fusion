#!/usr/bin/env python3
"""
EAGLE BRD Analyzer

Analyzes an Autodesk EAGLE .brd XML file without modifying it.

The analyzer reports:
- board file information
- XML element counts
- polygons and their vertex counts
- polygon bounding boxes
- polygon area and perimeter
- whether a polygon is approximately circular
- estimated circle center and radius
- existing circle-like EAGLE elements
- wire elements using curves
- suspiciously large/high-vertex polygons

All output is in English.
"""

import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


CIRCLE_TOLERANCE = 0.02       # 2% radial deviation
LARGE_POLYGON_VERTICES = 100
VERY_LARGE_POLYGON_VERTICES = 1000


def local_name(tag):
    """Return an XML tag name without a namespace."""
    return tag.rsplit("}", 1)[-1]


def attr_float(element, name, default=None):
    value = element.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def polygon_points(polygon):
    points = []

    for child in polygon:
        if local_name(child.tag) != "vertex":
            continue

        x = attr_float(child, "x")
        y = attr_float(child, "y")

        if x is not None and y is not None:
            points.append((x, y))

    return points


def bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    return min(xs), min(ys), max(xs), max(ys)


def polygon_area(points):
    if len(points) < 3:
        return 0.0

    area = 0.0

    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        area += x1 * y2 - x2 * y1

    return abs(area) * 0.5


def polygon_perimeter(points):
    if len(points) < 2:
        return 0.0

    total = 0.0

    for i, (x1, y1) in enumerate(points):
        x2, y2 = points[(i + 1) % len(points)]
        total += math.hypot(x2 - x1, y2 - y1)

    return total


def estimate_circle(points):
    """
    Estimate a circle from the polygon bounding box.

    This is intentionally simple and robust for polygons generated
    from a circle using many equally distributed vertices.
    """
    if len(points) < 8:
        return None

    min_x, min_y, max_x, max_y = bbox(points)

    width = max_x - min_x
    height = max_y - min_y

    if width <= 0 or height <= 0:
        return None

    cx = (min_x + max_x) / 2.0
    cy = (min_y + max_y) / 2.0
    radius = (width + height) / 4.0

    distances = [
        math.hypot(x - cx, y - cy)
        for x, y in points
    ]

    min_r = min(distances)
    max_r = max(distances)
    mean_r = sum(distances) / len(distances)

    radial_deviation = (max_r - min_r) / mean_r if mean_r else float("inf")

    aspect_error = abs(width - height) / max(width, height)

    circular = (
        radial_deviation <= CIRCLE_TOLERANCE
        and aspect_error <= CIRCLE_TOLERANCE
    )

    return {
        "cx": cx,
        "cy": cy,
        "radius": mean_r,
        "min_radius": min_r,
        "max_radius": max_r,
        "radial_deviation": radial_deviation,
        "aspect_error": aspect_error,
        "circular": circular,
    }


def print_element_counts(root):
    counts = {}

    for element in root.iter():
        name = local_name(element.tag)
        counts[name] = counts.get(name, 0) + 1

    print("\nXML ELEMENT COUNTS")
    print("-" * 70)

    for name in sorted(counts):
        print(f"{name:<30} {counts[name]:>10}")


def print_circles(root):
    circles = []

    for element in root.iter():
        name = local_name(element.tag)

        if name == "circle":
            circles.append(element)

    print("\nNATIVE <circle> ELEMENTS")
    print("-" * 70)
    print(f"Count: {len(circles)}")

    for index, circle in enumerate(circles, 1):
        x = attr_float(circle, "x")
        y = attr_float(circle, "y")
        radius = attr_float(circle, "radius")
        layer = circle.get("layer")

        print(
            f"  Circle {index}: "
            f"x={x}, y={y}, radius={radius}, layer={layer}"
        )


def print_curved_wires(root):
    curved = []

    for element in root.iter():
        if local_name(element.tag) != "wire":
            continue

        curve = element.get("curve")
        if curve is not None:
            curved.append(element)

    print("\nCURVED <wire> ELEMENTS")
    print("-" * 70)
    print(f"Count: {len(curved)}")

    for index, wire in enumerate(curved[:20], 1):
        print(
            f"  Wire {index}: "
            f"x1={wire.get('x1')}, y1={wire.get('y1')}, "
            f"x2={wire.get('x2')}, y2={wire.get('y2')}, "
            f"curve={wire.get('curve')}, "
            f"layer={wire.get('layer')}"
        )

    if len(curved) > 20:
        print(f"  ... {len(curved) - 20} more curved wires")


def print_polygons(root):
    polygons = []

    for element in root.iter():
        if local_name(element.tag) == "polygon":
            points = polygon_points(element)
            polygons.append((element, points))

    print("\nPOLYGONS")
    print("-" * 70)
    print(f"Count: {len(polygons)}")

    if not polygons:
        return

    for index, (polygon, points) in enumerate(polygons, 1):
        layer = polygon.get("layer")
        rank = polygon.get("rank")
        isolate = polygon.get("isolate")
        thermals = polygon.get("thermals")

        print(f"\nPolygon {index}")
        print(f"  Layer: {layer}")
        print(f"  Rank: {rank}")
        print(f"  Isolate: {isolate}")
        print(f"  Thermals: {thermals}")
        print(f"  Vertices: {len(points)}")

        if len(points) < 3:
            print("  Status: INVALID / LESS THAN 3 VERTICES")
            continue

        min_x, min_y, max_x, max_y = bbox(points)

        print(
            f"  Bounding box: "
            f"({min_x:.6f}, {min_y:.6f}) - "
            f"({max_x:.6f}, {max_y:.6f})"
        )

        print(f"  Width:  {max_x - min_x:.6f}")
        print(f"  Height: {max_y - min_y:.6f}")
        print(f"  Area:   {polygon_area(points):.6f}")
        print(f"  Perimeter: {polygon_perimeter(points):.6f}")

        circle = estimate_circle(points)

        if circle:
            print(
                f"  Estimated center: "
                f"({circle['cx']:.6f}, {circle['cy']:.6f})"
            )
            print(f"  Estimated radius: {circle['radius']:.6f}")
            print(
                f"  Radial deviation: "
                f"{circle['radial_deviation'] * 100:.4f}%"
            )
            print(
                f"  Bounding-box aspect error: "
                f"{circle['aspect_error'] * 100:.4f}%"
            )

            if circle["circular"]:
                print("  CLASSIFICATION: CIRCULAR POLYGON")
            else:
                print("  CLASSIFICATION: NON-CIRCULAR POLYGON")

        if len(points) >= VERY_LARGE_POLYGON_VERTICES:
            print("  WARNING: VERY LARGE POLYGON")
        elif len(points) >= LARGE_POLYGON_VERTICES:
            print("  WARNING: HIGH-VERTEX POLYGON")


def print_summary(root):
    polygons = []

    for element in root.iter():
        if local_name(element.tag) == "polygon":
            points = polygon_points(element)
            polygons.append((element, points))

    circular = 0
    large = 0
    very_large = 0

    for _, points in polygons:
        if len(points) >= LARGE_POLYGON_VERTICES:
            large += 1

        if len(points) >= VERY_LARGE_POLYGON_VERTICES:
            very_large += 1

        result = estimate_circle(points)
        if result and result["circular"]:
            circular += 1

    print("\nSUMMARY")
    print("-" * 70)
    print(f"Total polygons:              {len(polygons)}")
    print(f"Approximately circular:      {circular}")
    print(f"High-vertex polygons:        {large}")
    print(f"Very large polygons:         {very_large}")

    if circular:
        print(
            "\nThe analyzer found polygon(s) that can potentially be "
            "represented as native circular geometry."
        )


def analyze(path):
    print("=" * 70)
    print("EAGLE BRD ANALYZER")
    print("=" * 70)
    print(f"File: {path}")
    print(f"Size: {path.stat().st_size:,} bytes")

    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except ET.ParseError as exc:
        print("\nERROR: The file is not valid XML.")
        print(f"XML parser error: {exc}")
        return 2
    except OSError as exc:
        print("\nERROR: Cannot read file.")
        print(exc)
        return 2

    print(f"Root element: {local_name(root.tag)}")

    print_element_counts(root)
    print_circles(root)
    print_curved_wires(root)
    print_polygons(root)
    print_summary(root)

    print("\nNo changes were made to the input file.")
    return 0


def main():
    if len(sys.argv) != 2:
        print("Usage:")
        print("  python eagle_brd_analyzer.py <board.brd>")
        print()
        print("Example:")
        print("  python eagle_brd_analyzer.py Digital_clock.brd")
        return 1

    path = Path(sys.argv[1])

    if not path.is_file():
        print(f"ERROR: File not found: {path}")
        return 1

    return analyze(path)


if __name__ == "__main__":
    sys.exit(main())

