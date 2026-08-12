import fs from 'node:fs';
import vm from 'node:vm';

const sourcePath = process.argv[2];
const buttons = ['chat', 'code', 'work'].map(mode => ({
  dataset: { thomasMode: mode },
  attributes: {},
  classList: { toggle() {} },
  setAttribute(name, value) { this.attributes[name] = value; },
  addEventListener() {},
  focus() {},
}));
const elements = new Map([
  ['tc-shell', { dataset: {} }],
  ['tc-history-label', {}],
  ['tc-search', {}],
  ['tc-newchat', {}],
  ['tc-newchat-top', {}],
  ['tc-input', { focus() {} }],
  ['tc-mode-surface', {}],
]);

globalThis.window = {};
globalThis.document = {
  getElementById(id) { return elements.get(id) || null; },
  querySelectorAll(selector) { return selector === '[data-thomas-mode]' ? buttons : []; },
  querySelector(selector) {
    const match = selector.match(/data-thomas-mode="([^"]+)"/);
    return match ? buttons.find(button => button.dataset.thomasMode === match[1]) || null : null;
  },
};

const unhandled = [];
process.on('unhandledRejection', error => unhandled.push(String(error)));
vm.runInThisContext(fs.readFileSync(sourcePath, 'utf8'), { filename: sourcePath });

let releaseFirstCodeEnter;
const firstCodeEnter = new Promise(resolve => { releaseFirstCodeEnter = resolve; });
let codeEnters = 0;
let workShouldFail = true;
let codeRunning = false;
let workRunning = false;
let workLeaves = 0;
let workStops = 0;
const announcements = [];

window.ThomasUnifiedModes.registerAdapter('code', {
  async enter() {
    codeEnters += 1;
    if (codeEnters === 1) await firstCodeEnter;
  },
  async leave() {},
  async refresh() {},
  isBusy() { return codeRunning; },
});
window.ThomasUnifiedModes.registerAdapter('work', {
  async enter() {
    if (workShouldFail) throw new Error('work adapter failed');
  },
  async leave() { workLeaves += 1; },
  async refresh() {},
  isBusy() { return workRunning; },
  stop() { workStops += 1; workRunning = false; },
});
window.ThomasUnifiedModes.connect({
  isBusy: () => false,
  announce: message => announcements.push(message),
  modeChanged() {},
  renderHistory() {},
});

const codeSwitch = window.ThomasUnifiedModes.setMode('code');
await new Promise(resolve => setTimeout(resolve, 0));
const failedWorkSwitch = window.ThomasUnifiedModes.setMode('work');
releaseFirstCodeEnter();
await Promise.all([codeSwitch, failedWorkSwitch]);
await new Promise(resolve => setTimeout(resolve, 0));

if (window.ThomasUnifiedModes.mode() !== 'code') throw new Error('failed Work transition did not roll back to Code');
if (unhandled.length) throw new Error(`unhandled rejection: ${unhandled.join(', ')}`);
if (!announcements.some(message => message.includes('Could not open Work'))) {
  throw new Error('failed Work transition did not announce recovery');
}
const selectedAfterFailure = buttons.find(button => button.attributes['aria-selected'] === 'true');
if (!selectedAfterFailure || selectedAfterFailure.dataset.thomasMode !== 'code') {
  throw new Error('tab chrome did not match the rolled-back Code mode');
}

workShouldFail = false;
const recovered = await window.ThomasUnifiedModes.setMode('work');
if (!recovered || window.ThomasUnifiedModes.mode() !== 'work') throw new Error('Work retry did not recover');
const selectedAfterRecovery = buttons.find(button => button.attributes['aria-selected'] === 'true');
if (!selectedAfterRecovery || selectedAfterRecovery.dataset.thomasMode !== 'work') {
  throw new Error('tab chrome did not match recovered Work mode');
}

workRunning = true;
const switchedFromRunningWork = await window.ThomasUnifiedModes.setMode('code');
if (!switchedFromRunningWork || window.ThomasUnifiedModes.mode() !== 'code') {
  throw new Error('running Work task blocked a presentation-only mode switch');
}
if (!workRunning || workLeaves < 1) throw new Error('leaving Work cancelled or lost its running state');

codeRunning = true;
const switchedFromRunningCode = await window.ThomasUnifiedModes.setMode('chat');
if (!switchedFromRunningCode || window.ThomasUnifiedModes.mode() !== 'chat' || !codeRunning) {
  throw new Error('leaving Code cancelled or blocked its running task');
}

await window.ThomasUnifiedModes.setMode('work');
if (!window.ThomasUnifiedModes.isBusy() || !window.ThomasUnifiedModes.stop() || workStops !== 1) {
  throw new Error('shared composer stop did not target the active Work mode');
}

process.stdout.write(JSON.stringify({ mode: window.ThomasUnifiedModes.mode(), codeEnters, workLeaves, workStops, announcements }));
