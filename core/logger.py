"""Rotating application log, bound explicitly to the current runtime log path."""

import logging
from logging.handlers import RotatingFileHandler
import threading
from pathlib import Path
from .runtime_paths import log_file, writable

LOG_FILE = Path("auto_processor_errors.log")
_logger_configured = False
_logger_lock = threading.RLock()


def setup_logging():
    global _logger_configured
    target = log_file()
    with _logger_lock:
        logger = logging.getLogger('emby_auto')
        owned = [handler for handler in logger.handlers if getattr(handler, '_animeman_handler', False)]
        if any(isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) == target for handler in owned):
            return
        # Construct the replacement first; failed setup does not remove the old handler.
        file_handler = RotatingFileHandler(str(writable(target)), maxBytes=10 * 1024 * 1024,
                                           backupCount=1, encoding='utf-8', delay=True)
        file_handler.setLevel(logging.WARNING)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        for handler in owned:
            logger.removeHandler(handler)
            handler.close()
        for handler in (file_handler, console_handler):
            handler._animeman_handler = True
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        _logger_configured = True


def get_logger(name=None):
    setup_logging()
    return logging.getLogger('emby_auto')
