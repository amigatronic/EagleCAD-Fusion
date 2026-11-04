# main.py
import tkinter as tk
from tkinter import filedialog, ttk
import os
import json
import sys

# Importiamo i moduli dedicati
from parser import EagleBoardParser
from geometry import BoardData
from optimizer import PlacementOptimizer
from parser_schematic import EagleSchematicParser
from gui import EagleGUI
from logger import get_logger, set_gui_logger_callback

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
        
        saved_calib = self._load_calibration()
        self.calibration_factor = tk.DoubleVar(value=saved_calib)
        
        # Inizializza GUI vuota (senza board data)
        self.gui = EagleGUI(window, None, None, "Nessun file caricato", self.calibration_factor)
        self.gui.set_open_file_callback(self._open_file)
        
        # Configura il logger per usare la GUI
        set_gui_logger_callback(self.gui.log_message)
        self.logger = get_logger()
        self.logger.info("Applicazione avviata correttamente")

    def _load_calibration(self) -> float:
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r") as f:
                    data = json.load(f)
                    return float(data.get("calibration_factor", 1.0))
        except Exception as e:
            self.logger.error(f"Impossibile leggere il file di configurazione: {e}")
        return 1.0

    def _save_calibration(self, value: float):
        try:
            if not os.path.exists(self.config_dir):
                os.makedirs(self.config_dir)
            with open(self.config_file, "w") as f:
                json.dump({"calibration_factor": value}, f)
        except Exception as e:
            self.logger.error(f"Errore durante il salvataggio della configurazione: {e}")
        
        # Aggiorna anche il fattore nella GUI
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
        path = filedialog.askopenfilename(
            title="Apri file .brd Convertito in XML",
            filetypes=[("File EAGLE Board", "*.brd"), ("Tutti i file", "*.*")]
        )
        if path:
            self.file_path = path
            parser = EagleBoardParser(path)
            self.board_data = parser.extract_data()
            
            # Ricavo ed estrazione automatica dello schema associato
            sch_path = os.path.splitext(path)[0] + ".sch"
            if os.path.exists(sch_path):
                sch_parser = EagleSchematicParser(sch_path)
                self.schematic_parts = sch_parser.extract_schematic_data()
                self.logger.success(f"Schema accoppiato con successo: {os.path.basename(sch_path)}")
                check_schematic_board_consistency(self.board_data, self.schematic_parts, self.logger)
                debug_print_schematic_entanglement(self.schematic_parts, self.logger)
            else:
                self.schematic_parts = {}
                self.logger.warning("Nessun file .sch corrispondente trovato.")
            
            # === AGGIUNTA: Passa le regole dello schema dentro board_data ===
            self.board_data.schematic_parts = self.schematic_parts
            
            # Inizializza l'ottimizzatore associato alla board caricata
            self.optimizer = PlacementOptimizer(self.board_data)
            
            # Stampa di debug per verificare l'estrazione e il funzionamento della netlist
            initial_rats = self.optimizer.calculate_ratsnest_length()
            self.logger.success(f"File caricato con successo! Numero reti: {len(self.board_data.signals)}")
            self.logger.info(f"Lunghezza Ratsnest iniziale: {initial_rats:.2f} mm")
            
            # Aggiorna la GUI esistente con i nuovi dati
            self.gui.board_data = self.board_data
            self.gui.optimizer = self.optimizer
            self.gui.file_path = os.path.basename(path)
            self.gui._render(self.schematic_parts)


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


    
    
    
def check_schematic_board_consistency(board_data, schematic_parts, logger=None) -> bool:
    """
    Effettua un parsing incrociato per verificare la consistenza quantistica (entanglement)
    tra i dati della Board (.brd) e quelli dello Schema (.sch), sanando i falsi positivi di swap.
    """
    is_consistent = True
    if logger:
        logger.info("=== AVVIO VERIFICA COERENZA SCHEMA-BOARD ===")
    else:
        print("\n=== AVVIO VERIFICA COERENZA SCHEMA-BOARD ===")

    # 1. Filtriamo i componenti dello schema escludendo i simboli di alimentazione (SUPPLY)
    sch_names = {
        name for name, part in schematic_parts.items() 
        if not part.library.lower().startswith("supply") and not name.startswith("SUPPLY")
    }
    board_names = set(board_data.components.keys())

    only_in_board = board_names - sch_names
    only_in_sch = sch_names - board_names

    if only_in_board:
        if logger:
            logger.error(f"Componenti reali presenti solo nella Board: {only_in_board}")
        else:
            print(f"❌ ERRORE: Componenti reali presenti solo nella Board: {only_in_board}")
        is_consistent = False
    if only_in_sch:
        if logger:
            logger.error(f"Componenti logici presenti solo nello Schema: {only_in_sch}")
        else:
            print(f"❌ ERRORE: Componenti logici presenti solo nello Schema: {only_in_sch}")
        is_consistent = False

    # 2. Controllo Coerenza Connessioni (Netlist vs Pin/Pad Map)
    board_netlist = {}
    for sig_name, signal in board_data.signals.items():
        for conn in signal.connections:
            board_netlist[(conn.element, conn.pad)] = sig_name

    # 3. Sanificazione Componenti Polarizzati (Protezione SwapLevel fasulli)
    for name in board_names.intersection(sch_names):
        part = schematic_parts[name]
        
        # Contiamo i pad unici collegati a questo componente nella board
        pads_collegati = set()
        for signal in board_data.signals.values():
            for conn in signal.connections:
                if conn.element == name:
                    pads_collegati.add(conn.pad)
        
        num_pads = len(pads_collegati)

        # Identificatori di diodi (mai swappabili)
        is_diode = any(t in part.library.lower() for t in ["diode", "led", "rectifier"]) or name.startswith("D")
        
        # Identificatori di transistor/MOSFET (non swappabili se hanno 3 o più pad)
        is_transistor = (name.startswith("Q") or name.startswith("T") or 
                         "transistor" in part.library.lower()) and num_pads >= 3
        
        if is_diode or is_transistor:
            ha_swap_attivo = any(
                any(p.swaplevel > 0 for p in pin_dict.values()) 
                for pin_dict in part.gate_pin_definitions.values()
            )
            
            if ha_swap_attivo:
                tipo = "diodo" if is_diode else "transistor/MOSFET"
                if logger:
                    logger.warning(f"Disattivato SwapLevel fasullo sui pin del {tipo} {name} ({part.deviceset}) [Rilevati {num_pads} pad].")
                else:
                    print(f"⚠️ WARNING: Disattivato SwapLevel fasullo sui pin del {tipo} {name} ({part.deviceset}) [Rilevati {num_pads} pad].")
                for gate_name, pin_dict in part.gate_pin_definitions.items():
                    for p_name in pin_dict:
                        part.gate_pin_definitions[gate_name][p_name].swaplevel = 0

    if is_consistent:
        if logger:
            logger.success("ENTANGLEMENT CONFERMATO: Schema e Board sono perfettamente sincronizzati!")
        else:
            print(f"✅ ENTANGLEMENT CONFERMATO: Schema e Board sono perfettamente sincronizzati!")
        # self.render_schematic_topology()
    else:
        if logger:
            logger.warning("Rilevate inconsistenze reali tra Schema e Board.")
        else:
            print("⚠️ ATTENZIONE: Rilevate inconsistenze reali tra Schema e Board.")

    return is_consistent

def debug_print_schematic_entanglement(schematic_parts, logger=None):
    """
    Stampa in console la radiografia dei componenti estratti dallo schema,
    mostrando chiaramente le porte (gate) e i pin che possiedono uno swaplevel.
    """
    if logger:
        logger.info("=== RADIOGRAFIA DEI DATI DELLO SCHEMA (ENTANGLEMENT) ===")
    else:
        print("\n=======================================================")
        print("      RADIOGRAFIA DEI DATI DELLO SCHEMA (ENTANGLEMENT)  ")
        print("=======================================================")
    
    componenti_con_swap = 0
    
    for name, part in schematic_parts.items():
        # Verifichiamo se il componente ha gate o pin con swaplevel > 0
        ha_gate_swap = any(g.swaplevel > 0 for g in part.gates.values())
        ha_pin_swap = any(
            any(p.swaplevel > 0 for p in pin_dict.values()) 
            for pin_dict in part.gate_pin_definitions.values()
        )
        
        if ha_gate_swap or ha_pin_swap:
            componenti_con_swap += 1
            if logger:
                logger.info(f"Componente: {name} | Device: {part.deviceset} | Lib: {part.library}")
            else:
                print(f"\n📦 Componente: {name} | Device: {part.deviceset} | Lib: {part.library}")
            
            if ha_gate_swap:
                if logger:
                    logger.info(f"PORTE (GATES) INTERSCAMBIABILI per {name}:")
                else:
                    print("  ├── 🔄 PORTE (GATES) INTERSCAMBIABILI:")
                for g_name, gate in part.gates.items():
                    if gate.swaplevel > 0:
                        if logger:
                            logger.debug(f"Gate '{g_name}' -> SwapLevel: {gate.swaplevel}")
                        else:
                            print(f"  │   └── Gate '{g_name}' -> SwapLevel: {gate.swaplevel} (Può essere scambiato con porte stesso livello)")
            
            if ha_pin_swap:
                if logger:
                    logger.info(f"PIN INTERSCAMBIABILI per {name}:")
                else:
                    print("  └── 🔀 PIN INTERSCAMBIABILI:")
                for g_name, pin_dict in part.gate_pin_definitions.items():
                    pins_scambiabili = [p_name for p_name, p_data in pin_dict.items() if p_data.swaplevel > 0]
                    if pins_scambiabili:
                        mappa_fisica = []
                        for p_name in pins_scambiabili:
                            full_key = f"{g_name}.{p_name}" if g_name else p_name
                            pad_fisico = part.pin_to_pad_map.get(full_key, "NC")
                            mappa_fisica.append(f"{p_name}(Pad {pad_fisico})")
                        
                        livello = pin_dict[pins_scambiabili[0]].swaplevel
                        if logger:
                            logger.debug(f"Gate '{g_name}': pin {', '.join(mappa_fisica)} hanno SwapLevel {livello}")
                        else:
                            print(f"      └── Nel Gate '{g_name}': i pin {', '.join(mappa_fisica)} hanno SwapLevel {livello} (Invertibili tra loro)")

    if logger:
        logger.info(f"Analisi completata: trovati {componenti_con_swap} componenti complessi con regole di swap.")
    else:
        print("\n=======================================================")
        print(f" Analisi completata: trovati {componenti_con_swap} componenti complessi con regole di swap.")
        print("=======================================================\n")




if __name__ == "__main__":
    root = tk.Tk()
    app = EagleApp(root)
    root.mainloop()