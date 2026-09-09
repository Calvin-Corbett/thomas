import fs from 'node:fs';
import vm from 'node:vm';

const htmlPath = process.argv[2];
if (!htmlPath) throw new Error('usage: node chat_message_model_attribution.mjs <chat.html>');
const html = fs.readFileSync(htmlPath, 'utf8');

function functionSource(name, nextName) {
  const start = html.indexOf(`function ${name}(`);
  let end = html.indexOf(`\n    function ${nextName}(`, start);
  if (end < 0) end = html.indexOf(`\n    async function ${nextName}(`, start);
  if (start < 0 || end < 0) throw new Error(`could not extract ${name}`);
  return html.slice(start, end);
}

// A `state` with a selected model is deliberately present in the context. The
// bug this guards was `state.modelLabel || 'GPT-5.6 Sol'` inside this function,
// which credited every saved reply to whatever the picker happened to be showing.
// If that reference ever comes back, `unknownIsNotInvented` below turns red --
// the codex case alone would NOT catch it, because a truthy row model masks it.
const context = { state: { modelLabel: 'GPT-5.6 Terra' } };
vm.createContext(context);
vm.runInContext(functionSource('mapRealMessages', 'refreshChats'), context);

const turns = [
  { role: 'user', content: 'make me a game' },
  { role: 'assistant', content: 'on it' },
];

const answeredByCodex = context.mapRealMessages(turns, 'codex');
const answeredByOllama = context.mapRealMessages(turns, 'qwen2.5-coder:7b');
const unrecorded = context.mapRealMessages(turns, '');
const missing = context.mapRealMessages(turns, undefined);
const whitespace = context.mapRealMessages(turns, '   ');

const checks = {
  // The model that actually answered is what the message reports.
  codexKeepsItsOwnModel: answeredByCodex[1].model === 'codex',
  ollamaKeepsItsOwnModel: answeredByOllama[1].model === 'qwen2.5-coder:7b',
  // The one that matters: an unknown model must stay unknown rather than being
  // filled in from the current selection.
  unknownIsNotInvented: unrecorded[1].model === '' && missing[1].model === '',
  whitespaceIsUnknown: whitespace[1].model === '',
  neverBorrowsThePicker: [answeredByCodex, unrecorded, missing]
    .every((turnList) => turnList.every((turn) => turn.model !== 'GPT-5.6 Terra')),
  // A user's own message never carries a model, whatever the row says.
  userTurnsCarryNoModel: answeredByCodex[0].model === '' && unrecorded[0].model === '',
  textAndRolesSurvive:
    answeredByCodex[0].role === 'user' &&
    answeredByCodex[1].role === 'assistant' &&
    answeredByCodex[0].text === 'make me a game',
};

for (const [name, passed] of Object.entries(checks)) {
  if (!passed) throw new Error(`chat model attribution check failed: ${name}`);
}
process.stdout.write(`${JSON.stringify(checks)}\n`);
