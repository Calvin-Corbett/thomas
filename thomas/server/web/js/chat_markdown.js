/* Chat markdown. Dependencies are supplied by the shell. */
(function () {
  'use strict';
  function create(deps) {

    function _looksLikeDoc(s) { return (/\n/.test(s) && s.length > 70) || s.length > 240; }

    // Minimal, streaming-tolerant Markdown -> HTML (re-rendered each chunk; partial
    // trailing lines just render as a paragraph until the next chunk completes them).
    function _mdInline(s) {
      s = deps.esc(s);
      s = s.replace(/`([^`]+)`/g, '<code>$1</code>');
      s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      s = s.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>');
      s = s.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
      return s;
    }

    // GFM table plumbing for mdToHtml. _tableCells splits a row treating "\|" as cell CONTENT, not a boundary; _tableAligns recognizes the delimiter row ("|:---|---:|") and reads its alignment colons. A line failing these checks is not table syntax and keeps mdToHtml's raw-text fallback.
    function _tableCells(line) { let s = String(line).trim(); if (s.startsWith('|')) s = s.slice(1); if (s.endsWith('|') && !s.endsWith('\\|')) s = s.slice(0, -1); return s.replace(/\\\|/g, '\u0000').split('|').map(c => c.replace(/\u0000/g, '|').trim()); }

    function _tableAligns(line) { if (String(line).indexOf('-') === -1) return null; const cells = _tableCells(line), aligns = []; if (!cells.length) return null; for (const c of cells) { if (!/^:?-+:?$/.test(c)) return null; aligns.push(c.startsWith(':') && c.endsWith(':') ? 'center' : c.endsWith(':') ? 'right' : ''); } return aligns; }

    function mdToHtml(md) {
      const lines = String(md || '').replace(/\r/g, '').split('\n');
      let html = '', list = null, code = null;
      const closeList = () => { if (list) { html += '</' + list + '>'; list = null; } };
      const closeCode = () => { if (code) { html += '<pre><code>' + deps.esc(code.join('\n')) + '</code></pre>'; code = null; } };
      for (let li = 0; li < lines.length; li++) {
        const raw = lines[li], line = raw.replace(/\s+$/, ''); let m;
        if (/^\s*```/.test(line)) { closeList(); if (code) closeCode(); else code = []; continue; }
        if (code) { code.push(raw); continue; }
        if (/^\s*$/.test(line)) { closeList(); continue; }
        if ((m = line.match(/^\s*(#{1,3})\s+(.*)$/))) { closeList(); const n = m[1].length; html += '<h' + n + '>' + _mdInline(m[2]) + '</h' + n + '>'; continue; }
        if (/^\s*(---+|\*\*\*+|___+)\s*$/.test(line)) { closeList(); html += '<hr>'; continue; }
        if ((m = line.match(/^\s*[-*]\s+(.*)$/))) { if (list !== 'ul') { closeList(); list = 'ul'; html += '<ul>'; } html += '<li>' + _mdInline(m[1]) + '</li>'; continue; }
        if ((m = line.match(/^\s*(\d+)[.)]\s+(.*)$/))) { if (list !== 'ol') { closeList(); list = 'ol'; html += '<ol start="' + m[1] + '">'; } html += '<li>' + _mdInline(m[2]) + '</li>'; continue; }
        // GFM table: a header row whose NEXT line is a matching delimiter row. Measured (2026-08-05): an explicitly-requested budget table hit the paragraph fallback below — 0 <table> elements in the DOM, every row its own <p> of literal pipes; the model wrote correct markdown, this renderer just didn't speak it. Ragged body rows normalize to the header's width (GFM behavior); a pipe line with no delimiter row underneath is NOT a table and keeps the raw-text fallback.
        const tA = (line.indexOf('|') !== -1 && li + 1 < lines.length) ? _tableAligns(lines[li + 1]) : null, tH = tA ? _tableCells(line) : null;
        if (tH && tH.length === tA.length) {
          closeList(); const at = i => tA[i] ? ' style="text-align:' + tA[i] + '"' : ''; let bi = li + 2, body = '';
          for (; bi < lines.length && lines[bi].indexOf('|') !== -1 && !/^\s*$/.test(lines[bi]); bi++) { const cs = _tableCells(lines[bi]); body += '<tr>' + tH.map((_c, i) => '<td' + at(i) + '>' + _mdInline(cs[i] || '') + '</td>').join('') + '</tr>'; }
          html += '<div class="tc-md-table"><table><thead><tr>' + tH.map((c, i) => '<th' + at(i) + '>' + _mdInline(c) + '</th>').join('') + '</tr></thead>' + (body ? '<tbody>' + body + '</tbody>' : '') + '</table></div>'; li = bi - 1; continue;
        }
        closeList(); html += '<p>' + _mdInline(line) + '</p>';
      }
      closeList(); closeCode();
      return html;
    }
    return { _looksLikeDoc, _mdInline, _tableCells, _tableAligns, mdToHtml };
  }
  window.ThomasChatMarkdown = { create };
})();
