"""Application settings management."""
import json
from pathlib import Path

DEFAULT_SETTINGS = {
    "lyrics_source": "lyricsovh",
    "genius_token": "",
    "output_format": "epub",
    "output_dir": str(Path.home() / "Documents" / "Ebooks"),
    "include_artwork": True,
}

LYRICS_SOURCES = {
    "lyricsovh": "Lyrics.ovh (Free, no API key required)",
    "genius": "Genius (Requires API token — higher quality)",
}

OUTPUT_FORMATS = {
    "epub": "EPUB 3 — Kobo, Nook, Apple Books, modern Kindle (recommended)",
    "epub2": "EPUB 2 — Older e-readers, compatible with Calibre for MOBI/AZW3 conversion",
}


class Settings:
    """Manages application settings with JSON persistence."""

    def __init__(self):
        self._config_dir = Path.home() / ".config" / "song-lyrics-to-ebook"
        self._config_file = self._config_dir / "settings.json"
        self._data: dict = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> None:
        """Load settings from disk, falling back to defaults on error."""
        try:
            if self._config_file.exists():
                with open(self._config_file, "r", encoding="utf-8") as fh:
                    saved = json.load(fh)
                    self._data.update(saved)
        except (json.JSONDecodeError, OSError):
            pass

    def save(self) -> None:
        """Persist settings to disk."""
        try:
            self._config_dir.mkdir(parents=True, exist_ok=True)
            with open(self._config_file, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)
        except OSError as exc:
            raise RuntimeError(f"Could not save settings: {exc}") from exc

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value

    def __getitem__(self, key: str):
        return self._data[key]

    def __setitem__(self, key: str, value) -> None:
        self._data[key] = value
