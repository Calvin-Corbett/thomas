// Drives the actual Markdown feature factory with GFM tables, like
// chat_markdown_renderer.mjs. Measured defect (2026-08-05, live): a budget
// table the user explicitly asked for rendered as literal pipe text — zero
// <table> elements in the DOM, each row its own <p>.
import { installFeature, installInlineCore } from './chat_feature_fixture.mjs';

const htmlPath = process.argv[2];
if (!htmlPath) throw new Error('usage: node chat_markdown_tables.mjs <chat.html>');

const context = {};
installInlineCore(context, htmlPath);
installFeature(context, htmlPath, 'markdown', ['mdToHtml']);

// The shape the budget answer actually used: header row, delimiter row with
// alignment colons, body rows. One cell carries an escaped pipe.
const budget = [
  'Here is the budget:',
  '',
  '| Category | Monthly | Share |',
  '|:---------|--------:|:-----:|',
  '| Rent | $1,200 | 40% |',
  '| Food \\| dining | $450 | 15% |',
  '',
  'Totals below.',
].join('\n');
const rendered = context.mdToHtml(budget);

// A pipe line NOT followed by a delimiter row is not a table — it must keep
// the raw-text fallback (one paragraph per line), never half a table.
const malformed = context.mdToHtml('| a | b |\n| just | words |');

// A body row with fewer cells than the header pads out; extra cells drop.
const ragged = context.mdToHtml('| A | B |\n| --- | --- |\n| one |\n| x | y | z |');

const checks = {
  realTable: rendered.includes('<table>') && rendered.includes('</table>'),
  headerCells: rendered.includes('<th>Category</th>'),
  rightAlign: rendered.includes('<th style="text-align:right">Monthly</th>') && rendered.includes('<td style="text-align:right">$1,200</td>'),
  centerAlign: rendered.includes('<th style="text-align:center">Share</th>') && rendered.includes('<td style="text-align:center">40%</td>'),
  bodyCell: rendered.includes('<td>Rent</td>'),
  escapedPipe: rendered.includes('Food | dining'),
  delimiterNotARow: !rendered.includes(':---'),
  proseAroundSurvives: rendered.includes('<p>Here is the budget:</p>') && rendered.includes('<p>Totals below.</p>'),
  malformedStaysText: !malformed.includes('<table>') && malformed.includes('<p>| a | b |</p>'),
  raggedRowsNormalize: ragged.includes('<td>one</td><td></td>') && !ragged.includes('<td>z</td>'),
};

for (const [name, passed] of Object.entries(checks)) {
  if (!passed) throw new Error(`chat GFM table check failed: ${name}`);
}
process.stdout.write(`${JSON.stringify(checks)}\n`);
