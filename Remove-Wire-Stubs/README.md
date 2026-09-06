# Remove Wire Stubs (ULP for EagleCAD / Autodesk Fusion)

An User Language Program (ULP) for **Autodesk Eagle** and **Fusion 360 Electronics PCB Editor** that automatically detects, removes, and cleans up dead-end copper trace stubs (including multi-segment stub chains) from your PCB designs.

---

## 📌 Features

- **Multi-Segment Chain Detection:** Iteratively analyzes trace connections to detect not only single dangling segments, but entire multi-segment dead-end chains.
- **Smart Connectivity Check:** Correctly identifies trace connections with pads, surface-mount devices (SMD), vias, and other active copper traces (Layers 1–16).
- **Automated RIPUP & RATSNEST:** Automatically generates exact grid-aligned RIPUP commands targeting midpoints of stub segments and refreshes airwires using RATSNEST.
- **Interactive & Loop Autorouting Modes:**
  - **Autoroute + Repeat:** Automatically routes unrouted signals affected by removed stubs, relaunching itself in a silent loop until the board is completely clean or a safety iteration limit (6 loops) is reached.
  - **Remove Only:** Deletes identified stubs without invoking the autorouter.
- **Safety Cap & Diagnostics:** Displays exact signal names affected by stubs to pinpoint unrouteable nets caused by DRC rules or board congestion.

---

## 🛠️ Installation

1. Download `remove_Wire_Stub.ulp` from this repository.
2. Save the file into your local Eagle/Fusion ULP directory:
   - **Eagle:** `Documents/EAGLE/ulp/` or the default installation `ulp` directory.
   - **Fusion 360:** Save to any accessible folder on your system.

---

## 🚀 How to Use

1. Open your PCB board design (`.brd`) in **Autodesk Eagle** or **Fusion 360 PCB Editor**.
2. Open the Command Console or CLI in the editor.
3. Run the script using the command: `RUN remove_Wire_Stub.ulp`
4. Choose an action from the popup dialog:
   - **Autoroute + repeat until clean:** Removes stubs, autoroutes affected signals, and re-scans automatically until no stubs remain.
   - **Remove only:** Removes stubs, updates airwires, and exits.
   - **Cancel:** Aborts the operation without modifying the layout.

---

## 📄 License

This project is open-source and released under the **Apache License 2.0**. See the `LICENSE` file for details.
