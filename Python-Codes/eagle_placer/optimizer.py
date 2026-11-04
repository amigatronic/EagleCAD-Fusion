# optimizer.py
import math
from geometry import BoardData, ComponentData
from typing import List, Tuple

class PlacementOptimizer:
    def __init__(self, board_data: BoardData):
        self.board_data = board_data
        
    def _get_absolute_pad_coords(self, comp: ComponentData, conn) -> Tuple[float, float]:
        """
        Prende le coordinate locali di un pad dal package e restituisce
        la sua coordinata assoluta attuale sulla board, applicando mirror, rotazione e traslazione.
        """
        # 1. Recupero del nome del pad (Board o Schema)
        pad_name = None
        for attr in ['pad', 'pin', 'contact']:
            if hasattr(conn, attr):
                pad_name = getattr(conn, attr)
                break
                
        if pad_name is None:
            return comp.x, comp.y
            
        # 2. Recupero sicuro del package dai dati della board (Supporta sia 'package' che 'package_name')
        package = None
        pkg_name = getattr(comp, 'package', getattr(comp, 'package_name', None))
        lib_name = getattr(comp, 'library', getattr(comp, 'library_name', None))
        
        if pkg_name and hasattr(self.board_data, 'packages'):
            if lib_name:
                lib_dict = self.board_data.packages.get(lib_name)
                if lib_dict:
                    package = lib_dict.get(pkg_name)
            
            # FALLBACK: Se la libreria specifica manca, cerchiamo in tutte le librerie
            if package is None:
                for lib_dict in self.board_data.packages.values():
                    if pkg_name in lib_dict:
                        package = lib_dict[pkg_name]
                        break

        # Se il package o la mappa pad non esistono, usiamo il centro del componente
        if not package or 'pads' not in package:
            return comp.x, comp.y
            
        # Ricerca case-insensitive del pad nel package
        pads_dict = package['pads']
        pad_key = str(pad_name).strip().upper()
        matched_key = next((k for k in pads_dict if str(k).strip().upper() == pad_key), None)
        
        if matched_key is None:
            return comp.x, comp.y
            
        # 3. Coordinate locali fisse del pad
        local_x, local_y = pads_dict[matched_key]
        
        # 4. Gestione Specchiamento (Mirror / lato BOTTOM)
        if getattr(comp, 'mirror', False):
            local_x = -local_x
        
        # Convertiamo la rotazione del componente in radianti (EAGLE usa i gradi)
        angle_rad = math.radians(comp.rot)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)
        
        # Formula di rotazione attorno al centro (0,0) del componente
        rotated_x = local_x * cos_a - local_y * sin_a
        rotated_y = local_x * sin_a + local_y * cos_a
        
        # Applichiamo la traslazione (posizione assoluta sulla board)
        absolute_x = comp.x + rotated_x
        absolute_y = comp.y + rotated_y
        
        return absolute_x, absolute_y
        
    def calculate_ratsnest_length(self) -> float:
        """
        Calcola la lunghezza totale del Ratsnest usando l'algoritmo di Kruskal (MST)
        per trovare la connessione minima reale all'interno di ogni singola Net.
        """
        total_length = 0.0
        
        # Cicliamo su ogni singola rete (Net) definita nella Netlist della board
        for sig_name, signal in self.board_data.signals.items():
            connections = signal.connections
            n = len(connections)
            
            # Se la rete ha meno di 2 pin, non c'è nulla da collegare. Passiamo oltre.
            if n < 2:
                continue
                
            # 1. RACCOLTA COORDINATE REALI DEI PAD
            pin_coords = []
            for conn in connections:
                comp = self.board_data.components.get(conn.element)
                if comp:
                    # Calcoliamo la posizione esatta del PAD rototraslato nello spazio!
                    px, py = self._get_absolute_pad_coords(comp, conn)
                    pin_coords.append((px, py))
                else:
                    # Fallback di sicurezza sulle coordinate originali del contatto
                    pin_coords.append((conn.x, conn.y))
            
            # 2. GENERAZIONE DI TUTTI I POSSIBILI COLLEGAMENTI (Archi del Grafo)
            edges = []
            for i in range(n):
                for j in range(i + 1, n):
                    dist = math.hypot(
                        pin_coords[i][0] - pin_coords[j][0], 
                        pin_coords[i][1] - pin_coords[j][1]
                    )
                    edges.append((dist, i, j))
            
            # Ordiniamo tutti i segmenti trovati dal PIÙ CORTO al PIÙ LUNGO (Cuore di Kruskal)
            edges.sort(key=lambda x: x[0])
            
            # 3. STRUTTURA DATI "UNION-FIND" (Per evitare di creare cerchi/anelli chiusi di rame)
            parent = list(range(n))
            
            def find(i):
                if parent[i] == i:
                    return i
                parent[i] = find(parent[i])
                return parent[i]
                
            def union(i, j):
                root_i = find(i)
                root_j = find(j)
                if root_i != root_j:
                    parent[root_i] = root_j
                    return True
                return False
            
            # 4. COSTRUZIONE DELL'ALBERO MINIMO (MST)
            mst_edges_count = 0
            for dist, u, v in edges:
                if union(u, v):
                    total_length += dist
                    mst_edges_count += 1
                    # Un albero con 'n' nodi è completo quando ha esattamente 'n - 1' collegamenti
                    if mst_edges_count == n - 1:
                        break
                        
        return total_length

    def is_placement_valid(self, comp: ComponentData, new_x: float, new_y: float, new_layer: str) -> bool:
        """
        Verifica i vincoli rigidi (Hard Constraints).
        """
        if comp.locked:
            return False
            
        if comp.is_tht and new_layer != "TOP":
            return False
            
        return True