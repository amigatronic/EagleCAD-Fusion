#!/usr/bin/env python3
"""
EaglePCBView3D - Offline renderer for EAGLE .brd / .sch files (XML format).
Script: eagle_pcb_view_3d.py

Usage:
    python eagle_pcb_view_3d.py                      open the GUI
    python eagle_pcb_view_3d.py file.brd [-o OUTDIR] command line; the matching file.sch is loaded
                                              automatically (and vice versa), like EAGLE does
    python eagle_pcb_view_3d.py -h                   full command line help

For every input file it writes:
    <name>.svg   static vector drawing (dark background, EAGLE-like colors)
    <name>.htm   standalone interactive viewer (pan, zoom, layer toggles); board viewers also embed a
                 3D view ("3D rendering" button) that follows the layer checkboxes

Version 1.0 (2026-10-12)
by Arky - amigatronic.com - https://www.amigatronic.com
License: MIT. Provided "AS IS", without warranty of any kind (see the notice in HELP_TEXT).

Only the Python standard library is required. The 3D view uses three.js r147 and its TrackballControls,
both embedded (compressed) at the end of this file; they are MIT licensed, see the notice there.

Known limits versus the real EAGLE:
  - text uses a system font, sized/stretched to approximate the vector font
  - copper pours are NOT recalculated: polygons are drawn as translucent outlines
  - ratsnest/airwires are not drawn
"""
import argparse
import base64
import html
import json
import math
import os
import re
import sys
import zlib
import xml.etree.ElementTree as ET

# Approximation of the EAGLE color palette (index -> hex), tuned for a dark background
PALETTE = {
    1: "#3c3cf0", 2: "#32b432", 3: "#00b4b4", 4: "#d23232", 5: "#b432b4",
    6: "#b4b400", 7: "#d2d2d2", 8: "#787878", 9: "#6e6eff", 10: "#6ee66e",
    11: "#6ee6e6", 12: "#ff7878", 13: "#ff78ff", 14: "#ffff50", 15: "#c8c828",
    16: "#aaaaaa",
}

# Layer pairs swapped when an element is placed on the bottom side
MIRROR_LAYERS = {
    1: 16, 16: 1, 21: 22, 22: 21, 23: 24, 24: 23, 25: 26, 26: 25, 27: 28,
    28: 27, 29: 30, 30: 29, 31: 32, 32: 31, 33: 34, 34: 33, 35: 36, 36: 35,
    37: 38, 38: 37, 39: 40, 40: 39, 41: 42, 42: 41, 51: 52, 52: 51,
}

# Drawing order (first = bottom of the stack); remaining layers follow, sorted
BOARD_ORDER = [16, 1, 17, 18, 45, 46, 22, 21, 52, 51, 26, 25, 28, 27, 20]
SCH_ORDER = [94, 93, 91, 92, 95, 96, 97, 98]

# Warning sink: run() redirects it to the GUI log; each message is reported only once per run
_warn_sink = print
_warn_seen = set()


def warn(msg):
    if msg not in _warn_seen:
        _warn_seen.add(msg)
        _warn_sink("warning: " + msg)


def missing_marker(cv, x, y, name):
    """Visible placeholder for a part whose library data is missing (instead of dropping it silently)."""
    cv.poly(94, rect_pts(x, y, 5.08, 5.08), fill=False, w=0.15)
    cv.wire(94, (x - 2.54, y - 2.54), (x + 2.54, y + 2.54), 0.15)
    cv.wire(94, (x - 2.54, y + 2.54), (x + 2.54, y - 2.54), 0.15)
    cv.text(95, x, y + 3.2, 1.27, 0.0, name + " (missing)", "bottom-center")


# Pin length keywords -> millimeters
PIN_LEN = {"point": 0.0, "short": 2.54, "middle": 5.08, "long": 7.62}


# ----------------------------------------------------------------- helpers
def num(el, key, default=0.0):
    """Read a float attribute, falling back to a default when missing."""
    v = el.get(key)
    return float(v) if v not in (None, "") else default


def parse_rot(s):
    """Parse EAGLE rotation strings like 'R90', 'MR180', 'SR0' -> (mirror, spin, angle)."""
    m = re.match(r"^(S?)(M?)R(-?[\d.]+)$", s or "R0")
    if not m:
        return False, False, 0.0
    return bool(m.group(2)), bool(m.group(1)), float(m.group(3))


class Tf:
    """2D transform: optional mirror (x -> -x), then rotation (deg, CCW), then translation."""

    def __init__(self, x=0.0, y=0.0, rot=0.0, mirror=False):
        self.x, self.y, self.rot, self.m = x, y, rot, mirror
        r = math.radians(rot)
        self.c, self.s = math.cos(r), math.sin(r)

    def pt(self, x, y):
        if self.m:
            x = -x
        return (x * self.c - y * self.s + self.x, x * self.s + y * self.c + self.y)


def rect_pts(cx, cy, w, h, rot=0.0):
    """Corners of a rectangle centered at (cx, cy), rotated by rot degrees."""
    r = math.radians(rot)
    c, s = math.cos(r), math.sin(r)
    return [(cx + dx * c - dy * s, cy + dx * s + dy * c)
            for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2))]


def rrect_pts(cx, cy, w, h, rot, rad, steps=6):
    """Rounded rectangle outline as a polygon (rad = corner radius)."""
    rad = min(rad, w / 2, h / 2)
    if rad <= 1e-6:
        return rect_pts(cx, cy, w, h, rot)
    pts = []
    corners = ((w / 2 - rad, h / 2 - rad, 0), (-w / 2 + rad, h / 2 - rad, 90),
               (-w / 2 + rad, -h / 2 + rad, 180), (w / 2 - rad, -h / 2 + rad, 270))
    for ox, oy, a0 in corners:
        for i in range(steps + 1):
            a = math.radians(a0 + 90.0 * i / steps)
            pts.append((ox + rad * math.cos(a), oy + rad * math.sin(a)))
    r = math.radians(rot)
    c, s = math.cos(r), math.sin(r)
    return [(cx + x * c - y * s, cy + x * s + y * c) for x, y in pts]


def markup(txt):
    """Escape text and convert EAGLE '!' overbar markers into SVG overline tspans."""
    if "!" not in txt:
        return html.escape(txt)
    out, over = [], False
    for part in txt.split("!"):
        if part:
            esc = html.escape(part)
            out.append('<tspan text-decoration="overline">%s</tspan>' % esc if over else esc)
        over = not over
    return "".join(out)


def arc_seg(p1, p2, curve):
    """SVG path segment from p1 to p2 (EAGLE coords) for an EAGLE curve angle (deg, CCW positive).
    Returns a straight 'L' segment when the curve is flat."""
    if abs(curve) <= 0.01 or p1 == p2:
        return "L%.4f,%.4f" % (p2[0], -p2[1])
    chord = math.dist(p1, p2)
    th = math.radians(min(abs(curve), 359.9))
    r = chord / (2 * math.sin(th / 2))
    large = 1 if th > math.pi else 0
    # The Y negation combined with SVG's Y-down axis keeps the visual orientation,
    # so EAGLE's CCW (positive curve) maps to sweep-flag 0
    sweep = 0 if curve > 0 else 1
    return "A%.4f,%.4f 0 %d %d %.4f,%.4f" % (r, r, large, sweep, p2[0], -p2[1])


# Dash patterns (mm) for EAGLE wire styles
DASH = {"longdash": "5.08 1.27", "shortdash": "2.032 1.016", "dashdot": "5.08 1.27 0.508 1.27"}

# Values for text variables such as >DRAWING_NAME (filled by process())
VARS = {}


def expand_vars(txt, subst):
    """Replace EAGLE text variables (>NAME, >VALUE, >PART, ...) case-insensitively."""
    if ">" not in txt:
        return txt
    table = dict(VARS)
    table.update(subst or {})
    return re.sub(r">([A-Za-z_][A-Za-z0-9_]*)", lambda m: table.get(m.group(1).upper(), m.group(0)), txt)


# ----------------------------------------------------------------- canvas
class Canvas:
    """Collects SVG fragments per layer. Coordinates are EAGLE ones (Y up); Y is flipped on output."""

    def __init__(self, layers):
        self.layers = layers
        self.items = {}
        self.bbox = [1e9, 1e9, -1e9, -1e9]
        self.no_mirror_text = False  # schematics never show mirrored text
        # data collected for the 3D view (drills are (center, radius, layer): 17 pads, 18 vias, 45 holes)
        self.outline_segs, self.outline_circles, self.drills, self.extra = [], [], [], {}

    def _bb(self, x, y, m=0.0):
        b = self.bbox
        b[0], b[1] = min(b[0], x - m), min(b[1], y - m)
        b[2], b[3] = max(b[2], x + m), max(b[3], y + m)

    def add(self, layer, s):
        self.items.setdefault(layer, []).append(s)

    def wire(self, layer, p1, p2, w, curve=0.0, cap="round", style=None):
        w = max(w, 0.1) if w <= 0 else w
        self._bb(*p1, m=w / 2)
        self._bb(*p2, m=w / 2)
        a = "%.4f,%.4f" % (p1[0], -p1[1])
        b = "%.4f,%.4f" % (p2[0], -p2[1])
        d = "M%s %s" % (a, arc_seg(p1, p2, curve))
        if abs(curve) > 0.01 and p1 != p2:
            chord = math.dist(p1, p2)
            th = math.radians(min(abs(curve), 359.9))
            r = chord / (2 * math.sin(th / 2))
            # extend bbox with the arc midpoint (offset from the chord midpoint by the sagitta)
            mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
            sag = r * (1 - math.cos(th / 2)) if th <= math.pi else r * (1 + math.cos(math.pi - th / 2))
            nx, ny = -(p2[1] - p1[1]) / chord, (p2[0] - p1[0]) / chord
            sgn = 1 if curve > 0 else -1  # CCW arcs bulge to the right of the p1->p2 direction
            self._bb(mx - sgn * nx * sag, my - sgn * ny * sag, m=w / 2)
        dash = ' stroke-dasharray="%s"' % DASH[style] if style in DASH else ""
        if dash:
            cap = "butt"
        self.add(layer, '<path d="%s" fill="none" stroke="currentColor" stroke-width="%.4f" '
                        'stroke-linecap="%s"%s/>' % (d, w, cap, dash))

    def poly(self, layer, pts, fill=True, w=0.0, opacity=1.0, curves=None):
        """curves[i] is the EAGLE curve angle of the segment from pts[i] to the next point."""
        if len(pts) < 2:
            return
        for p in pts:
            self._bb(*p, m=w / 2)
        if curves and any(abs(c) > 0.01 for c in curves):
            d = "M%.4f,%.4f" % (pts[0][0], -pts[0][1])
            for i, c in enumerate(curves):
                d += " " + arc_seg(pts[i], pts[(i + 1) % len(pts)], c)
            d += " Z"
        else:
            d = "M" + " L".join("%.4f,%.4f" % (x, -y) for x, y in pts) + " Z"
        st = 'fill="currentColor"' if fill else 'fill="none"'
        if fill and opacity < 1:
            st += ' fill-opacity="%.2f"' % opacity
        if w > 0:
            st += ' stroke="currentColor" stroke-width="%.4f" stroke-linejoin="round"' % w
        self.add(layer, '<path d="%s" %s/>' % (d, st))

    def circle(self, layer, c, r, w=0.0, fill=None, color=None, cls=None):
        """Ring when w>0 and no fill; filled disk when w==0 (EAGLE convention) or fill=True.
        cls adds a CSS class (used to strip 2D-only decorations from the 3D texture)."""
        self._bb(*c, m=r + w / 2)
        filled = fill if fill is not None else (w <= 0)
        col = color or "currentColor"
        ca = ' class="%s"' % cls if cls else ""
        if filled:
            self.add(layer, '<circle cx="%.4f" cy="%.4f" r="%.4f" fill="%s"%s/>' % (c[0], -c[1], r, col, ca))
        else:
            self.add(layer, '<circle cx="%.4f" cy="%.4f" r="%.4f" fill="none" stroke="%s" '
                            'stroke-width="%.4f"%s/>' % (c[0], -c[1], r, col, w, ca))

    def text(self, layer, x, y, size, ang, txt, align="bottom-left", mirror=False, spin=False, dist=50.0,
             fit=True):
        """Draw (possibly multi-line) text at absolute position/angle, honoring EAGLE alignment."""
        if not txt:
            return
        lines = txt.split("\n")
        if self.no_mirror_text:
            mirror = False
        ang %= 360.0
        parts = (align or "bottom-left").split("-")
        v, h = ("center", "center") if parts == ["center"] else parts
        if not spin and 90.0 < ang <= 270.0:  # upside-down text is flipped by 180 degrees
            ang = (ang + 180.0) % 360.0
            h = {"left": "right", "right": "left"}.get(h, h)
            v = {"top": "bottom", "bottom": "top"}.get(v, v)
        anchor = {"left": "start", "center": "middle", "right": "end"}[h]
        if mirror:
            anchor = {"start": "end", "end": "start"}.get(anchor, anchor)
        pitch = size * (1.0 + dist / 100.0)  # line distance (EAGLE default: 50% of the size)
        block = (len(lines) - 1) * pitch      # distance between first and last baseline
        # baseline of the first line, relative to the anchor point (local Y points down)
        first = {"bottom": -block, "center": -block / 2 + 0.5 * size, "top": size}[v]
        maxlen = max(max(len(l.replace("!", "")), 1) for l in lines) * size * 0.62
        ar = math.radians(ang)  # bbox: anchor point and the far end of the longest line
        self._bb(x, y, m=size * 0.5)
        if fit:  # very long texts (e.g. bus names) must not dominate the initial view
            self._bb(x + maxlen * math.cos(ar), y + maxlen * math.sin(ar), m=size * 0.5 + block)
        tr = "translate(%.4f,%.4f) rotate(%.3f)%s" % (x, -y, -ang, " scale(-1,1)" if mirror else "")
        spans = []
        for k, ln in enumerate(lines):
            ln_len = max(len(ln.replace("!", "")), 1) * size * 0.62
            spans.append('<tspan x="0" y="%.4f" textLength="%.4f" lengthAdjust="spacingAndGlyphs">%s</tspan>'
                         % (first + k * pitch, ln_len, markup(ln) if ln else "&#160;"))
        self.add(layer, '<text transform="%s" font-family="DejaVu Sans Mono,Consolas,monospace" '
                        'font-size="%.4f" text-anchor="%s" fill="currentColor">%s</text>'
                 % (tr, size * 1.25, anchor, "".join(spans)))


# ----------------------------------------------------------------- parsing
def parse_layers(drawing):
    out = {}
    for l in drawing.find("layers").findall("layer"):
        out[int(l.get("number"))] = {"name": l.get("name"), "color": int(l.get("color", 7)),
                                     "visible": l.get("visible") == "yes", "fill": int(l.get("fill", 1))}
    return out


def parse_libs(libs_el):
    """Index packages, symbols, device sets (gates + pad connections) by library name."""
    out = {}
    if libs_el is None:
        return out
    for lib in libs_el.findall("library"):
        L = {"packages": {}, "symbols": {}, "gates": {}, "addlevel": {}, "devmap": {}}
        pk = lib.find("packages")
        if pk is not None:
            for p in pk.findall("package"):
                L["packages"][p.get("name")] = p
        sy = lib.find("symbols")
        if sy is not None:
            for s in sy.findall("symbol"):
                L["symbols"][s.get("name")] = s
        ds = lib.find("devicesets")
        if ds is not None:
            for d in ds.findall("deviceset"):
                n = d.get("name")
                L["gates"][n] = {g.get("name"): g.get("symbol") for g in d.iter("gate")}
                L["addlevel"][n] = {g.get("name"): g.get("addlevel", "next") for g in d.iter("gate")}
                for dv in d.iter("device"):
                    L["devmap"][(n, dv.get("name", ""))] = {
                        (c.get("gate"), c.get("pin")): c.get("pad") for c in dv.iter("connect")}
        # The same library name can appear several times with different URNs (cloud vs local copy),
        # so index by (name, urn) first and keep a plain-name fallback for files without library_urn
        out[(lib.get("name"), lib.get("urn"))] = L
        out.setdefault(lib.get("name"), L)
    return out


def find_lib(libs, el):
    """Look up the library an element/part refers to, honoring library_urn when present."""
    name = el.get("library")
    return libs.get((name, el.get("library_urn"))) or libs.get(name)


# ----------------------------------------------------------------- shared drawing
def draw_common(cv, ch, tf, ml, subst=None, skip_dyn=False, pour=False):
    """Draw wire/rectangle/circle/polygon/text/hole children. Returns True if handled."""
    t = ch.tag
    if t == "wire":
        L = ml(int(ch.get("layer")))
        p1, p2 = tf.pt(num(ch, "x1"), num(ch, "y1")), tf.pt(num(ch, "x2"), num(ch, "y2"))
        curve = num(ch, "curve")
        cv.wire(L, p1, p2, num(ch, "width"), -curve if tf.m else curve,
                "flat" if ch.get("cap") == "flat" else "round", ch.get("style"))
        if L == 20:  # board outline (Dimension layer) for the 3D view
            cv.outline_segs.append((p1, p2, -curve if tf.m else curve))
    elif t == "rectangle":
        L = ml(int(ch.get("layer")))
        x1, y1, x2, y2 = (num(ch, k) for k in ("x1", "y1", "x2", "y2"))
        pts = rect_pts((x1 + x2) / 2, (y1 + y2) / 2, abs(x2 - x1), abs(y2 - y1), parse_rot(ch.get("rot"))[2])
        cv.poly(L, [tf.pt(*p) for p in pts])
    elif t == "circle":
        L = ml(int(ch.get("layer")))
        cc = tf.pt(num(ch, "x"), num(ch, "y"))
        cv.circle(L, cc, num(ch, "radius"), num(ch, "width"))
        if L == 20:
            cv.outline_circles.append((cc, num(ch, "radius")))
    elif t == "polygon":
        L = ml(int(ch.get("layer")))
        vs = ch.findall("vertex")
        pts = [tf.pt(num(v, "x"), num(v, "y")) for v in vs]
        curves = [(-num(v, "curve") if tf.m else num(v, "curve")) for v in vs]  # arc to the next vertex
        w = num(ch, "width")
        if pour:  # pours are not recomputed: show translucent fill + outline
            cv.poly(L, pts, fill=True, w=max(w, 0.1), opacity=0.35, curves=curves)
        else:
            cv.poly(L, pts, fill=True, w=w, curves=curves)
    elif t == "hole":
        hc = tf.pt(num(ch, "x"), num(ch, "y"))
        hr = num(ch, "drill") / 2
        cv.circle(45, hc, hr, 0, fill=True, color="#000")  # real hole: opaque black disk, like a pad drill
        cv.circle(45, hc, hr, 0.1, fill=False, cls="hr")   # thin outline so the hole stays visible on bare board
        cv.drills.append((hc, hr, 45))
    elif t == "text":
        txt = ch.text or ""
        if txt.strip().upper() in (">NAME", ">VALUE") and skip_dyn:
            return True
        txt = expand_vars(txt, subst)
        L = ml(int(ch.get("layer")))
        tm, ts, r = parse_rot(ch.get("rot"))
        ang = tf.rot + ((180.0 - r) if tf.m else r)
        x, y = tf.pt(num(ch, "x"), num(ch, "y"))
        cv.text(L, x, y, num(ch, "size", 1.27), ang, txt, ch.get("align", "bottom-left"), tf.m != tm, ts,
                num(ch, "distance", 50.0))
    else:
        return False
    return True


# Design rules of the board being rendered (parsed from <designrules>, values in mm)
DESIGN_RULES = {}
UNIT_MM = {"": 1.0, "mm": 1.0, "mil": 0.0254, "inch": 25.4, "in": 25.4, "micron": 0.001, "um": 0.001}


def parse_design_rules(board):
    """Read the restring parameters (rv* = ratio, rl* = length) from the file's own design rules."""
    DESIGN_RULES.clear()
    dr = board.find("designrules")
    for pm in (dr.iter("param") if dr is not None else []):
        name, val = pm.get("name", ""), pm.get("value", "")
        m = re.match(r"^\s*(-?[\d.]+)\s*([a-zA-Z]*)\s*$", val)
        if not m:
            continue
        if name.startswith("rv"):
            DESIGN_RULES[name] = float(m.group(1))
        elif name.startswith("rl"):
            DESIGN_RULES[name] = float(m.group(1)) * UNIT_MM.get(m.group(2).lower(), 1.0)


def pad_dia(drill, dia, kind="PadTop"):
    """Pad/via diameter: explicit value, else drill + 2 * restring from the file's design rules.
    kind is the rule suffix: PadTop/PadBottom/PadInner or ViaOuter/ViaInner."""
    if dia:
        return dia
    # fallbacks are EAGLE's factory defaults, used only when the file has no such parameter
    rv = DESIGN_RULES.get("rv" + kind, 0.25)
    lo = DESIGN_RULES.get("rlMin" + kind, 0.254)
    hi = DESIGN_RULES.get("rlMax" + kind, 0.508)
    return drill + 2 * min(max(drill * rv, lo), hi)


# ----------------------------------------------------------------- board
def draw_element(cv, el, libs):
    m, _spin, a = parse_rot(el.get("rot"))
    tf = Tf(num(el, "x"), num(el, "y"), a, m)
    lib = find_lib(libs, el) or {"packages": {}}
    pkg = lib["packages"].get(el.get("package"))
    if pkg is None:
        lname = el.get("library")
        why = ("library '%s' not present in the file" % lname if find_lib(libs, el) is None else
               "library '%s' has no package '%s' (it contains %d packages)"
               % (lname, el.get("package"), len(lib["packages"])))
        warn("%s: %s" % (el.get("name"), why))
        missing_marker(cv, tf.x, tf.y, el.get("name", "?"))
        return
    smashed = el.get("smashed") == "yes"
    name, value = el.get("name", ""), el.get("value", "")
    subst = {"NAME": name, "VALUE": value}
    for at in el.findall("attribute"):  # user attributes usable as >ATTRIBUTE in package texts
        if at.get("value") is not None and at.get("name", "").upper() not in subst:
            subst[at.get("name", "").upper()] = at.get("value")

    def ml(n):
        return MIRROR_LAYERS.get(n, n) if m else n

    for ch in pkg:
        if ch.tag == "smd":
            L = ml(int(ch.get("layer", 1)))
            rr = num(ch, "roundness") / 100.0
            dx, dy = num(ch, "dx"), num(ch, "dy")
            pts = rrect_pts(num(ch, "x"), num(ch, "y"), dx, dy, parse_rot(ch.get("rot"))[2], rr * min(dx, dy) / 2)
            cv.poly(L, [tf.pt(*p) for p in pts])
            cv.extra.setdefault(("smd", L), []).append(cv.items[L][-1])  # SMD pads (exposed copper in 3D)
        elif ch.tag == "pad":
            drill = num(ch, "drill")
            dia = pad_dia(drill, num(ch, "diameter"))
            c = tf.pt(num(ch, "x"), num(ch, "y"))
            shape = ch.get("shape", "round")
            pr = parse_rot(ch.get("rot"))[2]
            cx, cy = num(ch, "x"), num(ch, "y")
            if shape == "square":
                pts = rect_pts(cx, cy, dia, dia, pr)
            elif shape == "octagon":
                pts = [(cx + dia / 2 / math.cos(math.pi / 8) * math.cos(math.radians(pr + 22.5 + 45 * k)),
                        cy + dia / 2 / math.cos(math.pi / 8) * math.sin(math.radians(pr + 22.5 + 45 * k)))
                       for k in range(8)]
            elif shape in ("long", "offset"):
                length = dia * 2.0
                off = (dia / 2) if shape == "offset" else 0.0
                r = math.radians(pr)
                pts = rrect_pts(cx + off * math.cos(r), cy + off * math.sin(r), length, dia, pr, dia / 2)
            else:
                pts = None
            if pts:
                cv.poly(17, [tf.pt(*p) for p in pts])
            else:
                cv.circle(17, c, dia / 2, 0, fill=True)
            cv.circle(17, c, drill / 2, 0, fill=True, color="#000")  # drill hole
            cv.drills.append((c, drill / 2, 17))
        else:
            draw_common(cv, ch, tf, ml, subst, skip_dyn=smashed)
    if smashed:  # name/value texts carry their own absolute position
        for at in el.findall("attribute"):
            if at.get("x") is None or at.get("display") == "off":
                continue
            an = at.get("name", "").upper()
            txt = name if an == "NAME" else value if an == "VALUE" else at.get("value", "")
            tm, ts, r = parse_rot(at.get("rot"))
            cv.text(int(at.get("layer", 25)), num(at, "x"), num(at, "y"), num(at, "size", 1.27), r, txt,
                    at.get("align", "bottom-left"), tm, ts)


def render_board(root):
    d = root.find("drawing")
    layers = parse_layers(d)
    b = d.find("board")
    libs = parse_libs(b.find("libraries"))
    parse_design_rules(b)
    cv = Canvas(layers)
    ident = Tf()
    plain = b.find("plain")
    if plain is not None:
        for ch in plain:
            draw_common(cv, ch, ident, lambda n: n)
    els = b.find("elements")
    if els is not None:
        for el in els.findall("element"):
            draw_element(cv, el, libs)
    sigs = b.find("signals")
    if sigs is not None:
        for sig in sigs.findall("signal"):
            for ch in sig:
                if ch.tag == "via":
                    drill = num(ch, "drill")
                    dia = pad_dia(drill, num(ch, "diameter"), "ViaOuter")
                    c = (num(ch, "x"), num(ch, "y"))
                    cv.circle(18, c, dia / 2, 0, fill=True)
                    cv.circle(18, c, drill / 2, 0, fill=True, color="#000")
                    cv.drills.append((c, drill / 2, 18))
                elif ch.tag in ("wire", "polygon"):
                    draw_common(cv, ch, ident, lambda n: n, pour=True)
    return [("", cv, BOARD_ORDER)]


# ----------------------------------------------------------------- schematic
def draw_xref_flag(cv, layer, x, y, size, rot, name):
    """Draw a net label with xref="yes" as EAGLE does: a pentagonal flag whose tip sits on the
    label anchor and whose body extends along the label direction, with the net name inside."""
    m, _s, a = parse_rot(rot)
    t = Tf(0, 0, a, m)
    d, n = t.pt(1, 0), t.pt(0, 1)  # direction along the flag / perpendicular
    h, mg = size * 1.3, size * 0.4
    length = h / 2 + mg + max(len(name.replace("!", "")), 1) * size * 0.62 + mg

    def P(u, v):
        return (x + d[0] * u + n[0] * v, y + d[1] * u + n[1] * v)

    cv.poly(layer, [P(0, 0), P(h / 2, h / 2), P(length, h / 2), P(length, -h / 2), P(h / 2, -h / 2)],
            fill=False, w=0.2)
    sx, sy = P(h / 2 + mg, 0)
    cv.text(layer, sx, sy, size, math.degrees(math.atan2(d[1], d[0])), name, "center-left")


def draw_symbol(cv, sym, tf, libs_pad, inst_name, value, smashed, gate_label, extra=None):
    """Draw one symbol instance. libs_pad maps (gate, pin) -> pad number for this device."""
    subst = {"NAME": gate_label, "VALUE": value}
    subst.update(extra or {})

    def ml(n):
        return n

    for ch in sym:
        if ch.tag == "pin":
            draw_pin(cv, ch, tf, libs_pad)
        else:
            draw_common(cv, ch, tf, ml, subst, skip_dyn=smashed)


def draw_pin(cv, pin, tf, pads):
    x, y = num(pin, "x"), num(pin, "y")
    ln = PIN_LEN.get(pin.get("length", "long"), 7.62)
    m, _s, r = parse_rot(pin.get("rot"))
    rr = math.radians(r)
    dx, dy = math.cos(rr), math.sin(rr)
    p0, p1 = tf.pt(x, y), tf.pt(x + dx * ln, y + dy * ln)
    cv.wire(94, p0, p1, 0.1524)
    cv.circle(93, p0, 0.25, 0, fill=True)  # connection point marker
    vis = pin.get("visible", "both")
    name = re.sub(r"@\d+$", "", pin.get("name", ""))
    vert = abs(dy) > 0.5
    ang_local = 90.0 if vert else 0.0
    if vis in ("pin", "both") and name:
        inward = dx > 0.5 or dy > 0.5  # the symbol body lies in this direction
        ex, ey = x + dx * (ln + 0.762), y + dy * (ln + 0.762)
        al = "center-left" if inward else "center-right"
        tx, ty = tf.pt(ex, ey)
        cv.text(95, tx, ty, 1.778, tf.rot + ((180 - ang_local) if tf.m else ang_local), name, al, tf.m)
    if vis in ("pad", "both"):
        pad = pads.get((pin.get("_gate"), pin.get("name")))
        if pad:
            mx, my = x + dx * ln / 2, y + dy * ln / 2
            ox, oy = (-0.3, 0.0) if vert else (0.0, 0.3)
            tx, ty = tf.pt(mx + ox, my + oy)
            cv.text(95, tx, ty, 1.27, tf.rot + ((180 - ang_local) if tf.m else ang_local), pad,
                    "bottom-center", tf.m)


def render_sch(root):
    d = root.find("drawing")
    layers = parse_layers(d)
    s = d.find("schematic")
    libs = parse_libs(s.find("libraries"))
    parts = {p.get("name"): p for p in s.find("parts").findall("part")}
    sheets = s.find("sheets").findall("sheet")
    out = []
    for idx, sh in enumerate(sheets, 1):
        cv = Canvas(layers)
        cv.no_mirror_text = True
        ident = Tf()
        plain = sh.find("plain")
        if plain is not None:
            for ch in plain:
                draw_common(cv, ch, ident, lambda n: n)
        netmap = {}
        nets_el = sh.find("nets")
        for net in (nets_el.findall("net") if nets_el is not None else []):
            for pr in net.iter("pinref"):
                netmap[(pr.get("part"), pr.get("gate"), pr.get("pin"))] = net.get("name", "")
        insts = sh.find("instances")
        for inst in (insts.findall("instance") if insts is not None else []):
            part = parts.get(inst.get("part"))
            if part is None:
                continue
            lib = find_lib(libs, part)
            ix, iy = num(inst, "x"), num(inst, "y")
            if lib is None:
                warn("%s: library '%s' not present in the file" % (part.get("name"), part.get("library")))
                missing_marker(cv, ix, iy, part.get("name", "?"))
                continue
            dset = part.get("deviceset")
            gates = lib["gates"].get(dset)
            if gates is None:
                why = "library '%s' has no deviceset '%s'" % (part.get("library"), dset)
            elif inst.get("gate") not in gates:
                why = "deviceset '%s' has no gate '%s' (gates: %s)" % (dset, inst.get("gate"), ", ".join(gates))
            elif gates[inst.get("gate")] not in lib["symbols"]:
                why = "symbol '%s' is missing in library '%s'" % (gates[inst.get("gate")], part.get("library"))
            else:
                why = None
            if why:
                warn("%s: %s" % (part.get("name"), why))
                missing_marker(cv, ix, iy, part.get("name", "?"))
                continue
            sym = lib["symbols"][gates[inst.get("gate")]]
            pads = {}
            for (g, pn), pad in lib["devmap"].get((part.get("deviceset"), part.get("device", "")), {}).items():
                pads[(g, pn)] = pad
            # tag pins with their gate so draw_pin can look up the pad number
            for pin in sym.findall("pin"):
                pin.set("_gate", inst.get("gate"))
            m, _sp, a = parse_rot(inst.get("rot"))
            tf = Tf(num(inst, "x"), num(inst, "y"), a, m)
            gname = inst.get("gate", "")
            # EAGLE rule: 'always'/'must'/'request' gates always show their gate name; 'next'/'can'
            # gates show it only when the device has more than one gate of that kind
            levels = lib["addlevel"].get(dset, {})
            level = levels.get(gname, "next")
            same_kind = sum(1 for v in levels.values() if v in ("next", "can"))
            add = level in ("always", "must", "request") or same_kind > 1
            label = part.get("name") + (gname if add else "")
            smashed = inst.get("smashed") == "yes"
            value = part.get("value")
            if value is None:
                sup = [pn for pn in sym.findall("pin") if pn.get("direction") == "sup"]
                if sup:  # supply symbols show the name of the net their pin is connected to
                    value = netmap.get((part.get("name"), inst.get("gate"), sup[0].get("name")),
                                       sup[0].get("name"))
                else:
                    # EAGLE default: deviceset name with '*' replaced by the technology (or the technology
                    # appended when there is no '*'), then the device name ('?' is replaced by it, else appended)
                    ds, dv, tech = part.get("deviceset", ""), part.get("device", ""), part.get("technology", "")
                    value = ds.replace("*", tech) if "*" in ds else ds + tech
                    value = value.replace("?", dv) if "?" in value else value + dv
            extra = {"PART": part.get("name", ""), "GATE": gname, "SHEET": "%d/%d" % (idx, len(sheets))}
            for pa in part.findall("attribute"):  # part attributes can be used as >ATTRIBUTE in symbol texts
                extra.setdefault(pa.get("name", "").upper(), pa.get("value", ""))
            draw_symbol(cv, sym, tf, pads, part.get("name"), value, smashed, label, extra)
            if smashed:
                for at in inst.findall("attribute"):
                    if at.get("x") is None or at.get("display") == "off":
                        continue
                    an = at.get("name", "").upper()
                    txt = label if an == "NAME" else value if an == "VALUE" else at.get("value", "")
                    tm, ts, r = parse_rot(at.get("rot"))
                    cv.text(int(at.get("layer", 95)), num(at, "x"), num(at, "y"), num(at, "size", 1.778), r,
                            txt, at.get("align", "bottom-left"), tm, ts)
        # nets and busses
        for tag, grp in (("net", "nets"), ("bus", "busses")):
            g = sh.find(grp)
            for net in (g.findall(tag) if g is not None else []):
                for seg in net.findall("segment"):
                    for ch in seg:
                        if ch.tag == "wire":
                            draw_common(cv, ch, ident, lambda n: n)
                        elif ch.tag == "junction":
                            cv.circle(91, (num(ch, "x"), num(ch, "y")), 0.508, 0, fill=True)
                        elif ch.tag == "label":
                            m, sp, a = parse_rot(ch.get("rot"))
                            name = net.get("name", "")
                            if tag == "bus":  # bus labels show only the name, not the member list
                                name = name.split(":")[0]
                            if ch.get("xref") == "yes" and tag == "net":  # flag-style label
                                draw_xref_flag(cv, int(ch.get("layer", 95)), num(ch, "x"), num(ch, "y"),
                                               num(ch, "size", 1.778), ch.get("rot"), name)
                            else:
                                cv.text(int(ch.get("layer", 95)), num(ch, "x"), num(ch, "y"),
                                        num(ch, "size", 1.778), a, name, "bottom-left", m, sp)
        out.append(("" if len(sheets) == 1 else "_sheet%d" % idx, cv, SCH_ORDER))
    return out


# ----------------------------------------------------------------- output
# EAGLE layer fill styles other than solid (1): (hatch kind, spacing in mm). 0 = empty.
FILL_PATTERNS = {2: ("/", 0.5), 3: ("/", 0.8), 4: ("\\", 0.8), 5: ("-", 0.8), 6: ("\\", 0.5), 7: ("|", 0.8),
                 8: ("/", 1.6), 9: ("-", 0.5), 10: ("/", 1.2), 11: ("x", 1.0)}


# Hatch tile size in screen pixels (EAGLE patterns do not scale with the zoom level)
FILL_PX = {2: 4, 3: 6, 4: 6, 5: 6, 6: 4, 7: 6, 8: 8, 9: 4, 10: 8, 11: 8}


def pattern_def(pid, color, kind, sp, px=6):
    """SVG <pattern> drawing hatch lines (the layer color shows through the gaps, i.e. transparent)."""
    rot = {"/": -45, "\\": 45, "-": 0, "|": 90, "x": 45}[kind]
    h = sp / 2
    lines = "M0,%.3f L%.3f,%.3f" % (h, sp, h)
    if kind == "x":
        lines += " M%.3f,0 L%.3f,%.3f" % (h, h, sp)
    return ('<pattern id="%s" patternUnits="userSpaceOnUse" width="%.3f" height="%.3f" '
            'patternTransform="rotate(%d)" data-kind="%s" data-px="%d">'
            '<path d="%s" stroke="%s" stroke-width="0.12" fill="none"/></pattern>'
            % (pid, sp, sp, rot, kind, px, lines, color))


# Keepout / restrict layers: wires, polygon outlines and rings are drawn at least 32 mil wide and hatched,
# like the stop mask layers (whose items carry that width in the file)
KEEPOUT_RESTRICT = (39, 40, 41, 42, 43)
KEEPOUT_RESTRICT_WIDTH = 0.3  # in mm


def apply_fill(item, fill, pid, min_w=0.0):
    """Swap the solid fill of path/circle items for the layer's hatch pattern (texts stay solid).
    min_w > 0 also hatches strokes of any kind and widens thin ones to at least min_w."""
    if not (item.startswith("<path") or item.startswith("<circle")):
        return item
    target = "none" if fill == 0 else "url(#%s)" % pid
    item = item.replace('fill="currentColor"', 'fill="%s"' % target)
    if fill == 0 or 'stroke="currentColor"' not in item:
        return item
    m = re.search(r'stroke-width="([\d.]+)"', item)
    if min_w > 0 and m:
        item = item.replace(m.group(0), 'stroke-width="%.4f"' % max(float(m.group(1)), min_w), 1)
        item = item.replace('stroke="currentColor"', 'stroke="%s"' % target)
    elif "stroke-linecap" in item and m and float(m.group(1)) >= 0.4:  # wide wires (e.g. stop mask tracks)
        item = item.replace('stroke="currentColor"', 'stroke="%s"' % target)
    return item


def layer_color(layers, n):
    info = layers.get(n)
    return PALETTE.get(info["color"], "#c8c8c8") if info else "#c8c8c8"


def build_svg(cv, order):
    """Return (svg_text, layer_list, defs) where layer_list = [(id, label, color, visible)] and defs is the
    hatch <pattern> markup (mm based, reused by the 3D textures)."""
    x0, y0, x1, y1 = cv.bbox
    mg = max(x1 - x0, y1 - y0) * 0.03 + 1.0
    vb = (x0 - mg, -y1 - mg, (x1 - x0) + 2 * mg, (y1 - y0) + 2 * mg)
    used = [n for n in order if n in cv.items] + sorted(n for n in cv.items if n not in order)
    groups, info, defs = [], [], []
    for n in used:
        meta = cv.layers.get(n, {"name": str(n), "visible": True})
        col = layer_color(cv.layers, n)
        vis = meta["visible"]
        items, fill = cv.items[n], meta.get("fill", 1)
        if fill == 0 or fill in FILL_PATTERNS:  # non-solid layer fill style (hatched / empty)
            pid = "hatch%d" % n
            mw = KEEPOUT_RESTRICT_WIDTH if n in KEEPOUT_RESTRICT else 0.0

            if fill in FILL_PATTERNS:
                kind, sp = FILL_PATTERNS[fill]

                if mw > 0:
                    # Keepout hatch: line width and spacing use the same value.
                    defs.append(pattern_def(pid, col, kind, mw, px=FILL_PX.get(fill, 6)))
                else:
                    # Preserve the original hatch for all other layers.
                    defs.append(pattern_def(pid, col, kind, sp, px=FILL_PX.get(fill, 6)))

            items = [apply_fill(it, fill, pid, mw) for it in items]
        groups.append('<g id="L%d" color="%s"%s>\n%s\n</g>' % (
            n, col, "" if vis else ' style="display:none"', "\n".join(items)))
        info.append(("L%d" % n, "%d %s" % (n, meta["name"]), col, vis))
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%.3f %.3f %.3f %.3f">\n<defs>%s</defs>\n'
           '<rect x="%.3f" y="%.3f" width="%.3f" height="%.3f" fill="#000"/>\n<g id="content">\n%s\n</g>\n</svg>'
           % (vb + ("".join(defs),) + vb + ("\n".join(groups),)))
    return svg, info, "".join(defs)


HTML_TMPL = r"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>__TITLE__</title>
<style>
body{margin:0;display:flex;height:100vh;background:#000;color:#ddd;font:13px sans-serif}
#side{width:230px;overflow:auto;padding:8px;background:#161616;border-right:1px solid #333}
#side label{display:block;white-space:nowrap;cursor:pointer;padding:1px 0}
#side button{margin:0 4px 8px 0}
#view{flex:1;min-width:0;position:relative}
#view>svg{width:100%;height:100%;display:block;touch-action:none;cursor:grab}
#v3d{position:absolute;inset:0;display:none;background:#101010}
#v3d canvas{display:block}
#bar3d{position:absolute;top:8px;left:8px;z-index:2}
#bar3d button{margin-right:4px}
#bar3d label{margin-left:8px}
#msg3d{position:absolute;bottom:8px;left:8px;z-index:2;color:#999}
</style></head><body>
<div id="side"><b>__TITLE__</b><br><br>
<button id="fit">Fit</button><button id="all">All</button><button id="none">None</button>__FLIP____BTN3D__
__LAYERS__</div>
<div id="view">__SVG__
__OVERLAY3D__</div>
<script>
// Pan/zoom by editing the SVG viewBox; layers toggled through the display style.
const svg = document.querySelector('#view > svg');
const vb0 = svg.getAttribute('viewBox').split(' ').map(Number);
let vb = vb0.slice();
// Hatch patterns keep a constant size in screen pixels, like EAGLE's bitmap fill styles
const pats = [...document.querySelectorAll('pattern[data-px]')];
function scalePatterns() {
  const s = svg.getScreenCTM().a;
  if (!s) return;
  pats.forEach(p => {
    const t = (+p.dataset.px) / s, h = t / 2, path = p.firstElementChild;
    p.setAttribute('width', t); p.setAttribute('height', t);
    path.setAttribute('d', 'M0,' + h + ' L' + t + ',' + h + (p.dataset.kind === 'x' ? ' M' + h + ',0 L' + h + ',' + t : ''));
    path.setAttribute('stroke-width', 1.1 / s);
  });
}
const apply = () => { svg.setAttribute('viewBox', vb.join(' ')); scalePatterns(); };
window.addEventListener('resize', scalePatterns);
setTimeout(scalePatterns, 0);
document.getElementById('fit').onclick = () => { vb = vb0.slice(); apply(); };
// Flip: mirror the whole drawing horizontally around the center of the initial view (board only)
const flipBtn = document.getElementById('flip');
if (flipBtn) {
  let flipped = false;
  flipBtn.onclick = () => {
    flipped = !flipped;
    document.getElementById('content').setAttribute('transform',
      flipped ? 'translate(' + (2 * vb0[0] + vb0[2]) + ',0) scale(-1,1)' : '');
  };
}
const boxes = [...document.querySelectorAll('#side input')];
boxes.forEach(b => b.onchange = () => {
  document.getElementById(b.dataset.l).style.display = b.checked ? '' : 'none';
  if (window.layersChanged) window.layersChanged();  // keeps the 3D view in sync (board only)
});
document.getElementById('all').onclick = () => boxes.forEach(b => { b.checked = true; b.onchange(); });
document.getElementById('none').onclick = () => boxes.forEach(b => { b.checked = false; b.onchange(); });
const toSvg = (cx, cy) => {
  const p = svg.createSVGPoint(); p.x = cx; p.y = cy;
  return p.matrixTransform(svg.getScreenCTM().inverse());
};
svg.addEventListener('wheel', e => {
  e.preventDefault();
  const k = e.deltaY > 0 ? 1.15 : 1 / 1.15;
  const p = toSvg(e.clientX, e.clientY);
  vb = [p.x - (p.x - vb[0]) * k, p.y - (p.y - vb[1]) * k, vb[2] * k, vb[3] * k];
  apply();
}, {passive: false});
let drag = null;
svg.addEventListener('pointerdown', e => { drag = [e.clientX, e.clientY]; svg.setPointerCapture(e.pointerId); });
svg.addEventListener('pointerup', () => drag = null);
svg.addEventListener('pointermove', e => {
  if (!drag) return;
  const s = svg.getScreenCTM().a;
  vb[0] -= (e.clientX - drag[0]) / s; vb[1] -= (e.clientY - drag[1]) / s;
  drag = [e.clientX, e.clientY]; apply();
});
</script>
__SCRIPTS3D__</body></html>
"""

OVERLAY_3D = ('<div id="v3d"><div id="bar3d"><button data-v="iso">Iso</button><button data-v="top">Top</button>'
              '<button data-v="bottom">Bottom</button>'
              '<label>Mask <select id="s-mask"></select></label>'
              '<label>Finish <select id="s-fin"></select></label>'
              '<label>Pads <select id="s-pad"></select></label></div><div id="msg3d"></div></div>')


def build_html(title, svg, info, flip=False, three=None):
    """Standalone 2D viewer. three = (json_data, three_js, controls_js) adds the embedded 3D view."""
    rows = "\n".join(
        '<label><input type="checkbox" data-l="%s"%s><span style="color:%s">&#9632;</span> %s</label>'
        % (i, " checked" if vis else "", col, html.escape(lab)) for i, lab, col, vis in info)
    page = (HTML_TMPL.replace("__TITLE__", html.escape(title))
            .replace("__FLIP__", '<button id="flip">Flip</button>' if flip else "")
            .replace("__BTN3D__", '<button id="b3d">3D rendering</button>' if three else "")
            .replace("__LAYERS__", rows).replace("__SVG__", svg)
            .replace("__OVERLAY3D__", OVERLAY_3D if three else ""))
    scripts = ""
    if three:  # big payloads are inserted last so their content is never touched by the replacements above
        data, three_js, controls_js = three
        scripts = ('<script type="application/json" id="data3d">' + data + "</script>\n"
                   "<script>" + three_js + "</script>\n<script>" + controls_js + "</script>\n"
                   "<script>" + JS3D + "</script>\n")
    return page.replace("__SCRIPTS3D__", scripts)


# ----------------------------------------------------------------- 3D view
BOARD_THICKNESS = 1.6  # mm (EAGLE .brd files do not store the stack-up)


def arc_points(p1, p2, curve, step=6.0):
    """Polyline for an EAGLE arc from p1 (excluded) to p2 (included); curve in degrees, CCW positive."""
    chord = math.dist(p1, p2)
    if abs(curve) <= 0.01 or chord < 1e-9:
        return [p2]
    th = math.radians(curve)
    r = chord / (2 * math.sin(abs(th) / 2))
    mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
    lx, ly = -(p2[1] - p1[1]) / chord, (p2[0] - p1[0]) / chord  # left normal of p1 -> p2
    d = r * math.cos(abs(th) / 2) * (1 if th > 0 else -1)       # signed distance chord midpoint -> center
    cx, cy = mx + lx * d, my + ly * d
    a0 = math.atan2(p1[1] - cy, p1[0] - cx)
    n = max(2, int(abs(curve) / step) + 1)
    pts = [(cx + r * math.cos(a0 + th * i / n), cy + r * math.sin(a0 + th * i / n)) for i in range(1, n)]
    pts.append(p2)
    return pts


def poly_area(pts):
    return 0.5 * sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                     for i in range(len(pts)))


def point_in_poly(pt, poly):
    x, y, inside = pt[0], pt[1], False
    for i in range(len(poly)):
        x1, y1, x2, y2 = poly[i][0], poly[i][1], poly[(i + 1) % len(poly)][0], poly[(i + 1) % len(poly)][1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def build_outline(segs, circles, tol=0.05):
    """Chain Dimension-layer wires/arcs into closed loops. Returns (outer, holes) as point lists."""
    loops = [[(c[0] + r * math.cos(2 * math.pi * i / 48), c[1] + r * math.sin(2 * math.pi * i / 48))
              for i in range(48)] for c, r in circles]
    rem = list(segs)
    while rem:
        a, b, c = rem.pop(0)
        start, end, pts = a, b, [a] + arc_points(a, b, c)
        progress = True
        while progress and math.dist(end, start) > tol:
            progress = False
            for i, (a2, b2, c2) in enumerate(rem):
                if math.dist(a2, end) <= tol:
                    pts += arc_points(a2, b2, c2)
                    end = b2
                elif math.dist(b2, end) <= tol:
                    pts += arc_points(b2, a2, -c2)
                    end = a2
                else:
                    continue
                rem.pop(i)
                progress = True
                break
        if math.dist(end, start) <= tol and len(pts) >= 4:
            loops.append(pts[:-1])  # the last point repeats the first one
    if not loops:
        return None, []
    loops.sort(key=lambda l: -abs(poly_area(l)))
    outer = loops[0]
    return outer, [l for l in loops[1:] if point_in_poly(l[0], outer)]


# Layers that belong to one board side; every other visible layer is drawn on both faces
TOP_LAYERS = (1, 21, 23, 25, 27, 29, 31, 33, 35, 37, 39, 41, 51, 53)
BOTTOM_LAYERS = (16, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40, 42, 52, 54)

JS3D = r"""
// 3D view: the board outline is extruded and both faces are textured from the 2D layer groups that are
// currently ticked in the side panel. Every change of a checkbox rebuilds the textures and the drilled holes.
(function () {
  const D = JSON.parse(document.getElementById('data3d').textContent);
  const btn = document.getElementById('b3d'), host = document.getElementById('v3d');
  const msg = document.getElementById('msg3d'), svg2d = document.querySelector('#view > svg');
  const HINT = 'Left drag: rotate | wheel: zoom | right drag: pan | the 3D view follows the layer checkboxes';
  const W = D.bbox[2], H = D.bbox[3], T = D.thickness;
  const cx = D.bbox[0] + W / 2, cy = D.bbox[1] + H / 2;
  const V = p => new THREE.Vector2(p[0] - cx, p[1] - cy);
  const TOP = new Set(D.top_layers), BOT = new Set(D.bottom_layers);
  // Solder mask presets: [label, mask color, tracks seen through the mask, silkscreen color]
  const MASKS = {
    green: ['Green', '#0d6b36', '#2f9e58', '#f2f2f2'], red: ['Red', '#a31616', '#cf3b3b', '#f2f2f2'],
    blue: ['Blue', '#14409e', '#3c6bd0', '#f2f2f2'], yellow: ['Yellow', '#d4ae0a', '#ecd04a', '#151515'],
    white: ['White', '#dcdcdc', '#f6f6f6', '#151515'], black: ['Black', '#141414', '#2c2c2c', '#f2f2f2'],
    magenta: ['Magenta / Purple', '#8a1a7e', '#b24aa6', '#f2f2f2'], orange: ['Orange', '#d4621a', '#ee8a42', '#f2f2f2'],
    pink: ['Pink', '#d8648f', '#ef8fb2', '#f2f2f2'], gray: ['Gray', '#6f7377', '#8f9498', '#f2f2f2'],
    clear: ['Transparent (clear)', '#c2a066', '#b8733a', '#f2f2f2']};
  const FINISHES = {glossy: ['Glossy', 45, 0x3a3a3a], matte: ['Matte', 4, 0x101010]};
  const PADS = {gold: ['Gold (ENIG)', '#d9bf63'], tin: ['Tin (HASL)', '#c9ccd0'], copper: ['Bare copper', '#c87f4a']};
  const selMask = document.getElementById('s-mask'), selFin = document.getElementById('s-fin'),
        selPad = document.getElementById('s-pad');
  [[selMask, MASKS], [selFin, FINISHES], [selPad, PADS]].forEach(([sel, tab]) => {
    Object.keys(tab).forEach(k => sel.add(new Option(tab[k][0], k)));
    sel.onchange = () => window.layersChanged();
  });
  // colors for the current selection; any layer not listed here keeps its 2D color
  function palette() {
    const m = MASKS[selMask.value], p = PADS[selPad.value][1], s = m[3];
    return {base: m[1], pad: p, real: {1: m[2], 16: m[2], 17: p, 18: p,
            21: s, 22: s, 25: s, 26: s, 27: s, 28: s}};
  }
  const ser = new XMLSerializer();
  let renderer, scene, camera, controls, group = null, dist = 1;
  let active = false, ready = false, looping = false, timer = null, token = 0;

  const on = n => { const b = document.querySelector('#side input[data-l="L' + n + '"]'); return !!b && b.checked; };

  function pip(x, y, poly) {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const xi = poly[i][0], yi = poly[i][1], xj = poly[j][0], yj = poly[j][1];
      if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }

  // Face texture from the visible 2D layer groups (inner copper layers are not visible from outside)
  function textureSvg(top, pal) {
    const other = top ? BOT : TOP, cu = top ? 1 : 16;
    let body = '';
    document.querySelectorAll('#content > g').forEach(g => {
      const n = +g.id.slice(1);
      if (!on(n) || other.has(n) || (n >= 2 && n <= 15)) return;
      const c = g.cloneNode(true);
      c.querySelectorAll('.hr').forEach(e => e.remove());  // hole outline rings are 2D only
      c.removeAttribute('style'); c.removeAttribute('id');
      c.setAttribute('color', pal.real[n] || g.getAttribute('color'));
      body += ser.serializeToString(c);
      if (n === cu && D.smd[cu]) body += '<g color="' + pal.pad + '">' + D.smd[cu] + '</g>';  // exposed SMD pads
    });
    const y0 = -(D.bbox[1] + H);
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + D.px[0] + '" height="' + D.px[1] +
      '" viewBox="' + D.bbox[0] + ' ' + y0 + ' ' + W + ' ' + H + '"><defs>' + D.defs + '</defs>' +
      '<rect x="' + D.bbox[0] + '" y="' + y0 + '" width="' + W + '" height="' + H + '" fill="' + pal.base + '"/>' +
      body + '</svg>';
  }

  // Board shape: outline + cut-outs + real holes for every drill whose layer is visible
  // (pad drills = layer 17, via drills = layer 18, mounting holes = layer 45)
  function buildShape() {
    const shape = new THREE.Shape(D.outer.map(V));
    D.holes.forEach(h => shape.holes.push(new THREE.Path(h.map(V))));
    const seen = new Set();
    D.drills.forEach(d => {
      if (!on(d[3]) || d[2] <= 0) return;
      const k = d[0].toFixed(3) + ',' + d[1].toFixed(3) + ',' + d[2].toFixed(3);
      if (seen.has(k) || !pip(d[0], d[1], D.outer)) return;
      seen.add(k);
      const p = new THREE.Path();
      p.absarc(d[0] - cx, d[1] - cy, d[2], 0, Math.PI * 2, false);
      shape.holes.push(p);
    });
    return shape;
  }

  const img = s => new Promise((ok, ko) => {
    const url = URL.createObjectURL(new Blob([s], {type: 'image/svg+xml;charset=utf-8'}));
    const i = new Image();
    i.onload = () => { URL.revokeObjectURL(url); ok(i); };
    i.onerror = () => { URL.revokeObjectURL(url); ko(new Error('texture SVG could not be rasterized')); };
    i.src = url;
  });
  async function texture(s) {
    const a = await img(s);
    const c = document.createElement('canvas'); c.width = D.px[0]; c.height = D.px[1];
    c.getContext('2d').drawImage(a, 0, 0, c.width, c.height);
    const t = new THREE.CanvasTexture(c);
    t.encoding = THREE.sRGBEncoding; t.anisotropy = renderer.capabilities.getMaxAnisotropy();
    return t;
  }
  function face(shape, z, tex) {
    const fin = FINISHES[selFin.value];
    const g = new THREE.ShapeGeometry(shape, 16), p = g.attributes.position, u = g.attributes.uv;
    for (let i = 0; i < p.count; i++) u.setXY(i, (p.getX(i) + W / 2) / W, (p.getY(i) + H / 2) / H);
    g.translate(0, 0, z);
    return new THREE.Mesh(g, new THREE.MeshPhongMaterial({
      map: tex, side: THREE.DoubleSide, shininess: fin[1], specular: fin[2]}));
  }
  function disposeGroup(g) {
    g.traverse(o => {
      if (o.geometry) o.geometry.dispose();
      if (o.material) [].concat(o.material).forEach(m => { if (m.map) m.map.dispose(); m.dispose(); });
    });
  }

  async function rebuild() {
    const my = ++token;
    msg.textContent = 'Updating 3D view...';
    try {
      const shape = buildShape();
      const pal = palette();
      const [tt, tb] = await Promise.all([texture(textureSvg(true, pal)), texture(textureSvg(false, pal))]);
      if (my !== token) { tt.dispose(); tb.dispose(); return; }  // a newer rebuild superseded this one
      const g = new THREE.Group();
      const eg = new THREE.ExtrudeGeometry(shape, {depth: T, bevelEnabled: false, curveSegments: 16});
      eg.translate(0, 0, -T / 2);
      // caps are hidden (the textured faces replace them); the side walls also line the drilled holes
      g.add(new THREE.Mesh(eg, [new THREE.MeshBasicMaterial({visible: false}),
                                new THREE.MeshPhongMaterial({color: 0x9a8440, shininess: 10})]));
      g.add(face(shape, T / 2 + 0.02, tt));
      g.add(face(shape, -T / 2 - 0.02, tb));
      if (group) { scene.remove(group); disposeGroup(group); }
      group = g; scene.add(g);
      msg.textContent = HINT;
    } catch (e) { msg.textContent = '3D error: ' + e.message; }
  }

  function setView(x, y, z) {
    camera.position.set(x * dist, y * dist, z * dist);
    camera.up.set(0, 1, 0); controls.target.set(0, 0, 0); camera.lookAt(0, 0, 0); controls.update();
  }
  function resize() {
    if (!renderer) return;
    renderer.setSize(host.clientWidth, host.clientHeight);
    camera.aspect = host.clientWidth / host.clientHeight; camera.updateProjectionMatrix();
    controls.handleResize();
  }
  function init() {
    try { renderer = new THREE.WebGLRenderer({antialias: true}); }
    catch (e) { return false; }
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.outputEncoding = THREE.sRGBEncoding;
    host.insertBefore(renderer.domElement, host.firstChild);
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x101010);
    camera = new THREE.PerspectiveCamera(35, 1, 0.5, 20000);
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const l1 = new THREE.DirectionalLight(0xffffff, 0.7); l1.position.set(-1, -1, 2); scene.add(l1);
    const l2 = new THREE.DirectionalLight(0xffffff, 0.5); l2.position.set(1, 1, -2); scene.add(l2);
    dist = Math.max(W, H) * 1.8;
    controls = new THREE.TrackballControls(camera, renderer.domElement);
    controls.rotateSpeed = 3; controls.zoomSpeed = 1.2; controls.panSpeed = 0.8; controls.staticMoving = true;
    const views = {iso: [0, -0.55, 0.85], top: [0, 0, 1], bottom: [0, 0, -1]};
    host.querySelectorAll('#bar3d button').forEach(b => b.onclick = () => setView(...views[b.dataset.v]));
    window.addEventListener('resize', resize);
    host.style.display = 'block'; resize(); setView(...views.iso);
    ready = true;
    return true;
  }
  function loop() {
    if (!active) { looping = false; return; }
    looping = true; requestAnimationFrame(loop);
    controls.update(); renderer.render(scene, camera);
  }

  btn.onclick = () => {
    if (!active) {
      host.style.display = 'block';
      if (!ready && !init()) {
        host.style.display = 'none';
        btn.disabled = true; btn.textContent = '3D unavailable (no WebGL)';
        return;
      }
      active = true; svg2d.style.visibility = 'hidden'; btn.textContent = '2D view';
      resize(); rebuild(); if (!looping) loop();
    } else {
      active = false; host.style.display = 'none'; svg2d.style.visibility = ''; btn.textContent = '3D rendering';
    }
  };
  // called by the layer checkboxes of the 2D panel (debounced: All/None toggle many boxes at once)
  window.layersChanged = () => { if (active) { clearTimeout(timer); timer = setTimeout(rebuild, 300); } };
})();
"""


def embedded_js(blob):
    """Decode one of the embedded third-party scripts (zlib + base64) for inlining in a <script> tag."""
    return zlib.decompress(base64.b64decode("".join(blob.split()))).decode("utf-8").replace("</script", "<\\/script")


def build_3d_payload(cv, defs, log=print):
    """Return (json_data, three_js, controls_js) for the 3D view embedded in the 2D HTML, or None."""
    outer, holes = build_outline(cv.outline_segs, cv.outline_circles)
    if outer is None:
        log("note: 3D view skipped - no closed board outline found on layer 20 (Dimension)")
        return None
    xs, ys = [p[0] for p in outer], [p[1] for p in outer]
    bb = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    ppm = min(20.0, 4096.0 / max(bb[2], bb[3]))  # texture resolution in pixels per mm
    rnd = lambda pts: [[round(x, 4), round(y, 4)] for x, y in pts]
    data = {"outer": rnd(outer), "holes": [rnd(h) for h in holes],
            "bbox": list(bb), "thickness": BOARD_THICKNESS,
            "px": [max(1, int(bb[2] * ppm)), max(1, int(bb[3] * ppm))],
            "drills": [[round(c[0], 4), round(c[1], 4), round(r, 4), layer] for c, r, layer in cv.drills if r > 0],
            "smd": {str(n): "".join(cv.extra.get(("smd", n), [])) for n in (1, 16)},
            "defs": defs, "top_layers": list(TOP_LAYERS), "bottom_layers": list(BOTTOM_LAYERS)}
    return (json.dumps(data, separators=(",", ":")).replace("</", "<\\/"),
            embedded_js(THREE_JS_B64), embedded_js(CONTROLS_JS_B64))


CREDIT_URL = "https://www.amigatronic.com"
VERSION = "1.0"
VERSION_DATE = "2026-10-12"

HELP_TEXT = """EaglePCBView3D - Help
Version 1.0 (2026-10-12)
by Arky - amigatronic.com (https://www.amigatronic.com)

WHAT IT DOES
Reads EAGLE .brd (board) and .sch (schematic) XML files and writes, for each one:
  <name>_brd.svg / <name>_brd.htm   and   <name>_sch.svg / <name>_sch.htm
The 2D .htm files are standalone viewers: mouse wheel = zoom, drag = pan,
side panel = layer on/off, "Fit" = reset the view, "Flip" (board) = mirror the view.
Hatched layer fill styles keep a constant size on screen, like in EAGLE.
Holes (layer 45) are drawn as real holes, like the pad drills.

3D VIEW (board only, no component models)
Every board .htm file contains a "3D rendering" button. The board outline (layer 20) is extruded (1.6 mm)
and the visible 2D layers are applied as texture on both faces. Pad drills (layer 17), via drills
(layer 18) and holes (layer 45) are real through holes. The 3D view follows the layer checkboxes of the
side panel: untick a layer and it disappears from the 3D view too (live, while the 3D view is open).
Left drag = rotate on all axes, wheel = zoom, right drag = pan; Iso/Top/Bottom buttons.
It needs WebGL. three.js r147 and TrackballControls are embedded in eagle_pcb_view_3d.py (MIT license) and
copied into every board .htm, so the generated file is fully standalone (and large).
Mask color, mask finish (glossy / matte) and pad finish can be changed from the 3D toolbar.

COMPANION FILES
Opening test.sch also loads test.brd (and vice versa) when it sits in the same folder
with the same name. If the companion is missing, the file you chose is still rendered
and a message tells you the companion was not found. Untick "Load companion file"
to render only the file you selected.

OUTPUT FOLDER
Pick any folder with "Browse...". It is created if it does not exist.
By default it is the folder of the input file.

COMMAND LINE
  python eagle_pcb_view_3d.py file.brd -o OUTDIR [--no-pair] [--open]
  python eagle_pcb_view_3d.py            (no arguments: opens this window)
  python eagle_pcb_view_3d.py --gui      (force the window)

KNOWN LIMITS
- text uses a system font, so shapes/widths are approximated
- copper pours are not recalculated (translucent outline only)
- the ratsnest is not drawn
- the 3D view shows no component models; inner copper layers are not shown in 3D

CREDITS
by Arky - amigatronic.com  ->  https://www.amigatronic.com

LICENSE (MIT) AND DISCLAIMER
Copyright (c) 2026 Arky. Released under the MIT License.
THIS SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
LIMITED TO MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. There is no guarantee
that the software is free of bugs beyond the known limits listed above; the 2D/3D output is a visual aid
and must not replace the original EAGLE files or the manufacturing data. In no event shall the author be
liable for any claim, damages or other liability arising from the use of the software.
If you find a bug, please report it to Arky through https://www.amigatronic.com
The embedded three.js code is also MIT licensed (see the notice at the end of the source file).
"""


def find_companion(path):
    """Return the .sch for a .brd (or the .brd for a .sch) with the same base name, else None."""
    stem, ext = os.path.splitext(os.path.basename(path))
    want = {".brd": ".sch", ".sch": ".brd"}.get(ext.lower())
    if want is None:
        return None
    folder = os.path.dirname(os.path.abspath(path))
    for fn in sorted(os.listdir(folder)):
        b, e = os.path.splitext(fn)
        if e.lower() == want and b.lower() == stem.lower():  # case-insensitive match
            return os.path.join(folder, fn)
    return None


def collect_inputs(files, pair=True, log=print):
    """Expand the input list with companion files; a missing companion is reported, never fatal."""
    out = []
    for f in files:
        if f not in out:
            out.append(f)
        if not pair:
            continue
        comp = find_companion(f)
        if comp is None:
            ext = os.path.splitext(f)[1].lower()
            if ext in (".brd", ".sch"):
                kind = "schematic (.sch)" if ext == ".brd" else "board (.brd)"
                log("note: matching %s not found next to %s - rendering only this file"
                    % (kind, os.path.basename(f)))
        elif comp not in out and os.path.abspath(comp) not in [os.path.abspath(o) for o in out]:
            log("companion file found: %s" % os.path.basename(comp))
            out.append(comp)
    return out


def process(path, outdir, log=print):
    """Render one file; returns the list of written .htm paths (empty on failure)."""
    try:
        root = ET.parse(path).getroot()
        d = root.find("drawing")
        base = os.path.splitext(os.path.basename(path))[0]
        import time
        VARS.clear()
        VARS.update({"DRAWING_NAME": os.path.basename(path),
                     "LAST_DATE_TIME": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(path))),
                     "PLOT_DATE_TIME": time.strftime("%Y-%m-%d %H:%M:%S")})
        if d.find("board") is not None:
            sheets = render_board(root)
            base += "_brd"
        elif d.find("schematic") is not None:
            sheets = render_sch(root)
            base += "_sch"
        else:
            log("skipped (not a board/schematic): %s" % path)
            return []
        written = []
        is_board = d.find("board") is not None
        for suffix, cv, order in sheets:
            svg, info, defs = build_svg(cv, order)
            name = base + suffix
            with open(os.path.join(outdir, name + ".svg"), "w", encoding="utf-8") as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n' + svg)
            three = build_3d_payload(cv, defs, log) if is_board else None  # 3D view embedded in the 2D HTML
            hp = os.path.join(outdir, name + ".htm")
            with open(hp, "w", encoding="utf-8") as f:
                f.write(build_html(name, svg, info, flip=is_board, three=three))
            log("written: %s.svg, %s.htm%s" % (name, name, " (with 3D view)" if three else ""))
            written.append(hp)
        return written
    except (ET.ParseError, OSError, AttributeError) as e:
        log("error while processing %s: %s" % (os.path.basename(path), e))
        return []


def run(files, outdir, pair=True, open_browser=False, log=print):
    """Shared entry point for CLI and GUI."""
    global _warn_sink
    _warn_sink = log
    _warn_seen.clear()
    os.makedirs(outdir, exist_ok=True)
    results = []
    for p in collect_inputs(files, pair, log):
        results += process(p, outdir, log)
    if open_browser:
        import pathlib
        import webbrowser
        for hp in results:
            webbrowser.open(pathlib.Path(hp).resolve().as_uri())  # correct file URI on every OS
    return results


def launch_gui():
    """Small tkinter front end (standard library only)."""
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, scrolledtext
    except ImportError:
        print("tkinter is not available: install it (e.g. 'sudo apt install python3-tk') "
              "or use the command line (python eagle_pcb_view_3d.py -h).")
        return 1

    win = tk.Tk()
    win.title("EaglePCBView3D v%s" % VERSION)
    win.geometry("720x460")
    v_file, v_out = tk.StringVar(), tk.StringVar()
    v_pair, v_open = tk.BooleanVar(value=True), tk.BooleanVar(value=True)
    v_status = tk.StringVar(value="Choose a .brd or .sch file")
    state = {"auto_out": ""}  # last output folder proposed automatically

    def log(msg):
        box.configure(state="normal")
        box.insert("end", msg + "\n")
        box.see("end")
        box.configure(state="disabled")
        win.update_idletasks()

    def update_status(*_):
        f = v_file.get().strip()
        if not f:
            return
        if not os.path.isfile(f):
            v_status.set("File not found")
            return
        comp = find_companion(f)
        if comp:
            v_status.set("Companion file: %s" % os.path.basename(comp))
        elif os.path.splitext(f)[1].lower() in (".brd", ".sch"):
            v_status.set("Companion file not found (only this file will be rendered)")

    def browse_file():
        f = filedialog.askopenfilename(title="Open EAGLE file", filetypes=[
            ("EAGLE files", "*.brd *.sch"), ("Board", "*.brd"), ("Schematic", "*.sch"), ("All files", "*.*")])
        if f:
            v_file.set(f)
            if not v_out.get() or v_out.get() == state["auto_out"]:  # do not override a manual choice
                state["auto_out"] = os.path.dirname(f)
                v_out.set(state["auto_out"])
            update_status()

    def browse_out():
        d = filedialog.askdirectory(title="Output folder", initialdir=v_out.get() or None)
        if d:
            v_out.set(d)

    def do_render():
        f = v_file.get().strip()
        if not f or not os.path.isfile(f):
            log("error: choose an existing .brd or .sch file first")
            return
        out = v_out.get().strip() or os.path.dirname(os.path.abspath(f))
        log("--- rendering %s -> %s" % (os.path.basename(f), out))
        res = run([f], out, v_pair.get(), v_open.get(), log)
        log("done: %d viewer(s) created" % len(res) if res else "nothing was created")

    def show_help():
        import webbrowser
        h = tk.Toplevel(win)
        h.title("Help")
        h.geometry("640x520")
        t = scrolledtext.ScrolledText(h, wrap="word", font=("TkDefaultFont", 10))
        t.insert("1.0", HELP_TEXT)
        pos = "1.0"
        while True:  # make every occurrence of the credit URL a clickable link
            pos = t.search(CREDIT_URL, pos, stopindex="end")
            if not pos:
                break
            end = "%s+%dc" % (pos, len(CREDIT_URL))
            t.tag_add("link", pos, end)
            pos = end
        t.tag_config("link", foreground="#0645ad", underline=True)
        t.tag_bind("link", "<Button-1>", lambda e: webbrowser.open(CREDIT_URL))
        t.tag_bind("link", "<Enter>", lambda e: t.config(cursor="hand2"))
        t.tag_bind("link", "<Leave>", lambda e: t.config(cursor=""))
        t.configure(state="disabled")
        t.pack(fill="both", expand=True)

    frm = ttk.Frame(win, padding=10)
    frm.pack(fill="both", expand=True)
    frm.columnconfigure(1, weight=1)
    frm.rowconfigure(5, weight=1)
    ttk.Label(frm, text="EAGLE file:").grid(row=0, column=0, sticky="w")
    e1 = ttk.Entry(frm, textvariable=v_file)
    e1.grid(row=0, column=1, sticky="ew", padx=6, pady=3)
    e1.bind("<FocusOut>", update_status)
    ttk.Button(frm, text="Browse...", command=browse_file).grid(row=0, column=2)
    ttk.Label(frm, text="Output folder:").grid(row=1, column=0, sticky="w")
    ttk.Entry(frm, textvariable=v_out).grid(row=1, column=1, sticky="ew", padx=6, pady=3)
    ttk.Button(frm, text="Browse...", command=browse_out).grid(row=1, column=2)
    ttk.Label(frm, textvariable=v_status, foreground="#555").grid(row=2, column=1, sticky="w", padx=6)
    ttk.Checkbutton(frm, text="Load companion file (.brd <-> .sch)", variable=v_pair).grid(
        row=3, column=1, sticky="w", padx=6)
    ttk.Checkbutton(frm, text="Open in browser when done", variable=v_open).grid(
        row=4, column=1, sticky="w", padx=6)
    box = scrolledtext.ScrolledText(frm, height=10, state="disabled", font=("TkFixedFont", 9))
    box.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=8)
    bar = ttk.Frame(frm)
    bar.grid(row=6, column=0, columnspan=3, sticky="e")
    ttk.Button(bar, text="Render", command=do_render).pack(side="left", padx=4)
    ttk.Button(bar, text="Help", command=show_help).pack(side="left", padx=4)
    ttk.Button(bar, text="Quit", command=win.destroy).pack(side="left", padx=4)
    win.mainloop()
    return 0


def main():
    ap = argparse.ArgumentParser(prog="eagle_pcb_view_3d.py",
        description="Render EAGLE .brd/.sch files to SVG + standalone HTML viewer. "
                    "Without arguments the GUI is opened. The matching .sch/.brd is loaded automatically.",
        epilog="by Arky - amigatronic.com - " + CREDIT_URL)
    ap.add_argument("files", nargs="*", help="input .brd / .sch file(s)")
    ap.add_argument("-o", "--outdir", default=None,
                    help="output folder (default: current folder; created if missing)")
    ap.add_argument("--no-pair", action="store_true", help="do not load the matching companion file")
    ap.add_argument("--open", action="store_true", help="open the generated .htm files in the browser")
    ap.add_argument("--gui", action="store_true", help="force the graphical interface")
    ap.add_argument("--version", action="version", version="EaglePCBView3D %s (%s)" % (VERSION, VERSION_DATE))
    args = ap.parse_args()
    if args.gui or not args.files:
        return launch_gui()
    run(args.files, args.outdir or ".", not args.no_pair, args.open)
    return 0


# ----------------------------------------------------------------- embedded third-party code
# three.js r147 (build/three.min.js) and its examples/js/controls/TrackballControls.js, stored compressed
# (zlib + base64) and inlined into the generated 3D views. Both are part of three.js and are distributed
# under the MIT License:
#
#   Copyright (c) 2010-2022 three.js authors
#
#   Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
#   associated documentation files (the "Software"), to deal in the Software without restriction, including
#   without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#   copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the
#   following conditions: The above copyright notice and this permission notice shall be included in all
#   copies or substantial portions of the Software.
#
#   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT
#   LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO
#   EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
#   IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR
#   THE USE OR OTHER DEALINGS IN THE SOFTWARE.
THREE_JS_B64 = """
eNrcvftj2zayMPr791c4vntyRIqSRT1tOYxvmqZtdpM0m0e3bdbrQ0mQxA1FqiRlW050//Y7M3iTlO2k3T3nO3mIwAAYAIPBYPAa
HLnu/zlwD/7fOJqyJGfofpqut1m0WBYH3Y7faXU73e7Bu2XGWPuf+cGTTbFMsxzjvX397c+tFzxd6/mMJUU0j1g2Pnj5/B2EH/2f
B/NNMi2iNGkUHnM+HaaTf7JpcRgExXbN0vkBu16nWZE/fHi4SWZsHiVsdvhABq7S2SZmZ6whYjnjQ4lOY+CpHj7k33a4mp1xZ+PD
oUh3eA55j1mjUQR12SzidBLG75ZRfqad4+Lz55zFc6f97oc3z54Fn3bOrlFAgNfQVYIKbXJ2kBdZBJU6naZJXhyw4NDvjw69KPA7
HS8JevCbwa/v5fDb9UL47Xkp/Pa9GH6H3jTwWc9bYnzf2+Cn683w0/PW+Ol7K/wMvDl+ht4CPyPvEj/H3jV+TrwL+Phdb4ufvvcS
PwNvgp+h9xY+3Y53hZ+e9w4/Q+8Jfkbes6DXG42G3lP6jrwX9D323tD3xHsd9AbH/Y73nL6+9y19u94r+va8H4PeqH/S9W7oO/Te
w/cYivUNfU+87/Drd7yP9PW97+nb9X6ib8/7gb5972/0HXj/pO/Q+42+I+9n+h57v9D3xPsVv1CZP9PX9/4S9IaY/5+CLlL6r/jx
vaLAb9dj8O0DOKKv7yX07XoZfAcAz+nre2ER9KAN0gKby/di4JQ8W0wOvalwtWJgmjA79JZFMBoed7wNRB10+n1vBjEg0QHLD711
AUTtDU6ncZjnB6viUzibPbuEbvEiyguWsIx3g8s0mh10AuBhYKj2RSwCoRs0ShDkO8FXUTn2qUITfSjOIS1+gg/njtfyBbAdAbtf
/zhvMOfhQwKsN/kSfLtlmNcULJo39pXNyVixyZIH/t7i8AgHHMEDWaqW/6BSll3GVukl+6oC7MsecjhVqTFL5xOPWQSRkfUplacA
arTzNUo8yNd3drtZlK/DYrqkMmHPvndJWLUkbZQsdnGgbgAOswVwJMZX1WDtnIrRcU7nadaIGWJEuRG1Y5YsiuUpe5ScsmbTiT6w
8/Y0jGMuhwrnVGFMNnG82+04znkRfDjsdA69w46PP1386eFPH38G+DPEnxH+HOPPCf6E+DPBnyn+zPCH4c8cfnzE5yM+H/H5iM9H
fD7i8xGfj/h8xOcjPh/x+YjPR3w+4vMRn4/4uoivi/i6iK+L+LqIr4v4uoivi/i6iK+L+LqIr4v4uoivi/i6iK+L+HqIr4f4eoiv
h/h6iK+H+HqIr4f4eoivh/h6iK+H+HqIr4f4eoivh/j6iK+P+PqIr4/4+oivj/j6iA+F/GEf8fURXx/x9RFfH/H1EV8f8fUR3wDx
DRDfAPENEN8A8Q0Q3wDxDRDfAPENEN8A8Q0Q3wDxDRDfAPENEN8Q8Q0R3xDxDRHfEPENEd8Q8Q0R3xDxDRHfEPENEd8Q8Q0R3xDx
DRHfCPGNEN8I8Y0Q3wjxjRDfCPGNEN8I8Y0Q3wjxjRDfCPGNEN8I8Y0Q3zHiO0Z8x4jvGPEdI75jxHeM+I4R3zHiO0Z8x4jvGPEd
I75jxHeM+I4R3wniO0F8J4jvBPGdIL4TxHeC+E4Q3wniO0F8J4jvBPGdIL4TxHeC+E4QX4j4QsQXIr4Q8YWIL0R8IeILEV+I+ELE
FyK+EPGFiC9EfCHiCxHfBPFNEN8E8U0Q3wTxTRDfBPFNEN8E8U0Q3wTxTRDfBPFNEN8E8U0Q3xTxTRHfFPFNEd8U8U0R3xTxTRHf
FPFNEd8U8U0R3xTxTRHfFPFNEd8M8c0Q3wzxzRDfDPHNEN8M8c0Q3wzxzRDfDPHNEN8M8c0Q3wzxzRAfQ3wM8THExxAfQ3wM8THE
xxAfQ3wM8THExxAfQ3wM8THExxDfHPHNEd8c8c0R3xzxzRHfHPHNEd8c8c0R3xzxzRHfHPHNEd8c8c3nh+enKEcXMBp3e/3BcCSk
7WURvAyLZfv18yMfhvBrCD/uHAnQqdTrDi6Khh48+t0TUGtG3ZOBSxGzMJmlq4bzueOx2wKj2wKTWwLFONqYFx+6g8HD4rwJruLx
4+OH4JUef2j6un3uO2wdNkUyRmFMJRNBjJL6g8/DvoxQSjzsPYw++91jCo7K6SMr60inFtkm5ErM0iZWkkQlcdpF+iK9YtnTMGcN
Z6fIvy1QF/BgABcaBRFoFV43mMedUdKIYPwz0rwsuP4gaFf8B2sy5z+YjjApIW34rchxi2bkGpHe0sgvcoWBv1E8LFo+qE44ghc6
3pUZj4q0Tq8aXV66KYviBrnidAHxOH+9eNU1y/vuNgzzOAVN4C4UT0SV86sI9JYGaxPHZptpkWbAvkDUg+/iNCx63SdZFm7HIrPi
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
VAZI5ZerFJDSX5Z+QKo+LTWBVH36tAVS87dPdyA1f/vUCFLzd6ZGQepJtDUMUsIzWLoGKeEZbKWDlPIMfvWD1D31HW2E1Dj1bb2E
lJ76XhWF1Dn1HYWF1Dj1Xd2F1Dz1XT2G1Dz1XZ0Gs6Pafs1ScmhzYylgheEJWlr9a+NlbUqOit7SB6yyFUo61XYClK29vJyU4q/J
t07E/pGq8aaPFFO/Is5QrkidJFfZIqW/HL2LlPxw9C9Syjxamhip/vYpZKTm72ztjNSXmqmxkXoSbSWOVH9b5zrLUt9+RY/UTsnU
+0g9ibkGIORgSMmPh9lm8Dg4sQzcqKSA2uuO8FIqyry4Q42LQqLtX4BMS5cDpnII2CeB8tiZVh67tYwbXO2xaHIF8et7VI2MKn/Z
+S/IasP98kdarK2srq7Way39nEAUfpRw3U3Scp0akZiTgpb8u+ZI/2hZ+Sygk4TIiuoocTmU8iZJBEPKG6Up6qmsr1k8l1Id8jBb
vhxgmwR/FPgZHjMbGY2qcoKttG1szW+cSVO5nis5SE1v+EGmBIyjRtacpOoza2ZSN43OVcr/eqcrtRLc2UvpL2saU/VpTGYqPswJ
TeWXZ2JT46d/llM7xZ7zVH9nTn7qScxYD6mTlLU0UjdNL5MU/uVERahBzZSd0z7/2kuFSum5RQq4pYZreVwqpVfj4XeM2wHvL13q
5M0yY9gohFCpMLkaTgd99FeHdfr8FAU1LUFnrIpqgRv6pghMmlexs+sab5DqfAOnBfoC+UY6FnkZbVTp4xSrA7p7oGUmiTQcEdM0
IH5U+KvwzyEeR6w+Qt8o12wNv7th8mE0GIZ96g99cYoMZx207viSQpRSGXzOtehweHA+NsjI828zngpPK1lDl6pPOoap8Ppgj1lK
ftCRS/lfjSzxVrnUMVoM4iXGT8lflIWSav0qL3k1bifKkSJg/zVdBt5K/IjZD8tpH2vZ56CfDwf3ui580mlHbw2hp1iX9zmJQMly
U6PGRzmq2Y/9pjugTs1uYSzbakfR7M9firABIZIf2GUprw2N+yMxy0dilofErwyLGWAxg3CCMzAEM0bUdnz8tMg0H4DMAXGN/ZQY
WXDvgRbeRRka14bftifAywv4HogJczsaLcLaDNJEDXSS0dsux5huuCVjNRr7jRAD8CnU2YQgpbou2F4ADp8NYyhfxa5TMQcDGRKc
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
dAtozaKO1N+6J9oXodkN4SnPqkdH6m9jRCKmth7lppCPyI2ty1lbz7MKiDgpTkS1e88qoFNM4jQ2ZluEzBQbTFHXKMrCkvKrkJlS
n99e1mp0bV6rqjiPx6yIGBdXSc2wnbqq1Mu3792CEFXJs6r4x0kcfcZevUeL2G5Nduq6klb9JXI9CQgzvsPMCCfdLijr5KVkyEyx
8pOvnjmxV59roZ+0Lr4+96raqlBZTazGadh0U6x2zrJz6qXy72anajdwPNcqJ3FWKVJQlUVkwIh30DI5u+RA67rAtHcSLDffRPAh
ws5WQ4baB5VNBa00q0g2CyOJN8S3jq3CEZyfcH5rMOJhO9VeRvSx9xGoAw4KMmSmWPnHbFZOVH4VMlOq+X/K4bDXBShopVXPQV1E
B600e2IBgKI40YXMCCd9ZcHXYfG5Uhgja/LVVfItECdmeQzbqXWl3rMzsxAErbRVDbmdlXHVXLU1hHFilYawnVpX6me32M92uZ9X
FuQyK0ZBktay062Cyg8rlap1DVufXzmDtQuudxy7uqoIhXHciuqdyq6uBP3IVmtZ5XHWoetKacc6VQEjXgi3dBNr2Ikx2qR2kNJx
JN+UVYeSVmbhTZLyVnxM2uuNfBG+0KbfSivPLEsW51n6llwAUF4rxs2xuiw34VWtgcfX515d26c0LotqZRRdm9eeT7g8sVweKSpk
ptSg3exZdsHyUJASTlw1l935nAmeUszGTzAj73wlujavVdVFXMSnYt3Et461z5gsRb/cM8avOjpopVlF5gXL0b8mvxuJgBFv94Tl
cCEjIgDXomJw1s5xmFpBp/xBb7g23e5lGp9l+ZQbsRF3TzI/o1P0dVzFoVkToc+UmpFk14nfErmWU9kYWhm4CYIghns0fXmGQfNG
VJ/ZvUTVFb0YrCn7qjT9jdUW311TPGe3Fr+/pvgPt7Y+Xdf6+9uLr2v9zbrOS9WuutIi63Jp3/aFL2hB03C/0Cq2BqSRCmUcV5kR
TrpN2sKWJyfKuqgdVcljI+2kSH5kubpVGGE71b5AX9L1EyC9uhOMtNQIILyXdthhjRTy8Cj4yVFUjg2IeKIvASqvEVfNZfMzxDmN
4moxl830nAxlpPKQV26eDT+9Kmp+LfIqb9SYWwbs/MJtN79LCGfemFt8VzN/UIdkrZNvm2kkHXhzzpHy/B03jTSvvggyq+xidV7B
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
OlHREw==
"""

CONTROLS_JS_B64 = """
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
"""


if __name__ == "__main__":
    sys.exit(main())
