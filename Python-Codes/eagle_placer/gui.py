import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import math
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union

from dru_parser import DesignRules  # <--- Importante: importiamo la gestione DRU

class EagleGUI:
    def __init__(self, window, board_data, optimizer, file_path, calibration_factor):
        self.window = window
        self.board_data = board_data
        self.optimizer = optimizer
        self.file_path = file_path
        self.calibration_factor = calibration_factor
        self.current_scale = "fit"
        self.base_dpi = self.window.winfo_fpixels('1i')
        
        # Gestione Design Rules (DRU)
        self.dru_file_path = None
        if hasattr(self.board_data, 'design_rules') and self.board_data.design_rules:
            self.design_rules = self.board_data.design_rules
        else:
            self.design_rules = DesignRules()
        
        # Attributi matplotlib
        self.fig = None
        self.ax = None
        self.canvas = None
        self.toolbar = None
        self.layer_artists = {}
        self.layer_visibility = {}
        self.check_buttons = None
        
        # Memorizza schematic_parts per render senza parametri
        self.schematic_parts = None
        
        self._build_ui()
        
    def _build_ui(self):
        # ---------------------------------------------------------
        # BARRA SUPERIORE (Open, File Info, Zoom/Scale)
        # ---------------------------------------------------------
        top_bar = ttk.Frame(self.window, padding=10)
        top_bar.pack(side=tk.TOP, fill=tk.X)
        
        btn_open = ttk.Button(top_bar, text="Apri File .brd", command=self._on_open_file)
        btn_open.pack(side=tk.LEFT, padx=5)
        
        self.lbl_file = ttk.Label(top_bar, text="Nessun file caricato", font=("Arial", 10, "italic"))
        self.lbl_file.pack(side=tk.LEFT, padx=15)
        if self.file_path:
            self.lbl_file.config(text=str(self.file_path), font=("Arial", 10, "bold"))
        
        ttk.Label(top_bar, text="Visualizzazione:").pack(side=tk.LEFT, padx=5)
        self.scale_var = tk.StringVar(value="Fit")
        scale_combo = ttk.Combobox(top_bar, textvariable=self.scale_var, state="readonly", width=10)
        scale_combo['values'] = ("Fit", "1:1 Real", "2:1", "5:1")
        scale_combo.pack(side=tk.LEFT, padx=5)
        scale_combo.bind("<<ComboboxSelected>>", self._on_scale_change)

        # ---------------------------------------------------------
        # PANNELLO CALIBRAZIONE RIGHELLO REALE
        # ---------------------------------------------------------
        calib_frame = ttk.LabelFrame(self.window, text=" Calibrazione Righello Reale ", padding=5)
        calib_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=2)
        
        ttk.Label(calib_frame, text="Allinea le misure dello schermo al righello. Fai CLICK sui componenti per bloccare/sbloccare (LOCK):").pack(side=tk.LEFT, padx=5)
        
        btn_minus = ttk.Button(calib_frame, text=" - Rimpicciolisci ", width=15, command=self._decrease_calib)
        btn_minus.pack(side=tk.LEFT, padx=5)
        
        self.lbl_calib_val = ttk.Label(calib_frame, text=f"Fattore: {self.calibration_factor.get():.3f}", font=("Arial", 10, "bold"))
        self.lbl_calib_val.pack(side=tk.LEFT, padx=10)
        
        btn_plus = ttk.Button(calib_frame, text=" + Ingrandisci ", width=15, command=self._increase_calib)
        btn_plus.pack(side=tk.LEFT, padx=5)

        # ---------------------------------------------------------
        # PANNELLO REGOLE DI DESIGN & CLEARANCE (DRU)
        # ---------------------------------------------------------
        dru_frame = ttk.LabelFrame(self.window, text=" Regole di Design e Clearance (DRU) ", padding=5)
        dru_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=2)

        # Pulsanti gestione DRU
        btn_load_dru = ttk.Button(dru_frame, text="📁 Carica .DRU", command=self._on_load_dru)
        btn_load_dru.pack(side=tk.LEFT, padx=5)

        self.btn_clear_dru = ttk.Button(dru_frame, text="✖ Reset a BRD", command=self._on_clear_dru, state="disabled")
        self.btn_clear_dru.pack(side=tk.LEFT, padx=5)

        self.lbl_dru_status = ttk.Label(dru_frame, text="Origine: Valori dal file .BRD", font=("Arial", 9, "italic"))
        self.lbl_dru_status.pack(side=tk.LEFT, padx=10)

        # Inputs Manuali per la clearance
        ttk.Label(dru_frame, text="Comp-Comp (mm):").pack(side=tk.LEFT, padx=(15, 2))
        self.spin_comp = ttk.Spinbox(dru_frame, from_=0.0, to=10.0, increment=0.05, width=6, command=self._on_manual_dru_change)
        self.spin_comp.pack(side=tk.LEFT, padx=2)

        ttk.Label(dru_frame, text="Bordo PCB (mm):").pack(side=tk.LEFT, padx=(10, 2))
        self.spin_edge = ttk.Spinbox(dru_frame, from_=0.0, to=20.0, increment=0.1, width=6, command=self._on_manual_dru_change)
        self.spin_edge.pack(side=tk.LEFT, padx=2)

        ttk.Label(dru_frame, text="Rame Base (mm):").pack(side=tk.LEFT, padx=(10, 2))
        self.spin_track = ttk.Spinbox(dru_frame, from_=0.0, to=5.0, increment=0.05, width=6, command=self._on_manual_dru_change)
        self.spin_track.pack(side=tk.LEFT, padx=2)

        # Inserisci questo pulsante dentro top_bar in _build_ui()
        btn_summary = ttk.Button(top_bar, text="📊 Stato Dati Optimizer", command=self._show_data_summary)
        btn_summary.pack(side=tk.RIGHT, padx=5)

        # Popoliamo i campi di input iniziali
        self._update_dru_ui_fields()

        # ---------------------------------------------------------
        # AREA PRINCIPALE DI RENDERING E LOG
        # ---------------------------------------------------------
        self.render_frame = ttk.Frame(self.window)
        self.render_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Pannello Board con Matplotlib (sinistra)
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
        
        # Pannello destra: Legenda + Log
        self.right_panel = ttk.Frame(self.render_frame)
        self.right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10, 0))
        
        # 1. LEGENDA (Costruita una sola volta)
        self.legend_container = ttk.LabelFrame(self.right_panel, text=" Legenda PCB (Click per attivare/disattivare) ")
        self.legend_container.pack(side=tk.TOP, fill=tk.X, pady=(0, 10))
        
        self.legend_vars = {}
        self.legend_rows = {}
        legend_data = [
            ("Profilo PCB", "#e9edf0", "#666666"),
            ("Keepout TOP (L39)", "#ff6b6b", "#e60000"),
            ("Keepout BOTTOM (L40)", "#4dadf7", "#0066cc"),
            ("Comp. Libero (TOP)", "#fffbeb", "#d97706"),
            ("Comp. Libero (BOTTOM)", "#eff6ff", "#2563eb"),
            ("Comp. Bloccato [LOCKED]", "#fee2e2", "#dc2626"),
            ("Foro Meccanico (Hole)", "#212529", "#888888"),
            ("Via Estetica", "#b87333", "#8a4f1a"),
            ("Ratsnest Swappabile (L19)", "#FF00FF", "#FF00FF")
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
        self.log_container = ttk.LabelFrame(self.right_panel, text=" Registro Eventi (LOG) ")
        self.log_container.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True)
        
        # Frame superiore per i controlli del Log (Pulsanti Salva e Pulisci)
        log_ctrl_frame = ttk.Frame(self.log_container)
        log_ctrl_frame.pack(side=tk.TOP, fill=tk.X, padx=5, pady=(2, 2))
        
        btn_clear_log = ttk.Button(log_ctrl_frame, text="🗑️ Pulisci Log", command=self._clear_log)
        btn_clear_log.pack(side=tk.RIGHT, padx=(2, 0))

        btn_save_log = ttk.Button(log_ctrl_frame, text="💾 Salva Log", command=self._save_log)
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
        """Verifica se il layer di appartenenza del componente è visibile in legenda."""
        if getattr(comp, 'locked', False):
            label = "Comp. Bloccato [LOCKED]"
        elif getattr(comp, 'mirror', False):
            label = "Comp. Libero (BOTTOM)"
        else:
            label = "Comp. Libero (TOP)"
        
        var = self.legend_vars.get(label)
        return var.get() if var is not None else True
    
    def _on_legend_toggle(self):
        """Richiamato al click sui Checkbutton della legenda."""
        self._apply_layer_visibility()
        if self.canvas:
            self.canvas.draw_idle()
    
    def _update_legend_visibility(self):
        """Mostra in legenda solo i layer che contengono effettivamente degli elementi grafici."""
        layer_mapping = {
            "Profilo PCB": "Profilo PCB",
            "Keepout TOP (L39)": "Keepout TOP",
            "Keepout BOTTOM (L40)": "Keepout BOTTOM",
            "Comp. Libero (TOP)": "Comp. TOP",
            "Comp. Libero (BOTTOM)": "Comp. BOTTOM",
            "Comp. Bloccato [LOCKED]": "Comp. Bloccati",
            "Foro Meccanico (Hole)": "Fori (Holes)",
            "Via Estetica": "Vias",
            "Ratsnest Swappabile (L19)": "Ratsnest Swappabile"
        }
        for label, layer_key in layer_mapping.items():
            if label in self.legend_rows:
                # Se il layer contiene elementi disegnati, mostra la riga, altrimenti nascondila
                if layer_key in self.layer_artists and len(self.layer_artists[layer_key]) > 0:
                    self.legend_rows[label].pack(anchor=tk.W, padx=5, pady=2, fill=tk.X)
                else:
                    self.legend_rows[label].pack_forget()
    
    def _apply_layer_visibility(self):
        """Applica lo stato attuale dei Checkbutton agli elementi grafici nel canvas."""
        layer_mapping = {
            "Profilo PCB": "Profilo PCB",
            "Keepout TOP (L39)": "Keepout TOP",
            "Keepout BOTTOM (L40)": "Keepout BOTTOM",
            "Comp. Libero (TOP)": "Comp. TOP",
            "Comp. Libero (BOTTOM)": "Comp. BOTTOM",
            "Comp. Bloccato [LOCKED]": "Comp. Bloccati",
            "Foro Meccanico (Hole)": "Fori (Holes)",
            "Via Estetica": "Vias",
            "Ratsnest Swappabile (L19)": "Ratsnest Swappabile"
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
        """Aggiorna le Spinbox con i valori correnti dell'oggetto DesignRules."""
        self.spin_comp.delete(0, tk.END)
        self.spin_comp.insert(0, f"{self.design_rules.clearance_comp_to_comp:.2f}")

        self.spin_edge.delete(0, tk.END)
        self.spin_edge.insert(0, f"{self.design_rules.clearance_board_edge:.2f}")

        self.spin_track.delete(0, tk.END)
        self.spin_track.insert(0, f"{self.design_rules.clearance_track_to_track:.2f}")

    def _on_load_dru(self):
        """Carica un file .dru esterno."""
        path = filedialog.askopenfilename(
            title="Seleziona File Design Rules (.dru)",
            filetypes=[("Eagle Design Rules", "*.dru"), ("Tutti i file", "*.*")]
        )
        if not path:
            return

        if self.design_rules.load_from_dru_file(path):
            self.dru_file_path = path
            filename = path.replace("\\", "/").split("/")[-1]
            self.lbl_dru_status.config(text=f"DRU Attivo: {filename}", foreground="green")
            self.btn_clear_dru.config(state="normal")
            
            self._update_dru_ui_fields()
            self._toggle_dru_inputs(enable=False)
            
            if self.board_data:
                self.board_data.design_rules = self.design_rules
            
            self.log_message(f"Caricate regole di design da: {filename}", "SUCCESS")
        else:
            messagebox.showerror("Errore DRU", "Impossibile caricare il file .dru selezionato.")

    def _clear_log(self):
        """Svuota il contenuto del registro eventi."""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.config(state=tk.DISABLED)
    
    def _save_log(self):
        """Salva il contenuto del registro eventi in un file di testo."""
        content = self.log_text.get("1.0", tk.END).strip()
        if not content:
            messagebox.showwarning("Log Vuoto", "Non c'è alcun evento da salvare.")
            return

        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("File di testo", "*.txt"), ("Tutti i file", "*.*")],
            title="Salva Registro Eventi"
        )
        if file_path:
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(content)
                self.log_message(f"Log salvato in: {file_path}", "SUCCESS")
            except Exception as e:
                messagebox.showerror("Errore Salvataggio", f"Impossibile salvare il log:\n{e}")
    
    def _on_clear_dru(self):
        """Ripristina le regole lette dal .BRD originale."""
        self.dru_file_path = None
        self.btn_clear_dru.config(state="disabled")
        self._toggle_dru_inputs(enable=True)

        if hasattr(self.board_data, 'design_rules') and self.board_data.design_rules:
            self.design_rules = self.board_data.design_rules
            self.lbl_dru_status.config(text="Origine: Valori dal file .BRD", foreground="black")
        else:
            self.lbl_dru_status.config(text="Origine: Valori Manuali", foreground="black")

        self._update_dru_ui_fields()
        self.log_message("Ripristinate le regole di design predefinite dal BRD.", "INFO")

    def _on_manual_dru_change(self):
        """Eseguito quando l'utente cambia manualmente uno spinbox."""
        if not self.dru_file_path:
            try:
                comp_c = float(self.spin_comp.get())
                edge_c = float(self.spin_edge.get())
                track_c = float(self.spin_track.get())
                self.design_rules.load_from_manual_inputs(comp_c, edge_c, track_c)
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
        """Restituisce l'oggetto DesignRules attivo per l'ottimizzatore."""
        self._on_manual_dru_change()
        return self.design_rules

    # ------------------------------------------------------------------
    # RESTO DEI METODI ORIGINALI DI GUI.PY
    # ------------------------------------------------------------------
    def log_message(self, message: str, level: str = "INFO"):
        """Aggiunge un messaggio al registro log"""
        timestamp = __import__('datetime').datetime.now().strftime("%H:%M:%S")
        
        colors = {
            "INFO": "#00FF00",      # Verde
            "WARNING": "#FFFF00",   # Giallo
            "ERROR": "#FF0000",     # Rosso
            "DEBUG": "#00FFFF",     # Ciano
            "SUCCESS": "#00FF00"    # Verde
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
        self.lbl_calib_val.config(text=f"Fattore: {new_val:.3f}")
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
        if event.inaxes != self.ax:
            return

        if not self.board_data or event.xdata is None or event.ydata is None:
            return
            
        clicked_component = None
        min_dist = float('inf')
        
        for name, comp in self.board_data.components.items():
            # <--- AGGIUNTA: Ignora i componenti se il loro layer non è visibile
            if not self._is_component_layer_visible(comp):
                continue

            dist = math.hypot(event.xdata - comp.x, event.ydata - comp.y)
            threshold = max(comp.width, comp.height) / 1.4
            if dist < threshold and dist < min_dist:
                min_dist = dist
                clicked_component = name
        
        if clicked_component:
            comp = self.board_data.components[clicked_component]
            
            # === TASTO SINISTRO: Lock/Unlock Posizione ===
            if event.button == 1:
                comp.locked = not getattr(comp, 'locked', False)
                status = "LOCKED 🔒" if comp.locked else "UNLOCKED 🔓"
                self.log_message(f"Posizione componente {clicked_component} impostata su: {status}", "INFO")
                
            # === TASTO DESTRO: Enable/Disable Swap Logico ===
            elif event.button == 3:
                if self._is_component_swappable(clicked_component):
                    current_swap = getattr(comp, 'swap_enabled', True)
                    comp.swap_enabled = not current_swap
                    status = "ABILITATO 🔄" if comp.swap_enabled else "DISABILITATO 🚫"
                    self.log_message(f"Swap logico per {clicked_component} impostato su: {status}", "INFO")
                else:
                    self.log_message(f"Il componente {clicked_component} non ha Gate/Pin swappabili nello schema.", "WARNING")
            if self.optimizer:
                ratsnest = self.optimizer.calculate_ratsnest_length()
            self._render()

    def _show_data_summary(self):
        """Apre una finestra di ispezione completa con tutti i dati e i controlli per optimizer.py."""
        if not self.board_data:
            messagebox.showwarning("Nessun Dato", "Caricare un file .BRD per visualizzare i dati.")
            return

        summary_win = tk.Toplevel(self.window)
        summary_win.title("Ispezione Dati e Vincoli per Optimizer")
        summary_win.geometry("750x700")

        txt = tk.Text(summary_win, bg="#1E1E1E", fg="#00FF00", font=("Consolas", 9), wrap=tk.WORD, padx=10, pady=10)
        vbar = ttk.Scrollbar(summary_win, orient=tk.VERTICAL, command=txt.yview)
        txt.configure(yscrollcommand=vbar.set)

        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        lines = []
        warnings = []

        lines.append("=" * 70)
        lines.append("  ISPEZIONE DATI DI INGRESSO E VERIFICA PER OPTIMIZER.PY")
        lines.append("=" * 70 + "\n")

        # 1. PROFILO BOARD E OFF-LIMIT
        lines.append("1. PROFILO PCB & AREE OFF-LIMIT")
        lines.append("-" * 50)
        try:
            poly_count = len(self.board_data.boundary_polygons)
            lines.append(f"   • Poligoni di Contorno PCB: {poly_count}")
            if poly_count >= 1:
                outer_poly = Polygon(self.board_data.boundary_polygons[0])
                lines.append(f"   • Area Bordo PCB (Esterna): {outer_poly.area:.2f} mm²")
            else:
                warnings.append("⚠️ Nessun contorno PCB rilevato!")
        except Exception:
            lines.append("   • Area PCB: N/D")
            warnings.append("⚠️ Impossibile calcolare l'area del bordo PCB.")

        kp_top = len(getattr(self.board_data, 'keepouts_top', []))
        kp_bot = len(getattr(self.board_data, 'keepouts_bottom', []))
        holes = len(getattr(self.board_data, 'holes', []))
        vias = len(getattr(self.board_data, 'isolated_vias', []))
        lines.append(f"   • Zone Keepout TOP (L39): {kp_top} | BOTTOM (L40): {kp_bot}")
        lines.append(f"   • Fori Meccanici: {holes} | Vias Orfane: {vias}\n")

        # 2. COMPONENTI, GEOMETRIE E TECNOLOGIA (SMD vs THT)
        lines.append("2. COMPONENTI, GEOMETRIE E TECNOLOGIA (SMD vs THT)")
        lines.append("-" * 50)
        comps = getattr(self.board_data, 'components', {})
        lines.append(f"   • Totale Componenti: {len(comps)}")

        top_comps = sum(1 for c in comps.values() if not getattr(c, 'mirror', False))
        bot_comps = sum(1 for c in comps.values() if getattr(c, 'mirror', False))
        lines.append(f"   • Posizione Attuale: TOP ({top_comps}) | BOTTOM ({bot_comps})")

        # Conteggio basato sull'attributo reale 'is_tht'
        tht_count = sum(1 for c in comps.values() if getattr(c, 'is_tht', False))
        smd_count = len(comps) - tht_count
        lines.append(f"   • Tecnologia: SMD ({smd_count}) | THT ({tht_count})")

        # Controllo THT posizionati erroneamente su layer BOTTOM
        tht_on_bottom = [name for name, c in comps.items() if getattr(c, 'is_tht', False) and getattr(c, 'mirror', False)]
        if tht_on_bottom:
            warnings.append(f"⚠️ Componenti THT posizionati su BOTTOM: {', '.join(tht_on_bottom)}")

        # Verifica Rotazioni e Offset Centro Geometrico
        missing_offset = [name for name, c in comps.items() if not hasattr(c, 'offset_x') or not hasattr(c, 'offset_y')]
        if missing_offset:
            warnings.append(f"⚠️ Offset centro geometrico mancante per {len(missing_offset)} componenti.")

        total_bbox_area = sum(c.width * c.height for c in comps.values())
        lines.append(f"   • Area Totale Bounding Boxes: {total_bbox_area:.2f} mm²\n")

        # 3. STATO LOCKING COMPONENTI
        lines.append("3. STATO LOCKING COMPONENTI")
        lines.append("-" * 50)
        locked_comps = [name for name, c in comps.items() if getattr(c, 'locked', False)]
        lines.append(f"   • Componenti Bloccati (LOCKED): {len(locked_comps)}")
        if locked_comps:
            lines.append(f"     Elenco: {', '.join(locked_comps)}")
        lines.append(f"   • Componenti Liberi (UNLOCKED): {len(comps) - len(locked_comps)}\n")

        # 4. SWAPPING PIN/GATE E MAPPATURA PIN-TO-PAD (.SCH)
        lines.append("4. PIN/GATE SWAPPING E MAPPATURA PIN-TO-PAD")
        lines.append("-" * 50)
        if not hasattr(self, 'schematic_parts') or not self.schematic_parts:
            warnings.append("⚠️ File Schema (.SCH) non caricato! Pin/Gate swapping disabilitato.")
            lines.append("   • Mappatura Pin-to-Pad / DeviceSet: DATI SCHEMA MANCANTI")
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

            lines.append(f"   • Componenti Swappabili identificati: {swappable_count}")
            lines.append(f"   • Componenti con Swap Attivo: {swappable_count - disabled_swap_count}")
            lines.append(f"   • Componenti con Swap Disabilitato Manualmente: {disabled_swap_count}")
            
            if missing_map_count > 0:
                warnings.append(f"⚠️ Mappatura Pin-to-Pad mancante per {missing_map_count} componenti swappabili.")

        lines.append("")

        # 5. MATRICE DI EQUIVALENZA PASSIVI IDENTICI
        lines.append("5. MATRICE EQUIVALENZA PASSIVI IDENTICI")
        lines.append("-" * 50)
        passive_groups = getattr(self.board_data, 'passive_equivalence_groups', {})
        if passive_groups:
            lines.append(f"   • Gruppi di Passivi Equivalenti Trovati: {len(passive_groups)}")
            for grp_id, members in passive_groups.items():
                lines.append(f"     Group '{grp_id}': {', '.join(members)}")
        else:
            lines.append("   • Nessun gruppo di passivi interscambiabili identificato o non ancora calcolato.")
        lines.append("")

        # 6. REGOLE DI DESIGN (DRU) E COSTI/PENALITÀ
        lines.append("6. REGOLE DI DESIGN (DRU) & PARAMETRI COSTO (FITNESS)")
        lines.append("-" * 50)
        source = "File .DRU Esterno" if self.dru_file_path else ("Default BRD" if hasattr(self.board_data, 'design_rules') and self.board_data.design_rules else "Manuale GUI")
        lines.append(f"   • Origine Regole: {source}")
        lines.append(f"   • Clearance Comp-to-Comp: {self.design_rules.clearance_comp_to_comp:.2f} mm")
        lines.append(f"   • Clearance Board Edge: {self.design_rules.clearance_board_edge:.2f} mm")
        lines.append(f"   • Clearance Track-to-Track: {self.design_rules.clearance_track_to_track:.2f} mm")
        
        via_penalty = getattr(self.design_rules, 'via_penalty', 10.0)
        lines.append(f"   • Penalità Layer Swap/Via (Fitness Function): {via_penalty:.2f}\n")

        # 7. NET CLASSES E RATSNEST
        lines.append("7. NET CLASSES, SEGNALI E RATSNEST")
        lines.append("-" * 50)
        signals = getattr(self.board_data, 'signals', {})
        lines.append(f"   • Totale Reti/Segnali (Nets): {len(signals)}")
        
        brd_classes = getattr(self.board_data, 'net_classes', {})
        sch_classes = getattr(self.schematic_parts, 'net_classes', {}) if hasattr(self, 'schematic_parts') and hasattr(self.schematic_parts, 'net_classes') else brd_classes
        
        if brd_classes != sch_classes:
            warnings.append("⚠️ Discrepanza tra Net Classes del file .BRD e del file .SCH!")
            lines.append(f"   • Classi di Rete: DISCREPANZA RILEVATA! (BRD: {len(brd_classes)}, SCH: {len(sch_classes)})")
        else:
            lines.append(f"   • Classi di Rete (Net Classes BRD/SCH): {len(brd_classes)} [CONGRUENTI]")

        if self.optimizer:
            try:
                ratsnest_len = self.optimizer.calculate_ratsnest_length()
                lines.append(f"   • Stima Lunghezza Ratsnest Iniziale: {ratsnest_len:.2f} mm")
            except Exception:
                lines.append("   • Stima Ratsnest: In calcolo...")

        lines.append("\n" + "=" * 70)

        # SEZIONE AVVISI E VALIDAZIONE
        if warnings:
            lines.append("  ⚠️ AVVISI E ANOMALIE RILEVATE:")
            lines.append("-" * 50)
            for w in warnings:
                lines.append(f"  {w}")
            lines.append("\n  STATO: Dati incompleti o con avvisi. Verificare prima di avviare l'ottimizzazione.")
        else:
            lines.append("  STATO: Tutti i dati sono validati, congruenti e pronti per optimizer.py")
        lines.append("=" * 70)

        txt.insert(tk.END, "\n".join(lines))
        txt.config(state=tk.DISABLED)
    
    def _render(self, schematic_parts=None):
        if not self.board_data or not hasattr(self, 'fig'):
            return
        
        if schematic_parts is not None:
            self.schematic_parts = schematic_parts

        # Aggiorna i campi delle regole se presenti nel board_data
        if hasattr(self.board_data, 'design_rules') and self.board_data.design_rules and not self.dru_file_path:
            self.design_rules = self.board_data.design_rules
            self._update_dru_ui_fields()
            
        self.fig.clf()
        
        self.ax = self.fig.add_axes([0.08, 0.1, 0.65, 0.8])
        
        self.ax.set_aspect('equal')
        self.ax.grid(True, linestyle=':', alpha=0.6, color="#444444")
        self.ax.set_facecolor('#212529')
        self.fig.patch.set_facecolor('#f0f0f0')
        self.ax.autoscale(enable=True, axis='both', tight=True)
        self.ax.set_xlabel("X (mm)")
        self.ax.set_ylabel("Y (mm)")
        
        title_scale = "Adattato" if self.current_scale == "fit" else f"{int(self.current_scale)}:1 Reale"
        self.ax.set_title(f"Board: {self.file_path} | Scala: {title_scale}", pad=15)

        self.layer_artists = {
            "Profilo PCB": [],
            "Keepout TOP": [],
            "Keepout BOTTOM": [],
            "Comp. TOP": [],
            "Comp. BOTTOM": [],
            "Comp. Bloccati": [],
            "Fori (Holes)": [],
            "Vias": [],
            "Ratsnest Swappabile": []
        }
        
        # 1. Profilo PCB
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
                            self.layer_artists["Profilo PCB"].extend(patches_list)
                    elif isinstance(placement_area, MultiPolygon):
                        for geom in placement_area.geoms:
                            patches_list = self._plot_single_polygon(geom, facecolor="#e9edf0", edgecolor="#666666")
                            if patches_list:
                                self.layer_artists["Profilo PCB"].extend(patches_list)
        except Exception:
            pass

        # 2. Keepout TOP
        try:
            for kp in self.board_data.keepouts_top:
                p = patches.Polygon(kp, closed=True, facecolor='#ff6b6b', edgecolor='#e60000', alpha=0.5, linewidth=1.5, zorder=3)
                self.ax.add_patch(p)
                self.layer_artists["Keepout TOP"].append(p)
        except Exception:
            pass

        # 3. Keepout BOTTOM
        try:
            for kp in self.board_data.keepouts_bottom:
                p = patches.Polygon(kp, closed=True, facecolor='#4dadf7', edgecolor='#0066cc', alpha=0.5, linewidth=1.5, zorder=3)
                self.ax.add_patch(p)
                self.layer_artists["Keepout BOTTOM"].append(p)
        except Exception:
            pass

        # 4. Fori Meccanici
        try:
            for x, y, drill in self.board_data.holes:
                c = patches.Circle((x, y), radius=drill/2, facecolor='#212529', edgecolor='#888888', linewidth=1, zorder=5)
                self.ax.add_patch(c)
                cross, = self.ax.plot(x, y, marker='+', color='#ffffff', markersize=5, zorder=6)
                self.layer_artists["Fori (Holes)"].extend([c, cross])
        except Exception:
            pass

        # 5. Vias
        try:
            for via in self.board_data.isolated_vias:
                v_out = patches.Circle((via.x, via.y), radius=via.diameter/2, facecolor='#b87333', edgecolor='#8a4f1a', linewidth=0.5, zorder=4)
                v_in = patches.Circle((via.x, via.y), radius=via.drill/2, facecolor='#212529', edgecolor='none', zorder=5)
                self.ax.add_patch(v_out)
                self.ax.add_patch(v_in)
                self.layer_artists["Vias"].extend([v_out, v_in])
        except Exception:
            pass

        # 6. Componenti
        try:
            if hasattr(self.board_data, 'components') and self.board_data.components:
                for name, comp in self.board_data.components.items():
                    w = comp.width
                    h = comp.height
                    
                    category = "Comp. Bloccati" if comp.locked else ("Comp. BOTTOM" if comp.mirror else "Comp. TOP")
                    
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
            pass

        # 7. Pin Swappabili
        try:
            if self.schematic_parts and self.board_data.signals:
                swappable_pads_by_comp = {}
                for comp_name, part in self.schematic_parts.items():
                    c_name_upper = str(comp_name).strip().upper()
                    
                    # Se lo swap è disabilitato da tasto destro, ignora questo componente
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
                                pad_fisico = pin_to_pad.get(full_key)
                                
                                if pad_fisico is None:
                                    pad_fisico = pin_to_pad.get(pin_label)
                                
                                if pad_fisico is not None:
                                    if c_name_upper not in swappable_pads_by_comp:
                                        swappable_pads_by_comp[c_name_upper] = set()
                                    swappable_pads_by_comp[c_name_upper].add(str(pad_fisico).strip().upper())                
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
                    self.layer_artists["Ratsnest Swappabile"].append(scatter_dots)
        except Exception:
            pass

        # Gestione resize/scale
        if self.current_scale != "fit":
            all_x, all_y = [], []
            for loop in self.board_data.boundary_polygons:
                for px, py in loop:
                    all_x.append(px)
                    all_y.append(py)
            
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
            self.ax.relim()
            self.ax.autoscale_view()

        # Applica lo stato dei Checkbutton esistenti ai nuovi elementi grafici appena creati
        self._update_legend_visibility()
        self._apply_layer_visibility()
        self.canvas.draw()

    def _is_component_swappable(self, comp_name: str) -> bool:
        """Verifica se il componente possiede Gate o Pin con swaplevel > 0 nello schema."""
        if not self.schematic_parts:
            return False

        # Cerca la parte corrispondente in schematic_parts (case-insensitive)
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
        
        outer_patches = self.ax.fill(xs, ys, color=facecolor, edgecolor=edgecolor, linewidth=2, label="Profilo PCB")
        created_artists.extend(outer_patches)
        
        for interior in polygon.interiors:
            ix, iy = interior.xy
            inner_patches = self.ax.fill(ix, iy, color="#212529", edgecolor=edgecolor, linewidth=1.5)
            created_artists.extend(inner_patches)
            
        return created_artists
    
    def open_schematic_canvas(self, schematic_parts):
        """
        Apre una finestra separata per visualizzare lo schema in modo stilizzato.
        """
        schematic_win = tk.Toplevel(self.window)
        schematic_win.title("Topologia Logica dello Schema (Gate & Pin)")
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