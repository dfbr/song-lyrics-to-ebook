# song-lyrics-to-ebook

A visual Python application that searches for music artists, browses their albums, downloads song lyrics, and creates polished EPUB ebooks — ready to send to a Kindle or any compatible e-reader.

---

## Features

| Feature | Detail |
|---------|--------|
| **Artist search** | Powered by the free [MusicBrainz](https://musicbrainz.org/) API — no account needed |
| **Album browser** | Lists all albums, EPs, singles, and other releases; filterable by type |
| **Track listing** | Shows every track with its duration |
| **Lyrics download** | Choose between two sources (see *Settings* below) |
| **Album artwork** | Front cover from the [Cover Art Archive](https://coverartarchive.org/) + any additional images (booklet, back cover, …) |
| **EPUB creation** | Cover page → title page → table of contents → one chapter per song (with metadata) |
| **Back catalogue** | One-click combined ebook of an artist's entire discography in chronological order |
| **Kindle & e-reader support** | Saves as EPUB 3 (Kobo, Nook, Apple Books, modern Kindle) or EPUB 2 (older readers) |

---

## Requirements

- Python 3.10 or newer
- `tkinter` (usually bundled with Python; on Debian/Ubuntu: `sudo apt install python3-tk`)

Install Python dependencies:

```bash
pip install -r requirements.txt
```

---

## Usage

```bash
python main.py
```

### Workflow

1. **Search** — type an artist name and press **Search** or **↵**.
2. **Select artist** — click an artist in the left pane; their releases load automatically.
3. **Select release** — use the type filter (All / Album / Single / EP …) then click a release; tracks appear on the right.
4. **Create ebook** — press **Create Album Ebook** to build a single-album EPUB, or **Create Entire Back Catalogue** to build a combined ebook for every release.
5. **Open folder** — a dialog confirms the saved path and offers to open the output folder.

---

## Settings

Open the **Settings** tab to configure:

| Setting | Description |
|---------|-------------|
| **Lyrics source** | `lyricsovh` — free, no key needed; `genius` — higher quality, requires a free API token |
| **Genius API token** | Get one at <https://genius.com/api-clients> (free account) |
| **Output format** | EPUB 3 (recommended) or EPUB 2 (for Calibre conversion to MOBI/AZW3) |
| **Output directory** | Where ebooks are saved (default: `~/Documents/Ebooks`) |
| **Include artwork** | Toggle download of cover art and additional images |

### Sending to Kindle

- **Modern Kindle** (2022+) supports EPUB directly via the *Send to Kindle* app or email.
- For **older Kindle** devices, convert the EPUB to AZW3/MOBI using [Calibre](https://calibre-ebook.com/) (free).

---

## Project structure

```
song-lyrics-to-ebook/
├── main.py               # Entry point
├── requirements.txt
└── src/
    ├── app.py            # tkinter GUI
    ├── settings.py       # JSON-persisted settings
    ├── api/
    │   ├── musicbrainz.py  # Artist / release / track metadata
    │   ├── coverart.py     # Cover Art Archive image download
    │   └── lyrics.py       # Multi-source lyrics (lyrics.ovh, Genius)
    └── ebook/
        └── builder.py      # EPUB builder (single album + full catalogue)
```

---

## Data sources

| Source | Used for | Auth |
|--------|----------|------|
| [MusicBrainz](https://musicbrainz.org/) | Artist search, albums, tracks | None |
| [Cover Art Archive](https://coverartarchive.org/) | Album artwork | None |
| [lyrics.ovh](https://lyricsovh.docs.apiary.io/) | Lyrics (default) | None |
| [Genius](https://genius.com/developers) | Lyrics (optional) | Free API token |

All data sources are free and publicly accessible.

---

## Running tests

```bash
python -m pytest tests/ -v
```
