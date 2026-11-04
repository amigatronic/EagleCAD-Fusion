import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import math
import logging
import json
import csv
from pathlib import Path
import threading
import queue
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.ticker import FuncFormatter
from matplotlib.collections import LineCollection
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union

from dru_parser import DesignRules
from geometry import interpolate_arc
from eagle_export import export_placement_pair

class EagleGUI:
    def __init__(self, window, board_data, optimizer, file_path, calibration_factor):
        self.window = window
        self.board_data = board_data
        self.optimizer = optimizer
        self.file_path = file_path
        self.calibration_factor = calibration_factor
        self.current_scale = "fit"
        self._optimizer_queue = queue.Queue()
        self._optimizer_thread = None
        self._optimizer_cancel_event = threading.Event()
        self._optimizer_running = False
        self._optimizer_poll_active = False
        self._plateau_dialog = None
        self._plateau_pending = None
        self._monitor_history = []
        self._benchmark_history = []
        self._benchmark_result = None
        self._placement_before = None
        self._placement_after = None
        self._placement_file_path = file_path
        self._last_rendered_file_path = file_path
        self.base_dpi = self.window.winfo_fpixels('1i')
        self.unit_label = getattr(self.board_data, "display_unit", "mm")
        self._warning_blink_state = False
        self._warning_blink_job = None
        self._stop_recommended_seen = False
        self.display_unit_var = tk.StringVar(value=self.unit_label)
        self._display_unit_choices = ("mm", "mil", "in", "um")
        self._warning_blink_job = None
        self._stop_recommended_seen = False

        # Design-rule management.
        self.dru_file_path = None
        if hasattr(self.board_data, 'design_rules') and self.board_data.design_rules:
            self.design_rules = self.board_data.design_rules
        else:
            self.design_rules = DesignRules()
        
        # Matplotlib attributes
        self.fig = None
        self.ax = None
        self.canvas = None
        self.toolbar = None
        self.layer_artists = {}
        self.layer_visibility = {}
        self.check_buttons = None
        
        # Store schematic_parts for rendering without extra parameters
        self.schematic_parts = None
        self.schematic_file_path = None
        self._export_ready = False
        
        self._build_ui()
        self._configure_progress_styles()
        self._on_display_unit_change(render=False)
        
    def _configure_progress_styles(self):
        """Initialize the custom status bar used for unlimited searches."""
        self._set_progress_status("green")

    def _set_progress_status(self, state):
        """Keep the bar full; use color to indicate search quality, never completion."""
        colors = {
            "green": "#2EAD58",
            "amber": "#E0A020",
            "red": "#E53935",
            "neutral": "#7B8794",
        }
        color = colors.get(state, colors["neutral"])
        self.optimizer_progress.delete("all")
        width = max(1, int(self.optimizer_progress.winfo_width()))
        height = max(1, int(self.optimizer_progress.winfo_height()))
        if width <= 2:
            width = 130
        if height <= 2:
            height = 18
        self.optimizer_progress.configure(background="#E5E7EB")
        self.optimizer_progress.create_rectangle(1, 1, width - 1, height - 1, fill=color, outline=color)

    def _format_distance(self, value_mm):
        """Format an internal millimeter distance in the unit declared by the BRD grid."""
        unit = self.display_unit_var.get() if hasattr(self, "display_unit_var") else (getattr(self.board_data, "display_unit", "mm") or "mm")
        factor = {"mm": 1.0, "mil": 1.0 / 0.0254, "in": 1.0 / 25.4, "um": 1000.0}.get(unit, 1.0)
        precision = 3 if unit in {"mm", "in"} else 1 if unit == "mil" else 0
        return f"{float(value_mm) * factor:.{precision}f} {unit}"

    def _unit_factor(self):
        unit = self.display_unit_var.get() if hasattr(self, "display_unit_var") else (getattr(self.board_data, "display_unit", "mm") or "mm")
        return {"mm": 1.0, "mil": 1.0 / 0.0254, "in": 1.0 / 25.4, "um": 1000.0}.get(unit, 1.0)

    def _format_axis_units(self, axis):
        factor = self._unit_factor()
        formatter = FuncFormatter(lambda value, _position: f"{value * factor:g}")
        axis.xaxis.set_major_formatter(formatter)
        axis.yaxis.set_major_formatter(formatter)

    def _on_display_unit_change(self, _event=None, render=True):
        """Refresh all visible distance labels using the selected display unit."""
        self.unit_label = self.display_unit_var.get()
        for label, unit in (("Comp-Comp", self.unit_label), ("Board Edge", self.unit_label), ("Copper Width", self.unit_label)):
            widget = getattr(self, {"Comp-Comp": "lbl_comp_unit", "Board Edge": "lbl_edge_unit", "Copper Width": "lbl_track_unit"}[label], None)
            if widget is not None:
                widget.configure(text=f"{label} ({unit}):")
        factor = self._unit_factor()
        for spinbox, max_mm, increment_mm in (
            (getattr(self, "spin_comp", None), 10.0, 0.05),
            (getattr(self, "spin_edge", None), 20.0, 0.1),
            (getattr(self, "spin_track", None), 5.0, 0.05),
        ):
            if spinbox is not None:
                spinbox.configure(to=max_mm * factor, increment=increment_mm * factor)
        self._update_dru_ui_fields()
        if hasattr(self, "monitor_table"):
            self.monitor_table.heading("best", text=f"Best Fitness ({self.unit_label})")
        grid_spacing = getattr(self.board_data, "grid_spacing_mm", None) if self.board_data else None
        if hasattr(self, "snap_grid_check"):
            self.snap_grid_check.configure(text=f"Snap to board grid ({self._format_distance(grid_spacing)})" if grid_spacing else "Snap to board grid (not defined in BRD)")
        if hasattr(self, "monitor_best_label"):
            self.monitor_best_label.configure(text=f"Best fitness: {self._format_distance(getattr(self.optimizer, 'last_result', {}).get('final_fitness', 0.0)) if getattr(self.optimizer, 'last_result', None) else '—'}")
        if render and self.board_data:
            self._render()

    def _start_warning_blink(self):
        if self._warning_blink_job is None:
            self._warning_blink_state = False
            self._blink_warning()

    def _blink_warning(self):
        if not self._optimizer_running and not self._stop_recommended_seen:
            self._warning_blink_job = None
            return
        self._warning_blink_state = not self._warning_blink_state
        self.monitor_warning_label.configure(
            foreground="#FFFFFF" if self._warning_blink_state else "#FF3030",
            background="#7F1010" if self._warning_blink_state else "#300909",
        )
        self._warning_blink_job = self.window.after(450, self._blink_warning)
        if not self._optimizer_running:
            self.window.after(8000, self._stop_warning_blink)

    def _stop_warning_blink(self):
        if self._warning_blink_job is not None:
            try:
                self.window.after_cancel(self._warning_blink_job)
            except tk.TclError:
                pass
            self._warning_blink_job = None

    def _build_ui(self):
        # ---------------------------------------------------------
        # TOP BAR (Open, file information, zoom/scale)
        # ---------------------------------------------------------
        top_bar = ttk.Frame(self.window, padding=10)
        top_bar.pack(side=tk.TOP, fill=tk.X)
        btn_open = ttk.Button(top_bar, text="Open .brd File", command=self._on_open_file)
        btn_open.pack(side=tk.LEFT, padx=5)
        
        self.lbl_file = ttk.Label(top_bar, text="No file loaded", font=("Arial", 10, "italic"))
        self.lbl_file.pack(side=tk.LEFT, padx=15)
        if self.file_path:
            self.lbl_file.config(text=str(self.file_path), font=("Arial", 10, "bold"))
        
        ttk.Label(top_bar, text="View:").pack(side=tk.LEFT, padx=5)
        self.scale_var = tk.StringVar(value="Fit")
        scale_combo = ttk.Combobox(top_bar, textvariable=self.scale_var, state="readonly", width=10)
        scale_combo['values'] = ("Fit", "1:1 Real", "2:1", "5:1")
        scale_combo.pack(side=tk.LEFT, padx=5)
        scale_combo.bind("<<ComboboxSelected>>", self._on_scale_change)
        ttk.Label(top_bar, text="Units:").pack(side=tk.LEFT, padx=(8, 2))
        self.unit_combo = ttk.Combobox(top_bar, textvariable=self.display_unit_var, state="readonly", width=6,
                                       values=self._display_unit_choices)
        self.unit_combo.pack(side=tk.LEFT, padx=3)
        self.unit_combo.bind("<<ComboboxSelected>>", self._on_display_unit_change)

        # ---------------------------------------------------------
        # PHYSICAL RULER CALIBRATION PANEL
        # ---------------------------------------------------------
        calib_frame = ttk.LabelFrame(self.window, text=" Physical Ruler Calibration ", padding=5)
        calib_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=2)
        
        ttk.Label(calib_frame, text="Align screen measurements with a physical ruler. Click components to lock or unlock them.").pack(side=tk.LEFT, padx=5)
        
        btn_minus = ttk.Button(calib_frame, text=" - Zoom Out ", width=15, command=self._decrease_calib)
        btn_minus.pack(side=tk.LEFT, padx=5)
        
        self.lbl_calib_val = ttk.Label(calib_frame, text=f"Scale factor: {self.calibration_factor.get():.3f}", font=("Arial", 10, "bold"))
        self.lbl_calib_val.pack(side=tk.LEFT, padx=10)
        
        btn_plus = ttk.Button(calib_frame, text=" + Zoom In ", width=15, command=self._increase_calib)
        btn_plus.pack(side=tk.LEFT, padx=5)

        # ---------------------------------------------------------
        # DESIGN RULES AND CLEARANCE (DRU) PANEL
        # ---------------------------------------------------------
        dru_frame = ttk.LabelFrame(self.window, text=" Design Rules and Clearance (DRU) ", padding=5)
        dru_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=2)

        # DRU controls
        btn_load_dru = ttk.Button(dru_frame, text="📁 Load .DRU", command=self._on_load_dru)
        btn_load_dru.pack(side=tk.LEFT, padx=5)

        self.btn_clear_dru = ttk.Button(dru_frame, text="✖ Reset to BRD", command=self._on_clear_dru, state="disabled")
        self.btn_clear_dru.pack(side=tk.LEFT, padx=5)

        self.lbl_dru_status = ttk.Label(dru_frame, text="Source: Values from .BRD file", font=("Arial", 9, "italic"))
        self.lbl_dru_status.pack(side=tk.LEFT, padx=10)

        # Manual clearance inputs
        self.unit_label = getattr(self.board_data, "display_unit", "mm")
        self.lbl_comp_unit = ttk.Label(dru_frame, text=f"Comp-Comp ({self.unit_label}):")
        self.lbl_comp_unit.pack(side=tk.LEFT, padx=(15, 2))
        self.spin_comp = ttk.Spinbox(dru_frame, from_=0.0, to=10.0, increment=0.05, width=6, command=self._on_manual_dru_change)
        self.spin_comp.pack(side=tk.LEFT, padx=2)

        self.lbl_edge_unit = ttk.Label(dru_frame, text=f"Board Edge ({self.unit_label}):")
        self.lbl_edge_unit.pack(side=tk.LEFT, padx=(10, 2))
        self.spin_edge = ttk.Spinbox(dru_frame, from_=0.0, to=20.0, increment=0.1, width=6, command=self._on_manual_dru_change)
        self.spin_edge.pack(side=tk.LEFT, padx=2)

        self.lbl_track_unit = ttk.Label(dru_frame, text=f"Copper Width ({self.unit_label}):")
        self.lbl_track_unit.pack(side=tk.LEFT, padx=(10, 2))
        self.spin_track = ttk.Spinbox(dru_frame, from_=0.0, to=5.0, increment=0.05, width=6, command=self._on_manual_dru_change)
        self.spin_track.pack(side=tk.LEFT, padx=2)

        # Add this button to top_bar in _build_ui()
        self.btn_optimize = ttk.Button(top_bar, text="Run Orbit Placement Engine", command=self._start_optimization, state="disabled")
        self.btn_optimize.pack(side=tk.RIGHT, padx=5)
        self.btn_stop_optimization = ttk.Button(top_bar, text="Stop", command=self._stop_optimization, state="disabled")
        self.btn_stop_optimization.pack(side=tk.RIGHT, padx=2)
        self.optimizer_progress = tk.Canvas(
            top_bar, width=130, height=18, background="#E5E7EB",
            highlightthickness=1, highlightbackground="#9CA3AF", borderwidth=0
        )
        self.optimizer_progress.pack(side=tk.RIGHT, padx=4)
        self.optimizer_status = ttk.Label(top_bar, text="Optimizer idle")
        self.optimizer_status.pack(side=tk.RIGHT, padx=4)

        placement_options = ttk.LabelFrame(self.window, text="Placement Constraints", padding=(8, 4))
        placement_options.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 4))

        self.seed_var = tk.StringVar(value="7")
        ttk.Label(placement_options, text="Random Seed:").pack(side=tk.LEFT, padx=(4, 3))
        self.seed_entry = ttk.Entry(placement_options, textvariable=self.seed_var, width=9)
        self.seed_entry.pack(side=tk.LEFT, padx=(0, 12))

        self.allow_layer_swaps_var = tk.BooleanVar(value=False)
        self.layer_swap_check = ttk.Checkbutton(
            placement_options, text="Allow SMD layer swaps", variable=self.allow_layer_swaps_var,
        )
        self.layer_swap_check.pack(side=tk.LEFT, padx=(0, 12))
        self.snap_grid_var = tk.BooleanVar(value=bool(getattr(self.board_data, "grid_spacing_mm", None)))
        grid_spacing = getattr(self.board_data, "grid_spacing_mm", None)
        grid_label = f"Snap to board grid ({self._format_distance(grid_spacing)})" if grid_spacing else "Snap to board grid (not defined in BRD)"
        self.snap_grid_check = ttk.Checkbutton(
            placement_options, text=grid_label, variable=self.snap_grid_var,
        )
        self.snap_grid_check.pack(side=tk.LEFT, padx=(0, 12))
        self._displayed_grid_spacing = grid_spacing
        if not grid_spacing:
            self.snap_grid_check.configure(state="disabled")

        self.adaptive_strategy_var = tk.BooleanVar(value=True)
        self.adaptive_strategy_check = ttk.Checkbutton(
            placement_options, text="Adaptive strategy selection", variable=self.adaptive_strategy_var,
        )
        self.adaptive_strategy_check.pack(side=tk.LEFT, padx=(0, 10))
        self.auto_stop_var = tk.BooleanVar(value=True)
        self.auto_stop_check = ttk.Checkbutton(
            placement_options, text="Auto-stop after plateau", variable=self.auto_stop_var,
        )
        self.auto_stop_check.pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(placement_options, text="Min (min):").pack(side=tk.LEFT, padx=(2, 2))
        self.auto_stop_minutes_var = tk.StringVar(value="20")
        self.auto_stop_minutes_entry = ttk.Entry(placement_options, textvariable=self.auto_stop_minutes_var, width=4)
        self.auto_stop_minutes_entry.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(placement_options, text="Stale windows:").pack(side=tk.LEFT, padx=(2, 2))
        self.auto_stop_patience_var = tk.StringVar(value="20")
        self.auto_stop_patience_entry = ttk.Entry(placement_options, textvariable=self.auto_stop_patience_var, width=4)
        self.auto_stop_patience_entry.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_before_after = ttk.Button(
            placement_options, text="Before / After Placement", command=self._show_before_after,
            state="disabled",
        )
        self.btn_before_after.pack(side=tk.RIGHT, padx=4)
        self.btn_export_eagle = ttk.Button(
            placement_options, text="Export Eagle Project", command=self._export_eagle_project,
            state="disabled",
        )
        self.btn_export_eagle.pack(side=tk.RIGHT, padx=4)

        self.monitor_frame = ttk.LabelFrame(self.window, text="Live Placement Search Monitor", padding=(8, 5))
        self.monitor_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=(0, 4))
        metrics = ttk.Frame(self.monitor_frame)
        metrics.pack(fill=tk.X)
        self.monitor_eval_label = ttk.Label(metrics, text="Evaluations: 0 / No limit")
        self.monitor_eval_label.pack(side=tk.LEFT, padx=(0, 16))
        self.monitor_best_label = ttk.Label(metrics, text="Best fitness: —")
        self.monitor_best_label.pack(side=tk.LEFT, padx=(0, 16))
        self.monitor_total_label = ttk.Label(metrics, text="Total improvement: 0.000%")
        self.monitor_total_label.pack(side=tk.LEFT, padx=(0, 16))
        self.monitor_window_label = ttk.Label(metrics, text="Latest window: —")
        self.monitor_window_label.pack(side=tk.LEFT, padx=(0, 16))
        self.monitor_warning_label = tk.Label(
            self.monitor_frame,
            text="Search monitor idle. The best placement will be restored when you stop.",
            foreground="#555555",
            background="#F0F0F0",
            anchor="w",
            padx=4,
        )
        self.monitor_warning_label.pack(anchor=tk.W, pady=(4, 3))
        columns = ("evaluations", "best", "window", "total", "trend")
        self.monitor_table = ttk.Treeview(self.monitor_frame, columns=columns, show="headings", height=4)
        for column, heading, width in (
            ("evaluations", "Evaluations", 120),
            ("best", f"Best Fitness ({self.unit_label})", 145),
            ("window", "Window Improvement", 155),
            ("total", "Total Improvement", 145),
            ("trend", "Search Status", 240),
        ):
            self.monitor_table.heading(column, text=heading)
            self.monitor_table.column(column, width=width, anchor=tk.W, stretch=column == "trend")
        self.monitor_table.pack(fill=tk.X, expand=False)
        benchmark_controls = ttk.Frame(self.monitor_frame)
        benchmark_controls.pack(fill=tk.X, pady=(4, 0))
        self.btn_export_benchmark = ttk.Button(
            benchmark_controls, text="Export Benchmark CSV", command=self._export_benchmark_csv, state="disabled"
        )
        self.btn_export_benchmark.pack(side=tk.RIGHT, padx=2)

        btn_summary = ttk.Button(top_bar, text="📊 Optimizer Data Status", command=self._show_data_summary)
        btn_summary.pack(side=tk.RIGHT, padx=5)

        # Populate the initial input fields
        self._update_dru_ui_fields()

        # ---------------------------------------------------------
        # MAIN RENDERING AND LOG AREA
        # ---------------------------------------------------------
        self.render_frame = ttk.Frame(self.window)
        self.render_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Board panel with Matplotlib (left)
        board_container = ttk.Frame(self.render_frame)
        board_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.fig, self.ax = plt.subplots(figsize=(10, 7))
        self.canvas = FigureCanvasTkAgg(self.fig, master=board_container)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        self.fig.canvas.mpl_connect('button_press_event', self._on_canvas_click)
        
        self.toolbar = NavigationToolbar2Tk(self.canvas, board_container)
        self.toolbar.update()
        
        self.window.update_idletasks() 
        self.canvas.get_tk_widget().bind("<Configure>", self._on_window_resize)
        
        # Right panel: legend and log
        self.right_panel = ttk.Frame(self.render_frame)
        self.right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))
        
        # 1. LEGEND (built once)
        self.legend_container = ttk.LabelFrame(self.right_panel, text=" PCB Legend (Click to Show/Hide) ")
        self.legend_container.pack(side=tk.TOP, fill=tk.X, pady=(0, 10))
        
        self.legend_vars = {}
        self.legend_rows = {}
        legend_data = [
            ("PCB Outline", "#e9edf0", "#666666"),
            ("Top Copper (L1)", "#ef4444", "#ef4444"),
            ("Bottom Copper (L16)", "#3b82f6", "#3b82f6"),
            ("Inner Copper Layers", "#a855f7", "#a855f7"),
            ("Top Keepout (L39)", "#ff6b6b", "#e60000"),
            ("Bottom Keepout (L40)", "#4dadf7", "#0066cc"),
            ("Top Restrict (L41)", "#f59e0b", "#b45309"),
            ("Bottom Restrict (L42)", "#a78bfa", "#6d28d9"),
            ("Comp. Unlocked (TOP)", "#fffbeb", "#d97706"),
            ("Comp. Unlocked (BOTTOM)", "#eff6ff", "#2563eb"),
            ("Comp. Locked [LOCKED]", "#fee2e2", "#dc2626"),
            ("Mechanical Hole", "#212529", "#888888"),
            ("Via", "#b87333", "#8a4f1a"),
            ("Swappable Ratsnest (L19)", "#FF00FF", "#FF00FF")
        ]
        
        for label, facecolor, edgecolor in legend_data:
            var = tk.BooleanVar(value=True)
            self.legend_vars[label] = var
            
            row_frame = tk.Frame(self.legend_container, bg='#f0f0f0')
            self.legend_rows[label] = row_frame
            row_frame.pack(anchor=tk.W, padx=5, pady=2, fill=tk.X)
            
            patch_canvas = tk.Canvas(row_frame, width=20, height=16, bg='#f0f0f0', highlightthickness=0)
            patch_canvas.pack(side=tk.LEFT, padx=2)
            patch_canvas.create_rectangle(2, 2, 18, 14, fill=facecolor, outline=edgecolor, width=1)
            
            chk = tk.Checkbutton(
                row_frame,
                text=label,
                variable=var,
                command=self._on_legend_toggle,
                font=("Arial", 8),
                bg='#f0f0f0',
                activebackground='#f0f0f0'
            )
            chk.pack(side=tk.LEFT, anchor=tk.W)

        # 2. LOG PANEL
        self.log_container = ttk.LabelFrame(self.right_panel, text=" Event Log ")
        self.log_container.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True)
        
        # Top row for log controls (Save and Clear buttons)
        log_ctrl_frame = ttk.Frame(self.log_container)
        log_ctrl_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=(2, 2))
        
        btn_clear_log = ttk.Button(log_ctrl_frame, text="🗑️ Clear Log", command=self._clear_log)
        btn_clear_log.pack(side=tk.RIGHT, padx=(2, 0))

        btn_save_log = ttk.Button(log_ctrl_frame, text="💾 Save Log", command=self._save_log)
        btn_save_log.pack(side=tk.RIGHT, padx=2)

        # Area di testo e Scrollbar
        self.log_text = tk.Text(self.log_container, bg="#1E1E1E", fg="#00FF00", font=("Consolas", 9), wrap=tk.WORD)
        log_vbar = ttk.Scrollbar(self.log_container, orient=tk.VERTICAL, command=self.log_text.yview)
        
        self.log_text.configure(yscrollcommand=log_vbar.set)
        
        log_vbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.log_text.config(state=tk.DISABLED)
        self._update_legend_visibility()
        
    def _is_component_layer_visible(self, comp) -> bool:
        """Check whether the component layer is visible in the legend."""
        if getattr(comp, 'locked', False):
            label = "Comp. Locked [LOCKED]"
        elif getattr(comp, 'mirror', False):
            label = "Comp. Unlocked (BOTTOM)"
        else:
            label = "Comp. Unlocked (TOP)"
        
        var = self.legend_vars.get(label)
        return var.get() if var is not None else True
    
    def _on_legend_toggle(self):
        """Handle clicks on legend checkbuttons."""
        self._apply_layer_visibility()
        if self.canvas:
            self.canvas.draw_idle()
    
    def _update_legend_visibility(self):
        """Show only legend layers that contain drawable elements."""
        layer_mapping = {
            "PCB Outline": "PCB Outline",
            "Top Copper (L1)": "Copper TOP",
            "Bottom Copper (L16)": "Copper BOTTOM",
            "Inner Copper Layers": "Copper Inner",
            "Top Keepout (L39)": "Keepout TOP",
            "Bottom Keepout (L40)": "Keepout BOTTOM",
            "Top Restrict (L41)": "Restrict TOP",
            "Bottom Restrict (L42)": "Restrict BOTTOM",
            "Comp. Unlocked (TOP)": "Components TOP",
            "Comp. Unlocked (BOTTOM)": "Components BOTTOM",
            "Comp. Locked [LOCKED]": "Locked Components",
            "Mechanical Hole": "Holes",
            "Via": "Vias",
            "Swappable Ratsnest (L19)": "Swappable Ratsnest"
        }
        for label, layer_key in layer_mapping.items():
            if label in self.legend_rows:
                # Show the row when the layer contains drawable elements; otherwise hide it
                if layer_key in self.layer_artists and len(self.layer_artists[layer_key]) > 0:
                    self.legend_rows[label].pack(anchor=tk.W, padx=5, pady=2, fill=tk.X)
                else:
                    self.legend_rows[label].pack_forget()
    
    def _apply_layer_visibility(self):
        """Apply the current checkbutton states to canvas graphics."""
        layer_mapping = {
            "PCB Outline": "PCB Outline",
            "Top Copper (L1)": "Copper TOP",
            "Bottom Copper (L16)": "Copper BOTTOM",
            "Inner Copper Layers": "Copper Inner",
            "Top Keepout (L39)": "Keepout TOP",
            "Bottom Keepout (L40)": "Keepout BOTTOM",
            "Top Restrict (L41)": "Restrict TOP",
            "Bottom Restrict (L42)": "Restrict BOTTOM",
            "Comp. Unlocked (TOP)": "Components TOP",
            "Comp. Unlocked (BOTTOM)": "Components BOTTOM",
            "Comp. Locked [LOCKED]": "Locked Components",
            "Mechanical Hole": "Holes",
            "Via": "Vias",
            "Swappable Ratsnest (L19)": "Swappable Ratsnest"
        }
        for label, layer_key in layer_mapping.items():
            if label in self.legend_vars and layer_key in self.layer_artists:
                is_visible = self.legend_vars[label].get()
                for artist in self.layer_artists[layer_key]:
                    artist.set_visible(is_visible)
    
    
    # ------------------------------------------------------------------
    # GESTIONE METODI DRU (Design Rules)
    # ------------------------------------------------------------------
    def _update_dru_ui_fields(self):
        """Update spinboxes with the current DesignRules values."""
        self.spin_comp.delete(0, tk.END)
        self.spin_comp.insert(0, f"{self.design_rules.clearance_comp_to_comp * self._unit_factor():.3f}")

        self.spin_edge.delete(0, tk.END)
        self.spin_edge.insert(0, f"{self.design_rules.clearance_board_edge * self._unit_factor():.3f}")

        self.spin_track.delete(0, tk.END)
        self.spin_track.insert(0, f"{self.design_rules.clearance_track_to_track * self._unit_factor():.3f}")

    def _on_load_dru(self):
        """Load an external .dru file."""
        path = filedialog.askopenfilename(
            title="Select Design Rules File (.dru)",
            filetypes=[("Eagle Design Rules", "*.dru"), ("All files", "*.*")]
        )
        if not path:
            return

        if self.design_rules.load_from_dru_file(path):
            self.dru_file_path = path
            filename = path.replace("\\", "/").split("/")[-1]
            self.lbl_dru_status.config(text=f"DRU active: {filename}", foreground="green")
            self.btn_clear_dru.config(state="normal")
            
            self._update_dru_ui_fields()
            self._toggle_dru_inputs(enable=False)
            
            if self.board_data:
                self.board_data.design_rules = self.design_rules
            
            self.log_message(f"Loaded design rules from: {filename}", "SUCCESS")
        else:
            messagebox.showerror(
                "DRU Error",
                self.design_rules.last_error or "Unable to load the selected .dru file.",
            )

    def _clear_log(self):
        """Clear the event log."""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)
    
    def _save_log(self):
        """Save the event log to a text file."""
        content = self.log_text.get("1.0", tk.END).strip()
        if not content:
            messagebox.showwarning("Empty Log", "There are no log entries to save.")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            title="Save Event Log"
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
                self.log_message(f"Log saved to: {file_path}", "SUCCESS")
            except Exception as e:
                messagebox.showerror("Save Error", f"Unable to save the log:\n{e}")
    
    def _on_clear_dru(self):
        """Restore the rules read from the original .BRD file."""
        self.dru_file_path = None
        self.btn_clear_dru.config(state="disabled")
        self._toggle_dru_inputs(enable=True)

        if hasattr(self.board_data, 'design_rules') and self.board_data.design_rules:
            self.design_rules = self.board_data.design_rules
            self.lbl_dru_status.config(text="Source: Values from .BRD file", foreground="black")
        else:
            self.lbl_dru_status.config(text="Source: Manual Values", foreground="black")

        self._update_dru_ui_fields()
        self.log_message("Restored the default design rules from the BRD.", "INFO")

    def _on_manual_dru_change(self):
        """Run when the user manually changes a spinbox."""
        if not self.dru_file_path:
            try:
                comp_c = float(self.spin_comp.get())
                edge_c = float(self.spin_edge.get())
                track_c = float(self.spin_track.get())
                factor = self._unit_factor()
                self.design_rules.load_from_manual_inputs(comp_c / factor, edge_c / factor, track_c / factor)
                if self.board_data:
                    self.board_data.design_rules = self.design_rules
            except ValueError:
                pass

    def _toggle_dru_inputs(self, enable: bool):
        state = "normal" if enable else "disabled"
        self.spin_comp.config(state=state)
        self.spin_edge.config(state=state)
        self.spin_track.config(state=state)

    def get_effective_design_rules(self) -> DesignRules:
        """Return the active DesignRules object used by the optimizer."""
        self._on_manual_dru_change()
        return self.design_rules

    # ------------------------------------------------------------------
    # Remaining GUI methods.
    # ------------------------------------------------------------------
    def log_message(self, message: str, level: str = "INFO"):
        """Append a message to the log."""
        timestamp = __import__('datetime').datetime.now().strftime("%H:%M:%S")
        
        colors = {
            "INFO": "#00FF00",      # Green
            "WARNING": "#FFFF00",   # Yellow
            "ERROR": "#FF0000",     # Red
            "DEBUG": "#00FFFF",     # Cyan
            "SUCCESS": "#00FF00"    # Green
        }
        
        color = colors.get(level, "#00FF00")
        
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{timestamp}] {level}: {message}\n", (level,))
        self.log_text.tag_config(level, foreground=color)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
    
    def set_open_file_callback(self, callback):
        self._open_file_callback = callback
    
    def _on_open_file(self):
        if hasattr(self, '_open_file_callback'):
            self._open_file_callback()
    
    def _on_scale_change(self, event):
        val = self.scale_var.get().lower()
        if "fit" in val:
            self.current_scale = "fit"
        elif "1:1" in val:
            self.current_scale = 1.0
        elif "2:1" in val:
            self.current_scale = 2.0
        elif "5:1" in val:
            self.current_scale = 5.0
        self._render()
    
    def _update_calibration_and_save(self, new_val: float):
        self.calibration_factor.set(new_val)
        self.lbl_calib_val.config(text=f"Scale factor: {new_val:.3f}")
        if self.current_scale != "fit":
            self._render()
    
    def _decrease_calib(self):
        val = self.calibration_factor.get()
        self._update_calibration_and_save(max(0.1, val - 0.01))
    
    def _increase_calib(self):
        val = self.calibration_factor.get()
        self._update_calibration_and_save(val + 0.01)
    
    def _on_window_resize(self, event):
        if not hasattr(self, 'fig') or not self.board_data:
            return
        if self.current_scale == "fit":
            self._render()
    
    def _clean_and_validate_polygon(self, pts) -> Polygon:
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        return poly
    
    def _on_canvas_click(self, event):
        if self._optimizer_running:
            return
        if event.inaxes != self.ax:
            return

        if not self.board_data or event.xdata is None or event.ydata is None:
            return
            
        clicked_component = None
        min_dist = float('inf')
        
        for name, comp in self.board_data.components.items():
            # <--- Ignore components whose layer is hidden
            if not self._is_component_layer_visible(comp):
                continue

            dist = math.hypot(event.xdata - comp.x, event.ydata - comp.y)
            threshold = max(comp.width, comp.height) / 1.4
            if dist < threshold and dist < min_dist:
                min_dist = dist
                clicked_component = name
        
        if clicked_component:
            comp = self.board_data.components[clicked_component]
            
            # === LEFT CLICK: lock or unlock component position ===
            if event.button == 1:
                comp.locked = not getattr(comp, 'locked', False)
                status = "LOCKED 🔒" if comp.locked else "UNLOCKED 🔓"
                self.log_message(f"Component {clicked_component} position set to: {status}", "INFO")
                
            # RIGHT CLICK: enable or disable logical swapping
            elif event.button == 3:
                if self._is_component_swappable(clicked_component):
                    current_swap = getattr(comp, 'swap_enabled', True)
                    comp.swap_enabled = not current_swap
                    status = "ENABLED 🔄" if comp.swap_enabled else "DISABLED 🚫"
                    self.log_message(f"Logical swap for {clicked_component} set to: {status}", "INFO")
                else:
                    self.log_message(f"Component {clicked_component} has no swappable gates or pins in the schematic.", "WARNING")
            if self.optimizer:
                ratsnest = self.optimizer.calculate_ratsnest_length()
            self._render()

    def _start_optimization(self):
        """Run the placement optimizer in a worker and update a live, non-modal monitor."""
        if not self.optimizer or not self.board_data or self._optimizer_running:
            return
        orphan_names = set(getattr(self.board_data, "orphan_components", set()) or set())
        movable = [
            component for component in self.board_data.components.values()
            if not component.locked and component.name not in orphan_names
        ]
        try:
            seed = int(self.seed_var.get().strip())
        except (ValueError, AttributeError):
            messagebox.showerror("Invalid Random Seed", "Random Seed must be a whole integer.")
            self.seed_entry.focus_set()
            return
        try:
            auto_stop_minutes = float(self.auto_stop_minutes_var.get().strip())
            auto_stop_patience = int(self.auto_stop_patience_var.get().strip())
            if auto_stop_minutes < 0 or auto_stop_patience < 1:
                raise ValueError
        except (ValueError, AttributeError):
            messagebox.showerror(
                "Invalid Auto-Stop Settings",
                "Minimum search time must be zero or greater, and stale windows must be a positive integer.",
            )
            self.auto_stop_minutes_entry.focus_set()
            return

        if len(movable) < 2:
            self.log_message(
                "Optimization skipped: fewer than two eligible unlocked components are available.",
                "WARNING",
            )
            return

        # Keep a very large safety budget; normal termination is manual or plateau-based auto-stop.
        max_evaluations = 1_000_000_000_000
        self._optimizer_running = True
        self._stop_recommended_seen = False
        self._optimizer_cancel_event.clear()
        self._placement_before = {
            name: (comp.x, comp.y, comp.rot, comp.mirror)
            for name, comp in self.board_data.components.items()
        }
        self._placement_after = None
        self.btn_before_after.configure(state="disabled")
        snap_to_grid = bool(self.snap_grid_var.get() and getattr(self.board_data, "grid_spacing_mm", None))
        allow_layer_swaps = bool(self.allow_layer_swaps_var.get())
        adaptive_strategy = bool(self.adaptive_strategy_var.get())
        auto_stop_enabled = bool(self.auto_stop_var.get())
        self._monitor_history.clear()
        self._benchmark_history.clear()
        self._benchmark_result = None
        self.btn_export_benchmark.configure(state="disabled")
        for item in self.monitor_table.get_children():
            self.monitor_table.delete(item)
        self.btn_optimize.configure(state="disabled")
        self.btn_stop_optimization.configure(state="normal")
        self._set_progress_status("green")
        self.optimizer_status.configure(text="Search running...")
        self.monitor_eval_label.configure(text="Evaluations: 0 / No limit")
        self.monitor_best_label.configure(text="Best fitness: —")
        self.monitor_total_label.configure(text="Total improvement: 0.000%")
        self.monitor_window_label.configure(text="Latest window: waiting for first checkpoint")
        self.monitor_warning_label.configure(
            text="Search active. Automatic stop is governed by the configured minimum time and plateau threshold.",
            foreground="#555555",
        )
        self.log_message(
            "Placement search started with a large safety evaluation budget. Manual Stop is always available. "
            f"Random seed: {seed}. Adaptive strategy selection: {'enabled' if adaptive_strategy else 'disabled'}. "
            f"Automatic plateau stop: {'enabled' if auto_stop_enabled else 'disabled'}.",
            "INFO",
        )

        def report_progress(current, total, fitness):
            self._optimizer_queue.put(("progress", current, total, fitness))

        def report_monitor(details):
            self._optimizer_queue.put(("monitor", details))

        def worker():
            try:
                result = self.optimizer.optimize(
                    max_iterations=max_evaluations,
                    max_evaluations=max_evaluations,
                    progress_callback=report_progress,
                    cancel_callback=self._optimizer_cancel_event.is_set,
                    plateau_window=5000,
                    plateau_threshold_percent=0.01,
                    plateau_patience=auto_stop_patience,
                    monitor_callback=report_monitor,
                    snap_to_grid=snap_to_grid,
                    allow_layer_swaps=allow_layer_swaps,
                    seed=seed,
                    adaptive_strategy=adaptive_strategy,
                    auto_stop_enabled=auto_stop_enabled,
                    auto_stop_min_seconds=auto_stop_minutes * 60.0,
                    auto_stop_patience=auto_stop_patience,
                )
                self._optimizer_queue.put(("done", result))
            except Exception as exc:
                self._optimizer_queue.put(("error", str(exc)))

        self._optimizer_thread = threading.Thread(target=worker, name="PlacementOptimizer", daemon=True)
        self._optimizer_thread.start()
        if not self._optimizer_poll_active:
            self._optimizer_poll_active = True
            self.window.after(100, self._poll_optimizer_queue)

    def _update_placement_monitor(self, details):
        """Refresh the live metrics and retain a short history of search checkpoints."""
        evaluations = int(details.get("evaluations", 0))
        maximum = int(details.get("max_evaluations", 0))
        best = float(details.get("best_fitness", 0.0))
        window_gain = float(details.get("window_improvement_percent", 0.0))
        total_gain = float(details.get("total_improvement_percent", 0.0))
        stale = int(details.get("stale_windows", 0))
        recommended = bool(details.get("stop_recommended", False))
        self.monitor_eval_label.configure(text=f"Evaluations: {evaluations:,} / No limit")
        self.monitor_best_label.configure(text=f"Best fitness: {self._format_distance(best)}")
        self.monitor_total_label.configure(text=f"Total improvement: {total_gain:.3f}%")
        self.monitor_window_label.configure(text=f"Latest window: {window_gain:.4f}%")
        if recommended:
            self._set_progress_status("red")
        elif window_gain < 0.1:
            self._set_progress_status("amber")
        else:
            self._set_progress_status("green")
        self.optimizer_status.configure(text=f"{evaluations:,} evaluations | Best {self._format_distance(best)} | {total_gain:.3f}% better")

        if recommended:
            warning = (
                f"STOP RECOMMENDED: improvement has stayed below {details.get('threshold_percent', 0.1):.3f}% "
                f"for {stale} consecutive checkpoints. The search is still running; press Stop to show the best placement. "
                + ("Automatic stop is enabled and will trigger when the minimum-time and patience settings are met. "
                 "You can still press Stop at any time." if details.get("auto_stop_enabled") else
                 "Automatic stop is disabled; press Stop whenever you choose.")
            )
            self.monitor_warning_label.configure(text=warning, foreground="#FF2020", background="#3B1111")
            self._stop_recommended_seen = True
            self._start_warning_blink()
            if not getattr(self, "_monitor_warning_logged", False):
                self.log_message(warning, "WARNING")
                self._monitor_warning_logged = True
        else:
            self._stop_warning_blink()
            self.monitor_warning_label.configure(
                text=f"Search active. Latest window improvement: {window_gain:.4f}%; "
                     f"{stale} consecutive low-improvement checkpoints.",
                foreground="#555555", background="#F0F0F0",
            )
            self._monitor_warning_logged = False

        trend = "Stop may be worthwhile" if recommended else ("Improving" if window_gain >= 0.1 else "Still searching")
        row = (f"{evaluations:,}", self._format_distance(best), f"{window_gain:.4f}%", f"{total_gain:.3f}%", trend)
        self._monitor_history.append(row)
        self._benchmark_history.append({
            "evaluations": evaluations,
            "elapsed_seconds": float(details.get("elapsed_seconds", 0.0)),
            "best_fitness": best,
            "total_improvement_percent": total_gain,
            "action_stats": details.get("action_stats", {}),
            "chain_depth_stats": details.get("chain_depth_stats", {}),
            "strategy_weights": details.get("strategy_weights", {}),
        })
        self.btn_export_benchmark.configure(state="normal")
        self.monitor_table.insert("", tk.END, values=row)
        children = self.monitor_table.get_children()
        while len(children) > 8:
            self.monitor_table.delete(children[0])
            children = self.monitor_table.get_children()

    def _export_benchmark_csv(self):
        """Export benchmark checkpoints and per-action search statistics as CSV."""
        result = self._benchmark_result or getattr(self.optimizer, "last_result", {}) or {}
        history = result.get("benchmark_history") or self._benchmark_history
        if not history and not result:
            messagebox.showinfo("Benchmark Export", "No benchmark data is available yet.")
            return
        default_name = Path(self.file_path).stem + "_placement_benchmark.csv" if self.file_path else "placement_benchmark.csv"
        output_path = filedialog.asksaveasfilename(
            title="Export Placement Benchmark",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not output_path:
            return
        columns = [
            "record_type", "board_file", "seed", "evaluations", "elapsed_seconds",
            "initial_fitness", "best_fitness", "total_improvement_percent", "action",
            "attempted", "evaluated", "valid", "accepted", "best_improvements",
            "chain_depth", "chain_attempted", "chain_accepted", "chain_best_improvements",
            "adaptive_strategy", "auto_stop_enabled", "auto_stop_reason", "strategy_weights", "status",
        ]
        board_file = str(self.file_path or "")
        rows = []
        for checkpoint in history:
            common = {
                "board_file": board_file,
                "seed": result.get("seed", ""),
                "evaluations": checkpoint.get("evaluations", ""),
                "elapsed_seconds": checkpoint.get("elapsed_seconds", ""),
                "initial_fitness": result.get("initial_fitness", ""),
                "best_fitness": checkpoint.get("best_fitness", ""),
                "total_improvement_percent": checkpoint.get("total_improvement_percent", ""),
                "adaptive_strategy": result.get("adaptive_strategy", ""),
                "auto_stop_enabled": result.get("auto_stop_enabled", ""),
                "auto_stop_reason": result.get("auto_stop_reason", ""),
                "strategy_weights": json.dumps(checkpoint.get("strategy_weights", {}), sort_keys=True),
                "status": "checkpoint",
            }
            rows.append({**common, "record_type": "checkpoint"})
            for action_name, stats in checkpoint.get("action_stats", {}).items():
                rows.append({**common, "record_type": "action", "action": action_name, **stats})
            for depth, stats in checkpoint.get("chain_depth_stats", {}).items():
                rows.append({
                    **common, "record_type": "chain_depth", "chain_depth": depth,
                    "chain_attempted": stats.get("attempted", 0),
                    "chain_accepted": stats.get("accepted", 0),
                    "chain_best_improvements": stats.get("best_improvements", 0),
                })
        if result:
            rows.append({
                "record_type": "final", "board_file": board_file, "seed": result.get("seed", ""),
                "evaluations": result.get("evaluations", ""), "elapsed_seconds": result.get("elapsed_seconds", ""),
                "initial_fitness": result.get("initial_fitness", ""), "best_fitness": result.get("final_fitness", ""),
                "total_improvement_percent": result.get("improvement_percent", ""),
                "adaptive_strategy": result.get("adaptive_strategy", ""),
                "auto_stop_enabled": result.get("auto_stop_enabled", ""),
                "auto_stop_reason": result.get("auto_stop_reason", ""),
                "strategy_weights": json.dumps(result.get("strategy_weights", {}), sort_keys=True),
                "status": result.get("status", ""),
            })
            for action_name, stats in result.get("action_stats", {}).items():
                rows.append({
                    "record_type": "final_action", "board_file": board_file, "seed": result.get("seed", ""),
                    "evaluations": result.get("evaluations", ""), "elapsed_seconds": result.get("elapsed_seconds", ""),
                    "initial_fitness": result.get("initial_fitness", ""), "best_fitness": result.get("final_fitness", ""),
                    "total_improvement_percent": result.get("improvement_percent", ""),
                    "adaptive_strategy": result.get("adaptive_strategy", ""),
                    "auto_stop_enabled": result.get("auto_stop_enabled", ""),
                    "auto_stop_reason": result.get("auto_stop_reason", ""),
                    "action": action_name, **stats, "status": result.get("status", ""),
                })
            for depth, stats in result.get("chain_depth_stats", {}).items():
                rows.append({
                    "record_type": "final_chain_depth", "board_file": board_file, "seed": result.get("seed", ""),
                    "evaluations": result.get("evaluations", ""), "elapsed_seconds": result.get("elapsed_seconds", ""),
                    "initial_fitness": result.get("initial_fitness", ""), "best_fitness": result.get("final_fitness", ""),
                    "total_improvement_percent": result.get("improvement_percent", ""),
                    "chain_depth": depth, "chain_attempted": stats.get("attempted", 0),
                    "chain_accepted": stats.get("accepted", 0),
                    "chain_best_improvements": stats.get("best_improvements", 0), "status": result.get("status", ""),
                })
        try:
            with open(output_path, "w", newline="", encoding="utf-8-sig") as csv_file:
                writer = csv.DictWriter(csv_file, fieldnames=columns, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
        except OSError as exc:
            messagebox.showerror("Benchmark Export Failed", f"Could not write the benchmark CSV:\n{exc}")
            return
        self.log_message(f"Benchmark CSV exported to: {output_path}", "SUCCESS")

    def _stop_optimization(self):
        if self._optimizer_running:
            self._optimizer_cancel_event.set()
            self.btn_stop_optimization.configure(state="disabled")
            self.optimizer_status.configure(text="Stopping and restoring best placement...")
            self.monitor_warning_label.configure(
                text="Stop requested. Restoring the best placement found so far...",
                foreground="#1D4ED8",
            )
            self.log_message("Optimization stop requested; the best placement will be restored.", "WARNING")

    def _poll_optimizer_queue(self):
        """Consume worker updates on the Tk main thread."""
        finished = False
        try:
            while True:
                item = self._optimizer_queue.get_nowait()
                kind = item[0]
                if kind == "progress":
                    _, current, total, fitness = item
                    # The search has no completion percentage; the full bar communicates activity.
                    self.optimizer_status.configure(text=f"Step {current:,} | Fitness {self._format_distance(fitness)}")
                elif kind == "monitor":
                    self._update_placement_monitor(item[1])
                elif kind == "done":
                    self._finish_optimization(item[1])
                    finished = True
                elif kind == "error":
                    self.log_message(f"Placement optimization failed: {item[1]}", "ERROR")
                    self.optimizer_status.configure(text="Optimization failed")
                    self._reset_optimizer_controls()
                    finished = True
        except queue.Empty:
            pass
        if not finished and self._optimizer_running:
            self.window.after(100, self._poll_optimizer_queue)
        else:
            self._optimizer_poll_active = False

    def _finish_optimization(self, result):
        self._benchmark_result = result
        self.btn_export_benchmark.configure(state="normal")
        self._reset_optimizer_controls()
        self._monitor_warning_logged = False
        self._set_progress_status("neutral")
        self.optimizer_status.configure(
            text=f"Finished | Improvement {result['improvement_percent']:.2f}% | {self._format_distance(result['final_fitness'])}"
        )
        self._stop_warning_blink()
        self.monitor_eval_label.configure(text=f"Evaluations: {result.get('evaluations', 0):,} / No limit")
        self.monitor_best_label.configure(text=f"Best fitness: {self._format_distance(result['final_fitness'])}")
        self.monitor_total_label.configure(text=f"Total improvement: {result['improvement_percent']:.3f}%")
        self.monitor_window_label.configure(text="Search finished; best placement restored")
        self.monitor_warning_label.configure(
            text=f"{result['status']} The displayed board is the best placement found during this search.",
            foreground="#166534",
        )
        self.log_message(
            "Placement optimization finished: "
            f"{self._format_distance(result['initial_fitness'])} -> {self._format_distance(result['final_fitness'])}; "
            f"improvement {result['improvement_percent']:.2f}%; "
            f"accepted moves {result.get('accepted_moves', 0)}, rotations {result.get('accepted_rotations', 0)}, "
            f"device-position swaps {result['accepted_swaps']}, compound moves {result.get('accepted_compound_moves', 0)}, "
            f"layer swaps {result.get('accepted_layer_swaps', 0)}; "
            f"evaluations {result['evaluations']}, plateau checks {result.get('plateau_checks', 0)}. "
            f"{result['status']}",
            "SUCCESS" if result["final_fitness"] <= result["initial_fitness"] else "WARNING",
        )
        self._placement_after = {
            name: (comp.x, comp.y, comp.rot, comp.mirror)
            for name, comp in self.board_data.components.items()
        }
        self.btn_before_after.configure(state="normal" if self._placement_before is not None else "disabled")
        self._export_ready = bool(
            self.file_path and self._placement_after
            and self.schematic_file_path and Path(self.schematic_file_path).is_file()
        )
        self.btn_export_eagle.configure(state="normal" if self._export_ready else "disabled")
        self._render(self.schematic_parts)

    def _export_eagle_project(self):
        """Export optimized placements into a BRD copy and pair its SCH."""
        if not self._export_ready or not self._placement_after:
            messagebox.showwarning("Export unavailable", "Run placement optimization before exporting.")
            return
        source_brd = getattr(self, "source_brd_path", None)
        source_sch = getattr(self, "schematic_file_path", None)
        if not source_brd or not Path(source_brd).is_file():
            messagebox.showerror("Export failed", "The original BRD file path is unavailable.")
            return
        if not source_sch or not Path(source_sch).is_file():
            messagebox.showerror(
                "Export unavailable",
                "A valid companion SCH file is required for a synchronized Eagle project export."
            )
            return

        output_brd = filedialog.asksaveasfilename(
            title="Export optimized Eagle board",
            defaultextension=".brd",
            initialfile=f"{Path(source_brd).stem}_optimized.brd",
            filetypes=[("EAGLE Board", "*.brd")],
        )
        if not output_brd:
            return
        output_sch = str(Path(output_brd).with_suffix(".sch"))
        if Path(output_brd).exists() or Path(output_sch).exists():
            if not messagebox.askyesno(
                "Confirm overwrite",
                f"The export target already exists. Replace both files?\n\n{output_brd}\n{output_sch}"
            ):
                return

        try:
            updated = export_placement_pair(
                source_brd, source_sch, output_brd, output_sch, self._placement_after
            )
            self.log_message(
                f"EAGLE project exported: {updated} placements written. Original SCH copied unchanged. "
                "Logical gate/pin swaps are not applied in this export stage.",
                "SUCCESS",
            )
            messagebox.showinfo(
                "EAGLE project exported",
                f"Optimized board:\n{output_brd}\n\nCompanion schematic:\n{output_sch}\n\n"
                "The SCH was copied unchanged. Gate/pin swaps are not yet applied."
            )
        except Exception as exc:
            self.log_message(f"EAGLE project export failed: {exc}", "ERROR")
            messagebox.showerror("EAGLE export failed", str(exc))

    def _show_before_after(self):
        """Show the original and optimized component placements side by side."""
        if not self._placement_before or not self._placement_after or not self.board_data:
            return

        compare_win = tk.Toplevel(self.window)
        compare_win.title("Before / After Placement Comparison")
        compare_win.geometry("1200x650")
        figure, axes = plt.subplots(1, 2, figsize=(13, 6), constrained_layout=True)
        canvas = FigureCanvasTkAgg(figure, master=compare_win)
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        all_x, all_y = [], []
        for polygon in self.board_data.boundary_polygons:
            all_x.extend(point[0] for point in polygon)
            all_y.extend(point[1] for point in polygon)
        for state in (self._placement_before, self._placement_after):
            for values in state.values():
                all_x.append(values[0])
                all_y.append(values[1])
        if not all_x or not all_y:
            all_x, all_y = [0.0, 100.0], [0.0, 100.0]
        margin = max(max(all_x) - min(all_x), max(all_y) - min(all_y), 1.0) * 0.06
        x_limits = (min(all_x) - margin, max(all_x) + margin)
        y_limits = (min(all_y) - margin, max(all_y) + margin)

        for axis, title, state in zip(
            axes, ("Before Optimization", "After Optimization"),
            (self._placement_before, self._placement_after),
        ):
            axis.set_title(title)
            for outline in self.board_data.boundary_polygons:
                axis.add_patch(patches.Polygon(outline, closed=True, fill=False, edgecolor="black", linewidth=1.2))
            for name, values in state.items():
                comp = self.board_data.components.get(name)
                if comp is None:
                    continue
                polygon = self.optimizer._component_polygon(comp, values[0], values[1], values[2], values[3]) if self.optimizer else None
                if polygon is not None and not polygon.is_empty:
                    # Component layer is independent of mirror/orientation state.
                    layer = str(getattr(comp, "layer", "top")).lower()
                    is_bottom = "bottom" in layer or layer in {"16", "bottom copper"}
                    color = "#2D79C7" if values[3] else "#E58B35"
                    axis.add_patch(patches.Polygon(list(polygon.exterior.coords), closed=True, fill=False,
                                                   edgecolor=color, linewidth=0.65, alpha=0.9))
                    axis.plot(values[0], values[1], marker=".", markersize=2, color=color)
            axis.set_xlim(*x_limits)
            axis.set_ylim(*y_limits)
            axis.set_aspect("equal", adjustable="box")
            axis.set_xlabel(f"X ({self.unit_label})")
            axis.set_ylabel(f"Y ({self.unit_label})")
            self._format_axis_units(axis)
            axis.grid(True, linestyle=":", alpha=0.35)
        canvas.draw()

    def _reset_optimizer_controls(self):
        self._optimizer_running = False
        can_optimize = bool(self.optimizer and self.board_data and len(getattr(self.board_data, "components", {})) >= 2)
        self.btn_optimize.configure(state="normal" if can_optimize else "disabled")
        self.btn_stop_optimization.configure(state="disabled")
        self._optimizer_thread = None

    def _show_data_summary(self):
        """Open a detailed inspection window with all data and optimizer.py checks."""
        if not self.board_data:
            messagebox.showwarning("No Data", "Load a .BRD file to view its data.")
            return

        summary_win = tk.Toplevel(self.window)
        summary_win.title("Optimizer Data and Constraint Inspection")
        summary_win.geometry("750x700")

        txt = tk.Text(summary_win, bg="#1E1E1E", fg="#00FF00", font=("Consolas", 9), wrap=tk.WORD, padx=10, pady=10)
        vbar = ttk.Scrollbar(summary_win, orient=tk.VERTICAL, command=txt.yview)
        txt.configure(yscrollcommand=vbar.set)

        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        lines = []
        warnings = []

        lines.append("=" * 70)
        lines.append("  INPUT DATA INSPECTION AND VALIDATION FOR OPTIMIZER.PY")
        lines.append("=" * 70 + "\n")

        # 1. BOARD OUTLINE AND RESTRICTED AREAS
        lines.append("1. PCB OUTLINE AND RESTRICTED AREAS")
        lines.append("-" * 50)
        try:
            poly_count = len(self.board_data.boundary_polygons)
            lines.append(f"   • PCB Outline Polygons: {poly_count}")
            if poly_count >= 1:
                outer_poly = Polygon(self.board_data.boundary_polygons[0])
                area_factor = self._unit_factor() ** 2
                lines.append(f"   • Outer PCB Area: {outer_poly.area * area_factor:.2f} {self.unit_label}²")
            else:
                warnings.append("⚠️ No PCB outline detected!")
        except Exception:
            lines.append("   • PCB Area: N/A")
            warnings.append("⚠️ Unable to calculate the PCB outline area.")

        kp_top = len(getattr(self.board_data, 'keepouts_top', []))
        kp_bot = len(getattr(self.board_data, 'keepouts_bottom', []))
        holes = len(getattr(self.board_data, 'holes', []))
        vias = len(getattr(self.board_data, 'isolated_vias', []))
        lines.append(f"   • Top Keepout Areas (L39): {kp_top} | Bottom (L40): {kp_bot}")
        lines.append(f"   • Top Restrict Areas (L41): {len(getattr(self.board_data, 'restrict_top', []))} | Bottom (L42): {len(getattr(self.board_data, 'restrict_bottom', []))}")
        grid_spacing = getattr(self.board_data, "grid_spacing_mm", None)
        lines.append(f"   • BRD Grid Spacing: {self._format_distance(grid_spacing)}" if grid_spacing else "   • BRD Grid Spacing: Not defined")
        lines.append(f"   • Mechanical Holes: {holes} | Unconnected Vias: {vias}\n")

        # 2. COMPONENTS, GEOMETRY, AND TECHNOLOGY (SMD vs THT)
        lines.append("2. COMPONENTS, GEOMETRY, AND TECHNOLOGY (SMD vs THT)")
        lines.append("-" * 50)
        comps = getattr(self.board_data, 'components', {})
        lines.append(f"   • Total Components: {len(comps)}")

        top_comps = sum(1 for c in comps.values() if not getattr(c, 'mirror', False))
        bot_comps = sum(1 for c in comps.values() if getattr(c, 'mirror', False))
        lines.append(f"   • Current Side: TOP ({top_comps}) | BOTTOM ({bot_comps})")

        # Conteggio basato sull'attributo reale 'is_tht'
        tht_count = sum(1 for c in comps.values() if getattr(c, 'is_tht', False))
        smd_count = len(comps) - tht_count
        lines.append(f"   • Technology: SMD ({smd_count}) | THT ({tht_count})")

        # Check for THT components incorrectly placed on the BOTTOM layer
        tht_on_bottom = [name for name, c in comps.items() if getattr(c, 'is_tht', False) and getattr(c, 'mirror', False)]
        if tht_on_bottom:
            warnings.append(f"⚠️ THT components placed on BOTTOM: {', '.join(tht_on_bottom)}")

        # Check rotations and geometric-center offsets
        missing_offset = [name for name, c in comps.items() if not hasattr(c, 'offset_x') or not hasattr(c, 'offset_y')]
        if missing_offset:
            warnings.append(f"⚠️ Missing geometric-center offsets for {len(missing_offset)} components.")

        total_bbox_area = sum(c.width * c.height for c in comps.values())
        lines.append(f"   • Total Bounding-Box Area: {total_bbox_area * self._unit_factor() ** 2:.2f} {self.unit_label}²\n")

        # 3. COMPONENT LOCK STATUS
        lines.append("3. COMPONENT LOCK STATUS")
        lines.append("-" * 50)
        locked_comps = [name for name, c in comps.items() if getattr(c, 'locked', False)]
        lines.append(f"   • Locked Components (LOCKED): {len(locked_comps)}")
        if locked_comps:
            lines.append(f"     Names: {', '.join(locked_comps)}")
        lines.append(f"   • Unlocked Components (UNLOCKED): {len(comps) - len(locked_comps)}\n")

        # 4. PIN/GATE SWAPPING AND PIN-TO-PAD MAPPING (.SCH)
        lines.append("4. PIN/GATE SWAPPING E MAPPATURA PIN-TO-PAD")
        lines.append("-" * 50)
        if not hasattr(self, 'schematic_parts') or not self.schematic_parts:
            warnings.append("⚠️ Schematic file (.SCH) not loaded! Pin/gate swapping is disabled.")
            lines.append("   • Pin-to-Pad / DeviceSet Mapping: SCHEMATIC DATA MISSING")
        else:
            self.board_data.merge_schematic_data(self.schematic_parts)
            swappable_count = 0
            disabled_swap_count = 0
            missing_map_count = 0

            for name, comp in comps.items():
                if self._is_component_swappable(name):
                    swappable_count += 1
                    if not getattr(comp, 'swap_enabled', True):
                        disabled_swap_count += 1
                    if not getattr(comp, 'pin_to_pad_map', None):
                        missing_map_count += 1

            lines.append(f"   • Identified Swappable Components: {swappable_count}")
            lines.append(f"   • Components with Swapping Enabled: {swappable_count - disabled_swap_count}")
            lines.append(f"   • Components with Swapping Manually Disabled: {disabled_swap_count}")
            
            if missing_map_count > 0:
                warnings.append(f"⚠️ Missing pin-to-pad mappings for {missing_map_count} swappable components.")

        lines.append("")

        # 5. EQUIVALENCE MATRIX FOR IDENTICAL PASSIVES
        lines.append("5. EQUIVALENCE MATRIX FOR IDENTICAL PASSIVES")
        lines.append("-" * 50)
        passive_groups = getattr(self.board_data, 'passive_equivalence_groups', {})
        if passive_groups:
            lines.append(f"   • Equivalent Passive Groups Found: {len(passive_groups)}")
            for grp_id, members in passive_groups.items():
                lines.append(f"     Group '{grp_id}': {', '.join(members)}")
        else:
            lines.append("   • No interchangeable passive groups identified or calculated yet.")
        lines.append("")

        # 6. DESIGN RULES (DRU) AND COST/PENALTY PARAMETERS
        lines.append("6. DESIGN RULES (DRU) AND FITNESS COST PARAMETERS")
        lines.append("-" * 50)
        source = "External .DRU File" if self.dru_file_path else ("Default BRD" if hasattr(self.board_data, 'design_rules') and self.board_data.design_rules else "GUI Manual Values")
        lines.append(f"   • Rules Source: {source}")
        lines.append(f"   • Clearance Comp-to-Comp: {self._format_distance(self.design_rules.clearance_comp_to_comp)}")
        lines.append(f"   • Clearance Board Edge: {self._format_distance(self.design_rules.clearance_board_edge)}")
        lines.append(f"   • Clearance Track-to-Track: {self._format_distance(self.design_rules.clearance_track_to_track)}")
        
        via_penalty = getattr(self.design_rules, 'via_penalty', 10.0)
        lines.append(f"   • Layer-Swap/Via Penalty (Fitness Function): {via_penalty:.2f}\n")

        # 7. NET CLASSES AND RATSNEST
        lines.append("7. NET CLASSES, SIGNALS, AND RATSNEST")
        lines.append("-" * 50)
        signals = getattr(self.board_data, 'signals', {})
        lines.append(f"   • Total Nets/Signals: {len(signals)}")
        
        brd_classes = getattr(self.board_data, 'net_classes', {})
        sch_classes = getattr(self.schematic_parts, 'net_classes', {}) if hasattr(self, 'schematic_parts') and hasattr(self.schematic_parts, 'net_classes') else brd_classes
        
        if brd_classes != sch_classes:
            warnings.append("⚠️ Net classes differ between the .BRD and .SCH files!")
            lines.append(f"   • Net Classes: MISMATCH DETECTED! (BRD: {len(brd_classes)}, SCH: {len(sch_classes)})")
        else:
            lines.append(f"   • Net Classes (BRD/SCH): {len(brd_classes)} [MATCH]")

        if self.optimizer:
            try:
                ratsnest_len = self.optimizer.calculate_ratsnest_length()
                lines.append(f"   • Initial Ratsnest Length Estimate: {self._format_distance(ratsnest_len)}")
            except Exception:
                lines.append("   • Ratsnest Estimate: Calculating...")

        lines.append("\n" + "=" * 70)

        # WARNINGS AND VALIDATION
        if warnings:
            lines.append("  ⚠️ WARNINGS AND ANOMALIES DETECTED:")
            lines.append("-" * 50)
            for w in warnings:
                lines.append(f"  {w}")
            lines.append("\n  STATUS: Data is incomplete or warnings were found. Review before starting optimization.")
        else:
            lines.append("  STATUS: All data is validated and ready for optimizer.py")
        lines.append("=" * 70)

        txt.insert(tk.END, "\n".join(lines))
        txt.config(state=tk.DISABLED)
    
    def _get_content_bounds(self):
        """Return X/Y coordinate lists for all drawable board geometry."""
        all_x, all_y = [], []
        for collection_name in ("boundary_polygons", "keepouts_top", "keepouts_bottom"):
            for loop in getattr(self.board_data, collection_name, []) or []:
                for x, y in loop:
                    all_x.append(float(x))
                    all_y.append(float(y))
        for track in getattr(self.board_data, "tracks", []) or []:
            all_x.extend((float(track.p1[0]), float(track.p2[0])))
            all_y.extend((float(track.p1[1]), float(track.p2[1])))
        for comp in getattr(self.board_data, "components", {}).values():
            all_x.extend((float(comp.x - comp.width / 2), float(comp.x + comp.width / 2)))
            all_y.extend((float(comp.y - comp.height / 2), float(comp.y + comp.height / 2)))
        for x, y, drill in getattr(self.board_data, "holes", []) or []:
            all_x.extend((float(x - drill / 2), float(x + drill / 2)))
            all_y.extend((float(y - drill / 2), float(y + drill / 2)))
        for via in getattr(self.board_data, "isolated_vias", []) or []:
            radius = float(via.diameter) / 2
            all_x.extend((float(via.x - radius), float(via.x + radius)))
            all_y.extend((float(via.y - radius), float(via.y + radius)))
        return all_x, all_y

    def _render(self, schematic_parts=None):
        logging.info("GUI render requested; board_data=%s; figure_available=%s", bool(self.board_data), hasattr(self, "fig"))
        if getattr(self, "_last_rendered_file_path", None) != self.file_path:
            declared_unit = getattr(self.board_data, "display_unit", "mm") if self.board_data else "mm"
            if hasattr(self, "display_unit_var"):
                self.display_unit_var.set(declared_unit if declared_unit in self._display_unit_choices else "mm")
                self.unit_label = self.display_unit_var.get()
            self._placement_before = None
            self._placement_after = None
            self._placement_file_path = self.file_path
            self._last_rendered_file_path = self.file_path
            if hasattr(self, "display_unit_var"):
                self._on_display_unit_change(render=False)
            if hasattr(self, "btn_before_after"):
                self.btn_before_after.configure(state="disabled")
        grid_spacing = getattr(self.board_data, "grid_spacing_mm", None) if self.board_data else None
        if hasattr(self, "snap_grid_check") and grid_spacing != getattr(self, "_displayed_grid_spacing", None):
            self._displayed_grid_spacing = grid_spacing
            self.snap_grid_var.set(bool(grid_spacing))
            declared_unit = getattr(self.board_data, "display_unit", "mm")
            if hasattr(self, "display_unit_var"):
                self.display_unit_var.set(declared_unit)
            self.unit_label = declared_unit
            if hasattr(self, "display_unit_var"):
                self._on_display_unit_change(render=False)
            label = f"Snap to board grid ({self._format_distance(grid_spacing)})" if grid_spacing else "Snap to board grid (not defined in BRD)"
            self.snap_grid_check.configure(text=label, state="normal" if grid_spacing else "disabled")
        if not self.board_data or not hasattr(self, 'fig'):
            return
        self.unit_label = self.display_unit_var.get() if hasattr(self, "display_unit_var") else getattr(self.board_data, "display_unit", "mm")
        can_optimize = bool(self.optimizer and len(getattr(self.board_data, "components", {})) >= 2 and not self._optimizer_running)
        self.btn_optimize.configure(state="normal" if can_optimize else "disabled")
        
        if schematic_parts is not None:
            self.schematic_parts = schematic_parts

        # Update rule fields when present in board_data
        if hasattr(self.board_data, 'design_rules') and self.board_data.design_rules and not self.dru_file_path:
            self.design_rules = self.board_data.design_rules
            self._update_dru_ui_fields()
            
        logging.info("GUI render starting; components=%s signals=%s", len(getattr(self.board_data, "components", {})), len(getattr(self.board_data, "signals", {})))
        self.fig.clf()
        
        self.ax = self.fig.add_axes([0.08, 0.1, 0.65, 0.8])
        
        self.ax.set_aspect('equal')
        self.ax.grid(True, linestyle=':', alpha=0.6, color="#444444")
        self.ax.set_facecolor("white")
        self.fig.patch.set_facecolor("#f0f0f0")
        self.ax.tick_params(colors="black")
        self.ax.xaxis.label.set_color("black")
        self.ax.yaxis.label.set_color("black")
        self.ax.autoscale(enable=True, axis='both', tight=True)
        self.ax.set_xlabel(f"X ({self.unit_label})")
        self.ax.set_ylabel(f"Y ({self.unit_label})")
        self._format_axis_units(self.ax)
        
        title_scale = "Fit to Window" if self.current_scale == "fit" else f"{int(self.current_scale)}:1 Real Size"
        self.ax.set_title(f"Board: {self.file_path} | Scale: {title_scale}", pad=15)

        self.layer_artists = {
            "PCB Outline": [],
            "Copper TOP": [],
            "Copper BOTTOM": [],
            "Copper Inner": [],
            "Keepout TOP": [],
            "Keepout BOTTOM": [],
            "Restrict TOP": [],
            "Restrict BOTTOM": [],
            "Components TOP": [],
            "Components BOTTOM": [],
            "Locked Components": [],
            "Holes": [],
            "Vias": [],
            "Swappable Ratsnest": []
        }
        
        # 1. PCB outline
        try:
            if len(self.board_data.boundary_polygons) >= 1:
                shapely_polygons = []
                for p in self.board_data.boundary_polygons:
                    if len(p) >= 3:
                        poly = self._clean_and_validate_polygon(p)
                        if not poly.is_empty:
                            shapely_polygons.append(poly)
                
                if shapely_polygons:
                    shapely_polygons.sort(key=lambda p: p.area, reverse=True)
                    board_outer = shapely_polygons[0]
                    cutouts = shapely_polygons[1:]
                    
                    if cutouts:
                        try:
                            merged_cutouts = unary_union(cutouts)
                            if not merged_cutouts.is_valid:
                                merged_cutouts = merged_cutouts.buffer(0)
                            placement_area = board_outer.difference(merged_cutouts)
                        except Exception as geom_err:
                            placement_area = board_outer
                    else:
                        placement_area = board_outer
                    
                    if not placement_area.is_valid:
                        placement_area = placement_area.buffer(0)

                    if isinstance(placement_area, Polygon):
                        patches_list = self._plot_single_polygon(placement_area, facecolor="#e9edf0", edgecolor="#666666")
                        if patches_list:
                            self.layer_artists["PCB Outline"].extend(patches_list)
                    elif isinstance(placement_area, MultiPolygon):
                        for geom in placement_area.geoms:
                            patches_list = self._plot_single_polygon(geom, facecolor="#e9edf0", edgecolor="#666666")
                            if patches_list:
                                self.layer_artists["PCB Outline"].extend(patches_list)
        except Exception:
            logging.exception("Rendering PCB outline failed")

        # 2. Routed copper tracks, including boards reconstructed from Gerber files.
        try:
            layer_groups = {}
            for track in getattr(self.board_data, "tracks", []):
                if track.width <= 0:
                    continue
                if track.layer == 1:
                    group_key, color = "Copper TOP", "#ef4444"
                elif track.layer == 16:
                    group_key, color = "Copper BOTTOM", "#3b82f6"
                else:
                    group_key, color = "Copper Inner", "#a855f7"
                points = interpolate_arc(
                    track.p1[0], track.p1[1], track.p2[0], track.p2[1], track.curve
                )
                if len(points) >= 2:
                    layer_groups.setdefault(group_key, {"color": color, "segments": [], "widths": []})
                    layer_groups[group_key]["segments"].append(points)
                    layer_groups[group_key]["widths"].append(max(0.25, track.width * 2.83465))

            for group_key, group in layer_groups.items():
                collection = LineCollection(
                    group["segments"], colors=group["color"],
                    linewidths=group["widths"], alpha=0.92,
                    capstyle="round", zorder=2,
                )
                self.ax.add_collection(collection)
                self.layer_artists[group_key].append(collection)
            logging.info("Rendered copper tracks: total=%s by_layer=%s", len(getattr(self.board_data, "tracks", [])), {key: len(value["segments"]) for key, value in layer_groups.items()})
        except Exception:
            logging.exception("Rendering copper tracks failed")

        # 3. Keepout TOP
        try:
            for kp in self.board_data.keepouts_top:
                p = patches.Polygon(kp, closed=True, facecolor='#ff6b6b', edgecolor='#e60000', alpha=0.5, linewidth=1.5, zorder=3)
                self.ax.add_patch(p)
                self.layer_artists["Keepout TOP"].append(p)
        except Exception:
            logging.exception("Rendering top keepouts failed")

        # 4. Keepout BOTTOM
        try:
            for kp in self.board_data.keepouts_bottom:
                p = patches.Polygon(kp, closed=True, facecolor='#4dadf7', edgecolor='#0066cc', alpha=0.5, linewidth=1.5, zorder=3)
                self.ax.add_patch(p)
                self.layer_artists["Keepout BOTTOM"].append(p)
        except Exception:
            logging.exception("Rendering bottom keepouts failed")

        # 5. Top and bottom restrict regions
        try:
            for region in getattr(self.board_data, "restrict_top", []):
                patch = patches.Polygon(region, closed=True, facecolor="#f59e0b", edgecolor="#b45309",
                                        alpha=0.32, linewidth=1.2, hatch="///", zorder=3)
                self.ax.add_patch(patch)
                self.layer_artists["Restrict TOP"].append(patch)
        except Exception:
            logging.exception("Rendering top restrict regions failed")
        try:
            for region in getattr(self.board_data, "restrict_bottom", []):
                patch = patches.Polygon(region, closed=True, facecolor="#a78bfa", edgecolor="#6d28d9",
                                        alpha=0.32, linewidth=1.2, hatch="\\\\", zorder=3)
                self.ax.add_patch(patch)
                self.layer_artists["Restrict BOTTOM"].append(patch)
        except Exception:
            logging.exception("Rendering bottom restrict regions failed")

        # 6. Mechanical holes
        try:
            for x, y, drill in self.board_data.holes:
                c = patches.Circle((x, y), radius=drill/2, facecolor='#212529', edgecolor='#888888', linewidth=1, zorder=5)
                self.ax.add_patch(c)
                cross, = self.ax.plot(x, y, marker='+', color='#ffffff', markersize=5, zorder=6)
                self.layer_artists["Holes"].extend([c, cross])
        except Exception:
            logging.exception("Rendering mechanical holes failed")

        # 6. Vias
        try:
            for via in self.board_data.isolated_vias:
                v_out = patches.Circle((via.x, via.y), radius=via.diameter/2, facecolor='#b87333', edgecolor='#8a4f1a', linewidth=0.5, zorder=4)
                v_in = patches.Circle((via.x, via.y), radius=via.drill/2, facecolor='#212529', edgecolor='none', zorder=5)
                self.ax.add_patch(v_out)
                self.ax.add_patch(v_in)
                self.layer_artists["Vias"].extend([v_out, v_in])
        except Exception:
            logging.exception("Rendering vias failed")

        # 7. Components
        try:
            if hasattr(self.board_data, 'components') and self.board_data.components:
                for name, comp in self.board_data.components.items():
                    w = comp.width
                    h = comp.height
                    
                    category = "Locked Components" if comp.locked else ("Components BOTTOM" if comp.mirror else "Components TOP")
                    
                    if comp.locked:
                        edge_color = '#dc2626'
                        line_style = '--'
                        line_w = 2.0
                        face_color = '#fee2e2'
                    else:
                        line_style = '-'
                        line_w = 1.2
                        if not comp.mirror:
                            face_color = '#fffbeb'
                            edge_color = '#d97706'
                        else:
                            face_color = '#eff6ff'
                            edge_color = '#2563eb'
                    
                    rect = patches.Rectangle(
                        (-w/2, -h/2), w, h, 
                        facecolor=face_color, 
                        edgecolor=edge_color, 
                        linestyle=line_style,
                        linewidth=line_w, 
                        alpha=0.8, 
                        zorder=4
                    )
                    
                    t = (matplotlib.transforms.Affine2D()
                         .translate(comp.offset_x, comp.offset_y)
                         .rotate_deg(comp.rot)
                         .translate(comp.x, comp.y) + self.ax.transData)
                         
                    rect.set_transform(t)
                    self.ax.add_patch(rect)
                    self.layer_artists[category].append(rect)
                    
                    center_local_x = comp.offset_x
                    center_local_y = comp.offset_y
                    rad_rot = math.radians(comp.rot)
                    
                    text_x = comp.x + (center_local_x * math.cos(rad_rot) - center_local_y * math.sin(rad_rot))
                    text_y = comp.y + (center_local_x * math.sin(rad_rot) + center_local_y * math.cos(rad_rot))
                    
                    display_name = f"[{name}]" if comp.locked else name
                    text_color = '#dc2626' if comp.locked else '#0f172a'
                    
                    txt = self.ax.text(
                        text_x, text_y, display_name, 
                        color=text_color, 
                        fontsize=7, 
                        fontweight='bold',
                        ha='center', va='center', 
                        zorder=5,
                        clip_on=True
                    )
                    self.layer_artists[category].append(txt)
        except Exception:
            logging.exception("Rendering components failed")

        # 8. Swappable pins
        try:
            if self.schematic_parts and self.board_data.signals:
                swappable_pads_by_comp = {}
                for comp_name, part in self.schematic_parts.items():
                    c_name_upper = str(comp_name).strip().upper()
                    
                    # Skip this component if swapping was disabled by right-click
                    board_comp = self.board_data.components.get(comp_name)
                    if board_comp and not getattr(board_comp, 'swap_enabled', True):
                        continue
                    
                    gate_pin_defs = getattr(part, 'gate_pin_definitions', {})
                    gates_dict = getattr(part, 'gates', {})
                    pin_to_pad = getattr(part, 'pin_to_pad_map', {})
                    
                    for gate_name, pin_dict in gate_pin_defs.items():
                        gate_obj = gates_dict.get(gate_name)
                        gate_swap = gate_obj.swaplevel if gate_obj else 0
                        
                        for pin_label, pin_obj in pin_dict.items():
                            if getattr(pin_obj, 'swaplevel', 0) > 0 or gate_swap > 0:
                                full_key = f"{gate_name}.{pin_label}"
                                physical_pad = pin_to_pad.get(full_key)
                                
                                if physical_pad is None:
                                    physical_pad = pin_to_pad.get(pin_label)
                                
                                if physical_pad is not None:
                                    if c_name_upper not in swappable_pads_by_comp:
                                        swappable_pads_by_comp[c_name_upper] = set()
                                    swappable_pads_by_comp[c_name_upper].add(str(physical_pad).strip().upper())                
                pad_x_coords = []
                pad_y_coords = []
                
                for sig_name, signal in self.board_data.signals.items():
                    for conn in signal.connections:
                        c_element = str(conn.element).strip().upper()
                        c_pad = str(conn.pad).strip().upper()
                        
                        if c_element in swappable_pads_by_comp:
                            clean_swappable_pads = {str(p).strip().upper() for p in swappable_pads_by_comp[c_element]}
                            
                            if c_pad in clean_swappable_pads:
                                if hasattr(conn, 'x') and hasattr(conn, 'y') and conn.x is not None and conn.y is not None:
                                    pad_x_coords.append(float(conn.x))
                                    pad_y_coords.append(float(conn.y))
                                elif hasattr(conn, 'pos_x') and hasattr(conn, 'pos_y') and conn.pos_x is not None and conn.pos_y is not None:
                                    pad_x_coords.append(float(conn.pos_x))
                                    pad_y_coords.append(float(conn.pos_y))
                
                if pad_x_coords:
                    if self.current_scale != "fit":
                        scatter_size = 30
                    else:
                        all_x, all_y = [], []
                        for loop in self.board_data.boundary_polygons:
                            for px, py in loop:
                                all_x.append(px)
                                all_y.append(py)
                        
                        if all_x and all_y:
                            board_width = max(all_x) - min(all_x)
                            board_height = max(all_y) - min(all_y)
                            scatter_size = max(20, min(50, (board_width + board_height) / 200))
                        else:
                            scatter_size = 30
                    
                    scatter_dots = self.ax.scatter(
                        pad_x_coords, pad_y_coords,
                        color='#FF00FF',
                        s=scatter_size,
                        marker='o',
                        alpha=0.8,
                        edgecolors='none',
                        zorder=8
                    )
                    self.layer_artists["Swappable Ratsnest"].append(scatter_dots)
        except Exception:
            logging.exception("Suppressed GUI exception; inspect traceback in diagnostic log")

        # Keep the full board content in view, even when no outline is available.
        all_x, all_y = self._get_content_bounds()
        if self.current_scale != "fit":
            if all_x and all_y:
                min_x, max_x = min(all_x), max(all_x)
                min_y, max_y = min(all_y), max(all_y)
                
                cx = (min_x + max_x) / 2.0
                cy = (min_y + max_y) / 2.0
                
                self.canvas.get_tk_widget().update_idletasks()
                canvas_width_px = self.canvas.get_tk_widget().winfo_width()
                canvas_height_px = self.canvas.get_tk_widget().winfo_height()
                
                if canvas_width_px <= 1:
                    canvas_width_px = 800
                if canvas_height_px <= 1:
                    canvas_height_px = 600
                
                dpi_effettivo = self.base_dpi * self.calibration_factor.get()
                
                visible_width_mm = (canvas_width_px / dpi_effettivo) * 25.4 / self.current_scale
                visible_height_mm = (canvas_height_px / dpi_effettivo) * 25.4 / self.current_scale
                
                half_width_mm = visible_width_mm / 2.0
                half_height_mm = visible_height_mm / 2.0
                
                self.ax.set_xlim(cx - half_width_mm, cx + half_width_mm)
                self.ax.set_ylim(cy - half_height_mm, cy + half_height_mm)
            else:
                self.ax.relim()
                self.ax.autoscale_view()
        else:
            if all_x and all_y:
                min_x, max_x = min(all_x), max(all_x)
                min_y, max_y = min(all_y), max(all_y)
                pad_x = max((max_x - min_x) * 0.03, 0.5)
                pad_y = max((max_y - min_y) * 0.03, 0.5)
                self.ax.set_xlim(min_x - pad_x, max_x + pad_x)
                self.ax.set_ylim(min_y - pad_y, max_y + pad_y)
            else:
                self.ax.relim()
                self.ax.autoscale_view()

        # Apply existing checkbutton states to newly created graphics
        self._update_legend_visibility()
        self._apply_layer_visibility()
        self.canvas.draw()

    def _is_component_swappable(self, comp_name: str) -> bool:
        """Check whether the component has gates or pins with swaplevel > 0 in the schematic."""
        if not self.schematic_parts:
            return False

        # Find the matching part in schematic_parts (case-insensitive)
        part = None
        c_name_upper = str(comp_name).strip().upper()
        for k, v in self.schematic_parts.items():
            if str(k).strip().upper() == c_name_upper:
                part = v
                break

        if not part:
            return False

        gate_pin_defs = getattr(part, 'gate_pin_definitions', {})
        gates_dict = getattr(part, 'gates', {})

        for gate_name, pin_dict in gate_pin_defs.items():
            gate_obj = gates_dict.get(gate_name)
            gate_swap = getattr(gate_obj, 'swaplevel', 0) if gate_obj else 0
            if gate_swap > 0:
                return True

            for pin_obj in pin_dict.values():
                if getattr(pin_obj, 'swaplevel', 0) > 0:
                    return True

        return False
    
    
    
    def _plot_single_polygon(self, polygon: Polygon, facecolor: str, edgecolor: str) -> list:
        created_artists = []
        xs, ys = polygon.exterior.xy
        
        outer_patches = self.ax.fill(xs, ys, color=facecolor, edgecolor=edgecolor, linewidth=2, label="PCB Outline")
        created_artists.extend(outer_patches)
        
        for interior in polygon.interiors:
            ix, iy = interior.xy
            inner_patches = self.ax.fill(ix, iy, color="#212529", edgecolor=edgecolor, linewidth=1.5)
            created_artists.extend(inner_patches)
            
        return created_artists
    
    def open_schematic_canvas(self, schematic_parts):
        """
        Open a separate window showing a stylized schematic view.
        """
        schematic_win = tk.Toplevel(self.window)
        schematic_win.title("Schematic Logic Topology (Gates and Pins)")
        schematic_win.geometry("900x700")
        
        frame = tk.Frame(schematic_win)
        frame.pack(fill=tk.BOTH, expand=True)
        
        canvas = tk.Canvas(frame, bg="#1E1E1E")
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        x_offset = 50
        y_offset = 50
        row_height = 0
        
        for comp_name in sorted(schematic_parts.keys()):
            part = schematic_parts[comp_name]
            
            num_gates = max(len(part.gates), 1)
            comp_width = 180
            comp_height = 30 + (num_gates * 60)
            
            if x_offset + comp_width > 850:
                x_offset = 50
                y_offset += row_height + 40
                row_height = 0
                
            row_height = max(row_height, comp_height)
            
            canvas.create_rectangle(
                x_offset, y_offset, 
                x_offset + comp_width, y_offset + comp_height,
                outline="#888888", fill="#2D2D2D", width=2
            )
            canvas.create_text(
                x_offset + 10, y_offset + 15, 
                text=f"{comp_name} [{part.deviceset}]", 
                fill="#FFFFFF", anchor="w", font=("Consolas", 10, "bold")
            )
            
            gate_y = y_offset + 30
            for gate_name, gate_obj in sorted(part.gates.items()):
                canvas.create_rectangle(
                    x_offset + 10, gate_y, 
                    x_offset + comp_width - 10, gate_y + 50,
                    outline="#555555", fill="#3A3A3A"
                )
                
                swap_info = f" (SwapLvl {gate_obj.swaplevel})" if gate_obj.swaplevel > 0 else ""
                canvas.create_text(
                    x_offset + 15, gate_y + 12, 
                    text=f"Gate {gate_name}{swap_info}", 
                    fill="#A3D1FF", anchor="w", font=("Consolas", 8)
                )
                
                pin_x = x_offset + 20
                for full_pin, pad in part.pin_to_pad_map.items():
                    g_prefix = gate_name + "."
                    if full_pin.startswith(g_prefix) or (gate_name == "G$1" and "." not in full_pin):
                        pin_label = full_pin.split('.')[-1]
                        
                        canvas.create_oval(
                            pin_x - 3, gate_y + 35 - 3, 
                            pin_x + 3, gate_y + 35 + 3, 
                            fill="#FF5555"
                        )
                        
                        canvas.create_text(
                            pin_x, gate_y + 45, 
                            text=f"{pin_label}→P{pad}", 
                            fill="#E0E0E0", anchor="n", font=("Consolas", 7)
                        )
                        
                        pin_x += 45
                        
                gate_y += 60
                
            x_offset += comp_width + 30

        canvas.config(scrollregion=canvas.bbox("all"))