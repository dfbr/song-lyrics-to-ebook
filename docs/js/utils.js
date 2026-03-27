/**
 * utils.js — shared utility functions for the Song Lyrics to Ebook web app.
 *
 * Loaded first so that api.js, epub.js, and app.js can all rely on these
 * helpers without cross-file imports.
 */

"use strict";

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

/**
 * Normalise lyrics text: collapse runs of blank lines to a single blank line
 * and strip leading/trailing whitespace.
 *
 * @param {string|null} raw
 * @returns {string}
 */
function cleanLyrics(raw) {
  if (!raw) return "";
  return raw
    .replace(/\r\n/g, "\n")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/** Resolve after `ms` milliseconds. */
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
