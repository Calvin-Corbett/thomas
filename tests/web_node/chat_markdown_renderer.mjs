import fs from 'node:fs';
import vm from 'node:vm';

const htmlPath = process.argv[2];
if (!htmlPath) throw new Error('usage: node chat_markdown_renderer.mjs <chat.html>');
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
    functionSource('bubbleInner', 'copyMessageText'),
    functionSource('_mdInline', 'mdToHtml'),
    functionSource('mdToHtml', 'renderCanvas'),
  ].join('\n'),
  context,
);

const qaAnswer = [
  '## Eight-Step Product QA Plan',
  '',
  '### 1. Verify Chat',
  '- **User action:** Start the task.',
  '- **Expected behavior:** It survives a mode switch.',
  '',
  'CHAT_SWITCH_SURVIVED_0718_FINAL',
].join('\n');
const rendered = context.bubbleInner({ role: 'assistant', text: qaAnswer, streaming: false });
const userLiteral = context.bubbleInner({ role: 'user', text: '**keep literal** <script>x</script>', streaming: false });
const unsafe = context.mdToHtml('### Safe\n<script>alert(1)</script>\n[bad](javascript:alert(2))');
const fenced = context.mdToHtml('```html\n<script>alert(3)</script>\n```');

const checks = {
  heading: rendered.includes('<h2>Eight-Step Product QA Plan</h2>') && rendered.includes('<h3>1. Verify Chat</h3>'),
  list: rendered.includes('<ul><li><strong>User action:</strong> Start the task.</li>'),
  marker: rendered.includes('<p>CHAT_SWITCH_SURVIVED_0718_FINAL</p>'),
  userLiteral: userLiteral === '**keep literal** &lt;script&gt;x&lt;/script&gt;',
  escapedHtml: unsafe.includes('&lt;script&gt;alert(1)&lt;/script&gt;') && !unsafe.includes('<script>'),
  safeLinksOnly: !unsafe.includes('href='),
  fencedCode: fenced.includes('<pre><code>&lt;script&gt;alert(3)&lt;/script&gt;</code></pre>'),
};

for (const [name, passed] of Object.entries(checks)) {
  if (!passed) throw new Error(`chat Markdown check failed: ${name}`);
}
process.stdout.write(`${JSON.stringify(checks)}\n`);
