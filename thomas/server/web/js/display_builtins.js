/* The first two plugged-in renderers for the display kernel: "markdown" and "table". They register through
   ThomasDisplay.register like any other renderer would. "markdown" wraps ThomasMarkdown.mdToHtml, so a reply that is
   plain markdown draws exactly as it did before the kernel. "table" draws row lines, a stripe on every other row, and a
   heavier line under the header, the same look the Build reply gets in unified_code_plain.css. */
(function () {
  'use strict';
  const kernel = window.ThomasDisplay;
  if (!kernel) return;
  const esc = kernel.esc;

  function markdownApi() {
    const markdown = window.ThomasMarkdown;
    return markdown && typeof markdown.mdToHtml === 'function' ? markdown : null;
  }

  function renderMarkdown(data) {
    if (!data || typeof data.text !== 'string') throw new TypeError('a markdown block carries data.text');
    const markdown = markdownApi();
    return markdown ? markdown.mdToHtml(data.text) : esc(data.text);
  }

  function cell(text) {
    const markdown = window.ThomasMarkdown;
    return markdown && typeof markdown._mdInline === 'function' ? markdown._mdInline(String(text == null ? '' : text)) : esc(text);
  }

  function renderTable(data) {
    if (!data || !Array.isArray(data.headers) || !data.headers.length || !Array.isArray(data.rows)) {
      throw new TypeError('a table block carries data.headers and data.rows');
    }
    const aligns = Array.isArray(data.aligns) ? data.aligns : [];
    const at = i => (aligns[i] === 'left' || aligns[i] === 'right' || aligns[i] === 'center' ? ' style="text-align:' + aligns[i] + '"' : '');
    const head = data.headers.map((h, i) => '<th' + at(i) + '>' + cell(h) + '</th>').join('');
    const body = data.rows.map(row => {
      if (!Array.isArray(row)) throw new TypeError('each table row is a list of cells');
      return '<tr>' + data.headers.map((_h, i) => '<td' + at(i) + '>' + cell(row[i]) + '</td>').join('') + '</tr>';
    }).join('');
    return '<div class="tc-md-table tc-display-table"><table><thead><tr>' + head + '</tr></thead><tbody>' + body + '</tbody></table></div>';
  }

  const TABLE_CSS = [
    '.tc-display-table{margin:14px 0 18px;max-width:100%;overflow-x:auto}',
    '.tc-display-table table{border-collapse:collapse;width:100%;font-size:14px;line-height:1.5;--row-line:color-mix(in srgb,var(--c-text) 16%,transparent)}',
    '.tc-display-table th,.tc-display-table td{border:0;border-bottom:1px solid var(--row-line);padding:9px 14px 9px 0;text-align:left;vertical-align:top;background:none;overflow-wrap:anywhere}',
    '.tc-display-table th{border-bottom:2px solid color-mix(in srgb,var(--c-text) 30%,transparent);color:var(--c-strong);font-weight:650;white-space:nowrap}',
    '.tc-display-table tbody tr:nth-child(even) td{background:color-mix(in srgb,var(--c-text) 4%,transparent)}',
    '.tc-display-table td code{font-size:.86em}',
  ].join('\n');

  kernel.register('markdown', { render: renderMarkdown, version: 1 });
  kernel.register('table', { render: renderTable, css: TABLE_CSS, version: 1 });

  // Producers build blocks through these, so a block always carries its words.
  kernel.blocks.markdown = text => kernel.makeBlock('markdown', { text: String(text || '') }, String(text || ''));
  kernel.blocks.table = (headers, rows, aligns) => kernel.makeBlock(
    'table', { headers, rows, aligns: aligns || [] },
    [headers.join(' | ')].concat(rows.map(row => headers.map((_h, i) => (row[i] == null ? '' : String(row[i]))).join(' | '))).join('\n'));
})();
