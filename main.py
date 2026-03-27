"""Entry point for the Song Lyrics to Ebook application."""
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from src.logging_setup import setup_logging


def _print_tkinter_help(exc: ModuleNotFoundError) -> None:
    """Print actionable guidance when tkinter support is missing."""
    print("Error: tkinter is not available in this Python environment.", file=sys.stderr)
    print(f"Details: {exc}", file=sys.stderr)
    print("", file=sys.stderr)
    print("macOS options:", file=sys.stderr)
    print("  1) Install Tk support for Homebrew Python:", file=sys.stderr)
    print("     brew install python-tk@3.14", file=sys.stderr)
    print("  2) Or use a Python build that bundles tkinter (python.org installer).", file=sys.stderr)
    print("", file=sys.stderr)
    print("Then re-run: python main.py", file=sys.stderr)


def main():
    log_path = setup_logging()
    logger = logging.getLogger(__name__)

    try:
        from src.app import LyricsToEbookApp
    except ModuleNotFoundError as exc:
        if exc.name == "_tkinter":
            logger.exception("Application startup failed because tkinter is unavailable")
            _print_tkinter_help(exc)
            print(f"See logs: {log_path}", file=sys.stderr)
            sys.exit(1)
        raise

    logger.info("Application starting")
    app = LyricsToEbookApp()
    app.mainloop()


if __name__ == "__main__":
    main()
