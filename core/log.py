"""Logging and Houdini message helpers"""
import logging
import sys

import hou

LOGGER_NAME = "DinoWrite"

class _HoudiniConsoleHandler(logging.Handler):
    """Writes to the current sys.stdout on every record.

    Houdini swaps sys.stdout for its Python Shell / console, so a StreamHandler
    bound to the stream at creation time may print to the wrong place.
    """
    def emit(self, record):
        try:
            print(self.format(record), file=sys.stdout)
        except Exception:
            self.handleError(record)

def getLogger() -> logging.Logger:
    """Package logger with exactly one DinoWrite handler.

    Reloading this module defines a new handler class, so an isinstance() check misses the
    handler added before the reload and messages get printed twice, three times...
    Handlers are marked with an attribute instead, old ones are replaced.
    """
    logger = logging.getLogger(LOGGER_NAME)
    for old in [h for h in logger.handlers if getattr(h, "dinowrite", False)]:
        logger.removeHandler(old)
    handler = _HoudiniConsoleHandler()
    handler.dinowrite = True
    handler.setFormatter(logging.Formatter("[%(name)s] %(levelname)s: %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger

log = getLogger()

def hmsg(message:str,buttons=("Sorry,Dino!",),level="message") -> None:
    """Houdini message window 

    Args:
        message (str): Message to display
        buttons (tuple, optional): Buttons to provide to user. Defaults to ("Sorry,Dino!",).
        level (str, optional): Importance level of message. Defaults to "message" , available "warning" and "error".
    """
    levels = {
        "message": hou.severityType.Message,
        "warning": hou.severityType.Warning,
        "error": hou.severityType.Error
    }

    if message:
        hou.ui.displayMessage(message,buttons=buttons,severity=levels[level],title="DinoWrite say")
    else:
        log.warning("No message set in hsmg function")
