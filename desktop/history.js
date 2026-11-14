/* history.js — the browsing history the app keeps on its own disk (one JSON
 * line per page), split out of main.js. `create` takes the places it writes.
 */
"use strict";

const fs = require("node:fs");

function create({ historyPath, log }) {
  const HISTORY_PATH = historyPath;
  let lastHistoryKey = "";
  function recordHistory(url, title) {
    if (!url || url === "about:blank") return;
    const key = url + " " + (title || "");
    if (key === lastHistoryKey) return;
    lastHistoryKey = key;
    try {
      fs.appendFileSync(HISTORY_PATH(), JSON.stringify({ at: new Date().toISOString(), url, title: title || "" }) + "\n");
    } catch (e) { log("history write failed", e); }
  }
  function readHistory(query, limit) {
    try {
      const lines = fs.readFileSync(HISTORY_PATH(), "utf8").trim().split("\n");
      const q = String(query || "").toLowerCase();
      const rows = [];
      for (let i = lines.length - 1; i >= 0 && rows.length < (limit || 100); i--) {
        let row;
        try { row = JSON.parse(lines[i]); } catch (_) { continue; }
        // A row without a url used to throw past this loop and out of the
        // function, so ONE corrupt line (a crash mid-append, a hand edit)
        // returned an empty history for every query -- indistinguishable from
        // having no history at all. Skip the bad line, keep the rest.
        const url = typeof row.url === "string" ? row.url : "";
        if (!url) continue;
        const title = typeof row.title === "string" ? row.title : "";
        if (!q || url.toLowerCase().includes(q) || title.toLowerCase().includes(q)) rows.push(row);
      }
      return rows;
    } catch (_) { return []; }
  }
  return { recordHistory, readHistory };
}

module.exports = { create };
