# logger.py
import sys
from datetime import datetime

class GUILogger:
    """Custom logger that forwards output to the GUI."""
    
    def __init__(self, gui_callback=None):
        self.gui_callback = gui_callback
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
    
    def set_gui_callback(self, callback):
        """Set the GUI callback for log messages."""
        self.gui_callback = callback
    
    def info(self, message: str):
        """Write an INFO-level log message."""
        self._log(message, "INFO")
    
    def warning(self, message: str):
        """Write a WARNING-level log message."""
        self._log(message, "WARNING")
    
    def error(self, message: str):
        """Write an ERROR-level log message."""
        self._log(message, "ERROR")
    
    def debug(self, message: str):
        """Write a DEBUG-level log message."""
        self._log(message, "DEBUG")
    
    def success(self, message: str):
        """Write a SUCCESS-level log message."""
        self._log(message, "SUCCESS")
    
    def _log(self, message: str, level: str):
        """Internal logging method."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {level}: {message}"
        
        # Send to the GUI when available
        if self.gui_callback:
            try:
                self.gui_callback(message, level)
            except Exception as e:
                # Fall back to stdout if the GUI callback fails
                print(formatted_message, file=self.original_stdout)
        else:
            # Fall back to stdout when no GUI is available
            print(formatted_message, file=self.original_stdout)
    
    def redirect_stdout(self):
        """Redirect stdout and stderr to this logger."""
        sys.stdout = self
        sys.stderr = self
    
    def restore_stdout(self):
        """Restore the original stdout and stderr streams."""
        sys.stdout = self.original_stdout
        sys.stderr = self.original_stderr
    
    def write(self, text):
        """Provide compatibility with sys.stdout."""
        if text.strip():  # Ignore empty strings (e.g. newline characters)
            self.info(text.strip())
    
    def flush(self):
        """Provide compatibility with sys.stdout."""
        pass

# Logger globale
global_logger = GUILogger()

def get_logger():
    """Return the global logger."""
    return global_logger

def set_gui_logger_callback(callback):
    """Set the GUI callback for the global logger."""
    global_logger.set_gui_callback(callback)
