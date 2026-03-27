/**
 * app.js — UI controller for the Song Lyrics to Ebook web app.
 *
 * Depends on (loaded before this file in this order):
 *   utils.js  — slugify, fmtDuration, sleep, cleanLyrics, esc, lyricsToHtml
 *   api.js    — searchArtists, getArtistReleaseGroups, getReleaseGroupReleases,
 *               getReleaseTracks, getCoverArt, getLyrics
 *   epub.js   — buildAlbumEbook
 *
 * No frameworks, no build step — runs directly in the browser.
 */

"use strict";

(function () {

  /* ── Application state ── */

  let artists = [];
  let releaseGroups = [];
  let selectedArtist = null;
  let selectedRelease = null;   // chosen release (edition) within a release group
  let currentTracks = [];
  let currentReleaseInfo = null;
  let isBusy = false;

  /* ── DOM references ── */

  const searchInput       = document.getElementById("searchInput");
  const searchBtn         = document.getElementById("searchBtn");
  const statusMsg         = document.getElementById("statusMsg");
  const artistList        = document.getElementById("artistList");
  const releaseList       = document.getElementById("releaseList");
  const trackList         = document.getElementById("trackList");
  const typeFilter        = document.getElementById("typeFilter");
  const createEbookBtn    = document.getElementById("createEbookBtn");
  const progressContainer = document.getElementById("progressContainer");
  const progressFill      = document.getElementById("progressFill");
  const progressBar       = document.getElementById("progressBar");
  const progressLabel     = document.getElementById("progressLabel");
  const geniusToken       = document.getElementById("geniusToken");
  const includeArtwork    = document.getElementById("includeArtwork");
  const albumArt          = document.getElementById("albumArt");

  /* ── Album art helpers ── */

  // SVG placeholder — a simple music note inside a rounded square
  const PLACEHOLDER_ART_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120">
    <rect width="120" height="120" rx="8" fill="#e4e8ee"/>
    <text x="60" y="78" text-anchor="middle" font-size="52" fill="#9aa5b4">♪</text>
  </svg>`;
  const PLACEHOLDER_ART_SRC =
    "data:image/svg+xml;charset=utf-8," + encodeURIComponent(PLACEHOLDER_ART_SVG);

  let _currentArtBlobUrl = null;

  function showPlaceholderArt() {
    if (_currentArtBlobUrl) {
      URL.revokeObjectURL(_currentArtBlobUrl);
      _currentArtBlobUrl = null;
    }
    albumArt.src = PLACEHOLDER_ART_SRC;
    albumArt.alt = "";
    albumArt.title = "";
  }

  function showAlbumArt(arrayBuffer, albumTitle) {
    if (_currentArtBlobUrl) {
      URL.revokeObjectURL(_currentArtBlobUrl);
      _currentArtBlobUrl = null;
    }
    if (!arrayBuffer) {
      showPlaceholderArt();
      return;
    }
    const blob = new Blob([arrayBuffer], { type: "image/jpeg" });
    _currentArtBlobUrl = URL.createObjectURL(blob);
    albumArt.src = _currentArtBlobUrl;
    albumArt.alt = albumTitle ? `Album art for ${albumTitle}` : "Album art";
    albumArt.title = albumArt.alt;
  }

  // Initialise with placeholder
  showPlaceholderArt();

  /* ── Persist settings in localStorage ── */

  try {
    geniusToken.value = localStorage.getItem("sle_genius_token") || "";
    includeArtwork.checked = localStorage.getItem("sle_include_artwork") !== "false";
  } catch (_) {}

  geniusToken.addEventListener("change", () => {
    try { localStorage.setItem("sle_genius_token", geniusToken.value.trim()); } catch (_) {}
  });

  includeArtwork.addEventListener("change", () => {
    try { localStorage.setItem("sle_include_artwork", String(includeArtwork.checked)); } catch (_) {}
  });

  /* ── Status / progress helpers ── */

  function setStatus(msg, type) {
    statusMsg.textContent = msg;
    statusMsg.className = "status" + (type ? " " + type : "");
  }

  function setProgress(pct, label) {
    progressFill.style.width = pct + "%";
    progressBar.setAttribute("aria-valuenow", String(pct));
    progressLabel.textContent = label || "";
  }

  /* ── Search ── */

  searchBtn.addEventListener("click", doSearch);
  searchInput.addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });

  async function doSearch() {
    const query = searchInput.value.trim();
    if (!query || isBusy) return;

    setBusy(true);
    clearAll();
    setStatus("Searching…");

    try {
      artists = await searchArtists(query);
      if (artists.length === 0) {
        setStatus("No artists found.");
      } else {
        setStatus(`Found ${artists.length} artist(s). Click one to load their releases.`);
        renderArtists();
      }
    } catch (err) {
      setStatus("Search failed: " + err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  /* ── Artist list ── */

  function renderArtists() {
    artistList.innerHTML = "";
    for (const artist of artists) {
      const li = document.createElement("li");
      li.setAttribute("role", "option");

      const name = document.createElement("span");
      name.className = "item-name";
      name.textContent = artist.name;
      li.appendChild(name);

      const parts = [];
      if (artist.disambiguation) parts.push(artist.disambiguation);
      if (artist.country) parts.push(artist.country);
      if (parts.length > 0) {
        const meta = document.createElement("span");
        meta.className = "item-meta";
        meta.textContent = parts.join(" \u00b7 ");
        li.appendChild(meta);
      }

      li.addEventListener("click", () => onArtistSelected(artist, li));
      artistList.appendChild(li);
    }
  }

  async function onArtistSelected(artist, li) {
    if (isBusy) return;

    selectedArtist = artist;
    document.querySelectorAll("#artistList li").forEach((el) => el.classList.remove("selected"));
    li.classList.add("selected");

    // Clear downstream state
    releaseGroups = [];
    selectedRelease = null;
    currentTracks = [];
    currentReleaseInfo = null;
    releaseList.innerHTML = "";
    trackList.innerHTML = "";
    createEbookBtn.disabled = true;
    showPlaceholderArt();

    setBusy(true);
    setStatus(`Loading releases for ${artist.name}…`);

    try {
      releaseGroups = await getArtistReleaseGroups(artist.id);
      renderReleaseGroups();
      setStatus(
        releaseGroups.length > 0
          ? `${releaseGroups.length} release(s) found. Select one to see its tracks.`
          : "No releases found for this artist."
      );
    } catch (err) {
      setStatus("Failed to load releases: " + err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  /* ── Release group list ── */

  typeFilter.addEventListener("change", () => {
    if (releaseGroups.length > 0) renderReleaseGroups();
  });

  function renderReleaseGroups() {
    const filterVal = typeFilter.value;
    const visible = filterVal === "All"
      ? releaseGroups
      : releaseGroups.filter((rg) => rg.type === filterVal);

    releaseList.innerHTML = "";

    for (const rg of visible) {
      const li = document.createElement("li");
      li.setAttribute("role", "option");

      const name = document.createElement("span");
      name.className = "item-name";
      name.textContent = rg.title;
      li.appendChild(name);

      const parts = [];
      if (rg.firstReleaseDate) parts.push(rg.firstReleaseDate.slice(0, 4));
      if (rg.type && rg.type !== filterVal) parts.push(rg.type);
      if (parts.length > 0) {
        const meta = document.createElement("span");
        meta.className = "item-meta";
        meta.textContent = parts.join(" \u00b7 ");
        li.appendChild(meta);
      }

      li.addEventListener("click", () => onReleaseGroupSelected(rg, li));
      releaseList.appendChild(li);
    }
  }

  async function onReleaseGroupSelected(rg, li) {
    if (isBusy) return;

    document.querySelectorAll("#releaseList li").forEach((el) => el.classList.remove("selected"));
    li.classList.add("selected");

    selectedRelease = null;
    currentTracks = [];
    currentReleaseInfo = null;
    trackList.innerHTML = "";
    createEbookBtn.disabled = true;
    showPlaceholderArt();

    setBusy(true);
    setStatus(`Loading tracks for "${rg.title}"…`);

    try {
      // Pick the best release (prefer Official, then any)
      const releases = await getReleaseGroupReleases(rg.id);
      await sleep(1100); // rate limit

      const chosen = releases.find((r) => r.status === "Official") || releases[0];
      if (!chosen) {
        setStatus("No release editions found for this entry.", "error");
        setBusy(false);
        return;
      }

      selectedRelease = chosen;
      const { info, tracks } = await getReleaseTracks(chosen.id);
      currentReleaseInfo = info;
      currentTracks = tracks;

      renderTracks();
      createEbookBtn.disabled = false;
      setStatus(
        tracks.length > 0
          ? `${tracks.length} track(s) loaded. Press "Create Album Ebook" to build the ebook.`
          : "No tracks found for this release."
      );

      // Load cover art only for the selected album (non-blocking)
      getCoverArt(chosen.id).then((artData) => {
        // Only update if this album is still the selected one
        if (selectedRelease && selectedRelease.id === chosen.id) {
          showAlbumArt(artData, rg.title);
        }
      }).catch(() => {
        // Non-fatal — placeholder remains
      });

    } catch (err) {
      setStatus("Failed to load tracks: " + err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  /* ── Track list ── */

  function renderTracks() {
    trackList.innerHTML = "";
    for (const t of currentTracks) {
      const li = document.createElement("li");

      const num = document.createElement("span");
      num.className = "track-num";
      num.textContent = t.number || t.position;

      const title = document.createElement("span");
      title.className = "track-title";
      title.textContent = t.title;

      const dur = document.createElement("span");
      dur.className = "track-dur";
      dur.textContent = fmtDuration(t.length);

      li.append(num, title, dur);
      trackList.appendChild(li);
    }
  }

  /* ── Create ebook ── */

  createEbookBtn.addEventListener("click", createEbook);

  async function createEbook() {
    if (isBusy || !selectedArtist || !currentReleaseInfo || currentTracks.length === 0) return;

    setBusy(true);
    progressContainer.hidden = false;
    setProgress(0, "Preparing…");

    try {
      /* Step 1: cover art */
      let coverData = null;
      if (includeArtwork.checked && selectedRelease) {
        setProgress(5, "Fetching cover art…");
        try {
          coverData = await getCoverArt(selectedRelease.id);
        } catch (_) {
          // missing cover art is non-fatal
        }
      }

      /* Step 2: lyrics */
      setProgress(10, "Fetching lyrics…");
      const lyricsMap = {};
      const token = (geniusToken.value || "").trim();
      const missing = [];

      for (let i = 0; i < currentTracks.length; i++) {
        const track = currentTracks[i];
        const artist = track.artist || selectedArtist.name;
        const pct = 10 + Math.round(((i + 1) / currentTracks.length) * 60);
        setProgress(pct, `Fetching lyrics: "${track.title}" (${i + 1}/${currentTracks.length})`);

        try {
          const lyrics = await getLyrics(artist, track.title, token);
          if (lyrics) {
            lyricsMap[track.position] = lyrics;
          } else {
            missing.push(track.title);
          }
        } catch (_) {
          missing.push(track.title);
        }

        await sleep(350); // be polite to the lyrics API
      }

      /* Report any missing lyrics */
      if (missing.length > 0) {
        const preview = missing.slice(0, 3).join(", ") + (missing.length > 3 ? "\u2026" : "");
        setStatus(
          `Note: lyrics not found for ${missing.length} track(s): ${preview}`,
          "warning"
        );
      }

      /* Step 3: build EPUB */
      setProgress(75, "Building EPUB…");
      const blob = await buildAlbumEbook(
        selectedArtist,
        currentReleaseInfo,
        currentTracks,
        lyricsMap,
        coverData
      );

      /* Step 4: trigger download */
      setProgress(95, "Saving…");
      const artistSlug = slugify(selectedArtist.name);
      const year = (currentReleaseInfo.firstReleaseDate || currentReleaseInfo.date || "").slice(0, 4);
      const albumSlug = slugify(currentReleaseInfo.title);
      const filename = [artistSlug, year, albumSlug].filter(Boolean).join("-") + ".epub";

      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);

      setProgress(100, "Done!");
      if (missing.length === 0) setStatus("Ebook created and downloaded successfully!", "success");

    } catch (err) {
      setStatus("Failed to create ebook: " + err.message, "error");
      setProgress(0, "");
    } finally {
      setBusy(false);
    }
  }

  /* ── Utility ── */

  function setBusy(busy) {
    isBusy = busy;
    searchBtn.disabled = busy;
    createEbookBtn.disabled = busy || currentTracks.length === 0;
  }

  function clearAll() {
    artists = [];
    releaseGroups = [];
    selectedArtist = null;
    selectedRelease = null;
    currentTracks = [];
    currentReleaseInfo = null;
    artistList.innerHTML = "";
    releaseList.innerHTML = "";
    trackList.innerHTML = "";
    createEbookBtn.disabled = true;
    progressContainer.hidden = true;
    setProgress(0, "");
    showPlaceholderArt();
  }

})();
