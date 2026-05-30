/**
 * api.js — wrappers for MusicBrainz, Cover Art Archive, and lyrics.ovh.
 *
 * All network calls are intentionally plain fetch() so that no build tools
 * or bundlers are required — the file can be served directly from GitHub Pages.
 *
 * Depends on utils.js being loaded first (for sleep, cleanLyrics).
 */

"use strict";

/* ── Constants ── */

const MB_BASE = "https://musicbrainz.org/ws/2";
const MB_USER_AGENT = "SongLyricsToEbook/1.0 (https://github.com/dfbr/song-lyrics-to-ebook)";

/**
 * Perform a rate-limited GET to the MusicBrainz JSON API.
 * @param {string} path  — URL path relative to MB_BASE (must start with "/")
 * @param {Object} params — query-string parameters (fmt=json is added automatically)
 * @returns {Promise<Object>}
 */
async function mbGet(path, params = {}) {
  const url = new URL(MB_BASE + path);
  url.searchParams.set("fmt", "json");
  for (const [k, v] of Object.entries(params)) {
    url.searchParams.set(k, String(v));
  }

  const resp = await fetch(url.toString(), {
    headers: {
      "User-Agent": MB_USER_AGENT,
      Accept: "application/json",
    },
  });

  if (!resp.ok) {
    throw new Error(`MusicBrainz returned HTTP ${resp.status} for ${url.pathname}`);
  }

  return resp.json();
}

/* ── Artist search ── */

/**
 * Search MusicBrainz for artists matching `query`.
 * @param {string} query
 * @param {number} [limit=25]
 * @returns {Promise<Array<{id, name, disambiguation, country, score}>>}
 */
async function searchArtists(query, limit = 25) {
  const data = await mbGet("/artist", { query, limit });
  return (data.artists || []).map((a) => ({
    id: a.id,
    name: a.name || "",
    disambiguation: a.disambiguation || "",
    country: a.country || "",
    score: a.score || 0,
  }));
}

/**
 * Search MusicBrainz for release groups (albums/releases) matching `query`.
 * @param {string} query
 * @param {number} [limit=25]
 * @returns {Promise<Array<{id, title, type, primaryType, secondaryTypes, firstReleaseDate, artist, score}>>}
 */
async function searchReleaseGroups(query, limit = 25) {
  const data = await mbGet("/release-group", { query, limit });
  return (data["release-groups"] || []).map((rg) => {
    const firstCredit = (rg["artist-credit"] || [])[0];
    const artist = (firstCredit && typeof firstCredit === "object")
      ? ((firstCredit.artist || {}).name || "")
      : "";

    return {
      id: rg.id,
      title: rg.title || "",
      type: rg["primary-type"] || rg.type || "Other",
      primaryType: rg["primary-type"] || "",
      secondaryTypes: rg["secondary-types"] || [],
      firstReleaseDate: rg["first-release-date"] || "",
      artist,
      score: rg.score || 0,
    };
  });
}

/* ── Release groups ── */

/**
 * Retrieve all release groups for an artist, paginating as needed.
 * Results are sorted chronologically by first release date.
 *
 * @param {string} artistId — MusicBrainz artist MBID
 * @returns {Promise<Array<{id, title, type, primaryType, secondaryTypes, firstReleaseDate}>>}
 */
async function getArtistReleaseGroups(artistId) {
  const allGroups = [];
  const limit = 100;
  let offset = 0;

  while (true) {
    const data = await mbGet("/release-group", { artist: artistId, limit, offset });
    const groups = data["release-groups"] || [];
    const total = Number(data["release-group-count"] || 0);

    for (const rg of groups) {
      allGroups.push({
        id: rg.id,
        title: rg.title || "",
        type: rg["primary-type"] || rg.type || "Other",
        primaryType: rg["primary-type"] || "",
        secondaryTypes: rg["secondary-types"] || [],
        firstReleaseDate: rg["first-release-date"] || "",
      });
    }

    offset += groups.length;
    if (offset >= total || groups.length === 0) break;
    await sleep(1100); // respect MusicBrainz 1 req/sec rate limit
  }

  allGroups.sort((a, b) =>
    (a.firstReleaseDate || "0000").localeCompare(b.firstReleaseDate || "0000")
  );

  return allGroups;
}

/* ── Releases within a release group ── */

/**
 * Get individual releases (editions) that belong to a release group.
 * @param {string} releaseGroupId
 * @returns {Promise<Array<{id, title, status, date, country}>>}
 */
async function getReleaseGroupReleases(releaseGroupId) {
  const data = await mbGet(`/release-group/${releaseGroupId}`, { inc: "releases" });
  return (data.releases || []).map((r) => ({
    id: r.id,
    title: r.title || "",
    status: r.status || "",
    date: r.date || "",
    country: r.country || "",
  }));
}

/* ── Track listing ── */

/**
 * Fetch full release information and its track listing.
 *
 * @param {string} releaseId — MusicBrainz release MBID
 * @returns {Promise<{info: Object, tracks: Array}>}
 */
async function getReleaseTracks(releaseId) {
  const data = await mbGet(`/release/${releaseId}`, {
    inc: "recordings+artist-credits+release-groups+labels+media",
  });

  const info = {
    id: data.id || "",
    title: data.title || "",
    artist: "",
    date: data.date || "",
    status: data.status || "",
    country: data.country || "",
    barcode: data.barcode || "",
    label: "",
    catalogNumber: "",
    releaseGroupId: "",
    type: "",
    firstReleaseDate: "",
  };

  const labelInfoList = data["label-info"] || [];
  if (labelInfoList.length > 0) {
    const li = labelInfoList[0];
    info.label = (li.label || {}).name || "";
    info.catalogNumber = li["catalog-number"] || "";
  }

  const rg = data["release-group"] || {};
  info.releaseGroupId = rg.id || "";
  info.type = rg["primary-type"] || rg.type || "";
  info.firstReleaseDate = rg["first-release-date"] || "";

  const releaseCredits = data["artist-credit"] || [];
  if (releaseCredits.length > 0 && typeof releaseCredits[0] === "object") {
    info.artist = (releaseCredits[0].artist || {}).name || "";
  }

  const tracks = [];
  for (const medium of data.media || []) {
    const disc = parseInt(medium.position || 1, 10);
    for (const track of medium.tracks || []) {
      const rec = track.recording || {};
      let artistName = "";
      const credits = rec["artist-credit"] || [];
      if (credits.length > 0 && typeof credits[0] === "object") {
        artistName = (credits[0].artist || {}).name || "";
      }
      tracks.push({
        position: parseInt(track.position || 0, 10),
        disc,
        number: track.number || "",
        title: track.title || rec.title || "",
        length: parseInt(rec.length || 0, 10) || 0,
        recordingId: rec.id || "",
        artist: artistName,
      });
    }
  }

  return { info, tracks };
}

/* ── Cover art ── */

/**
 * Fetch the front cover image for a release as an ArrayBuffer.
 * Tries the 500 px thumbnail first, then falls back to full size.
 * Returns null if no image is found.
 *
 * @param {string} releaseId
 * @returns {Promise<ArrayBuffer|null>}
 */
async function getCoverArt(releaseId) {
  const urls = [
    `https://coverartarchive.org/release/${releaseId}/front-500`,
    `https://coverartarchive.org/release/${releaseId}/front`,
  ];
  for (const url of urls) {
    try {
      const resp = await fetch(url);
      if (resp.ok) return resp.arrayBuffer();
    } catch (_) {
      // try next URL
    }
  }
  return null;
}

/* ── Lyrics ── */

/**
 * Fetch lyrics from lyrics.ovh (free, no key required).
 * Returns the lyrics string or null.
 *
 * @param {string} artist
 * @param {string} title
 * @returns {Promise<string|null>}
 */
async function getLyricsOvh(artist, title) {
  try {
    const url = `https://api.lyrics.ovh/v1/${encodeURIComponent(artist)}/${encodeURIComponent(title)}`;
    const resp = await fetch(url);
    if (!resp.ok) return null;
    const data = await resp.json();
    return data.lyrics || null;
  } catch (_) {
    return null;
  }
}

/**
 * Fetch lyrics using the best available source.
 * Falls back to lyrics.ovh when no Genius token is provided (or the
 * Genius search yields no result — Genius does not expose raw lyrics via
 * its public API without scraping, so we always fall through to lyrics.ovh).
 *
 * @param {string} artist
 * @param {string} title
 * @param {string} [geniusToken=""]
 * @returns {Promise<string|null>}
 */
async function getLyrics(artist, title, geniusToken = "") {
  return getLyricsOvh(artist, title);
}
