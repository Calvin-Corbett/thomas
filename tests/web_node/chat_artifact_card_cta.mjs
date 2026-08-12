// The file-deliverable card's two calls to action, rendered for real.
//
// Measured defects (2026-08-05, live):
//   1. "Download packing.txt" spilled out of the 42px download button as
//      visible wrapping text. The anchor hides its label in a
//      class="sr-only" span — but chat.html never linked css/accessibility.css
//      (the only stylesheet that defines .sr-only), so the label rendered
//      visibly inside a box sized for one icon.
//   2. The secondary action read "Open UTF-8 preview" — encoding jargon where
//      the user just wants "Preview".
import fs from 'node:fs';
import vm from 'node:vm';

const htmlPath = process.argv[2];
if (!htmlPath) throw new Error('usage: node chat_artifact_card_cta.mjs <chat.html>');
const html = fs.readFileSync(htmlPath, 'utf8');

function functionSource(name, nextName) {
  const start = html.indexOf(`function ${name}(`);
  let end = html.indexOf(`\n    function ${nextName}(`, start);
  if (end < 0) end = html.indexOf(`\n    async function ${nextName}(`, start);
  if (start < 0 || end < 0) throw new Error(`could not extract ${name}`);
  return html.slice(start, end);
}

const context = {};
vm.createContext(context);
vm.runInContext(
  [
    functionSource('esc', 'botHTML'),
    functionSource('_isTextArtifact', 'canvasRender'),
    functionSource('artifactDownloadUrl', 'artifactHTML'),
    functionSource('artifactHTML', '_thinkingCard'),
  ].join('\n'),
  context,
);

const longName = 'seasonal-packing-checklist-for-the-whole-family-2026-final.txt';
const card = context.artifactHTML({ artifact: { name: 'packing.txt', url: '/deliverable/abc/packing.txt', kind: 'text' } });
const longCard = context.artifactHTML({ artifact: { name: longName, url: '/deliverable/abc/' + longName, kind: 'text' } });

// Every download label in the card must be a hidden .sr-only span — never a
// bare visible text node inside the icon-sized anchor.
function labelsAreHidden(rendered) {
  const anchors = rendered.match(/<a [^>]*data-artifact-download[^>]*>.*?<\/a>/gs) || [];
  if (!anchors.length) return false;
  return anchors.every(a => {
    const visible = a
      .replace(/<span class="sr-only">.*?<\/span>/gs, '')
      .replace(/<[^>]+>/g, '')
      .trim();
    return visible === '' && a.includes('<span class="sr-only">Download ');
  });
}

// The class the labels rely on must actually exist on this page: chat.html
// does not link css/accessibility.css, so a .sr-only rule has to be defined
// in the page's own stylesheet or the "hidden" label is fully visible.
// The rule now lives in css/tokens.css (the single design-token source);
// the guard holds if the page defines it locally OR links tokens.css and
// tokens.css defines it — either way the label can never render visible.
import path from 'node:path';
const tokensPath = path.join(path.dirname(htmlPath), 'css', 'tokens.css');
const srOnlyLocal = /\.sr-only\s*[,{]/.test(html);
const srOnlyFromTokens =
  html.includes('/static/css/tokens.css') &&
  fs.existsSync(tokensPath) &&
  /\.sr-only\s*[,{]/.test(fs.readFileSync(tokensPath, 'utf8'));
const srOnlyDefined = srOnlyLocal || srOnlyFromTokens;

const checks = {
  downloadLabelHidden: labelsAreHidden(card) && labelsAreHidden(longCard),
  srOnlyRuleExists: srOnlyDefined,
  previewNotJargon: card.includes('>Preview<') && !card.includes('UTF-8'),
  longNameStaysInCard: longCard.includes('text-overflow:ellipsis') && labelsAreHidden(longCard),
};

for (const [name, passed] of Object.entries(checks)) {
  if (!passed) throw new Error(`artifact card CTA check failed: ${name}`);
}
process.stdout.write(`${JSON.stringify(checks)}\n`);
