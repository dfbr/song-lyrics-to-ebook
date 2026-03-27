"""
Main tkinter GUI application for Song Lyrics to Ebook.

Layout
------
The window contains a two-tab Notebook:

Tab 1 — Create Ebook
    [Search bar]
    [Artists list] | [Release groups list + type filter] | [Track list]
    [Create Album Ebook]  [Create Entire Back Catalogue]
    [Progress bar + status label]

Tab 2 — Settings
    Lyrics source, API keys, output format, output directory, artwork toggle.
"""
import logging
import io
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Optional

from PIL import Image, ImageTk

from .settings import LYRICS_SOURCES, OUTPUT_FORMATS, Settings
from .api import musicbrainz as mb
from .api import coverart as ca
from .api.lyrics import clean_lyrics, get_lyrics_source
from .ebook.builder import EbookBuilder

logger = logging.getLogger(__name__)

# Size (pixels) for the album art thumbnail shown in the track panel
_ART_SIZE = 140


def _make_placeholder_image(size: int = _ART_SIZE) -> ImageTk.PhotoImage:
    """Return a grey square PhotoImage used as the album art placeholder."""
    img = Image.new("RGB", (size, size), color=(228, 232, 238))
    return ImageTk.PhotoImage(img)


def _bytes_to_photo(data: bytes, size: int = _ART_SIZE) -> ImageTk.PhotoImage:
    """Convert raw image bytes to a square PhotoImage scaled to *size* pixels."""
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((size, size), Image.LANCZOS)
    # Pad to exact square so the label size stays constant
    square = Image.new("RGB", (size, size), color=(228, 232, 238))
    offset = ((size - img.width) // 2, (size - img.height) // 2)
    square.paste(img, offset)
    return ImageTk.PhotoImage(square)


class LyricsToEbookApp(tk.Tk):
    """Root application window."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Song Lyrics to Ebook")
        self.geometry("1050x720")
        self.minsize(820, 580)

        self.settings = Settings()
        self._queue: queue.Queue = queue.Queue()

        # State
        self._artists: list[dict] = []
        self._release_groups: list[dict] = []
        self._selected_artist: Optional[dict] = None
        self._selected_release_group: Optional[dict] = None
        self._current_release_data: Optional[dict] = None
        # Keep a reference to the current album art PhotoImage to prevent GC
        self._art_photo: Optional[ImageTk.PhotoImage] = None

        self._setup_style()
        self._build_ui()
        self._poll_queue()

    # ------------------------------------------------------------------
    # Style / theme
    # ------------------------------------------------------------------

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        for theme in ("clam", "alt", "default"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break
        style.configure("TNotebook.Tab", padding=(12, 6))
        style.configure("Header.TLabel", font=("TkDefaultFont", 13, "bold"))
        style.configure("Status.TLabel", foreground="#555555")
        style.configure(
            "Action.TButton", padding=(10, 5), font=("TkDefaultFont", 10, "bold")
        )

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        main_frame = ttk.Frame(notebook)
        notebook.add(main_frame, text="  Create Ebook  ")
        self._build_main_tab(main_frame)

        settings_frame = ttk.Frame(notebook)
        notebook.add(settings_frame, text="  Settings  ")
        self._build_settings_tab(settings_frame)

    # ---- Main tab -------------------------------------------------------

    def _build_main_tab(self, parent: ttk.Frame) -> None:
        # Search bar
        search_outer = ttk.LabelFrame(parent, text="Artist Search", padding=8)
        search_outer.pack(fill=tk.X, padx=8, pady=(8, 4))

        ttk.Label(search_outer, text="Artist name:").pack(side=tk.LEFT, padx=(0, 6))
        self._search_var = tk.StringVar()
        self._search_entry = ttk.Entry(
            search_outer, textvariable=self._search_var, width=38
        )
        self._search_entry.pack(side=tk.LEFT, padx=(0, 6))
        self._search_entry.bind("<Return>", lambda _e: self._do_search())

        self._search_btn = ttk.Button(
            search_outer, text="Search", command=self._do_search
        )
        self._search_btn.pack(side=tk.LEFT, padx=(0, 8))

        self._status_var = tk.StringVar(
            value="Enter an artist name and press Search or ↵"
        )
        ttk.Label(
            search_outer, textvariable=self._status_var, style="Status.TLabel"
        ).pack(side=tk.LEFT, padx=4)

        # Three-column content area
        content = ttk.Frame(parent)
        content.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        content.columnconfigure(0, weight=2)
        content.columnconfigure(1, weight=3)
        content.columnconfigure(2, weight=2)
        content.rowconfigure(0, weight=1)

        # --- Artist list ---
        artist_frame = ttk.LabelFrame(content, text="Artists", padding=4)
        artist_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._artist_lb = tk.Listbox(artist_frame, selectmode=tk.SINGLE, exportselection=False)
        a_scroll = ttk.Scrollbar(artist_frame, orient=tk.VERTICAL, command=self._artist_lb.yview)
        self._artist_lb.configure(yscrollcommand=a_scroll.set)
        self._artist_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        a_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._artist_lb.bind("<<ListboxSelect>>", self._on_artist_selected)

        # --- Release list (with type filter) ---
        release_outer = ttk.Frame(content)
        release_outer.grid(row=0, column=1, sticky="nsew", padx=4)
        release_outer.rowconfigure(1, weight=1)
        release_outer.columnconfigure(0, weight=1)

        filter_bar = ttk.Frame(release_outer)
        filter_bar.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(filter_bar, text="Type filter:").pack(side=tk.LEFT, padx=(0, 4))
        self._type_filter_var = tk.StringVar(value="All")
        type_cb = ttk.Combobox(
            filter_bar,
            textvariable=self._type_filter_var,
            values=["All", "Album", "Single", "EP", "Broadcast", "Other"],
            state="readonly",
            width=12,
        )
        type_cb.pack(side=tk.LEFT)
        type_cb.bind("<<ComboboxSelected>>", lambda _e: self._refresh_releases())

        release_frame = ttk.LabelFrame(release_outer, text="Albums / Releases", padding=4)
        release_frame.grid(row=1, column=0, sticky="nsew")
        self._release_lb = tk.Listbox(release_frame, selectmode=tk.SINGLE, exportselection=False)
        r_scroll = ttk.Scrollbar(release_frame, orient=tk.VERTICAL, command=self._release_lb.yview)
        self._release_lb.configure(yscrollcommand=r_scroll.set)
        self._release_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        r_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._release_lb.bind("<<ListboxSelect>>", self._on_release_selected)

        # --- Track list ---
        track_frame = ttk.LabelFrame(content, text="Tracks", padding=4)
        track_frame.grid(row=0, column=2, sticky="nsew", padx=(4, 0))

        # Album art — packed first so it anchors to the bottom
        self._art_label = tk.Label(track_frame, bd=0, relief=tk.FLAT)
        self._art_label.pack(side=tk.BOTTOM, pady=(4, 2))
        self._show_placeholder_art()

        self._track_lb = tk.Listbox(track_frame, selectmode=tk.SINGLE, exportselection=False)
        t_scroll = ttk.Scrollbar(track_frame, orient=tk.VERTICAL, command=self._track_lb.yview)
        self._track_lb.configure(yscrollcommand=t_scroll.set)
        self._track_lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        t_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # --- Action buttons ---
        action_bar = ttk.Frame(parent)
        action_bar.pack(fill=tk.X, padx=8, pady=(4, 2))

        self._create_btn = ttk.Button(
            action_bar,
            text="Create Album Ebook",
            command=self._create_album_ebook,
            state=tk.DISABLED,
            style="Action.TButton",
        )
        self._create_btn.pack(side=tk.LEFT, padx=(0, 8))

        self._catalogue_btn = ttk.Button(
            action_bar,
            text="Create Entire Back Catalogue",
            command=self._create_catalogue_ebook,
            state=tk.DISABLED,
            style="Action.TButton",
        )
        self._catalogue_btn.pack(side=tk.LEFT)

        # --- Progress area ---
        progress_frame = ttk.Frame(parent)
        progress_frame.pack(fill=tk.X, padx=8, pady=(2, 8))

        self._progress_var = tk.DoubleVar(value=0.0)
        self._progress_bar = ttk.Progressbar(
            progress_frame, variable=self._progress_var, maximum=100
        )
        self._progress_bar.pack(fill=tk.X, pady=(0, 3))

        self._progress_label_var = tk.StringVar(value="")
        ttk.Label(
            progress_frame,
            textvariable=self._progress_label_var,
            style="Status.TLabel",
        ).pack(anchor=tk.W)

    # ---- Settings tab ---------------------------------------------------

    def _build_settings_tab(self, parent: ttk.Frame) -> None:
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        inner = ttk.Frame(canvas, padding=20)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_frame_configure(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event):
            canvas.itemconfig(inner_id, width=event.width)

        inner.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        ttk.Label(inner, text="Settings", style="Header.TLabel").pack(
            anchor=tk.W, pady=(0, 16)
        )

        # --- Lyrics source ---
        src_frame = ttk.LabelFrame(inner, text="Lyrics Source", padding=12)
        src_frame.pack(fill=tk.X, pady=(0, 12))
        src_frame.columnconfigure(2, weight=1)

        ttk.Label(src_frame, text="Primary source:").grid(
            row=0, column=0, sticky=tk.W, pady=4
        )
        self._lyrics_source_var = tk.StringVar(
            value=self.settings.get("lyrics_source", "lyricsovh")
        )
        src_combo = ttk.Combobox(
            src_frame,
            textvariable=self._lyrics_source_var,
            values=list(LYRICS_SOURCES.keys()),
            state="readonly",
            width=14,
        )
        src_combo.grid(row=0, column=1, sticky=tk.W, padx=8, pady=4)

        self._source_desc_var = tk.StringVar()
        ttk.Label(
            src_frame, textvariable=self._source_desc_var, style="Status.TLabel"
        ).grid(row=0, column=2, sticky=tk.W)
        src_combo.bind("<<ComboboxSelected>>", lambda _e: self._update_source_desc())
        self._update_source_desc()

        ttk.Label(src_frame, text="Genius API token:").grid(
            row=1, column=0, sticky=tk.W, pady=4
        )
        self._genius_token_var = tk.StringVar(
            value=self.settings.get("genius_token", "")
        )
        ttk.Entry(
            src_frame, textvariable=self._genius_token_var, width=50, show="*"
        ).grid(row=1, column=1, columnspan=2, sticky=tk.W, padx=8, pady=4)
        ttk.Label(
            src_frame,
            text="Required only for the Genius source. Get a free token at genius.com/api-clients",
            style="Status.TLabel",
        ).grid(row=2, column=1, columnspan=2, sticky=tk.W, padx=8)

        # --- Output format ---
        fmt_frame = ttk.LabelFrame(inner, text="Output Format", padding=12)
        fmt_frame.pack(fill=tk.X, pady=(0, 12))

        self._output_format_var = tk.StringVar(
            value=self.settings.get("output_format", "epub")
        )
        for i, (fmt_key, fmt_desc) in enumerate(OUTPUT_FORMATS.items()):
            ttk.Radiobutton(
                fmt_frame,
                text=f"{fmt_key.upper()}  —  {fmt_desc}",
                variable=self._output_format_var,
                value=fmt_key,
            ).grid(row=i, column=0, sticky=tk.W, pady=3)

        ttk.Label(
            fmt_frame,
            text=(
                "Tip: For Kindle MOBI/AZW3, convert the EPUB using Calibre (free, calibre-ebook.com) "
                "or drag the EPUB into the Kindle app / Send to Kindle."
            ),
            style="Status.TLabel",
            wraplength=620,
        ).grid(row=len(OUTPUT_FORMATS), column=0, sticky=tk.W, pady=(8, 0))

        # --- Output directory ---
        dir_frame = ttk.LabelFrame(inner, text="Output Directory", padding=12)
        dir_frame.pack(fill=tk.X, pady=(0, 12))
        dir_frame.columnconfigure(0, weight=1)

        self._output_dir_var = tk.StringVar(
            value=self.settings.get(
                "output_dir", str(Path.home() / "Documents" / "Ebooks")
            )
        )
        ttk.Entry(dir_frame, textvariable=self._output_dir_var).grid(
            row=0, column=0, sticky=tk.EW, padx=(0, 8)
        )
        ttk.Button(dir_frame, text="Browse…", command=self._browse_output_dir).grid(
            row=0, column=1
        )

        # --- Artwork toggle ---
        art_frame = ttk.LabelFrame(inner, text="Artwork", padding=12)
        art_frame.pack(fill=tk.X, pady=(0, 12))

        self._include_artwork_var = tk.BooleanVar(
            value=self.settings.get("include_artwork", True)
        )
        ttk.Checkbutton(
            art_frame,
            text="Download and include album artwork and additional images in ebook",
            variable=self._include_artwork_var,
        ).pack(anchor=tk.W)

        # --- Save button ---
        btn_row = ttk.Frame(inner)
        btn_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Button(btn_row, text="Save Settings", command=self._save_settings).pack(
            side=tk.LEFT
        )
        self._settings_status_var = tk.StringVar()
        ttk.Label(
            btn_row,
            textvariable=self._settings_status_var,
            style="Status.TLabel",
        ).pack(side=tk.LEFT, padx=10)

    # ------------------------------------------------------------------
    # Queue polling (runs on main thread via after())
    # ------------------------------------------------------------------

    def _poll_queue(self) -> None:
        """Drain the inter-thread message queue and update the UI."""
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg.get("type")

                if kind == "status":
                    self._status_var.set(msg["text"])

                elif kind == "progress":
                    self._progress_var.set(msg["value"])
                    self._progress_label_var.set(msg.get("label", ""))

                elif kind == "artists":
                    self._populate_artists(msg["data"])

                elif kind == "releases":
                    self._release_groups = msg["data"]
                    self._refresh_releases()
                    if self._release_groups:
                        self._catalogue_btn.config(state=tk.NORMAL)

                elif kind == "tracks":
                    self._current_release_data = msg["data"]
                    self._populate_tracks(msg["data"]["tracks"])
                    self._create_btn.config(state=tk.NORMAL)

                elif kind == "album_art":
                    self._show_album_art(msg.get("data"))

                elif kind == "enable_buttons":
                    self._set_busy(False)

                elif kind == "done":
                    self._set_busy(False)
                    self._on_creation_done(msg.get("path", ""), msg.get("error"))

                elif kind == "catalogue_done":
                    self._set_busy(False)
                    self._on_catalogue_done(
                        msg.get("paths", []), msg.get("error")
                    )

                elif kind == "confirm_missing":
                    action = self._prompt_missing_data_action(
                        missing_cover=msg.get("missing_cover", False),
                        missing_tracks=msg.get("missing_tracks", []),
                        allow_retry=msg.get("allow_retry", True),
                    )
                    response_queue = msg.get("response_queue")
                    if response_queue is not None:
                        response_queue.put(action)

        except queue.Empty:
            pass
        finally:
            self.after(100, self._poll_queue)

    # ------------------------------------------------------------------
    # Album art helpers
    # ------------------------------------------------------------------

    def _show_placeholder_art(self) -> None:
        """Reset the album art label to a grey placeholder image."""
        self._art_photo = _make_placeholder_image()
        self._art_label.config(image=self._art_photo)

    def _show_album_art(self, data: bytes | None) -> None:
        """Display *data* (raw image bytes) in the album art label, or placeholder."""
        if data:
            try:
                self._art_photo = _bytes_to_photo(data)
                self._art_label.config(image=self._art_photo)
                return
            except Exception:  # noqa: BLE001
                logger.debug("Failed to decode album art image", exc_info=True)
        self._show_placeholder_art()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _do_search(self) -> None:
        query = self._search_var.get().strip()
        if not query:
            return
        self._set_busy(True)
        self._status_var.set("Searching MusicBrainz…")
        self._artist_lb.delete(0, tk.END)
        self._release_lb.delete(0, tk.END)
        self._track_lb.delete(0, tk.END)
        self._artists = []
        self._release_groups = []
        self._selected_artist = None
        self._selected_release_group = None
        self._current_release_data = None
        self._progress_var.set(0)
        self._progress_label_var.set("")
        threading.Thread(target=self._search_worker, args=(query,), daemon=True).start()

    def _search_worker(self, query: str) -> None:
        try:
            artists = mb.search_artists(query)
            self._queue.put({"type": "artists", "data": artists})
            self._queue.put(
                {
                    "type": "status",
                    "text": f"Found {len(artists)} artist(s). Select one to see their releases.",
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Search failed for query '%s'", query)
            self._queue.put({"type": "status", "text": f"Search error: {exc}"})
        finally:
            self._queue.put({"type": "enable_buttons"})

    def _populate_artists(self, artists: list[dict]) -> None:
        self._artists = artists
        self._artist_lb.delete(0, tk.END)
        for artist in artists:
            label = artist["name"]
            if artist.get("disambiguation"):
                label += f" ({artist['disambiguation']})"
            if artist.get("country"):
                label += f" [{artist['country']}]"
            self._artist_lb.insert(tk.END, label)

    # ------------------------------------------------------------------
    # Release groups
    # ------------------------------------------------------------------

    def _on_artist_selected(self, _event=None) -> None:
        sel = self._artist_lb.curselection()
        if not sel:
            return
        self._selected_artist = self._artists[sel[0]]
        self._release_lb.delete(0, tk.END)
        self._track_lb.delete(0, tk.END)
        self._release_groups = []
        self._current_release_data = None
        self._create_btn.config(state=tk.DISABLED)
        self._catalogue_btn.config(state=tk.DISABLED)
        self._show_placeholder_art()
        self._status_var.set(
            f"Loading releases for '{self._selected_artist['name']}'…"
        )
        threading.Thread(
            target=self._load_releases_worker,
            args=(self._selected_artist["id"],),
            daemon=True,
        ).start()

    def _load_releases_worker(self, artist_id: str) -> None:
        try:
            release_groups = mb.get_artist_release_groups(artist_id)
            self._queue.put({"type": "releases", "data": release_groups})
            self._queue.put(
                {
                    "type": "status",
                    "text": f"Found {len(release_groups)} release(s). Select one to load its tracks.",
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed loading releases for artist id %s", artist_id)
            self._queue.put({"type": "status", "text": f"Error loading releases: {exc}"})

    def _refresh_releases(self) -> None:
        """Repopulate the release listbox using the current type filter."""
        self._release_lb.delete(0, tk.END)
        filter_type = self._type_filter_var.get()
        for rg in self._release_groups:
            rg_type = rg.get("type") or rg.get("primary_type") or "Other"
            if filter_type != "All" and rg_type.lower() != filter_type.lower():
                continue
            year = (rg.get("first_release_date") or "")[:4] or "????"
            title = rg.get("title", "Unknown")
            self._release_lb.insert(tk.END, f"{year}  —  {title}  [{rg_type}]")

    def _visible_release_groups(self) -> list[dict]:
        """Return the subset of release groups currently shown in the listbox."""
        filter_type = self._type_filter_var.get()
        if filter_type == "All":
            return list(self._release_groups)
        return [
            rg
            for rg in self._release_groups
            if (rg.get("type") or rg.get("primary_type") or "").lower()
            == filter_type.lower()
        ]

    # ------------------------------------------------------------------
    # Tracks
    # ------------------------------------------------------------------

    def _on_release_selected(self, _event=None) -> None:
        sel = self._release_lb.curselection()
        if not sel:
            return
        visible = self._visible_release_groups()
        idx = sel[0]
        if idx >= len(visible):
            return
        self._selected_release_group = visible[idx]
        self._track_lb.delete(0, tk.END)
        self._current_release_data = None
        self._create_btn.config(state=tk.DISABLED)
        self._show_placeholder_art()
        self._status_var.set("Loading tracks…")
        threading.Thread(
            target=self._load_tracks_worker,
            args=(self._selected_release_group["id"],),
            daemon=True,
        ).start()

    def _load_tracks_worker(self, release_group_id: str) -> None:
        try:
            releases = mb.get_release_group_releases(release_group_id)
            if not releases:
                self._queue.put(
                    {"type": "status", "text": "No releases found for this title."}
                )
                return
            release_id = releases[0]["id"]
            release_info, tracks = mb.get_release_tracks(release_id)
            self._queue.put(
                {
                    "type": "tracks",
                    "data": {
                        "release_id": release_id,
                        "release_info": release_info,
                        "tracks": tracks,
                    },
                }
            )
            self._queue.put(
                {
                    "type": "status",
                    "text": (
                        f"Loaded {len(tracks)} track(s). "
                        'Press "Create Album Ebook" to generate the ebook.'
                    ),
                }
            )
            # Fetch and display cover art only for the selected album
            art_data = ca.get_front_cover(release_id)
            self._queue.put({"type": "album_art", "data": art_data})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed loading tracks for release group id %s", release_group_id)
            self._queue.put({"type": "status", "text": f"Error loading tracks: {exc}"})

    def _populate_tracks(self, tracks: list[dict]) -> None:
        self._track_lb.delete(0, tk.END)
        for track in tracks:
            num = track.get("position", 0)
            title = track.get("title", "Unknown")
            ms = track.get("length", 0)
            dur = f"  ({ms // 60000}:{(ms // 1000) % 60:02d})" if ms else ""
            self._track_lb.insert(tk.END, f"{num:02d}.  {title}{dur}")

    # ------------------------------------------------------------------
    # Ebook creation workers
    # ------------------------------------------------------------------

    def _create_album_ebook(self) -> None:
        if not self._current_release_data or not self._selected_artist:
            return
        if not self._confirm_output_directory():
            return
        self._set_busy(True)
        self._progress_var.set(0)
        self._progress_label_var.set("")
        threading.Thread(
            target=self._album_ebook_worker, daemon=True
        ).start()

    def _request_missing_data_action(
        self,
        missing_cover: bool,
        missing_tracks: list[str],
        allow_retry: bool,
    ) -> str:
        """Request a user decision from the UI thread and block worker until answered."""
        response_queue: queue.Queue[str] = queue.Queue(maxsize=1)
        self._queue.put(
            {
                "type": "confirm_missing",
                "missing_cover": missing_cover,
                "missing_tracks": missing_tracks,
                "allow_retry": allow_retry,
                "response_queue": response_queue,
            }
        )
        return response_queue.get()

    def _prompt_missing_data_action(
        self,
        missing_cover: bool,
        missing_tracks: list[str],
        allow_retry: bool,
    ) -> str:
        """Show missing data details and return one of: retry, continue, cancel."""
        lines = []
        if missing_cover:
            lines.append("- Album cover art")
        if missing_tracks:
            preview = missing_tracks[:8]
            lines.append(f"- Lyrics for {len(missing_tracks)} track(s):")
            lines.extend([f"  - {title}" for title in preview])
            if len(missing_tracks) > len(preview):
                lines.append(f"  - ...and {len(missing_tracks) - len(preview)} more")

        details = "\n".join(lines) if lines else "- Unknown missing elements"

        if allow_retry:
            message = (
                "Some content could not be retrieved:\n\n"
                f"{details}\n\n"
                "Retry only missing items before creating the ebook?\n\n"
                "Yes = Retry missing items\n"
                "No = Continue without them\n"
                "Cancel = Abort creation"
            )
            choice = messagebox.askyesnocancel("Missing Data", message)
            if choice is True:
                return "retry"
            if choice is False:
                return "continue"
            return "cancel"

        message = (
            "Some content is still missing after retry:\n\n"
            f"{details}\n\n"
            "Continue creating the ebook without these items?"
        )
        return "continue" if messagebox.askyesno("Still Missing Data", message) else "cancel"

    def _confirm_output_directory(self) -> bool:
        """Ask user to confirm output directory before writing files."""
        output_dir = self.settings.get("output_dir")
        if not output_dir:
            messagebox.showerror("Missing Output Directory", "Please set an output directory in Settings.")
            return False

        confirm = messagebox.askyesno(
            "Confirm Output Directory",
            f"The ebook will be written to:\n\n{output_dir}\n\nContinue?",
        )
        if not confirm:
            return False

        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Output Directory Error", f"Could not access output directory:\n\n{exc}")
            logger.exception("Output directory is not writable: %s", output_dir)
            return False

        return True

    def _album_ebook_worker(self) -> None:
        try:
            data = self._current_release_data
            release_info: dict = data["release_info"]
            tracks: list[dict] = data["tracks"]
            release_id: str = data["release_id"]
            artist_info = self._selected_artist
            artist_name: str = artist_info["name"]
            album_title: str = release_info.get("title", "Unknown")

            # Merge release group type if available
            if self._selected_release_group:
                release_info = {
                    **release_info,
                    "type": self._selected_release_group.get("type", "Album"),
                    "first_release_date": self._selected_release_group.get(
                        "first_release_date", ""
                    ),
                }

            total = len(tracks) + 3
            step = 0

            def _progress(label: str) -> None:
                nonlocal step
                step += 1
                self._queue.put(
                    {
                        "type": "progress",
                        "value": min(step / total * 100, 99),
                        "label": label,
                    }
                )

            include_art = self.settings.get("include_artwork", True)

            _progress(f"Downloading cover art for '{album_title}'…")
            cover_image: bytes | None = None
            additional_images: list = []
            if include_art:
                cover_image = ca.get_front_cover(release_id)

            _progress("Fetching additional artwork…")
            if include_art:
                for img_meta in ca.get_release_images(release_id):
                    if not img_meta.get("front"):
                        img_data = ca.download_image(img_meta.get("image", ""))
                        if img_data:
                            additional_images.append((img_data, img_meta))

            # Lyrics
            source_name: str = self.settings.get("lyrics_source", "lyricsovh")
            lyrics_src = get_lyrics_source(
                source_name, {"genius_token": self.settings.get("genius_token", "")}
            )
            lyrics_map: dict[int, str] = {}
            for track in tracks:
                title = track.get("title", "")
                pos = track.get("position", 0)
                _progress(f"Lyrics: {title}")
                if title:
                    raw = lyrics_src.get_lyrics(artist_name, title)
                    if raw:
                        lyrics_map[pos] = clean_lyrics(raw)

            missing_cover = include_art and not cover_image
            missing_tracks = [
                track.get("title", "Unknown")
                for track in tracks
                if track.get("position", 0) not in lyrics_map
            ]

            if missing_cover or missing_tracks:
                logger.warning(
                    "Initial fetch missing data: cover=%s missing_lyrics=%s",
                    missing_cover,
                    len(missing_tracks),
                )
                action = self._request_missing_data_action(
                    missing_cover=missing_cover,
                    missing_tracks=missing_tracks,
                    allow_retry=True,
                )

                if action == "cancel":
                    self._queue.put({"type": "done", "error": "Creation cancelled by user."})
                    return

                if action == "retry":
                    _progress("Retrying missing items…")
                    if missing_cover and include_art:
                        cover_image = ca.get_front_cover(release_id)

                    missing_positions = {
                        track.get("position", 0)
                        for track in tracks
                        if track.get("position", 0) not in lyrics_map
                    }
                    for track in tracks:
                        pos = track.get("position", 0)
                        title = track.get("title", "")
                        if pos not in missing_positions or not title:
                            continue
                        raw = lyrics_src.get_lyrics(artist_name, title)
                        if raw:
                            lyrics_map[pos] = clean_lyrics(raw)

                    missing_cover = include_art and not cover_image
                    missing_tracks = [
                        track.get("title", "Unknown")
                        for track in tracks
                        if track.get("position", 0) not in lyrics_map
                    ]
                    if missing_cover or missing_tracks:
                        logger.warning(
                            "Data still missing after retry: cover=%s missing_lyrics=%s",
                            missing_cover,
                            len(missing_tracks),
                        )
                        action = self._request_missing_data_action(
                            missing_cover=missing_cover,
                            missing_tracks=missing_tracks,
                            allow_retry=False,
                        )
                        if action == "cancel":
                            self._queue.put({"type": "done", "error": "Creation cancelled by user."})
                            return

            _progress("Building EPUB…")
            builder = EbookBuilder(
                output_format=self.settings.get("output_format", "epub")
            )
            output_path = builder.build_album_book(
                artist_info=artist_info,
                release_info=release_info,
                tracks=tracks,
                lyrics_map=lyrics_map,
                cover_image=cover_image,
                additional_images=additional_images or None,
                output_dir=self.settings.get("output_dir"),
            )

            self._queue.put({"type": "progress", "value": 100, "label": "Done!"})
            self._queue.put({"type": "done", "path": output_path})

        except Exception as exc:  # noqa: BLE001
            logger.exception("Album ebook creation failed")
            self._queue.put({"type": "done", "error": str(exc)})

    def _create_catalogue_ebook(self) -> None:
        if not self._selected_artist or not self._release_groups:
            return
        if not self._confirm_output_directory():
            return
        self._set_busy(True)
        self._progress_var.set(0)
        self._progress_label_var.set("")
        threading.Thread(
            target=self._catalogue_worker, daemon=True
        ).start()

    def _catalogue_worker(self) -> None:
        try:
            artist_info = self._selected_artist
            artist_name: str = artist_info["name"]
            source_name: str = self.settings.get("lyrics_source", "lyricsovh")
            lyrics_src = get_lyrics_source(
                source_name, {"genius_token": self.settings.get("genius_token", "")}
            )
            include_art = self.settings.get("include_artwork", True)

            release_groups = sorted(
                self._release_groups,
                key=lambda rg: rg.get("first_release_date") or "0000",
            )
            total_rgs = len(release_groups)
            albums_data: list[dict] = []

            for rg_idx, rg in enumerate(release_groups):
                rg_title = rg.get("title", "Unknown")
                base_pct = (rg_idx / total_rgs) * 90
                self._queue.put(
                    {
                        "type": "progress",
                        "value": base_pct,
                        "label": f"Processing ({rg_idx + 1}/{total_rgs}): {rg_title}",
                    }
                )

                try:
                    releases = mb.get_release_group_releases(rg["id"])
                    if not releases:
                        continue
                    release_id = releases[0]["id"]
                    release_info, tracks = mb.get_release_tracks(release_id)
                    release_info = {
                        **release_info,
                        "type": rg.get("type", "Album"),
                        "first_release_date": rg.get("first_release_date", ""),
                    }

                    cover_image: bytes | None = None
                    additional_images: list = []
                    if include_art:
                        cover_image = ca.get_front_cover(release_id)
                        for img_meta in ca.get_release_images(release_id):
                            if not img_meta.get("front"):
                                img_data = ca.download_image(img_meta.get("image", ""))
                                if img_data:
                                    additional_images.append((img_data, img_meta))

                    lyrics_map: dict[int, str] = {}
                    for track in tracks:
                        title = track.get("title", "")
                        pos = track.get("position", 0)
                        if title:
                            raw = lyrics_src.get_lyrics(artist_name, title)
                            if raw:
                                lyrics_map[pos] = clean_lyrics(raw)

                    albums_data.append(
                        {
                            "release_info": release_info,
                            "tracks": tracks,
                            "lyrics_map": lyrics_map,
                            "cover_image": cover_image,
                            "additional_images": additional_images,
                        }
                    )
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Skipping release group due to processing error: id=%s title=%s",
                        rg.get("id", ""),
                        rg.get("title", ""),
                    )
                    continue  # skip problematic releases silently

            if not albums_data:
                self._queue.put(
                    {
                        "type": "catalogue_done",
                        "error": "No album data could be retrieved.",
                    }
                )
                return

            self._queue.put(
                {"type": "progress", "value": 92, "label": "Building catalogue EPUB…"}
            )
            builder = EbookBuilder(
                output_format=self.settings.get("output_format", "epub")
            )
            output_path = builder.build_catalogue_book(
                artist_info=artist_info,
                albums_data=albums_data,
                output_dir=self.settings.get("output_dir"),
            )
            self._queue.put({"type": "progress", "value": 100, "label": "Done!"})
            self._queue.put({"type": "catalogue_done", "paths": [output_path]})

        except Exception as exc:  # noqa: BLE001
            logger.exception("Catalogue ebook creation failed")
            self._queue.put({"type": "catalogue_done", "error": str(exc)})

    # ------------------------------------------------------------------
    # Completion callbacks
    # ------------------------------------------------------------------

    def _on_creation_done(self, path: str, error: Optional[str]) -> None:
        if error:
            messagebox.showerror("Error", f"Failed to create ebook:\n\n{error}")
            self._progress_label_var.set(f"Error: {error}")
        else:
            messagebox.showinfo(
                "Ebook Created",
                f"Your ebook has been saved to:\n\n{path}",
            )
            self._progress_label_var.set(f"Saved: {path}")
            if messagebox.askyesno("Open Folder", "Open the output folder?"):
                _open_folder(os.path.dirname(path))

    def _on_catalogue_done(
        self, paths: list[str], error: Optional[str]
    ) -> None:
        if error:
            messagebox.showerror(
                "Error", f"Failed to create catalogue ebook:\n\n{error}"
            )
            self._progress_label_var.set(f"Error: {error}")
        else:
            path = paths[0] if paths else ""
            messagebox.showinfo(
                "Catalogue Ebook Created",
                f"Your catalogue ebook has been saved to:\n\n{path}",
            )
            self._progress_label_var.set(f"Saved: {path}")
            if messagebox.askyesno("Open Folder", "Open the output folder?"):
                _open_folder(os.path.dirname(path))

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------

    def _update_source_desc(self) -> None:
        source = self._lyrics_source_var.get()
        self._source_desc_var.set(LYRICS_SOURCES.get(source, ""))

    def _browse_output_dir(self) -> None:
        directory = filedialog.askdirectory(
            initialdir=self._output_dir_var.get() or str(Path.home()),
            title="Select Output Directory",
        )
        if directory:
            self._output_dir_var.set(directory)

    def _save_settings(self) -> None:
        self.settings.set("lyrics_source", self._lyrics_source_var.get())
        self.settings.set("genius_token", self._genius_token_var.get())
        self.settings.set("output_format", self._output_format_var.get())
        self.settings.set("output_dir", self._output_dir_var.get())
        self.settings.set("include_artwork", self._include_artwork_var.get())
        try:
            self.settings.save()
            self._settings_status_var.set("✓ Settings saved.")
        except RuntimeError as exc:
            self._settings_status_var.set(f"Error saving settings: {exc}")

    # ------------------------------------------------------------------
    # Busy state management
    # ------------------------------------------------------------------

    def _set_busy(self, busy: bool) -> None:
        """Disable/enable interactive controls during background work."""
        if busy:
            self._search_btn.config(state=tk.DISABLED)
            self._create_btn.config(state=tk.DISABLED)
            self._catalogue_btn.config(state=tk.DISABLED)
        else:
            self._search_btn.config(state=tk.NORMAL)
            if self._current_release_data:
                self._create_btn.config(state=tk.NORMAL)
            if self._release_groups:
                self._catalogue_btn.config(state=tk.NORMAL)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _open_folder(path: str) -> None:
    """Open *path* in the platform's default file manager."""
    if not os.path.isdir(path):
        return
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:  # noqa: BLE001
        logger.exception("Failed to open folder: %s", path)
