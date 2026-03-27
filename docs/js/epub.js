/**
 * epub.js — client-side EPUB 3 builder.
 *
 * Requires JSZip to be loaded before this file.
 * Exposes a single public function: buildAlbumEbook().
 */

"use strict";

/* ── Internal helpers ── */

/**
 * Return a URL/filename-safe slug (max 60 characters).
 * @param {string} text
 * @returns {string}
 */
function slugify(text) {
  return (text || "")
    .toLowerCase()
    .replace(/[^\w\s-]/g, "")
    .trim()
    .replace(/[-\s]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
}

/**
 * Convert milliseconds to a "M:SS" string.
 * Returns an empty string for falsy input.
 * @param {number} ms
 * @returns {string}
 */
function fmtDuration(ms) {
  if (!ms) return "";
  const totalSec = Math.round(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

/**
 * Escape HTML special characters.
 * @param {string|null|undefined} text
 * @returns {string}
 */
function esc(text) {
  return (text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * Convert plain-text lyrics to an HTML fragment.
 * Lines matching /^\[.*\]$/ become section headers; blank lines separate
 * paragraphs; other lines become <br/>-joined content inside <p> elements.
 *
 * @param {string|null} lyrics
 * @returns {string} — HTML string (no surrounding wrapper element)
 */
function lyricsToHtml(lyrics) {
  if (!lyrics || !lyrics.trim()) {
    return '<p class="no-lyrics"><em>Lyrics not available.</em></p>';
  }

  const HEADER_RE = /^\[.+\]$/;
  const paragraphs = lyrics.split(/\n\n+/);
  const parts = [];

  for (const para of paragraphs) {
    const trimmed = para.trim();
    if (!trimmed) continue;

    const lines = trimmed.split("\n");
    const pending = [];

    for (const line of lines) {
      const stripped = line.trim();
      if (HEADER_RE.test(stripped)) {
        if (pending.length > 0) {
          parts.push(`<p>${pending.map(esc).join("<br/>")}</p>`);
          pending.length = 0;
        }
        parts.push(`<p class="section-header"><em>${esc(stripped)}</em></p>`);
      } else {
        pending.push(line);
      }
    }
    if (pending.length > 0) {
      parts.push(`<p>${pending.map(esc).join("<br/>")}</p>`);
    }
  }

  return parts.join("\n");
}

/* ── Public API ── */

/**
 * Build an EPUB 3 ebook for a single album and return it as a Blob.
 *
 * @param {Object}            artistInfo   — { id, name }
 * @param {Object}            releaseInfo  — release metadata from getReleaseTracks()
 * @param {Array}             tracks       — track list from getReleaseTracks()
 * @param {Object}            lyricsMap    — { [trackPosition]: lyricsString }
 * @param {ArrayBuffer|null}  coverImage   — JPEG image bytes, or null
 * @returns {Promise<Blob>}
 */
async function buildAlbumEbook(artistInfo, releaseInfo, tracks, lyricsMap, coverImage) {
  const zip = new JSZip(); // JSZip must be loaded from the page

  const artistName = (artistInfo && artistInfo.name) || "Unknown Artist";
  const albumTitle = (releaseInfo && releaseInfo.title) || "Unknown Album";
  const releaseYear = ((releaseInfo.firstReleaseDate || releaseInfo.date || "").slice(0, 4));
  const bookTitle = releaseYear
    ? `${artistName} \u2013 ${albumTitle} (${releaseYear})`
    : `${artistName} \u2013 ${albumTitle}`;

  const uid = `urn:uuid:${releaseInfo.id || String(Date.now())}`;
  const todayISO = new Date().toISOString().slice(0, 10);

  // Manifest and spine are built up incrementally
  const manifestItems = [];
  const spineItems = [];

  /* ── mimetype (must be stored uncompressed and first) ── */
  zip.file("mimetype", "application/epub+zip", { compression: "STORE" });

  /* ── META-INF/container.xml ── */
  zip.file(
    "META-INF/container.xml",
    `<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>`
  );

  /* ── Shared stylesheet ── */
  const stylesheet = `
body            { margin: 1.5em; font-family: serif; line-height: 1.7; }
h1.song-title   { font-size: 1.6em; margin-bottom: 0.1em; }
p.song-meta     { color: #666; font-size: 0.85em; margin-bottom: 1.5em; }
.lyrics p       { margin: 0 0 0.8em; }
.section-header { display: block; font-weight: bold; color: #555; font-style: italic; margin-top: 1em; }
.no-lyrics      { color: #888; font-style: italic; }
`.trimStart();

  zip.file("OEBPS/style.css", stylesheet);
  manifestItems.push(`<item id="css" href="style.css" media-type="text/css"/>`);

  /* ── Cover image (optional) ── */
  if (coverImage) {
    zip.file("OEBPS/cover.jpg", coverImage);
    manifestItems.push(
      `<item id="cover-img" href="cover.jpg" media-type="image/jpeg" properties="cover-image"/>`
    );
  }

  /* ── Cover page ── */
  const coverPageXhtml = coverImage
    ? `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops"
      xml:lang="en" lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>Cover</title>
  <style>body{margin:0;padding:0;text-align:center;background:#000;}img{max-width:100%;max-height:100vh;}</style>
</head>
<body epub:type="cover">
  <img src="cover.jpg" alt="${esc(albumTitle)} cover art"/>
</body>
</html>`
    : `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops"
      xml:lang="en" lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>Cover</title>
  <style>
    body{margin:3em 2em;font-family:serif;text-align:center;}
    h1{font-size:2.2em;margin-bottom:0.2em;}
    p{color:#555;}
  </style>
</head>
<body epub:type="cover">
  <h1>${esc(albumTitle)}</h1>
  <p>${esc(artistName)}</p>
  ${releaseYear ? `<p>${esc(releaseYear)}</p>` : ""}
</body>
</html>`;

  zip.file("OEBPS/cover.xhtml", coverPageXhtml);
  manifestItems.push(`<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>`);
  spineItems.push(`<itemref idref="cover"/>`);

  /* ── Title page ── */
  const metaRows = [];
  if (releaseInfo.label) metaRows.push(`<tr><th>Label</th><td>${esc(releaseInfo.label)}</td></tr>`);
  if (releaseInfo.type) metaRows.push(`<tr><th>Type</th><td>${esc(releaseInfo.type)}</td></tr>`);
  if (releaseInfo.date) metaRows.push(`<tr><th>Release date</th><td>${esc(releaseInfo.date)}</td></tr>`);
  if (releaseInfo.country) metaRows.push(`<tr><th>Country</th><td>${esc(releaseInfo.country)}</td></tr>`);

  const titlePageXhtml = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops"
      xml:lang="en" lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>${esc(bookTitle)}</title>
  <style>
    body{margin:3em 2em;font-family:serif;}
    h1{font-size:2em;margin-bottom:0.15em;}
    h2{font-size:1.25em;color:#444;margin-top:0;font-weight:normal;}
    table{border-collapse:collapse;margin-top:1.5em;}
    th{text-align:left;color:#666;padding:0.3em 1em 0.3em 0;font-weight:normal;}
    td{padding:0.3em 0;}
    .source{margin-top:2.5em;font-size:0.78em;color:#888;}
  </style>
</head>
<body epub:type="titlepage">
  <h1>${esc(albumTitle)}</h1>
  <h2>${esc(artistName)}</h2>
  ${metaRows.length > 0 ? `<table>${metaRows.join("\n  ")}</table>` : ""}
  <p class="source">Lyrics sourced via lyrics.ovh and MusicBrainz. Generated by Song Lyrics to Ebook.</p>
</body>
</html>`;

  zip.file("OEBPS/titlepage.xhtml", titlePageXhtml);
  manifestItems.push(`<item id="titlepage" href="titlepage.xhtml" media-type="application/xhtml+xml"/>`);
  spineItems.push(`<itemref idref="titlepage"/>`);

  /* ── Song chapters ── */
  const tocEntries = [];

  for (const track of tracks) {
    const idx = String(track.position).padStart(3, "0");
    const chapterId = `song-${idx}`;
    const filename = `${chapterId}.xhtml`;
    const rawLyrics = lyricsMap[track.position] || null;
    const cleaned = rawLyrics ? cleanLyrics(rawLyrics) : null;
    const trackArtist = track.artist || artistName;
    const duration = fmtDuration(track.length);

    const chapterXhtml = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops"
      xml:lang="en" lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>${esc(track.title)}</title>
  <link rel="stylesheet" type="text/css" href="style.css"/>
</head>
<body epub:type="chapter">
  <h1 class="song-title">${esc(track.title)}</h1>
  <p class="song-meta">${esc(trackArtist)}${duration ? ` \u00b7 ${esc(duration)}` : ""}</p>
  <div class="lyrics">
${lyricsToHtml(cleaned)}
  </div>
</body>
</html>`;

    zip.file(`OEBPS/${filename}`, chapterXhtml);
    manifestItems.push(
      `<item id="${chapterId}" href="${filename}" media-type="application/xhtml+xml"/>`
    );
    spineItems.push(`<itemref idref="${chapterId}"/>`);
    tocEntries.push({ id: chapterId, href: filename, title: track.title });
  }

  /* ── Navigation document (nav.xhtml — EPUB 3 required) ── */
  const navItems = tocEntries
    .map((e) => `      <li><a href="${e.href}">${esc(e.title)}</a></li>`)
    .join("\n");

  const navXhtml = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops"
      xml:lang="en" lang="en">
<head><meta charset="UTF-8"/><title>Contents</title></head>
<body>
  <nav epub:type="toc" id="toc">
    <h1>Contents</h1>
    <ol>
${navItems}
    </ol>
  </nav>
</body>
</html>`;

  zip.file("OEBPS/nav.xhtml", navXhtml);
  manifestItems.push(
    `<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>`
  );

  /* ── NCX (EPUB 2 compatibility) ── */
  const ncxNavPoints = tocEntries
    .map(
      (e, i) => `  <navPoint id="np-${i + 1}" playOrder="${i + 1}">
    <navLabel><text>${esc(e.title)}</text></navLabel>
    <content src="${e.href}"/>
  </navPoint>`
    )
    .join("\n");

  const ncx = `<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head>
    <meta name="dtb:uid" content="${uid}"/>
    <meta name="dtb:depth" content="1"/>
    <meta name="dtb:totalPageCount" content="0"/>
    <meta name="dtb:maxPageNumber" content="0"/>
  </head>
  <docTitle><text>${esc(bookTitle)}</text></docTitle>
  <navMap>
${ncxNavPoints}
  </navMap>
</ncx>`;

  zip.file("OEBPS/toc.ncx", ncx);
  manifestItems.push(
    `<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>`
  );

  /* ── content.opf (package document) ── */
  const opf = `<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf"
         version="3.0"
         unique-identifier="uid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="uid">${uid}</dc:identifier>
    <dc:title>${esc(bookTitle)}</dc:title>
    <dc:creator>${esc(artistName)}</dc:creator>
    <dc:language>en</dc:language>
    <dc:date>${releaseYear || todayISO}</dc:date>
    <meta property="dcterms:modified">${todayISO}T00:00:00Z</meta>
  </metadata>
  <manifest>
    ${manifestItems.join("\n    ")}
  </manifest>
  <spine toc="ncx">
    ${spineItems.join("\n    ")}
  </spine>
</package>`;

  zip.file("OEBPS/content.opf", opf);

  /* ── Generate and return blob ── */
  return zip.generateAsync({ type: "blob", mimeType: "application/epub+zip" });
}
