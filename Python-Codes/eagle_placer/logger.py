# logger.py
import sys
from datetime import datetime

class GUILogger:
    """Logger personalizzato che reindirizza l'output alla GUI"""
    
    def __init__(self, gui_callback=None):
        self.gui_callback = gui_callback
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
    
    def set_gui_callback(self, callback):
        """Imposta il callback della GUI per i messaggi di log"""
        self.gui_callback = callback
    
    def info(self, message: str):
        """Log di livello INFO"""
        self._log(message, "INFO")
    
    def warning(self, message: str):
        """Log di livello WARNING"""
        self._log(message, "WARNING")
    
    def error(self, message: str):
        """Log di livello ERROR"""
        self._log(message, "ERROR")
    
    def debug(self, message: str):
        """Log di livello DEBUG"""
        self._log(message, "DEBUG")
    
    def success(self, message: str):
        """Log di livello SUCCESS"""
        self._log(message, "SUCCESS")
    
    def _log(self, message: str, level: str):
        """Metodo interno per il logging"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {level}: {message}"
        
        # Invia alla GUI se disponibile
        if self.gui_callback:
            try:
                self.gui_callback(message, level)
            except Exception as e:
                # Fallback su stdout se la GUI fallisce
                print(formatted_message, file=self.original_stdout)
        else:
            # Fallback su stdout se non c'è GUI
            print(formatted_message, file=self.original_stdout)
    
    def redirect_stdout(self):
        """Reindirizza stdout e stderr a questo logger"""
        sys.stdout = self
        sys.stderr = self
    
    def restore_stdout(self):
        """Ripristina stdout e stderr originali"""
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr
    
    def write(self, text):
        """Metodo per compatibilità con sys.stdout"""
        if text.strip():  # Ignora stringhe vuote (es. newline)
            self.info(text.strip())
    
    def flush(self):
        """Metodo per compatibilità con sys.stdout"""
        pass

# Logger globale
global_logger = GUILogger()

def get_logger():
    """Restituisce il logger globale"""
    return global_logger

def set_gui_logger_callback(callback):
    """Imposta il callback GUI per il logger globale"""
    global_logger.set_gui_callback(callback)
