import logging
import sys
import os
from logging.handlers import RotatingFileHandler


def setup_logger(name="QuantBot", level=logging.INFO,
                 log_file=None, max_bytes=10 * 1024 * 1024, backup_count=3):
    """
    Configure a logger with console output and optional file rotation.

    Parameters
    ----------
    name : str
        Logger name.
    level : int
        Logging level (default logging.INFO).
    log_file : str, optional
        Path to a rotating log file. If None, only console handler is added.
    max_bytes : int
        Max size per log file before rotation.
    backup_count : int
        Number of rotated backups to keep.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # already configured

    logger.setLevel(level)

    # ── Console handler ─────────────────────────────────────────────
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    fmt = logging.Formatter('[%(asctime)s] %(levelname)s - %(message)s')
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # ── File handler (rotating) ────────────────────────────────────
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
        fh = RotatingFileHandler(
            log_file, maxBytes=max_bytes, backupCount=backup_count)
        fh.setLevel(level)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger
