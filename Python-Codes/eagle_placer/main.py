# main.py
import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import os
import json
import sys
import logging

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eagle_top_parser_debug.log")
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    encoding="utf-8",
    force=True,
)
logging.getLogger(__name__).info("Application module loaded; log file: %s", LOG_PATH)

# Importiamo i moduli dedicati
from parser import EagleBoardParser
from geometry import BoardData
from optimizer import PlacementOptimizer
from parser_schematic import EagleSchematicParser
from gui import EagleGUI
from logger import get_logger, set_gui_logger_callback

def classify_board_content(board_data):
    """Classify a parsed board without assuming that component placements exist."""
    counts = {
        "components": len(getattr(board_data, "components", {}) or {}),
        "tracks": len(getattr(board_data, "tracks", []) or []),
        "signals": len(getattr(board_data, "signals", {}) or {}),
        "outlines": len(getattr(board_data, "boundary_polygons", []) or []),
        "keepouts": len(getattr(board_data, "keepouts_top", []) or []) + len(getattr(board_data, "keepouts_bottom", []) or []),
        "holes": len(getattr(board_data, "holes", []) or []),
        "vias": len(getattr(board_data, "isolated_vias", []) or []),
    }
    has_geometry = any(counts[key] for key in ("components", "tracks", "outlines", "keepouts", "holes", "vias"))
    if counts["components"]:
        status = "component_board"
    elif has_geometry:
        status = "geometry_only"
    else:
        status = "empty"
    return status, counts


class EagleApp:
    def __init__(self, window):
        self.window = window
        self.window.title("Eagle Board Analyzer & Lock Manager V22")
        #self.window.geometry("1920x1080")
        self.window.state("zoomed")
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)
        
        self.config_dir = os.path.join(os.path.expanduser("~"), ".eagle_board_analyzer")
        self.config_file = os.path.join(self.config_dir, "config.json")
        
        self.board_data = None
        self.optimizer = None
        self.file_path = ""
        self.gui = None
        self.logger = get_logger()
        
        saved_calib = self._load_calibration()
        self.calibration_factor = tk.DoubleVar(value=saved_calib)
        
        # Initialize an empty GUI (without board data)
        self.gui = EagleGUI(window, None, None, "No file loaded", self.calibration_factor)
        self.gui.set_open_file_callback(self._open_file)
        
        # Configure the logger to use the GUI
        set_gui_logger_callback(self.gui.log_message)
        self.logger.info("Application started successfully")

    def _load_calibration(self) -> float:
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r") as f:
                    data = json.load(f)
                    return float(data.get("calibration_factor", 1.0))
        except Exception as e:
            self.logger.error(f"Unable to read the configuration file: {e}")
        return 1.0

    def _save_calibration(self, value: float):
        try:
            if not os.path.exists(self.config_dir):
                os.makedirs(self.config_dir)
            with open(self.config_file, "w") as f:
                json.dump({"calibration_factor": value}, f)
        except Exception as e:
            self.logger.error(f"Unable to save the configuration file: {e}")
        
        # Also update the calibration factor in the GUI
        if self.gui:
            self.gui.calibration_factor.set(value)

    def _on_close(self):
        try:
            import matplotlib.pyplot as plt
            plt.close('all')
        except Exception:
            pass
        self.window.quit()
        self.window.destroy()
        sys.exit(0)

    



    
    

    def _open_file(self):
        logging.info("Open-file dialog requested")
        try:
            self._open_file_impl()
        except Exception:
            logging.exception("Unhandled error while loading or displaying the board")
            try:
                messagebox.showerror(
                    "File loading failed",
                    "An error occurred while loading or displaying the files.\n\n"
                    f"A diagnostic log was written to:\n{LOG_PATH}",
                )
            except Exception:
                logging.exception("Unable to display the file-loading error dialog")

    def _open_file_impl(self):
        path = filedialog.askopenfilename(
            title="Open XML-Based .brd File",
            filetypes=[("EAGLE Board Files", "*.brd"), ("All files", "*.*")]
        )
        if path:
            logging.info("Selected board file: %s", path)
            self.file_path = path
            logging.info("Stage 1/6: initializing board parser")
            parser = EagleBoardParser(path)
            self.board_data = parser.extract_data()
            status, board_counts = classify_board_content(self.board_data)
            logging.info(
                "Stage 2/6: board parsed; status=%s components=%s tracks=%s signals=%s boundaries=%s keepouts=%s holes=%s vias=%s",
                status, board_counts["components"], board_counts["tracks"],
                board_counts["signals"], board_counts["outlines"],
                board_counts["keepouts"], board_counts["holes"], board_counts["vias"],
            )
            
            # Load the companion schematic when available, but never let it prevent
            # a valid board from being displayed.
            sch_path = os.path.splitext(path)[0] + ".sch"
            warning_messages = []
            if status == "geometry_only":
                message = (
                    "No component placements were found in this BRD. The available copper tracks "
                    "and board geometry will be displayed, but placement optimization is unavailable."
                )
                logging.warning("Geometry-only board detected: %s", board_counts)
                self.logger.warning(message)
                warning_messages.append(message)
            elif status == "empty":
                message = (
                    "The BRD contains no components or recognized board geometry. The file was parsed, "
                    "but the canvas may be empty. Check whether this is the intended board file."
                )
                logging.warning("Parsed BRD has no renderable geometry: %s", board_counts)
                self.logger.warning(message)
                warning_messages.append(message)
            self.schematic_parts = {}
            schematic_net_classes = {}
            schematic_usable = False

            if not os.path.exists(sch_path):
                message = (
                    "No companion schematic was found. The board will be loaded "
                    "in board-only placement mode; unlocked components remain eligible "
                    "for geometric optimization, while schematic-dependent logical swaps are disabled."
                )
                logging.warning("%s Path: %s", message, sch_path)
                self.logger.warning(message)
                warning_messages.append(message)
            else:
                logging.info("Stage 3/6: parsing companion schematic: %s", sch_path)
                try:
                    sch_parser = EagleSchematicParser(sch_path)
                    self.schematic_parts = sch_parser.extract_schematic_data()
                    schematic_net_classes = getattr(sch_parser, "net_classes", {}) or {}
                    logging.info(
                        "Schematic parsed; parts=%s net_classes=%s",
                        len(self.schematic_parts), len(schematic_net_classes)
                    )
                    if not self.schematic_parts:
                        message = (
                            "The companion schematic is empty or contains no usable parts. "
                            "The board will use board-only placement mode; unlocked components "
                            "remain eligible for geometric optimization, while logical swaps are disabled."
                        )
                        logging.warning("%s Path: %s", message, sch_path)
                        self.logger.warning(message)
                        warning_messages.append(message)
                    else:
                        schematic_usable = True
                        self.logger.success(
                            f"Companion schematic loaded: {os.path.basename(sch_path)}"
                        )
                except Exception as exc:
                    logging.exception("Unable to parse companion schematic: %s", sch_path)
                    message = (
                        "The companion schematic could not be read. The board will use "
                        "board-only placement mode; unlocked components remain eligible "
                        "for geometric optimization, while logical swaps are disabled."
                    )
                    self.logger.warning(f"{message} Details: {exc}")
                    warning_messages.append(message)
                    self.schematic_parts = {}
                    schematic_net_classes = {}

            if schematic_usable:
                logging.info("Stage 4/6: checking board/schematic consistency")
                try:
                    is_consistent = check_schematic_board_consistency(
                        self.board_data,
                        self.schematic_parts,
                        self.logger,
                        schematic_net_classes,
                    )
                    if not is_consistent:
                        message = (
                            "Board/schematic inconsistencies were detected. The BRD "
                            "will still be loaded; inspect the log for details."
                        )
                        logging.warning(message)
                        self.logger.warning(message)
                        warning_messages.append(message)
                except Exception as exc:
                    logging.exception("Board/schematic consistency check failed")
                    message = (
                        "The board/schematic consistency check failed. The BRD will "
                        "still be loaded without relying on the consistency result."
                    )
                    self.logger.warning(f"{message} Details: {exc}")
                    warning_messages.append(message)
                    self.board_data.orphan_components = set()
                    self.board_data.schematic_only_components = set()

                try:
                    debug_print_schematic_entanglement(self.schematic_parts, self.logger)
                except Exception:
                    logging.exception("Schematic diagnostic summary failed")
            else:
                # A board file contains its own component placements and net connectivity.
                # Without a usable schematic, keep explicit BRD lock flags authoritative
                # and allow all other board components to participate in placement search.
                self.board_data.orphan_components = set()
                self.board_data.schematic_only_components = set()
                logging.info(
                    "Schematic unavailable; board-only placement mode enabled for %s components",
                    len(self.board_data.components),
                )

            orphan_names = sorted(
                getattr(self.board_data, "orphan_components", set()) or set()
            )
            if schematic_usable and orphan_names:
                warning_messages.append(
                    f"{len(orphan_names)} board object(s) are not declared in the schematic "
                    "and will be preserved as fixed obstacles."
                )
                logging.warning("Board-only objects: %s", orphan_names)

            if warning_messages:
                warning_text = "\n\n".join(warning_messages)
                warning_text += (
                    "\n\nThe BRD remains the primary input and will be displayed. "
                    f"See the diagnostic log for details:\n{LOG_PATH}"
                )
                try:
                    messagebox.showwarning("Board loading warning", warning_text)
                except Exception:
                    logging.exception("Unable to display schematic warning dialog")

            # Pass schematic data into board_data
            self.board_data.schematic_parts = self.schematic_parts
            
            # Initialize the optimizer for the loaded board
            logging.info("Stage 5/6: initializing placement optimizer")
            self.optimizer = PlacementOptimizer(self.board_data)
            
            # Log diagnostic information about netlist extraction
            logging.info("Stage 6/6: calculating initial ratsnest")
            initial_rats = self.optimizer.calculate_ratsnest_length()
            self.logger.success(
                f"Board loaded successfully: {len(self.board_data.components)} components, "
                f"{len(getattr(self.board_data, 'tracks', []))} copper tracks, "
                f"{len(self.board_data.signals)} connected nets."
            )
            self.logger.info(f"Initial ratsnest length: {initial_rats:.2f} mm")
            
            # Update the existing GUI with the newly loaded data
            self.gui.board_data = self.board_data
            self.gui.optimizer = self.optimizer
            self.gui.file_path = os.path.basename(path)
            self.gui.source_brd_path = path
            self.gui.schematic_file_path = sch_path if schematic_usable else None
            self.gui._export_ready = False
            self.gui._placement_after = None
            if hasattr(self.gui, "btn_export_eagle"):
                self.gui.btn_export_eagle.configure(state="disabled")
            logging.info("Rendering board in GUI")
            self.gui._render(self.schematic_parts)
            logging.info("Board load workflow completed")


    def _decrease_calib(self):
        val = self.calibration_factor.get()
        new_val = max(0.1, val - 0.01)
        self.calibration_factor.set(new_val)
        self._save_calibration(new_val)
        if self.gui:
            self.gui.calibration_factor.set(new_val)
            self.gui._update_calibration_and_save(new_val)

    def _increase_calib(self):
        val = self.calibration_factor.get()
        new_val = val + 0.01
        self.calibration_factor.set(new_val)
        self._save_calibration(new_val)
        if self.gui:
            self.gui.calibration_factor.set(new_val)
            self.gui._update_calibration_and_save(new_val)


    
    
    
def check_schematic_board_consistency(
    board_data, schematic_parts, logger=None, schematic_net_classes=None
) -> bool:
    """Compare board and schematic component names and net connectivity."""
    is_consistent = True
    if logger:
        logger.info("=== STARTING BOARD-SCHEMATIC CONSISTENCY CHECK ===")
    else:
        print("\n=== STARTING BOARD-SCHEMATIC CONSISTENCY CHECK ===")

    schematic_names = {
        name for name, part in schematic_parts.items()
        if not str(getattr(part, "library", "")).lower().startswith("supply")
        and not str(name).upper().startswith("SUPPLY")
    }
    board_names = set(board_data.components)

    only_on_board = board_names - schematic_names
    only_in_schematic = schematic_names - board_names

    # The schematic is authoritative for electrical design intent. Board-only
    # elements may be standalone mechanical/graphic objects and must not block
    # analysis. Preserve them as fixed obstacles and exclude them from placement.
    board_data.orphan_components = set(only_on_board)
    board_data.schematic_only_components = set(only_in_schematic)
    if only_on_board:
        message = (
            "Board-only objects detected (not present in the schematic); "
            "they will be preserved as fixed obstacles and excluded from placement: "
            f"{sorted(only_on_board)}"
        )
        if logger:
            logger.warning(message)
        else:
            print(f"WARNING: {message}")
    if only_in_schematic:
        message = (
            "Schematic components not present on the board; they cannot be placed "
            "until a board footprint exists, but analysis will continue: "
            f"{sorted(only_in_schematic)}"
        )
        if logger:
            logger.warning(message)
        else:
            print(f"WARNING: {message}")

    board_netlist = {}
    for net_name, signal in board_data.signals.items():
        for connection in signal.connections:
            key = (connection.element, connection.pad)
            previous_net = board_netlist.get(key)
            if previous_net is not None and previous_net != net_name:
                message = (
                    f"Pad {connection.element}.{connection.pad} appears on multiple "
                    f"board nets: '{previous_net}' and '{net_name}'."
                )
                if logger:
                    logger.error(message)
                else:
                    print(f"ERROR: {message}")
                is_consistent = False
            board_netlist[key] = net_name

            part = schematic_parts.get(connection.element)
            if part is None:
                continue
            schematic_net_by_pin = getattr(part, "net_by_pin", {}) or {}
            pad_to_pin = getattr(part, "pad_to_pin_map", {}) or {}
            if not schematic_net_by_pin or not pad_to_pin:
                continue

            pin_name = next(
                (
                    mapped_pin for mapped_pad, mapped_pin in pad_to_pin.items()
                    if str(mapped_pad).strip().casefold()
                    == str(connection.pad).strip().casefold()
                ),
                None,
            )
            if pin_name is None:
                continue

            expected_net = next(
                (
                    schematic_net for schematic_pin, schematic_net in schematic_net_by_pin.items()
                    if str(schematic_pin).strip().casefold()
                    == str(pin_name).strip().casefold()
                ),
                None,
            )
            if expected_net is not None and expected_net != net_name:
                message = (
                    f"Net mismatch for {connection.element}.{connection.pad}: "
                    f"board='{net_name}', schematic='{expected_net}'."
                )
                if logger:
                    logger.error(message)
                else:
                    print(f"ERROR: {message}")
                is_consistent = False

    # Compare explicitly defined net classes when both board and schematic data exist.
    board_classes = getattr(board_data, "net_classes", {}) or {}
    schematic_classes = schematic_net_classes or {}
    board_explicit_classes = {number: data for number, data in board_classes.items() if number != 0}
    schematic_explicit_classes = {number: data for number, data in schematic_classes.items() if number != 0}
    if board_explicit_classes or schematic_explicit_classes:
        if set(board_explicit_classes) != set(schematic_explicit_classes):
            message = (
                "Net class number mismatch: "
                f"board={sorted(board_explicit_classes)}, "
                f"schematic={sorted(schematic_explicit_classes)}."
            )
            if logger:
                logger.error(message)
            else:
                print(f"ERROR: {message}")
            is_consistent = False
        else:
            for number, board_class in board_explicit_classes.items():
                schematic_class = schematic_explicit_classes[number]
                board_width = float(board_class.get("width", 0.0))
                schematic_width = float(schematic_class.width)
                # EAGLE net-class definitions do not define a per-class clearance.
                # Clearance is derived from board design rules, so comparing the
                # board's effective clearance with a missing schematic attribute
                # (implicitly parsed as zero) creates a false positive.
                if abs(board_width - schematic_width) > 0.001:
                    message = (
                        f"Net class {number} width mismatch: "
                        f"board={board_width:.4f} mm, schematic={schematic_width:.4f} mm."
                    )
                    if logger:
                        logger.error(message)
                    else:
                        print(f"ERROR: {message}")
                    is_consistent = False

    # Disable false-positive pin swap metadata on polarized components.
    for component_name in board_names.intersection(schematic_names):
        part = schematic_parts[component_name]
        connected_pads = {
            connection.pad
            for signal in board_data.signals.values()
            for connection in signal.connections
            if connection.element == component_name
        }
        pad_count = len(connected_pads)
        library_name = str(getattr(part, "library", "")).lower()
        upper_name = component_name.upper()
        is_diode = any(token in library_name for token in ("diode", "led", "rectifier")) or upper_name.startswith("D")
        is_transistor = (
            upper_name.startswith(("Q", "T")) or "transistor" in library_name
        ) and pad_count >= 3

        if not (is_diode or is_transistor):
            continue

        has_pin_swap = any(
            any(getattr(pin, "swaplevel", 0) > 0 for pin in pin_map.values())
            for pin_map in getattr(part, "gate_pin_definitions", {}).values()
        )
        if not has_pin_swap:
            continue

        component_type = "diode" if is_diode else "transistor/MOSFET"
        message = (
            f"Disabled invalid pin swap levels for {component_type} {component_name} "
            f"({getattr(part, 'deviceset', '')}); detected pads: {pad_count}."
        )
        if logger:
            logger.warning(message)
        else:
            print(f"WARNING: {message}")
        for pin_map in part.gate_pin_definitions.values():
            for pin in pin_map.values():
                pin.swaplevel = 0

    if is_consistent:
        message = "Board and schematic connectivity are consistent."
        if logger:
            logger.success(message)
        else:
            print(message)
    else:
        message = "Board and schematic inconsistencies were detected."
        if logger:
            logger.warning(message)
        else:
            print(f"WARNING: {message}")

    return is_consistent

def debug_print_schematic_entanglement(schematic_parts, logger=None):
    """Print a diagnostic summary of schematic components and their swappable gates and pins."""
    if logger:
        logger.info("=== SCHEMATIC SWAP DATA DIAGNOSTICS ===")
    else:
        print("\n=======================================================")
        print("      SCHEMATIC SWAP DATA DIAGNOSTICS                 ")
        print("=======================================================")
    
    components_with_swaps = 0
    
    for name, part in schematic_parts.items():
        # Check whether the component has gates or pins with swaplevel > 0
        has_gate_swaps = any(g.swaplevel > 0 for g in part.gates.values())
        has_pin_swaps = any(
            any(p.swaplevel > 0 for p in pin_dict.values()) 
            for pin_dict in part.gate_pin_definitions.values()
        )
        
        if has_gate_swaps or has_pin_swaps:
            components_with_swaps += 1
            if logger:
                logger.info(f"Component: {name} | Device set: {part.deviceset} | Library: {part.library}")
            else:
                print(f"\n📦 Component: {name} | Device set: {part.deviceset} | Library: {part.library}")
            
            if has_gate_swaps:
                if logger:
                    logger.info(f"SWAPPABLE GATES for {name}:")
                else:
                    print("  ├── 🔄 SWAPPABLE GATES:")
                for g_name, gate in part.gates.items():
                    if gate.swaplevel > 0:
                        if logger:
                            logger.debug(f"Gate '{g_name}' -> SwapLevel: {gate.swaplevel}")
                        else:
                            print(f"  │   └── Gate '{g_name}' -> SwapLevel: {gate.swaplevel} (Can be swapped with gates at the same level)")
            
            if has_pin_swaps:
                if logger:
                    logger.info(f"SWAPPABLE PINS for {name}:")
                else:
                    print("  └── 🔀 SWAPPABLE PINS:")
                for g_name, pin_dict in part.gate_pin_definitions.items():
                    swappable_pins = [p_name for p_name, p_data in pin_dict.items() if p_data.swaplevel > 0]
                    if swappable_pins:
                        physical_pad_map = []
                        for p_name in swappable_pins:
                            full_key = f"{g_name}.{p_name}" if g_name else p_name
                            physical_pad = part.pin_to_pad_map.get(full_key, "NC")
                            physical_pad_map.append(f"{p_name}(Pad {physical_pad})")
                        
                        swap_level = pin_dict[swappable_pins[0]].swaplevel
                        if logger:
                            logger.debug(f"Gate '{g_name}': pins {', '.join(physical_pad_map)} have SwapLevel {swap_level}")
                        else:
                            print(f"      └── Gate '{g_name}': pins {', '.join(physical_pad_map)} have SwapLevel {swap_level} (interchangeable with each other)")

    if logger:
        logger.info(f"Analysis complete: found {components_with_swaps} components with swap rules.")
    else:
        print("\n=======================================================")
        print(f" Analysis complete: found {components_with_swaps} components with swap rules.")
        print("=======================================================\n")




if __name__ == "__main__":
    root = tk.Tk()
    app = EagleApp(root)
    root.mainloop()