import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch, Circle, FancyArrowPatch, Polygon
import numpy as np

COPPER = "#C9792B"
MASK   = "#3E8E5A"
TIN    = "#B9BEC9"
SUB    = "#E3D6AE"
INK    = "#22313F"
ACC    = "#C0392B"
plt.rcParams["font.family"] = "DejaVu Sans"

# ------------------------------------------------------------------ Fig 1: cross section
def fig1():
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
    titles = ["Default: solder mask covers the copper", "With stop opening: HASL tins the bare copper"]
    for k, ax in enumerate(axes):
        ax.set_xlim(0, 12); ax.set_ylim(0, 5.2); ax.axis("off")
        ax.add_patch(Rectangle((0, 0.6), 12, 1.2, fc=SUB, ec=INK, lw=0.8))
        ax.text(0.25, 1.05, "substrate", fontsize=8, color=INK)
        xs = [(1.0, 2.6), (4.8, 7.2), (9.4, 11.0)]
        for i, (a, b) in enumerate(xs):
            exposed = (k == 1 and i == 1)
            if not exposed:
                # conformal solder mask coating, copper drawn inside it
                ax.add_patch(Rectangle((a - 0.2, 1.8), (b - a) + 0.4, 0.8, fc=MASK, ec=INK, lw=0.8, zorder=3))
            ax.add_patch(Rectangle((a, 1.8), b - a, 0.5, fc=COPPER, ec=INK, lw=0.8, zorder=4))
            if exposed:
                ax.add_patch(Rectangle((a - 0.05, 2.3), (b - a) + 0.1, 0.3, fc=TIN, ec=INK, lw=0.8, zorder=5))
        ax.text(6, 2.05, "copper track", ha="center", va="center", fontsize=8, color="white", zorder=6, weight="bold")
        if k == 0:
            ax.text(6, 3.45, "solder mask", ha="center", fontsize=9, color=MASK, weight="bold")
            ax.annotate("", xy=(6, 2.65), xytext=(6, 3.3), arrowprops=dict(arrowstyle="->", color=MASK))
        else:
            ax.text(6, 3.45, "tin (HASL)", ha="center", fontsize=9, color="#555B68", weight="bold")
            ax.annotate("", xy=(6, 2.65), xytext=(6, 3.3), arrowprops=dict(arrowstyle="->", color="#555B68"))
            ax.annotate("", xy=(4.5, 4.45), xytext=(7.5, 4.45), arrowprops=dict(arrowstyle="<->", color=ACC))
            ax.text(6, 4.6, "opening on tStop / bStop", ha="center", fontsize=8.5, color=ACC)
        ax.set_title(titles[k], fontsize=10, color=INK, pad=4)
    fig.tight_layout()
    fig.savefig("../images/concept.png", dpi=200)
    plt.close(fig)

# ------------------------------------------------------------------ Fig 2: workflow
def fig2():
    steps = [("1", "Run the ULP", "board editor\nRUN command"),
             ("2", "Select signals", "tick checkboxes,\nsort, filter"),
             ("3", "Set options", "defaults suit\nmost boards"),
             ("4", "Generate", ".scr is written\nand executed"),
             ("5", "Check", "layers 29 / 30,\nthen DRC / CAM")]
    fig, ax = plt.subplots(figsize=(10, 1.9))
    ax.set_xlim(0, 10); ax.set_ylim(0, 1.9); ax.set_aspect("equal"); ax.axis("off")
    w = 1.66; gap = 0.33
    for i, (n, t, d) in enumerate(steps):
        x = i * (w + gap) + 0.05
        ax.add_patch(FancyBboxPatch((x, 0.15), w, 1.35, boxstyle="round,pad=0.02,rounding_size=0.12",
                                    fc="#EEF3F8", ec=INK, lw=1.0))
        ax.add_patch(Circle((x + 0.3, 1.5), 0.19, fc=ACC, ec="white", lw=1.2, zorder=5))
        ax.text(x + 0.3, 1.5, n, color="white", ha="center", va="center", fontsize=9.5, weight="bold", zorder=6)
        ax.text(x + w / 2, 1.13, t, ha="center", va="center", fontsize=9, weight="bold", color=INK)
        ax.text(x + w / 2, 0.62, d, ha="center", va="center", fontsize=8.2, color=INK)
        if i < len(steps) - 1:
            ax.add_patch(FancyArrowPatch((x + w + 0.04, 0.85), (x + w + gap - 0.04, 0.85),
                                         arrowstyle="-|>", mutation_scale=13, color=INK))
    fig.tight_layout(pad=0.2)
    fig.savefig("../images/workflow.png", dpi=200)
    plt.close(fig)

# ------------------------------------------------------------------ Fig 3: dialog schematic
def circ_num(ax, x, y, n):
    ax.add_patch(Circle((x, y), 0.17, fc=ACC, ec="white", lw=1.2, zorder=10))
    ax.text(x, y, str(n), color="white", ha="center", va="center", fontsize=8.5, weight="bold", zorder=11)

def box(ax, x, y, w, h, fc="white", ec="#8794A3", lw=0.9, r=0.0):
    ax.add_patch(Rectangle((x, y), w, h, fc=fc, ec=ec, lw=lw))

def btn(ax, x, y, w, h, t, fs=7.5, fc="#F4F6F8"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.0,rounding_size=0.05", fc=fc, ec="#8794A3", lw=0.9))
    ax.text(x + w / 2, y + h / 2, t, ha="center", va="center", fontsize=fs, color=INK)

def fig3():
    fig, ax = plt.subplots(figsize=(10, 6.2))
    ax.set_xlim(0, 10); ax.set_ylim(0, 6.2); ax.axis("off")
    ax.add_patch(Rectangle((0.05, 0.05), 9.9, 6.1, fc="#FAFBFC", ec=INK, lw=1.4))
    ax.add_patch(Rectangle((0.05, 5.8), 9.9, 0.35, fc="#DDE4EC", ec=INK, lw=1.4))
    ax.text(0.25, 5.975, "Power tracks to solder stop", va="center", fontsize=9, color=INK, weight="bold")

    # list area
    ax.text(0.3, 5.55, "Signals routed on Top / Bottom copper:", fontsize=8.5, color=INK)
    heads = [("Use", 0.3, 0.5), ("Signal", 0.85, 1.5), ("Top", 2.4, 0.6), ("Bottom", 3.05, 0.75), ("Poly", 3.85, 0.6), ("Min w", 4.5, 0.7), ("Max w", 5.25, 0.7)]
    for t, x, w in heads:
        if t == "Use":
            ax.text(x + 0.1, 5.15, t, fontsize=8, weight="bold", color=INK)
        else:
            btn(ax, x, 5.02, w, 0.3, t)
    rows = [("+12V", 14, 3, 1, 0.254, 1.270, True),
            ("+5V_STBY", 6, 0, 0, 0.254, 0.610, True),
            ("GND", 40, 52, 2, 0.152, 0.508, False),
            ("PWR_OK", 4, 0, 0, 0.152, 0.254, False),
            ("VBAT", 9, 2, 0, 0.254, 0.762, False),
            ("N$12", 3, 1, 0, 0.152, 0.152, False)]
    for i, (n, t, b, p, mn, mx, chk) in enumerate(rows):
        y = 4.55 - i * 0.37
        ax.add_patch(Rectangle((0.35, y), 0.2, 0.2, fc="white", ec=INK, lw=0.9))
        if chk:
            ax.plot([0.38, 0.44, 0.53], [y + 0.1, y + 0.04, y + 0.17], color=ACC, lw=2)
        for txt, x in [(n, 0.9), (str(t), 2.55), (str(b), 3.25), (str(p), 4.05), ("%.3f" % mn, 4.55), ("%.3f" % mx, 5.3)]:
            ax.text(x, y + 0.1, txt, va="center", fontsize=7.6, color=INK)
    ax.text(3.2, 2.33, "...", ha="center", fontsize=10, color="#8794A3")
    btn(ax, 0.3, 1.78, 0.7, 0.3, "Prev"); ax.text(1.6, 1.93, "Page 1 / 2", va="center", fontsize=8, color=INK)
    btn(ax, 2.35, 1.78, 0.7, 0.3, "Next"); ax.text(5.95, 1.93, "Sort: Max w (desc)", va="center", ha="right", fontsize=8, color=INK)
    ax.text(0.3, 1.45, "Selected: 2 of 24 signals (23 wires, 1 polygons)", fontsize=8, color=INK)

    # selection group
    box(ax, 6.35, 3.15, 3.45, 2.5, fc="#F3F6F9")
    ax.text(6.45, 5.5, "Selection", fontsize=8.3, weight="bold", color=INK)
    btn(ax, 6.5, 5.03, 1.3, 0.3, "Select all"); btn(ax, 7.95, 5.03, 1.3, 0.3, "Clear all")
    btn(ax, 6.5, 4.6, 1.3, 0.3, "Invert")
    ax.text(6.5, 4.3, "Width >= (mm):", fontsize=7.6, va="center", color=INK)
    box(ax, 7.75, 4.18, 0.65, 0.24, fc="white"); ax.text(8.07, 4.3, "0.500", fontsize=7.6, va="center", ha="center", color=INK)
    btn(ax, 8.55, 4.18, 0.7, 0.26, "Select", fs=7.2)
    ax.text(6.5, 3.72, "Name contains:", fontsize=7.6, va="center", color=INK)
    box(ax, 7.75, 3.6, 0.95, 0.24, fc="white"); ax.text(7.82, 3.72, "12V", fontsize=7.6, va="center", color=INK)
    btn(ax, 8.8, 3.6, 0.7, 0.26, "Select", fs=7.2)

    # options group
    box(ax, 6.35, 0.8, 3.45, 2.2, fc="#F3F6F9")
    ax.text(6.45, 2.85, "Options", fontsize=8.3, weight="bold", color=INK)
    opts = [("Wire margin per side (mm): 0.000", None), ("[x] Include polygons (pours)", None),
            ("[x] Follow isolation cutouts", None), ("[x] Auto grow from clearance", None),
            ("Auto grow (fraction): 0.50   Extra grow: 0.00", None), ("Arc tolerance (mm): 0.005", None)]
    for i, (t, _) in enumerate(opts):
        ax.text(6.5, 2.55 - i * 0.26, t, fontsize=7.1, va="center", color=INK)
    ax.text(6.5, 0.98, "Script file:", fontsize=7.1, va="center", color=INK)
    box(ax, 7.2, 0.88, 2.5, 0.22, fc="white")
    ax.text(7.25, 0.99, "C:\\...\\power_tracks_to_stop.scr", fontsize=6.4, va="center", color=INK)

    # bottom buttons
    btn(ax, 0.3, 0.2, 0.9, 0.3, "Help")
    btn(ax, 7.4, 0.2, 1.15, 0.3, "Generate", fc="#DCEBDD"); btn(ax, 8.7, 0.2, 1.0, 0.3, "Cancel")

    # numbered markers (all placed in free space, see legend in the manual)
    circ_num(ax, 6.17, 3.9, 1)     # signal list / checkboxes
    circ_num(ax, 6.17, 5.17, 2)    # column headers
    circ_num(ax, 6.17, 1.93, 3)    # page navigation, sort label, status
    circ_num(ax, 9.55, 5.48, 4)    # selection tools
    circ_num(ax, 9.55, 2.82, 5)     # options
    circ_num(ax, 6.17, 0.99, 6)    # script file
    circ_num(ax, 7.15, 0.35, 7)    # buttons
    ax.text(5.0, 0.08, "Schematic of the dialog with example data (not a screenshot)", ha="center", fontsize=7, color="#6B7785", style="italic")
    fig.tight_layout(pad=0.2)
    fig.savefig("../images/dialog.png", dpi=200)
    plt.close(fig)

# ------------------------------------------------------------------ Fig 4: geometry across the isolation gap
def fig4():
    W, clr, grow = 0.36, 0.30, 0.15
    fig, ax = plt.subplots(figsize=(10, 4.7))
    ax.set_xlim(-1.35, 1.0); ax.set_ylim(-0.85, 4.75); ax.axis("off")
    y0 = 0.2
    # copper row
    ax.add_patch(Rectangle((-1.35, y0), 1.35, 0.5, fc=COPPER, ec=INK, lw=0.8))
    ax.add_patch(Rectangle((clr, y0), 1.0 - clr, 0.5, fc=COPPER, ec=INK, lw=0.8))
    ax.add_patch(Rectangle((0, y0), clr, 0.5, fc=SUB, ec=INK, lw=0.8, hatch="//", alpha=0.7))
    ax.text(-1.3, y0 - 0.12, "Top copper: pour", fontsize=8.5, color=INK, va="top")
    ax.text(clr + 0.03, y0 - 0.12, "pad of another net", fontsize=8.5, color=INK, va="top")
    ax.text(clr / 2, y0 + 0.6, "isolation gap\n= clearance", fontsize=8, ha="center", color=INK)
    # contour line and copper edge
    xc = -W / 2
    ax.plot([xc, xc], [y0 - 0.1, 3.95], color=INK, lw=1.2, ls="--")
    ax.text(xc - 0.03, 4.05, "pour contour\n(centre line)", ha="right", fontsize=8.5, color=INK, va="bottom")
    ax.plot([0, 0], [y0 - 0.1, 3.95], color=COPPER, lw=1.6)
    ax.text(0.03, 4.05, "real copper edge\n(contour + W/2)", ha="left", fontsize=8.5, color=COPPER, va="bottom")
    # stop layer row: fill polygon + border wire
    y1 = 1.7
    xl = xc - (W / 2 + grow)
    xe = xc + W / 2 + grow
    ax.add_patch(Rectangle((-1.35, y1), xc + 1.35, 0.5, fc="#CFE5D6", ec="none"))
    ax.add_patch(Rectangle((xl, y1), xe - xl, 0.5, fc="#8FC3A0", ec=MASK, lw=1.0))
    ax.text(-1.3, y1 + 0.25, "fill polygon (tStop)", fontsize=8.3, color=MASK, va="center")
    ax.text(-1.3, y1 - 0.18, "border wire on tStop: width = W + 2 x grow (round ends)", fontsize=8.3, color=MASK, va="top")
    # mask row
    y2 = 2.75
    ax.add_patch(Rectangle((-1.35, y2), xe + 1.35, 0.5, fc="#F4F4F4", ec=INK, lw=0.8))
    ax.text(-0.5, y2 + 0.25, "open: solder mask removed", ha="center", va="center", fontsize=8.3, color=INK)
    ax.add_patch(Rectangle((xe, y2), 1.0 - xe, 0.5, fc=MASK, ec=INK, lw=0.8, alpha=0.9))
    ax.text(0.55, y2 + 0.25, "solder mask", ha="center", va="center", fontsize=8.3, color="white", weight="bold")
    ax.plot([xe, xe], [y1 - 0.05, y2 + 0.55], color=MASK, lw=1.2, ls=":")
    # dimensions
    def dim(x1, x2, y, txt, col=INK):
        ax.annotate("", xy=(x1, y), xytext=(x2, y), arrowprops=dict(arrowstyle="<->", color=col, lw=1.0))
        ax.text((x1 + x2) / 2, y - 0.08, txt, ha="center", va="top", fontsize=8, color=col)
    dim(xc, 0, -0.42, "W/2", COPPER)
    dim(0, xe, -0.42, "grow", MASK)
    dim(xe, clr, -0.42, "remaining\nmask web", INK)
    ax.set_title("Geometry across the isolation gap (top view, not to scale)", fontsize=10, color=INK, pad=6)
    fig.tight_layout()
    fig.savefig("../images/gap-geometry.png", dpi=200)
    plt.close(fig)

# ------------------------------------------------------------------ Fig 5: keyhole
def fig5():
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9))
    th = np.linspace(0, 2 * np.pi, 60)
    for k, ax in enumerate(axes):
        ax.set_xlim(-0.2, 6.4); ax.set_ylim(-0.4, 4.4); ax.set_aspect("equal"); ax.axis("off")
        ax.add_patch(Rectangle((0, 0), 6, 4, fc=COPPER, ec=INK, lw=1.2))
        cx, cy, r = 3.2, 2.0, 1.0
        ax.add_patch(Polygon(np.c_[cx + r * np.cos(th), cy + r * np.sin(th)], closed=True, fc="white", ec=INK, lw=1.2))
        if k == 0:
            ax.set_title("Contour loops read from the pour", fontsize=10, color=INK)
            ax.text(0.2, 3.7, "outer loop", fontsize=9, color="white", weight="bold")
            ax.annotate("hole loop\n(isolation around a pad)", xy=(cx + r * 0.72, cy + r * 0.72), xytext=(0.25, 2.9),
                        fontsize=8.5, color="white", weight="bold", arrowprops=dict(arrowstyle="->", color="white"))
        else:
            ax.set_title("One polygon: hole joined by a zero-width bridge", fontsize=10, color=INK)
            ax.plot([cx, cx], [cy + r, 4.0], color=ACC, lw=2.6)
            ax.text(cx + 0.15, 3.45, "bridge", fontsize=9, color="white", weight="bold")
            ax.text(0.2, 3.7, "fill = copper area", fontsize=9, color="white", weight="bold")
            ax.text(cx, 0.55, "hole stays open", ha="center", fontsize=8.5, color="white", weight="bold")
    fig.tight_layout()
    fig.savefig("../images/pour-bridge.png", dpi=200)
    plt.close(fig)

fig1(); fig2(); fig3(); fig4(); fig5()
print("figures ok")
