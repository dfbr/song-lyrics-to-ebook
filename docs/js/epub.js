/**
 * epub.js — client-side EPUB 3 builder.
 *
 * Requires JSZip to be loaded before this file.
 * Requires utils.js to be loaded before this file (for slugify, fmtDuration,
 * esc, lyricsToHtml, cleanLyrics).
 *
 * Exposes a single public function: buildAlbumEbook().
 */

"use strict";

/**
 * Build an EPUB 3 ebook for a single album and return it as a Blob.
 *
 * @param {Object}            artistInfo   — { id, name }
 * @param {Object}            releaseInfo  — release metadata from getReleaseTracks()
 * @param {Array}             tracks       — track list from getReleaseTracks()
 * @param {Object}            lyricsMap    — { [trackPosition]: lyricsString }
 * @param {ArrayBuffer|null}  coverImage   — JPEG image bytes, or null
 * @param {string}            [lyricsSource] — name of the lyrics provider (e.g. "lyrics.ovh" or "Genius")
 * @returns {Promise<Blob>}
 */
async function buildAlbumEbook(artistInfo, releaseInfo, tracks, lyricsMap, coverImage, lyricsSource) {
  const zip = new JSZip(); // JSZip must be loaded from the page

  const artistName = (artistInfo && artistInfo.name) || "Unknown Artist";
  const albumTitle = (releaseInfo && releaseInfo.title) || "Unknown Album";
  const releaseYear = ((releaseInfo.firstReleaseDate || releaseInfo.date || "").slice(0, 4));
  const bookTitle = releaseYear
    ? `${artistName} \u2013 ${albumTitle} (${releaseYear})`
    : `${artistName} \u2013 ${albumTitle}`;

  const uid = `urn:uuid:${releaseInfo.id || String(Date.now())}`;
  const todayISO = new Date().toISOString().slice(0, 10);
  const sourceName = lyricsSource || "lyrics.ovh";

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
.disclaimer     { font-size: 0.78em; color: #888; margin-top: 2.5em; border-top: 1px solid #ddd; padding-top: 1em; }
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
  const coverDensity = coverDensityClass(artistName, albumTitle);
  const coverImageHtml = coverImage
    ? `<img class="cover-image" src="cover.jpg" alt="${esc(albumTitle)} cover art"/>`
    : "";
  const coverYearHtml = releaseYear ? `<p class="cover-year">${esc(releaseYear)}</p>` : "";

  const coverPageXhtml = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops"
      xml:lang="en" lang="en">
<head>
  <meta charset="UTF-8"/>
  <title>Cover</title>
  <style>
    body{margin:0;padding:0;}
    .cover-page{
      min-height:100vh;
      box-sizing:border-box;
      padding:7vh 8vw 4vh;
      display:flex;
      flex-direction:column;
      justify-content:space-between;
      gap:3vh;
      background:#f7f6f2;
      color:#1d1d1d;
      text-align:center;
    }
    .cover-top{
      margin:0 auto;
      width:100%;
      max-width:38em;
    }
    .cover-artist,
    .cover-album,
    .cover-year{
      font-family:"Avenir Next","Helvetica Neue",Helvetica,Arial,sans-serif;
      margin:0;
      hyphens:none;
      word-break:normal;
      overflow-wrap:normal;
    }
    .cover-artist{
      text-transform:uppercase;
      letter-spacing:0.18em;
      color:#565656;
      font-size:0.95rem;
      margin-bottom:0.8rem;
    }
    .cover-album{
      line-height:1.1;
      margin-bottom:0.7rem;
      color:#121212;
      font-size:2.2rem;
      font-weight:700;
    }
    .cover-year{
      letter-spacing:0.08em;
      color:#6a6a6a;
      font-size:1rem;
    }
    .cover-bottom{
      flex:1 1 auto;
      display:flex;
      justify-content:center;
      align-items:flex-end;
    }
    .cover-image{
      max-width:75vw;
      max-height:52vh;
      width:auto;
      height:auto;
      object-fit:contain;
      box-shadow:0 1.2rem 2.6rem rgba(0,0,0,.2);
    }
    .cover-density-compact .cover-album{font-size:1.9rem;}
    .cover-density-compact .cover-artist,
    .cover-density-compact .cover-year{font-size:0.9rem;}
    .cover-density-tight .cover-album{font-size:1.62rem;line-height:1.08;}
    .cover-density-tight .cover-artist,
    .cover-density-tight .cover-year{font-size:0.82rem;}
  </style>
</head>
<body epub:type="cover">
  <div class="cover-page ${coverDensity}">
    <div class="cover-top">
      <p class="cover-artist">${esc(artistName)}</p>
      <h1 class="cover-album">${esc(albumTitle)}</h1>
      ${coverYearHtml}
    </div>
    <div class="cover-bottom">
      ${coverImageHtml}
    </div>
  </div>
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
  <p class="source">Lyrics sourced via ${esc(sourceName)} and MusicBrainz. Generated by Song Lyrics to Ebook.</p>
  <p class="disclaimer">This ebook is for personal, educational and non-commercial use only. Lyrics are the copyright of their respective owners and artists. Do not distribute or publish this ebook.</p>
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

function coverDensityClass(artistName, albumTitle) {
  const totalLen = `${artistName || ""}${albumTitle || ""}`.trim().length;
  const words = `${artistName || ""} ${albumTitle || ""}`.trim().split(/\s+/).filter(Boolean);
  const longestWord = words.length > 0 ? words.reduce((maxLen, word) => Math.max(maxLen, word.length), 0) : 0;

  if (totalLen > 92 || longestWord > 24) return "cover-density-tight";
  if (totalLen > 68 || longestWord > 18) return "cover-density-compact";
  return "cover-density-normal";
}
