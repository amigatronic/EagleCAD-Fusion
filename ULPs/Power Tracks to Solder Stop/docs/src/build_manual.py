from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, PageBreak,
                                Image, Table, TableStyle, KeepTogether, Preformatted, NextPageTemplate)
from reportlab.platypus.tableofcontents import TableOfContents
from PIL import Image as PILImage

INK = colors.HexColor("#22313F")
ACC = colors.HexColor("#C0392B")
SOFT = colors.HexColor("#EEF3F8")
LINE = colors.HexColor("#B8C4D0")
COPPER = colors.HexColor("#C9792B")

ss = getSampleStyleSheet()
body = ParagraphStyle("body", parent=ss["Normal"], fontName="Helvetica", fontSize=10, leading=14.2,
                      textColor=INK, spaceAfter=6)
h1 = ParagraphStyle("h1", parent=body, fontName="Helvetica-Bold", fontSize=17, leading=21,
                    spaceBefore=14, spaceAfter=8, textColor=INK)
h2 = ParagraphStyle("h2", parent=body, fontName="Helvetica-Bold", fontSize=12.5, leading=16,
                    spaceBefore=10, spaceAfter=4, textColor=ACC)
cap = ParagraphStyle("cap", parent=body, fontName="Helvetica-Oblique", fontSize=8.8, leading=11.5,
                     textColor=colors.HexColor("#4B5A69"), alignment=TA_CENTER, spaceBefore=3, spaceAfter=10)
cell = ParagraphStyle("cell", parent=body, fontSize=9, leading=11.6, spaceAfter=0)
cellb = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold")
bul = ParagraphStyle("bul", parent=body, leftIndent=14, bulletIndent=3, spaceAfter=3)
note = ParagraphStyle("note", parent=body, fontSize=9.3, leading=13, backColor=SOFT, borderColor=LINE,
                      borderWidth=0.6, borderPadding=7, spaceBefore=6, spaceAfter=12, leftIndent=8, rightIndent=8)
code = ParagraphStyle("code", parent=ss["Code"], fontName="Courier", fontSize=8.3, leading=10.8,
                      backColor=colors.HexColor("#F5F6F8"), borderColor=LINE, borderWidth=0.5,
                      borderPadding=6, leftIndent=8, rightIndent=8, spaceBefore=4, spaceAfter=12)

TITLE = "Power Tracks to Solder Stop"
VERSION = "Version 1.0.0"
DATE = "November 1, 2026"

class Doc(BaseDocTemplate):
    def __init__(self, fn, **kw):
        super().__init__(fn, pagesize=A4, leftMargin=2*cm, rightMargin=2*cm, topMargin=2.1*cm,
                         bottomMargin=2.0*cm, title="Power Tracks to Solder Stop - User Manual",
                         author="power_tracks_to_stop.ulp", **kw)
        fr = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, id="f")
        self.addPageTemplates([PageTemplate(id="cover", frames=[fr], onPage=self.cover_page),
                               PageTemplate(id="main", frames=[fr], onPage=self.main_page)])
    def cover_page(self, c, d):
        c.saveState()
        w, h = A4
        c.setFillColor(INK); c.rect(0, h - 9.5*cm, w, 9.5*cm, stroke=0, fill=1)
        c.setFillColor(COPPER); c.rect(0, h - 9.5*cm, w, 0.35*cm, stroke=0, fill=1)
        c.restoreState()
    def main_page(self, c, d):
        c.saveState()
        w, h = A4
        c.setStrokeColor(LINE); c.setLineWidth(0.6)
        c.line(2*cm, h - 1.6*cm, w - 2*cm, h - 1.6*cm)
        c.line(2*cm, 1.55*cm, w - 2*cm, 1.55*cm)
        c.setFont("Helvetica", 8.3); c.setFillColor(colors.HexColor("#4B5A69"))
        c.drawString(2*cm, h - 1.4*cm, TITLE + " - User Manual")
        c.drawRightString(w - 2*cm, h - 1.4*cm, "power_tracks_to_stop.ulp  " + VERSION)
        c.drawString(2*cm, 1.05*cm, "EAGLE 9.x / Fusion 360 Electronics")
        c.drawRightString(w - 2*cm, 1.05*cm, "Page %d" % d.page)
        c.restoreState()
    def afterFlowable(self, fl):
        if isinstance(fl, Paragraph):
            st = fl.style.name
            if st == "h1":
                self.notify("TOCEntry", (0, fl.getPlainText(), self.page))
            elif st == "h2":
                self.notify("TOCEntry", (1, fl.getPlainText(), self.page))

def img(path, width_cm):
    w, h = PILImage.open(path).size
    return Image(path, width=width_cm * cm, height=width_cm * cm * h / w)

def fig(path, caption, width_cm=17):
    return KeepTogether([img(path, width_cm), Paragraph(caption, cap)])

def P(t, st=body): return Paragraph(t, st)
def B(items):
    return [Paragraph(t, bul, bulletText="\u2022") for t in items]

def tbl(rows, widths, header=True, zebra=True):
    data = []
    for i, r in enumerate(rows):
        data.append([Paragraph(str(c), cellb if (header and i == 0) else cell) for c in r])
    t = Table(data, colWidths=[w * cm for w in widths], repeatRows=1 if header else 0)
    st = [("GRID", (0, 0), (-1, -1), 0.5, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
          ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5)]
    if header:
        st.append(("BACKGROUND", (0, 0), (-1, 0), SOFT))
    if zebra:
        for i in range(2 if header else 1, len(rows), 2):
            st.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#F8FAFC")))
    t.setStyle(TableStyle(st))
    return t

S = []

# ------------------------------------------------------------------ cover
S.append(Spacer(1, 1.6*cm))
S.append(Paragraph('<font color="white" size="30"><b>Power Tracks<br/>to Solder Stop</b></font>',
                   ParagraphStyle("t", parent=body, leading=36)))
S.append(Spacer(1, 0.5*cm))
S.append(Paragraph('<font color="#E8EEF4" size="13">User Manual</font>', ParagraphStyle("t2", parent=body)))
S.append(Spacer(1, 8.2*cm))
S.append(P("<b>power_tracks_to_stop.ulp</b>", ParagraphStyle("c1", parent=body, fontSize=14, leading=18)))
S.append(P("An EAGLE / Fusion 360 Electronics user language program that copies the copper of selected "
           "signals (tracks and pours) onto the solder stop layers, so that the bare copper is tinned "
           "during HASL and the power tracks are reinforced.", ParagraphStyle("c2", parent=body, fontSize=11, leading=16)))
S.append(Spacer(1, 0.6*cm))
S.append(tbl([["Version", "1.0.0"], ["Date", DATE], ["Applies to", "EAGLE 9.x, Fusion 360 Electronics (board editor)"],
              ["Platform", "Windows 10"], ["Language of the program", "English"]], [4.2, 12.8], header=False, zebra=False))
S.append(NextPageTemplate("main"))
S.append(PageBreak())

# ------------------------------------------------------------------ contents
S.append(Paragraph("Contents", ParagraphStyle("ch", parent=h1, spaceBefore=0)))
toc = TableOfContents()
toc.levelStyles = [
    ParagraphStyle("toc0", parent=body, fontName="Helvetica-Bold", fontSize=10.5, leading=15, leftIndent=0, spaceBefore=4),
    ParagraphStyle("toc1", parent=body, fontSize=9.5, leading=13, leftIndent=16),
]
S.append(toc)
S.append(PageBreak())

# ------------------------------------------------------------------ 1 Introduction
S.append(P("1. Introduction", h1))
S.append(P("1.1 Purpose", h2))
S.append(P("On a printed circuit board the solder mask normally covers all copper except pads. If a track or a "
           "copper pour carries a significant current, it can be reinforced by leaving its copper bare: "
           "during the HASL (hot air solder levelling) step a layer of tin is deposited on every exposed "
           "copper surface, increasing the cross-section of the conductor."))
S.append(P("In EAGLE the solder mask openings are drawn on the stop layers. Opening the mask above a track "
           "therefore means drawing, on the stop layer, a shape that covers that track. Doing it by hand "
           "(copy the track, paste it on tStop or bStop) is slow and error-prone, especially for pours with "
           "many isolation cutouts. <b>power_tracks_to_stop.ulp</b> does it automatically for the signals you choose."))
S.append(fig("../images/concept.png", "Figure 1. Left: the solder mask covers the copper track. Right: an opening in the stop "
             "layer leaves the copper bare, and HASL deposits tin on it."))
S.append(P("1.2 Layer mapping", h2))
S.append(tbl([["Copper source", "Copied to", "Layer number"],
              ["Top copper (wires and pours)", "tStop", "1 &rarr; 29"],
              ["Bottom copper (wires and pours)", "bStop", "16 &rarr; 30"]], [7, 5, 5]))
S.append(Spacer(1, 6))
S.append(P("Only the signals' wires and polygons on layers 1 and 16 are considered. Pads and vias are not "
           "copied: the solder stop already opens them."))

# ------------------------------------------------------------------ 2 Installation
S.append(P("2. Requirements and installation", h1))
S.append(P("<b>Requirements:</b> EAGLE 9.x or Fusion 360 Electronics on Windows 10, with the board editor open on "
           "the board to be processed. Pours should be calculated (see section 5.2)."))
S.append(P("<b>Installation:</b>"))
S += B(["Copy <font name='Courier'>power_tracks_to_stop.ulp</font> to a folder of your choice.",
        "In EAGLE, a file placed in a folder listed under <i>Options &gt; Directories &gt; User Language "
        "Programs</i> appears in the ULP list. Any other location also works: use the full path in the "
        "<font name='Courier'>RUN</font> command."])
S.append(P("<b>Running it</b> (board editor only). Type in the command line, adapting the path:"))
S.append(Preformatted('RUN "C:\\Users\\you\\ulp\\power_tracks_to_stop.ulp"', code))
S.append(P("In EAGLE you can alternatively use <i>File &gt; Run ULP...</i> and browse to the file. If the program is "
           "started from the schematic editor or the control panel it stops with a message."))

# ------------------------------------------------------------------ 3 Quick start
S.append(P("3. Quick start", h1))
S.append(fig("../images/workflow.png", "Figure 2. Typical workflow."))
S += [Paragraph(t, bul, bulletText="%d." % (i + 1)) for i, t in enumerate([
    "Save the board. If it contains pours, run <font name='Courier'>RATSNEST</font> so that they are calculated.",
    "Run the ULP. The dialog lists every signal that has wires or pours on Top or Bottom copper.",
    "Tick the signals to expose. Sorting by <i>Max w</i> (descending) brings the widest tracks first; "
    "<i>Width &gt;=</i> selects them in one click.",
    "To include pours, tick <i>Include polygons (pours)</i>. The other options can stay at their defaults.",
    "Press <i>Generate</i>. A summary shows what was created, then the generated script is executed.",
    "Check layers 29 and 30 over the copper, then run the DRC and generate your manufacturing files as usual."])]
S.append(P("Tip: set the display to show only the stop layer and the copper layer to compare the openings with "
           "the copper before sending the board to production.", note))

# ------------------------------------------------------------------ 4 User interface
S.append(P("4. User interface", h1))
S.append(fig("../images/dialog.png", "Figure 3. The dialog (schematic, with example data). The numbers refer to table 1.", 16.5))
S.append(tbl([["#", "Area", "Description"],
              ["1", "Signal list", "One row per signal with wires or pours on Top/Bottom. The checkbox on the left "
                                   "marks the signal to expose. 16 rows are shown per page."],
              ["2", "Column headers", "Buttons. Click to sort by Signal, Top, Bottom, Poly, Min w or Max w; click again "
                                      "to reverse the order. Ties are sorted by name."],
              ["3", "Navigation and status", "<i>Prev</i> / <i>Next</i> change page (ticks are kept). The line on the right "
                                             "shows the current sort. The status line counts selected signals, wires and polygons."],
              ["4", "Selection tools", "Bulk selection, see table 2."],
              ["5", "Options", "Settings of the conversion, see table 3."],
              ["6", "Script file", "Path of the generated .scr file (default: the board's folder)."],
              ["7", "Buttons", "<i>Help</i> opens a 5-page help. <i>Generate</i> writes and runs the script. <i>Cancel</i> closes the dialog."]],
             [0.8, 3.6, 12.6]))
S.append(P("Table 1. Dialog areas.", cap))
S.append(P("4.1 Signal list columns", h2))
S.append(tbl([["Column", "Meaning"],
              ["Signal", "Signal name as in the board."],
              ["Top / Bottom", "Number of wires of the signal on layer 1 / layer 16."],
              ["Poly", "Number of polygons (pours) of the signal on Top and Bottom."],
              ["Min w / Max w", "Smallest and largest wire width on Top/Bottom, in mm. Signals that only have pours show 0."]],
             [4, 13]))
S.append(P("4.2 Selection tools", h2))
S.append(tbl([["Control", "Action"],
              ["Select all / Clear all / Invert", "Act on every signal, not only on the visible page."],
              ["Width &gt;= (mm) + Select", "Adds the signals that have at least one wire as wide as the value (default 0.5 mm)."],
              ["Name contains + Select", "Adds the signals whose name contains the text (case-insensitive)."]],
             [5.5, 11.5]))
S.append(P("Table 2. Selection tools. Selections are cumulative; use <i>Clear all</i> to start again.", cap))
opt_block = [P("4.3 Options", h2)]
opt_block.append(tbl([["Option", "Default", "Range", "Effect"],
              ["Wire margin per side (mm)", "0", "0 to 2", "Extra width added on each side of every copied wire. It does not apply to pours."],
              ["Include polygons (pours)", "off", "-", "Also copies the pours of the selected signals."],
              ["Follow isolation cutouts", "on", "-", "Uses the real poured copper, so isolation around other signals stays covered. "
                                                     "If off, the polygon outline is used and the cutouts are ignored."],
              ["Auto grow from clearance", "on", "-", "Widens the opening around each pour by a fraction of its clearance."],
              ["Auto grow (fraction)", "0.5", "0 to 0.9", "Fraction of the clearance used as extra opening per side."],
              ["Extra grow per side (mm)", "0", "0 to 1", "Manual extra opening, added to the automatic one."],
              ["Arc tolerance (mm)", "0.005", "0.0005 to 0.1", "Maximum distance between a pour arc and the segments approximating it."],
              ["Script file", "board folder", "-", "Where <font name='Courier'>power_tracks_to_stop.scr</font> is written."]],
             [4.3, 2.0, 2.1, 8.6]))
opt_block.append(P("Table 3. Options.", cap))
S.append(KeepTogether(opt_block))

# ------------------------------------------------------------------ 5 How it works
S.append(P("5. How it works", h1))
S.append(P("The ULP does not modify the board directly. It writes an EAGLE script (.scr) containing "
           "<font name='Courier'>LAYER</font>, <font name='Courier'>WIRE</font> and <font name='Courier'>POLYGON</font> "
           "commands and then executes it with <font name='Courier'>SCRIPT</font>."))
S.append(P("5.1 Wires", h2))
S.append(P("Each wire of a selected signal on layer 1 or 16 is copied to layer 29 or 30 with the same end points, "
           "the same curvature (arcs are preserved) and the same width, plus twice the wire margin. Before writing a wire the "
           "ULP checks whether an identical wire already exists on the stop layer; if so it is skipped and counted as a "
           "duplicate, so the wire part can be generated again safely."))
S.append(P("5.2 Pours (polygons)", h2))
S.append(P("A pour cannot simply be copied: its outline does not show the isolation around other signals. The ULP reads the "
           "<b>poured contour</b> that EAGLE computed, which includes those cutouts. This is why the pour must be calculated "
           "(<font name='Courier'>RATSNEST</font>). The steps are:"))
S += [Paragraph(t, bul, bulletText="%d." % (i + 1)) for i, t in enumerate([
    "The contour wires are chained into closed loops. Arcs are replaced by short segments, controlled by the arc tolerance.",
    "Each loop is classified by nesting: an outer boundary, a hole (isolation around a pad or another signal), or an island inside a hole.",
    "Every hole is joined to its outer boundary by a bridge of zero width, producing a single polygon. The bridge is chosen so that "
    "it lies entirely inside the copper.",
    "That polygon is written on the stop layer with a hairline edge: it only fills the area.",
    "The border of the pour is drawn separately with wires as wide as the pour width (plus the grow), following the same contour. "
    "This reproduces the copper edge, which extends half the pour width beyond the contour line."])]
S.append(fig("../images/pour-bridge.png", "Figure 4. Left: loops read from the pour. Right: the hole is joined to the outer boundary by a "
             "zero-width bridge (drawn thick here for visibility) so that one polygon describes the whole copper area."))
S.append(P("If a pour is not calculated, or <i>Follow isolation cutouts</i> is off, the polygon outline is used instead. The summary "
           "reports the polygons that fell back to the outline because they were not calculated.", note))
S.append(P("5.3 Border width and automatic grow", h2))
S.append(P("EAGLE draws the pour border as a wire of the pour width centred on the contour. The real copper edge is therefore "
           "half of that width beyond the contour. The stop border wire has the pour width plus twice the <i>grow</i>, so the opening "
           "reaches the copper edge and then <i>grow</i> beyond it."))
S.append(P("The automatic grow is <b>fraction &times; clearance</b>, where the clearance is the pour's isolate value or, if it is 0, "
           "the clearance of the signal's net class (0.2 mm if both are 0). With the default fraction of 0.5 the opening ends halfway "
           "into the isolation gap, which guarantees that it never reaches the neighbouring copper. The extra opening compensates small "
           "differences at the copper edge and makes sure the copper is fully exposed."))
S.append(fig("../images/gap-geometry.png", "Figure 5. Geometry across the isolation gap between a pour and the pad of another net.", 16.5))
S.append(P("5.4 Generated script", h2))
S.append(P("The script is plain text and can be opened with any editor. Example (values are illustrative):"))
S.append(Preformatted(
"GRID mm;\n"
"LAYER 29;\n"
"WIRE 0.5080 (12.7000 25.4000) (30.4800 25.4000);\n"
"LAYER 29;\n"
"POLYGON 0.0010\n"
"  (10.0000 10.0000) (50.0000 10.0000) (50.0000 40.0000) (10.0000 40.0000)\n"
"  (10.0000 10.0000);\n"
"LAYER 29;\n"
"WIRE 0.6556 (10.0000 10.0000) (50.0000 10.0000);", code))

# ------------------------------------------------------------------ 6 Good practice
S.append(P("6. Verification and good practice", h1))
S += B(["<b>Save the board before generating.</b> To revert, use undo or reload the saved file; a long script can produce many undo steps.",
        "<b>Mask web.</b> The opening is deliberately a little wider than the copper. Check with your manufacturer the minimum "
        "solder mask web between exposed copper and neighbouring pads and lower the auto grow if needed.",
        "<b>Calculate pours first</b> (RATSNEST) and regenerate after any change to the pours or to nearby copper.",
        "<b>Do not generate the same pours twice</b> without removing the previous stop polygons: duplicate wires are detected, polygons are not.",
        "<b>Inspect the result</b> with only layers 1/16 and 29/30 visible, and look at the Gerber output before ordering.",
        "<b>Large pours</b> contain many vertices; processing takes a few seconds."])

# ------------------------------------------------------------------ 7 Limitations
S.append(P("7. Limitations", h1))
S += B(["Only wires and polygons that belong to signals are listed. Wires or polygons that have no signal are ignored.",
        "Pads, vias, holes and text are not copied.",
        "The opening around a pour follows the contour and the auto grow rule; it is not a recalculation of the pour.",
        "The default auto grow fraction (0.5) is a starting point; it has been chosen for safety, not derived from a specific "
        "manufacturer's rules.",
        "In Fusion 360 Electronics the board may be stored in the cloud: if the script file cannot be written, choose a local folder in <i>Script file</i>."])

# ------------------------------------------------------------------ 8 Troubleshooting
S.append(P("8. Troubleshooting", h1))
S.append(tbl([["Symptom", "Likely cause", "What to do"],
              ["Message: run from the board editor", "The ULP was started from another editor.", "Open the board and run it there."],
              ["A signal with only a pour is missing", "The pour is not on layer 1 or 16, or the signal has no wires or pours on Top/Bottom.", "Check the layer of the pour."],
              ["Summary warns about uncalculated polygons", "The pour was not calculated, so only the outline was used.", "Run RATSNEST and generate again."],
              ["Isolation cutouts are covered by the opening", "<i>Follow isolation cutouts</i> is off, or the outline fallback was used.", "Turn the option on and calculate the pours."],
              ["Thin strip of copper is still covered by mask", "The grow is too small for the copper edge.", "Increase the auto grow fraction or the extra grow per side."],
              ["Opening reaches neighbouring pads", "The grow is too large for the clearance.", "Lower the auto grow fraction and the extra grow."],
              ["Generated polygons or wires appear twice", "The script was generated twice.", "Undo or delete the stop objects and generate once."],
              ["Script file cannot be written", "The board folder is read-only or cloud-only.", "Change <i>Script file</i> to a local folder."],
              ["Compile or runtime error", "-", "Report the exact message and the line number."]],
             [4.6, 6.2, 6.2]))

# ------------------------------------------------------------------ Appendix
app_block = [P("Appendix A. Commands in the generated script", h1)]
app_block.append(tbl([["Command", "Used for"],
              ["GRID mm;", "Sets millimetres as the unit for the coordinates that follow."],
              ["LAYER 29; / LAYER 30;", "Selects tStop or bStop."],
              ["WIRE w (x1 y1) (x2 y2);", "Copied wire, or border wire of a pour. An arc is written with its curvature between the two points."],
              ["POLYGON w (x y) ... ;", "Fill polygon of a pour, with a hairline edge width w."]],
             [5.5, 11.5]))

S.append(KeepTogether(app_block))

doc = Doc("../power_tracks_to_stop_manual.pdf")
doc.multiBuild(S)
print("pdf ok")
