"""
EPUB ebook builder.

Supports two modes:
* :meth:`EbookBuilder.build_album_book`  — single album / release
* :meth:`EbookBuilder.build_catalogue_book` — artist's entire back catalogue
"""
import hashlib
import io
import os
import re
from pathlib import Path
from typing import Optional

from ebooklib import epub
from PIL import Image


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    """Return a filesystem-safe slug from *text* (max 60 characters)."""
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[-\s]+", "-", text)
    return text.strip("-")[:60]


def _fmt_duration(ms: int) -> str:
    """Convert milliseconds to a ``M:SS`` string."""
    if not ms:
        return ""
    secs = ms // 1000
    return f"{secs // 60}:{secs % 60:02d}"


def _esc(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _lyrics_to_html(lyrics: str | None) -> str:
    """Convert plain-text lyrics to basic HTML paragraphs."""
    if not lyrics or not lyrics.strip():
        return '<p class="no-lyrics"><em>Lyrics not available</em></p>'

    _HEADER_RE = re.compile(r"^\[.*\]$")

    html: list[str] = []
    for para in re.split(r"\n\n+", lyrics):
        para = para.strip()
        if not para:
            continue
        lines = para.split("\n")
        # Each line is checked: lines matching [Header] become section headers,
        # other lines are grouped into <p> elements.
        pending: list[str] = []
        for line in lines:
            stripped = line.strip()
            if _HEADER_RE.match(stripped):
                # Flush any buffered lyric lines first
                if pending:
                    html.append(f'<p>{"<br/>".join(_esc(ln) for ln in pending)}</p>')
                    pending = []
                html.append(
                    f'<p class="section-header"><em>{_esc(stripped)}</em></p>'
                )
            else:
                pending.append(line)
        if pending:
            html.append(f'<p>{"<br/>".join(_esc(ln) for ln in pending)}</p>')
    return "\n".join(html)


def _cover_density_class(artist_name: str, album_title: str) -> str:
    """Return a CSS class that scales cover typography for long text."""
    total_len = len((artist_name or "").strip()) + len((album_title or "").strip())
    longest_word = max(
        [len(w) for w in f"{artist_name} {album_title}".split()] or [0]
    )

    if total_len > 92 or longest_word > 24:
        return "cover-density-tight"
    if total_len > 68 or longest_word > 18:
        return "cover-density-compact"
    return "cover-density-normal"


def _process_image(raw: bytes, max_size: tuple[int, int] = (800, 800)) -> bytes:
    """Resize *raw* image bytes if needed and normalise to JPEG."""
    try:
        img = Image.open(io.BytesIO(raw))
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.thumbnail(max_size, Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        # Return the original bytes as a fallback so the ebook can still be
        # built even if the image cannot be resized or converted.  The raw
        # bytes may be in a format the reader can display directly.
        return raw


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_CSS = """\
body {
    font-family: Georgia, "Times New Roman", serif;
    margin: 1.5em 2em;
    line-height: 1.65;
    color: #111;
}
h1 { font-size: 1.8em; margin: 0 0 0.3em 0; }
h2 { font-size: 1.35em; color: #333; margin-top: 1.8em; }
h3 { font-size: 1.1em; color: #555; }
.cover-page {
    min-height: 100vh;
    box-sizing: border-box;
    padding: 7vh 8vw 4vh;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    gap: 3vh;
    background: #f7f6f2;
    color: #1d1d1d;
    text-align: center;
    page-break-after: always;
}
.cover-top {
    margin: 0 auto;
    width: 100%;
    max-width: 38em;
}
.cover-artist,
.cover-album,
.cover-year {
    font-family: "Avenir Next", "Helvetica Neue", Helvetica, Arial, sans-serif;
    margin: 0;
    hyphens: none;
    word-break: normal;
    overflow-wrap: normal;
}
.cover-artist {
    text-transform: uppercase;
    letter-spacing: 0.18em;
    color: #565656;
    font-size: 0.95rem;
    margin-bottom: 0.8rem;
}
.cover-album {
    line-height: 1.1;
    margin-bottom: 0.7rem;
    color: #121212;
    font-size: 2.2rem;
    font-weight: 700;
}
.cover-year {
    letter-spacing: 0.08em;
    color: #6a6a6a;
    font-size: 1rem;
}
.cover-bottom {
    flex: 1 1 auto;
    display: flex;
    justify-content: center;
    align-items: flex-end;
}
.cover-image {
    max-width: 75vw;
    max-height: 52vh;
    width: auto;
    height: auto;
    object-fit: contain;
    box-shadow: 0 1.2rem 2.6rem rgba(0, 0, 0, 0.2);
}
.cover-density-compact .cover-album { font-size: 1.9rem; }
.cover-density-compact .cover-artist,
.cover-density-compact .cover-year { font-size: 0.9rem; }
.cover-density-tight .cover-album { font-size: 1.62rem; line-height: 1.08; }
.cover-density-tight .cover-artist,
.cover-density-tight .cover-year { font-size: 0.82rem; }
.title-page { text-align: center; padding-top: 4em; }
.metadata {
    color: #555;
    font-size: 0.88em;
    margin: 0.5em 0 1.5em 0;
    border-left: 3px solid #ccc;
    padding-left: 0.8em;
    line-height: 1.8;
}
.lyrics p { margin: 0.25em 0; text-indent: 0; }
.section-header { color: #444; font-weight: bold; margin-top: 1em; }
.no-lyrics { color: #999; font-style: italic; }
.artwork { text-align: center; margin: 1.2em 0; }
.artwork img { max-width: 100%; }
.artwork .caption { font-size: 0.85em; color: #777; margin-top: 0.3em; }
.disclaimer {
    font-size: 0.78em;
    color: #888;
    margin-top: 2.5em;
    border-top: 1px solid #ddd;
    padding-top: 1em;
}
"""

_DEFAULT_LYRICS_SOURCE = "lyrics.ovh"

# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class EbookBuilder:
    """Constructs EPUB ebooks from album metadata, lyrics, and artwork."""

    def __init__(self, output_format: str = "epub") -> None:
        # Currently EPUB is the primary format; output_format is reserved for
        # future format variants (e.g. epub2 spine/manifest differences).
        self.output_format = output_format

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def build_album_book(
        self,
        artist_info: dict,
        release_info: dict,
        tracks: list[dict],
        lyrics_map: dict[int, str],
        cover_image: Optional[bytes] = None,
        additional_images: Optional[list[tuple[bytes, dict]]] = None,
        output_dir: Optional[str] = None,
        lyrics_source: Optional[str] = None,
    ) -> str:
        """
        Build an EPUB for a single album / release.

        Parameters
        ----------
        artist_info:        dict with at least ``name`` and ``id``.
        release_info:       dict as returned by ``musicbrainz.get_release_tracks``.
        tracks:             list of track dicts (position, title, artist, length …).
        lyrics_map:         mapping of track ``position`` → cleaned lyrics string.
        cover_image:        raw front-cover image bytes (optional).
        additional_images:  list of (raw_bytes, metadata_dict) for extra artwork.
        output_dir:         directory to save the ``.epub`` file.

        Returns the absolute path of the created file.
        """
        book = epub.EpubBook()

        artist_name: str = artist_info.get("name", "Unknown Artist")
        album_title: str = release_info.get("title", "Unknown Album")
        year: str = (
            release_info.get("date") or release_info.get("first_release_date") or ""
        )[:4]
        album_type: str = release_info.get("type", "Album")
        label: str = release_info.get("label", "")

        book_id = hashlib.md5(f"{artist_name}-{album_title}".encode()).hexdigest()
        book.set_identifier(f"lyric-ebook-{book_id}")
        book.set_title(f"{album_title} — {artist_name}")
        book.set_language("en")
        book.add_author(artist_name)
        if year:
            book.add_metadata("DC", "date", year)
        book.add_metadata(
            "DC",
            "description",
            f"Lyrics from {album_type}: {album_title} by {artist_name}",
        )

        css_item = epub.EpubItem(
            uid="style",
            file_name="style.css",
            media_type="text/css",
            content=_CSS.encode("utf-8"),
        )
        book.add_item(css_item)

        spine: list = ["nav"]
        toc: list = []

        # ------ Cover page -----------------------------------------------
        cover_density = _cover_density_class(artist_name, album_title)
        year_html = f'<p class="cover-year">{_esc(year)}</p>' if year else ""
        if cover_image:
            cover_data = _process_image(cover_image)
            book.set_cover("cover.jpg", cover_data)
            cover_page = self._make_html(
                "cover_page.xhtml",
                "Cover",
                f'<div class="cover-page {cover_density}">'
                '<div class="cover-top">'
                f'<p class="cover-artist">{_esc(artist_name)}</p>'
                f'<h1 class="cover-album">{_esc(album_title)}</h1>'
                f"{year_html}"
                "</div>"
                '<div class="cover-bottom">'
                '<img class="cover-image" src="cover.jpg" alt="Album Cover"/>'
                "</div>"
                "</div>",
            )
            book.add_item(cover_page)
            spine.append(cover_page)
        else:
            cover_page = self._make_html(
                "cover_page.xhtml",
                "Cover",
                f'<div class="cover-page {cover_density}">'
                '<div class="cover-top">'
                f'<p class="cover-artist">{_esc(artist_name)}</p>'
                f'<h1 class="cover-album">{_esc(album_title)}</h1>'
                f"{year_html}"
                "</div>"
                '<div class="cover-bottom"></div>'
                "</div>",
            )
            book.add_item(cover_page)
            spine.append(cover_page)

        # ------ Title page -----------------------------------------------
        title_lines = [
            f'<h1>{_esc(album_title)}</h1>',
            f'<h2>{_esc(artist_name)}</h2>',
        ]
        if year:
            title_lines.append(f"<p>{year}</p>")
        if album_type:
            title_lines.append(f"<p>{_esc(album_type)}</p>")
        if label:
            title_lines.append(f"<p>{_esc(label)}</p>")

        source_label = _esc(lyrics_source) if lyrics_source else _DEFAULT_LYRICS_SOURCE
        title_lines.append(
            f'<p class="disclaimer">'
            f"Lyrics sourced via {source_label} and MusicBrainz. "
            f"Generated by Song Lyrics to Ebook.<br/>"
            f"This ebook is for personal, educational and non-commercial use only. "
            f"Lyrics are the copyright of their respective owners and artists. "
            f"Do not distribute or publish this ebook."
            f"</p>"
        )

        title_page = self._make_html(
            "title_page.xhtml",
            "Title Page",
            f'<div class="title-page">{"".join(title_lines)}</div>',
        )
        book.add_item(title_page)
        spine.append(title_page)
        toc.append(epub.Link("title_page.xhtml", "Title Page", "title"))

        # ------ Track chapters -------------------------------------------
        for track in tracks:
            chapter = self._make_track_chapter(
                track, artist_name, album_title, year, lyrics_map, prefix=""
            )
            book.add_item(chapter)
            spine.append(chapter)
            toc.append(
                epub.Link(
                    chapter.file_name,
                    track.get("title", f"Track {track.get('position', 0)}"),
                    chapter.file_name.replace(".xhtml", ""),
                )
            )

        # ------ Additional artwork ---------------------------------------
        if additional_images:
            extra_page = self._make_additional_artwork_page(
                book, additional_images, file_prefix=""
            )
            if extra_page:
                book.add_item(extra_page)
                spine.append(extra_page)
                toc.append(
                    epub.Link("additional_artwork.xhtml", "Additional Artwork", "artwork")
                )

        book.toc = tuple(toc)
        book.spine = spine
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        output_path = self._output_path(output_dir, year, artist_name, album_title)
        epub.write_epub(output_path, book, {})
        return output_path

    def build_catalogue_book(
        self,
        artist_info: dict,
        albums_data: list[dict],
        output_dir: Optional[str] = None,
        lyrics_source: Optional[str] = None,
    ) -> str:
        """
        Build a combined EPUB for an artist's entire back catalogue.

        *albums_data* is a list of dicts, each containing:
            release_info, tracks, lyrics_map, cover_image, additional_images.

        Albums are presented in the order supplied (caller should sort
        chronologically).  Returns the absolute path of the created file.
        """
        book = epub.EpubBook()
        artist_name: str = artist_info.get("name", "Unknown Artist")

        book_id = hashlib.md5(f"{artist_name}-catalogue".encode()).hexdigest()
        book.set_identifier(f"lyric-catalogue-{book_id}")
        book.set_title(f"Complete Lyrics — {artist_name}")
        book.set_language("en")
        book.add_author(artist_name)
        book.add_metadata(
            "DC", "description", f"Complete lyrics catalogue for {artist_name}"
        )

        css_item = epub.EpubItem(
            uid="style",
            file_name="style.css",
            media_type="text/css",
            content=_CSS.encode("utf-8"),
        )
        book.add_item(css_item)

        spine: list = ["nav"]
        toc: list = []

        # Use the first available album cover as the book cover
        for album_data in albums_data:
            if album_data.get("cover_image"):
                book.set_cover(
                    "cover.jpg", _process_image(album_data["cover_image"])
                )
                break

        # ------ Catalogue title page -------------------------------------
        source_label = _esc(lyrics_source) if lyrics_source else _DEFAULT_LYRICS_SOURCE
        disclaimer_html = (
            f'<p class="disclaimer">'
            f"Lyrics sourced via {source_label} and MusicBrainz. "
            f"Generated by Song Lyrics to Ebook.<br/>"
            f"This ebook is for personal, educational and non-commercial use only. "
            f"Lyrics are the copyright of their respective owners and artists. "
            f"Do not distribute or publish this ebook."
            f"</p>"
        )
        title_page = self._make_html(
            "title_page.xhtml",
            "Title Page",
            f'<div class="title-page">'
            f"<h1>Complete Lyrics</h1>"
            f"<h2>{_esc(artist_name)}</h2>"
            f"{disclaimer_html}"
            f"</div>",
        )
        book.add_item(title_page)
        spine.append(title_page)
        toc.append(epub.Link("title_page.xhtml", "Title Page", "title"))

        # ------ One section per album ------------------------------------
        for album_idx, album_data in enumerate(albums_data):
            release_info = album_data["release_info"]
            tracks: list[dict] = album_data["tracks"]
            lyrics_map: dict[int, str] = album_data["lyrics_map"]
            cover_image = album_data.get("cover_image")
            additional_images = album_data.get("additional_images", [])

            album_title: str = release_info.get("title", "Unknown Album")
            year: str = (
                release_info.get("date") or release_info.get("first_release_date") or ""
            )[:4]
            album_type: str = release_info.get("type", "Album")
            prefix = f"album{album_idx:02d}_"

            # Album section header page
            cover_html = ""
            if cover_image:
                img_fn = f"{prefix}cover.jpg"
                img_item = epub.EpubImage(
                    uid=f"cover-{album_idx}",
                    file_name=img_fn,
                    media_type="image/jpeg",
                    content=_process_image(cover_image),
                )
                book.add_item(img_item)
                cover_html = (
                    f'<div class="artwork">'
                    f'<img src="{img_fn}" alt="Album Cover"/>'
                    f"</div>"
                )

            meta_html = (
                f'<strong>Artist:</strong> {_esc(artist_name)}<br/>'
                + (f"<strong>Year:</strong> {year}<br/>" if year else "")
                + f'<strong>Type:</strong> {_esc(album_type)}'
            )
            album_header = self._make_html(
                f"{prefix}header.xhtml",
                f"{album_title} ({year})" if year else album_title,
                f"{cover_html}"
                f"<h1>{_esc(album_title)}</h1>"
                f'<div class="metadata">{meta_html}</div>',
            )
            book.add_item(album_header)
            spine.append(album_header)

            album_section = epub.Section(f"{album_title} ({year})" if year else album_title)
            album_track_links: list = []

            for track in tracks:
                chapter = self._make_track_chapter(
                    track, artist_name, album_title, year, lyrics_map, prefix=prefix
                )
                book.add_item(chapter)
                spine.append(chapter)
                album_track_links.append(
                    epub.Link(
                        chapter.file_name,
                        track.get("title", f"Track {track.get('position', 0)}"),
                        chapter.file_name.replace(".xhtml", ""),
                    )
                )

            if additional_images:
                extra_page = self._make_additional_artwork_page(
                    book,
                    additional_images,
                    file_prefix=prefix,
                )
                if extra_page:
                    book.add_item(extra_page)
                    spine.append(extra_page)
                    album_track_links.append(
                        epub.Link(
                            extra_page.file_name,
                            "Additional Artwork",
                            extra_page.file_name.replace(".xhtml", ""),
                        )
                    )

            toc.append((album_section, album_track_links))

        book.toc = tuple(toc)
        book.spine = spine
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())

        output_path = self._output_path(
            output_dir, "", artist_name, "complete-lyrics"
        )
        epub.write_epub(output_path, book, {})
        return output_path

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_html(file_name: str, title: str, body_html: str) -> epub.EpubHtml:
        """Wrap *body_html* in a minimal XHTML document."""
        item = epub.EpubHtml(title=title, file_name=file_name, lang="en")
        item.content = (
            "<?xml version='1.0' encoding='utf-8'?>"
            '<html xmlns="http://www.w3.org/1999/xhtml">'
            f"<head><title>{_esc(title)}</title>"
            '<link rel="stylesheet" href="style.css"/>'
            "</head>"
            f"<body>{body_html}</body>"
            "</html>"
        ).encode("utf-8")
        item.add_link(href="style.css", rel="stylesheet", type="text/css")
        return item

    def _make_track_chapter(
        self,
        track: dict,
        artist_name: str,
        album_title: str,
        year: str,
        lyrics_map: dict[int, str],
        prefix: str,
    ) -> epub.EpubHtml:
        """Build the XHTML chapter for a single track."""
        track_title: str = track.get("title", "Unknown")
        track_artist: str = track.get("artist") or artist_name
        track_num: int = track.get("position", 0)
        duration: str = _fmt_duration(track.get("length", 0))

        lyrics = lyrics_map.get(track_num)
        lyrics_html = _lyrics_to_html(lyrics)

        meta_parts: list[str] = []
        if track_artist and track_artist != artist_name:
            meta_parts.append(f"<strong>Artist:</strong> {_esc(track_artist)}")
        meta_parts.append(f"<strong>Album:</strong> {_esc(album_title)}")
        if year:
            meta_parts.append(f"<strong>Year:</strong> {year}")
        meta_parts.append(f"<strong>Track:</strong> {track_num}")
        if duration:
            meta_parts.append(f"<strong>Duration:</strong> {duration}")

        body = (
            f"<h1>{_esc(track_title)}</h1>"
            f'<div class="metadata">{"<br/>".join(meta_parts)}</div>'
            f'<div class="lyrics">{lyrics_html}</div>'
        )
        chapter_id = f"{prefix}track{track_num:03d}"
        return self._make_html(f"{chapter_id}.xhtml", track_title, body)

    @staticmethod
    def _make_additional_artwork_page(
        book: epub.EpubBook,
        images: list[tuple[bytes, dict]],
        file_prefix: str,
    ) -> epub.EpubHtml | None:
        """
        Add extra artwork images to *book* and return an HTML page listing them.
        Returns ``None`` if *images* is empty.
        """
        if not images:
            return None

        html_parts: list[str] = []
        for idx, (img_data, img_meta) in enumerate(images):
            img_fn = f"{file_prefix}extra{idx:03d}.jpg"
            processed = _process_image(img_data)
            img_item = epub.EpubImage(
                uid=f"{file_prefix}extra-img-{idx}",
                file_name=img_fn,
                media_type="image/jpeg",
                content=processed,
            )
            book.add_item(img_item)
            caption = img_meta.get("comment", "") or ", ".join(img_meta.get("types", []))
            caption_html = (
                f'<p class="caption">{_esc(caption)}</p>' if caption else ""
            )
            html_parts.append(
                f'<div class="artwork">'
                f'<img src="{img_fn}" alt="{_esc(caption)}"/>'
                f"{caption_html}"
                f"</div>"
            )

        page_fn = f"{file_prefix}additional_artwork.xhtml"
        item = epub.EpubHtml(title="Additional Artwork", file_name=page_fn, lang="en")
        item.content = (
            "<?xml version='1.0' encoding='utf-8'?>"
            '<html xmlns="http://www.w3.org/1999/xhtml">'
            '<head><title>Additional Artwork</title>'
            '<link rel="stylesheet" href="style.css"/></head>'
            "<body>"
            "<h1>Additional Artwork</h1>"
            + "".join(html_parts)
            + "</body></html>"
        ).encode("utf-8")
        item.add_link(href="style.css", rel="stylesheet", type="text/css")
        return item

    @staticmethod
    def _output_path(
        output_dir: str | None,
        year: str,
        artist_name: str,
        album_title: str,
    ) -> str:
        """Return the full path for the output ``.epub`` file."""
        if not output_dir:
            output_dir = str(Path.home() / "Documents" / "Ebooks")
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        slug_artist = _slugify(artist_name)
        slug_album = _slugify(album_title)
        filename = f"{slug_artist}-{slug_album}.epub"
        if year:
            filename = f"{year}-{filename}"
        return os.path.join(output_dir, filename)
