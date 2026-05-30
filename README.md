# song-lyrics-to-ebook

A tool for searching music artists, browsing their albums, downloading song lyrics, and creating polished EPUB ebooks — ready to send to a Kindle or any compatible e-reader.

Available in two forms:

- **Web app** (GitHub Pages) — runs entirely in your browser, no installation needed → [`docs/`](docs/)
- **Desktop app** (Python + tkinter) — full-featured local application with back-catalogue support

---

## Features

| Feature | Web app | Desktop app |
|---------|:-------:|:-----------:|
| **Artist search** (MusicBrainz) | ✓ | ✓ |
| **Album browser** with type filter | ✓ | ✓ |
| **Track listing** with durations | ✓ | ✓ |
| **Lyrics download** (lyrics.ovh) | ✓ | ✓ |
| **Genius lyrics** (with API token) | ✓ | ✓ |
| **Album artwork** (Cover Art Archive) | ✓ | ✓ |
| **EPUB creation** (cover → title → TOC → songs) | ✓ | ✓ |
| **Back catalogue** (entire discography in one ebook) | — | ✓ |
| **EPUB 2 / EPUB 3 format choice** | — | ✓ |
| **Configurable output directory** | — | ✓ |
| No installation needed | ✓ | — |

---

## Web app

The `docs/` folder contains a static client-side web app that can be hosted on [GitHub Pages](https://pages.github.com/) or any static file host.

### Workflow

1. **Search** — choose **Artist** or **Album** mode, enter a query, then press **Search** or ↵.
2. **Select result** — in Artist mode, choose an artist to load releases; in Album mode, choose an album result to load tracks directly.
3. **Select release** — for Artist mode, use the type filter, then click an album; tracks appear on the right.
4. **Create ebook** — press **⬇ Create Album Ebook**; lyrics are fetched and the EPUB is generated and downloaded entirely in your browser.

### Settings (web)

| Setting | Description |
|---------|-------------|
| **Genius API token** | Optional. Without a token, lyrics.ovh is used (free, no key). A Genius token gives better coverage — get one free at [genius.com/api-clients](https://genius.com/api-clients). |
| **Include artwork** | Toggle download of the album's front cover. |

---

## Requirements

- Python 3.10 or newer
- `tkinter` (usually bundled with Python; on Debian/Ubuntu: `sudo apt install python3-tk`)

### macOS note (Homebrew Python)

If you see `ModuleNotFoundError: No module named '_tkinter'`, your Python build does not include Tk.

Install Tk support for your Homebrew Python version:

```bash
brew install python-tk@3.14
```

Then run the app again.

### Logging

Runtime errors are written to:

`~/.config/song-lyrics-to-ebook/app.log`

The log file rotates automatically (`app.log`, `app.log.1`, `app.log.2`, ...).

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

1. **Search** — choose **Artist** or **Album** mode, enter a query, then press **Search** or **↵**.
2. **Select result** — in Artist mode, click an artist in the left pane; in Album mode, click an album result to load tracks directly.
3. **Select release** — in Artist mode, use the type filter (All / Album / Single / EP …) then click a release; tracks appear on the right.
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
├── docs/                 # Static web app (GitHub Pages)
│   ├── index.html
│   ├── css/style.css
│   └── js/
│       ├── api.js          # MusicBrainz / Cover Art / lyrics.ovh wrappers
│       ├── epub.js         # Client-side EPUB 3 builder (uses JSZip)
│       └── app.js          # UI controller
├── main.py               # Desktop app entry point
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
