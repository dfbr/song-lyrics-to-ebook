"""Application logging setup helpers."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path.home() / ".config" / "song-lyrics-to-ebook"
LOG_FILE = LOG_DIR / "app.log"


def setup_logging() -> Path:
    """Configure root logging for the application and return log file path."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Avoid duplicate handlers if setup_logging is called more than once.
    for handler in root.handlers:
        if isinstance(handler, RotatingFileHandler):
            if Path(getattr(handler, "baseFilename", "")) == LOG_FILE:
                return LOG_FILE

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(file_handler)

    return LOG_FILE