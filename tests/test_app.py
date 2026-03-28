"""
Tests for Song Lyrics to Ebook.

Run with:  python -m pytest tests/ -v
"""
import io
import os
import tempfile
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


# ---------------------------------------------------------------------------
# Settings tests
# ---------------------------------------------------------------------------

class TestSettings:
    def test_defaults(self):
        from src.settings import Settings, DEFAULT_SETTINGS
        s = Settings()
        for key, value in DEFAULT_SETTINGS.items():
            assert s.get(key) == value

    def test_get_set(self):
        from src.settings import Settings
        s = Settings()
        s.set("lyrics_source", "genius")
        assert s.get("lyrics_source") == "genius"

    def test_save_load(self, tmp_path):
        from src.settings import Settings
        s = Settings()
        s._config_file = tmp_path / "settings.json"
        s._config_dir = tmp_path
        s.set("genius_token", "secret123")
        s.save()

        s2 = Settings()
        s2._config_file = tmp_path / "settings.json"
        s2.load()
        assert s2.get("genius_token") == "secret123"

    def test_invalid_json_falls_back_to_defaults(self, tmp_path):
        from src.settings import Settings, DEFAULT_SETTINGS
        cfg = tmp_path / "settings.json"
        cfg.write_text("not valid json")
        s = Settings()
        s._config_file = cfg
        s.load()
        assert s.get("lyrics_source") == DEFAULT_SETTINGS["lyrics_source"]

    def test_item_access(self):
        from src.settings import Settings
        s = Settings()
        s["lyrics_source"] = "genius"
        assert s["lyrics_source"] == "genius"


# ---------------------------------------------------------------------------
# Lyrics helpers tests
# ---------------------------------------------------------------------------

class TestLyricsHelpers:
    def test_clean_lyrics_collapses_blank_lines(self):
        from src.api.lyrics import clean_lyrics
        raw = "Line 1\n\n\n\n\nLine 2"
        result = clean_lyrics(raw)
        assert "\n\n\n" not in result
        assert "Line 1" in result
        assert "Line 2" in result

    def test_clean_lyrics_strips_whitespace(self):
        from src.api.lyrics import clean_lyrics
        assert clean_lyrics("  \n") == ""

    def test_clean_lyrics_preserves_single_blank_line(self):
        from src.api.lyrics import clean_lyrics
        result = clean_lyrics("A\n\nB")
        assert "A" in result and "B" in result

    def test_lyrics_ovh_source_name(self):
        from src.api.lyrics import LyricsOvhSource
        assert LyricsOvhSource().name == "Lyrics.ovh"

    def test_genius_source_name(self):
        from src.api.lyrics import GeniusSource
        assert GeniusSource("token").name == "Genius"

    def test_genius_source_returns_none_without_token(self):
        from src.api.lyrics import GeniusSource
        src = GeniusSource("")
        result = src.get_lyrics("Artist", "Song")
        assert result is None

    def test_get_lyrics_source_ovh(self):
        from src.api.lyrics import get_lyrics_source, LyricsOvhSource
        src = get_lyrics_source("lyricsovh", {})
        assert isinstance(src, LyricsOvhSource)

    def test_get_lyrics_source_genius(self):
        from src.api.lyrics import get_lyrics_source, GeniusSource
        src = get_lyrics_source("genius", {"genius_token": "abc"})
        assert isinstance(src, GeniusSource)

    def test_get_lyrics_source_fallback(self):
        from src.api.lyrics import get_lyrics_source, LyricsOvhSource
        src = get_lyrics_source("unknown_source", {})
        assert isinstance(src, LyricsOvhSource)

    def test_lyrics_ovh_network_error_returns_none(self):
        from src.api.lyrics import LyricsOvhSource
        import requests
        src = LyricsOvhSource()
        with patch("requests.get", side_effect=requests.RequestException("fail")):
            result = src.get_lyrics("Artist", "Song")
        assert result is None

    def test_lyrics_ovh_404_returns_none(self):
        from src.api.lyrics import LyricsOvhSource
        src = LyricsOvhSource()
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("requests.get", return_value=mock_resp):
            result = src.get_lyrics("Artist", "Song")
        assert result is None

    def test_lyrics_ovh_success(self):
        from src.api.lyrics import LyricsOvhSource
        src = LyricsOvhSource()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"lyrics": "Hello world\nSecond line"}
        with patch("requests.get", return_value=mock_resp):
            result = src.get_lyrics("Artist", "Song")
        assert result == "Hello world\nSecond line"


# ---------------------------------------------------------------------------
# Ebook builder helper tests
# ---------------------------------------------------------------------------

class TestEbookBuilderHelpers:
    def test_slugify_basic(self):
        from src.ebook.builder import _slugify
        assert _slugify("The Beatles") == "the-beatles"

    def test_slugify_special_chars(self):
        from src.ebook.builder import _slugify
        result = _slugify("AC/DC & Friends!")
        assert "/" not in result
        assert "&" not in result

    def test_slugify_max_length(self):
        from src.ebook.builder import _slugify
        long_text = "a" * 100
        assert len(_slugify(long_text)) <= 60

    def test_fmt_duration(self):
        from src.ebook.builder import _fmt_duration
        assert _fmt_duration(3 * 60000 + 45 * 1000) == "3:45"
        assert _fmt_duration(0) == ""
        assert _fmt_duration(60000) == "1:00"

    def test_esc_html(self):
        from src.ebook.builder import _esc
        assert _esc("<b>Test & 'Me'</b>") == "&lt;b&gt;Test &amp; 'Me'&lt;/b&gt;"
        assert _esc('"quote"') == "&quot;quote&quot;"

    def test_lyrics_to_html_none(self):
        from src.ebook.builder import _lyrics_to_html
        html = _lyrics_to_html(None)
        assert "no-lyrics" in html

    def test_lyrics_to_html_empty(self):
        from src.ebook.builder import _lyrics_to_html
        html = _lyrics_to_html("")
        assert "no-lyrics" in html

    def test_lyrics_to_html_section_header(self):
        from src.ebook.builder import _lyrics_to_html
        html = _lyrics_to_html("[Verse 1]\nLine one\nLine two")
        assert "section-header" in html

    def test_lyrics_to_html_paragraphs(self):
        from src.ebook.builder import _lyrics_to_html
        html = _lyrics_to_html("Para 1 line 1\nPara 1 line 2\n\nPara 2")
        assert html.count("<p>") >= 2
        assert "<br/>" in html


# ---------------------------------------------------------------------------
# Ebook builder integration tests (no network)
# ---------------------------------------------------------------------------

def _make_jpeg(color=(100, 149, 237), size=(200, 200)) -> bytes:
    """Create a minimal JPEG image for testing.  Default colour is cornflower blue."""
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class TestEbookBuilder:
    def _base_data(self):
        artist_info = {"id": "a1", "name": "Test Artist"}
        release_info = {
            "id": "r1",
            "title": "Test Album",
            "date": "2023-06-01",
            "type": "Album",
            "label": "Test Records",
            "release_group_id": "rg1",
            "first_release_date": "2023",
        }
        tracks = [
            {
                "position": 1,
                "title": "First Song",
                "artist": "Test Artist",
                "length": 180000,
                "disc": 1,
            },
            {
                "position": 2,
                "title": "Second Song",
                "artist": "",
                "length": 240000,
                "disc": 1,
            },
        ]
        lyrics_map = {
            1: "[Verse 1]\nHello world\nThis is a test\n\n[Chorus]\nSing along",
        }
        return artist_info, release_info, tracks, lyrics_map

    def test_build_album_book_creates_file(self, tmp_path):
        from src.ebook.builder import EbookBuilder
        builder = EbookBuilder()
        artist, release, tracks, lyrics = self._base_data()
        path = builder.build_album_book(
            artist_info=artist,
            release_info=release,
            tracks=tracks,
            lyrics_map=lyrics,
            output_dir=str(tmp_path),
        )
        assert os.path.exists(path)
        assert path.endswith(".epub")
        assert os.path.getsize(path) > 1000

    def test_build_album_book_filename_contains_year(self, tmp_path):
        from src.ebook.builder import EbookBuilder
        builder = EbookBuilder()
        artist, release, tracks, lyrics = self._base_data()
        path = builder.build_album_book(
            artist_info=artist,
            release_info=release,
            tracks=tracks,
            lyrics_map=lyrics,
            output_dir=str(tmp_path),
        )
        assert "2023" in os.path.basename(path)

    def test_build_album_book_with_cover_art(self, tmp_path):
        from src.ebook.builder import EbookBuilder
        builder = EbookBuilder()
        artist, release, tracks, lyrics = self._base_data()
        cover = _make_jpeg()
        path = builder.build_album_book(
            artist_info=artist,
            release_info=release,
            tracks=tracks,
            lyrics_map=lyrics,
            cover_image=cover,
            output_dir=str(tmp_path),
        )
        assert os.path.exists(path)
        assert os.path.getsize(path) > 2000  # larger due to image

    def test_build_album_book_with_additional_images(self, tmp_path):
        from src.ebook.builder import EbookBuilder
        builder = EbookBuilder()
        artist, release, tracks, lyrics = self._base_data()
        extra = [(
            _make_jpeg(color=(255, 0, 0)),
            {"types": ["Booklet"], "comment": "Liner notes"},
        )]
        path = builder.build_album_book(
            artist_info=artist,
            release_info=release,
            tracks=tracks,
            lyrics_map=lyrics,
            additional_images=extra,
            output_dir=str(tmp_path),
        )
        assert os.path.exists(path)

    def test_build_album_book_no_lyrics(self, tmp_path):
        from src.ebook.builder import EbookBuilder
        builder = EbookBuilder()
        artist, release, tracks, _ = self._base_data()
        path = builder.build_album_book(
            artist_info=artist,
            release_info=release,
            tracks=tracks,
            lyrics_map={},  # no lyrics
            output_dir=str(tmp_path),
        )
        assert os.path.exists(path)

    def test_build_catalogue_book_creates_file(self, tmp_path):
        from src.ebook.builder import EbookBuilder
        builder = EbookBuilder()
        artist, release, tracks, lyrics = self._base_data()
        albums_data = [
            {
                "release_info": release,
                "tracks": tracks,
                "lyrics_map": lyrics,
                "cover_image": None,
                "additional_images": [],
            }
        ]
        path = builder.build_catalogue_book(
            artist_info=artist,
            albums_data=albums_data,
            output_dir=str(tmp_path),
        )
        assert os.path.exists(path)
        assert "complete-lyrics" in os.path.basename(path)

    def test_build_catalogue_with_cover_images(self, tmp_path):
        from src.ebook.builder import EbookBuilder
        builder = EbookBuilder()
        artist, release, tracks, lyrics = self._base_data()
        albums_data = [
            {
                "release_info": release,
                "tracks": tracks,
                "lyrics_map": lyrics,
                "cover_image": _make_jpeg(),
                "additional_images": [(
                    _make_jpeg(color=(0, 255, 0)),
                    {"types": ["Back"], "comment": ""},
                )],
            }
        ]
        path = builder.build_catalogue_book(
            artist_info=artist,
            albums_data=albums_data,
            output_dir=str(tmp_path),
        )
        assert os.path.exists(path)
        assert os.path.getsize(path) > 3000

    def test_build_catalogue_multiple_albums(self, tmp_path):
        from src.ebook.builder import EbookBuilder
        builder = EbookBuilder()
        artist = {"id": "a1", "name": "Multi Album Artist"}
        albums_data = []
        for i in range(3):
            release = {
                "id": f"r{i}",
                "title": f"Album {i+1}",
                "date": f"200{i}-01-01",
                "type": "Album",
                "label": "",
                "release_group_id": f"rg{i}",
                "first_release_date": f"200{i}",
            }
            tracks = [
                {"position": j+1, "title": f"Track {j+1}", "artist": "",
                 "length": 180000, "disc": 1}
                for j in range(3)
            ]
            albums_data.append({
                "release_info": release,
                "tracks": tracks,
                "lyrics_map": {},
                "cover_image": None,
                "additional_images": [],
            })
        path = builder.build_catalogue_book(
            artist_info=artist,
            albums_data=albums_data,
            output_dir=str(tmp_path),
        )
        assert os.path.exists(path)

    def _read_epub_titlepage(self, path: str) -> str:
        """Return the text content of title_page.xhtml inside the EPUB."""
        import zipfile
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            tp_name = next((n for n in names if "title_page" in n), None)
            assert tp_name is not None, f"title_page.xhtml not found in {names}"
            return z.read(tp_name).decode("utf-8")

    def test_build_album_book_disclaimer_in_titlepage(self, tmp_path):
        from src.ebook.builder import EbookBuilder
        builder = EbookBuilder()
        artist, release, tracks, lyrics = self._base_data()
        path = builder.build_album_book(
            artist_info=artist,
            release_info=release,
            tracks=tracks,
            lyrics_map=lyrics,
            output_dir=str(tmp_path),
        )
        content = self._read_epub_titlepage(path)
        assert "non-commercial" in content
        assert "personal" in content
        assert "copyright" in content

    def test_build_album_book_lyrics_source_default(self, tmp_path):
        from src.ebook.builder import EbookBuilder
        builder = EbookBuilder()
        artist, release, tracks, lyrics = self._base_data()
        path = builder.build_album_book(
            artist_info=artist,
            release_info=release,
            tracks=tracks,
            lyrics_map=lyrics,
            output_dir=str(tmp_path),
        )
        content = self._read_epub_titlepage(path)
        assert "lyrics.ovh" in content

    def test_build_album_book_lyrics_source_genius(self, tmp_path):
        from src.ebook.builder import EbookBuilder
        builder = EbookBuilder()
        artist, release, tracks, lyrics = self._base_data()
        path = builder.build_album_book(
            artist_info=artist,
            release_info=release,
            tracks=tracks,
            lyrics_map=lyrics,
            output_dir=str(tmp_path),
            lyrics_source="Genius",
        )
        content = self._read_epub_titlepage(path)
        assert "Genius" in content

    def test_build_catalogue_book_disclaimer_in_titlepage(self, tmp_path):
        from src.ebook.builder import EbookBuilder
        builder = EbookBuilder()
        artist, release, tracks, lyrics = self._base_data()
        albums_data = [
            {
                "release_info": release,
                "tracks": tracks,
                "lyrics_map": lyrics,
                "cover_image": None,
                "additional_images": [],
            }
        ]
        path = builder.build_catalogue_book(
            artist_info=artist,
            albums_data=albums_data,
            output_dir=str(tmp_path),
            lyrics_source="Genius",
        )
        content = self._read_epub_titlepage(path)
        assert "non-commercial" in content
        assert "Genius" in content


# ---------------------------------------------------------------------------
# Cover Art tests (mocked network)
# ---------------------------------------------------------------------------

class TestCoverArt:
    def test_get_front_cover_success(self):
        from src.api.coverart import get_front_cover
        fake_image = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # fake JPEG header
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = fake_image

        with patch("requests.get", return_value=mock_resp):
            result = get_front_cover("some-release-id")
        assert result == fake_image

    def test_get_front_cover_404_falls_back(self):
        from src.api.coverart import get_front_cover
        import requests as req

        call_count = 0

        def mock_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "front-500" in url:
                raise req.RequestException("not found")
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = b"fallback-image"
            return mock_resp

        with patch("requests.get", side_effect=mock_get):
            result = get_front_cover("release-id")
        assert result == b"fallback-image"
        assert call_count == 2

    def test_get_front_cover_all_fail(self):
        from src.api.coverart import get_front_cover
        import requests as req
        with patch("requests.get", side_effect=req.RequestException("fail")):
            result = get_front_cover("release-id")
        assert result is None

    def test_get_release_images_success(self):
        from src.api.coverart import get_release_images
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "images": [
                {
                    "id": "123",
                    "types": ["Front"],
                    "front": True,
                    "back": False,
                    "comment": "",
                    "image": "https://example.com/img.jpg",
                    "thumbnails": {},
                }
            ]
        }
        with patch("requests.get", return_value=mock_resp):
            images = get_release_images("some-id")
        assert len(images) == 1
        assert images[0]["front"] is True

    def test_get_release_images_404(self):
        from src.api.coverart import get_release_images
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("requests.get", return_value=mock_resp):
            images = get_release_images("missing-id")
        assert images == []
