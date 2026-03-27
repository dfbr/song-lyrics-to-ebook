"""
Lyrics fetching from multiple configurable sources.

Supported sources
-----------------
* lyricsovh  — lyrics.ovh free REST API (no API key required)
* genius     — Genius via the ``lyricsgenius`` library (API token required)
"""
import re
from abc import ABC, abstractmethod

import requests


class LyricsSource(ABC):
    """Abstract base class for a lyrics provider."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable display name for this source."""

    @abstractmethod
    def get_lyrics(self, artist: str, title: str) -> str | None:
        """
        Fetch lyrics for the given song.

        Returns the lyrics as a plain-text string, or ``None`` if not found.
        """


class LyricsOvhSource(LyricsSource):
    """Lyrics from the lyrics.ovh free, unauthenticated REST API."""

    _BASE = "https://api.lyrics.ovh/v1"

    @property
    def name(self) -> str:
        return "Lyrics.ovh"

    def get_lyrics(self, artist: str, title: str) -> str | None:
        try:
            url = f"{self._BASE}/{requests.utils.quote(artist)}/{requests.utils.quote(title)}"
            resp = requests.get(url, timeout=15)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            lyrics = resp.json().get("lyrics", "")
            return lyrics or None
        except (requests.RequestException, ValueError):
            return None


class GeniusSource(LyricsSource):
    """Lyrics from Genius via the ``lyricsgenius`` third-party library."""

    def __init__(self, api_token: str) -> None:
        self._token = api_token
        self._genius = None

    @property
    def name(self) -> str:
        return "Genius"

    def _client(self):
        if self._genius is None:
            try:
                import lyricsgenius  # noqa: PLC0415
            except ImportError as exc:
                raise RuntimeError(
                    "The 'lyricsgenius' package is required for the Genius source. "
                    "Install it with: pip install lyricsgenius"
                ) from exc
            self._genius = lyricsgenius.Genius(
                self._token,
                skip_non_songs=True,
                excluded_terms=["(Remix)", "(Live)"],
                remove_section_headers=False,
                verbose=False,
                timeout=15,
            )
        return self._genius

    def get_lyrics(self, artist: str, title: str) -> str | None:
        if not self._token:
            return None
        try:
            song = self._client().search_song(title, artist)
            return song.lyrics if song else None
        except Exception:  # noqa: BLE001
            return None


def get_lyrics_source(source_name: str, settings: dict) -> LyricsSource:
    """
    Return a :class:`LyricsSource` instance for *source_name*.

    Falls back to :class:`LyricsOvhSource` for unknown names.
    """
    if source_name == "genius":
        return GeniusSource(settings.get("genius_token", ""))
    return LyricsOvhSource()


def clean_lyrics(lyrics: str) -> str:
    """Normalise raw lyrics text for use inside an ebook."""
    if not lyrics:
        return ""

    # Collapse runs of more than two blank lines to a single blank line.
    lines = lyrics.split("\n")
    cleaned: list[str] = []
    blank_run = 0
    for line in lines:
        if line.strip() == "":
            blank_run += 1
            if blank_run <= 1:
                cleaned.append("")
        else:
            blank_run = 0
            cleaned.append(line.rstrip())

    # Strip leading/trailing blank lines and remove common Genius artefacts.
    # Genius prepends headers such as "42 ContributorsAlbum Name Lyrics" before
    # the actual lyrics; this pattern removes that generated header line.
    _GENIUS_HEADER_RE = re.compile(
        r"^\d+\s+Contributors?\s*\n.*?Lyrics\s*\n", re.IGNORECASE
    )
    text = "\n".join(cleaned).strip()
    text = _GENIUS_HEADER_RE.sub("", text)
    return text
