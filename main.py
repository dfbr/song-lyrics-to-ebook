"""Entry point for the Song Lyrics to Ebook application."""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from src.app import LyricsToEbookApp


def main():
    app = LyricsToEbookApp()
    app.mainloop()


if __name__ == "__main__":
    main()
