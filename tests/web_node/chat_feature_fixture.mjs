// Test adapter for the same feature factories loaded by the real chat page.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

export function installScript(context, htmlPath, name) {
  context.window ||= {};
  context.document ||= { getElementById() { return null; }, addEventListener() {} };
  if (!vm.isContext(context)) vm.createContext(context);
  const filename = path.join(path.dirname(htmlPath), 'js', name);
  vm.runInContext(fs.readFileSync(filename, 'utf8'), context, { filename });
}

export function installModelFixture(context, htmlPath) {
  installScript(context, htmlPath, 'chat_model_selection.js');
  context.state.profile = 'fixture';
  context.state.modelId = 'one';
  context.profilesData = [{ name: 'fixture', models: [{ id: 'one', available: true }] }];
  context.window.ThomasChatModelSelection.connect({
    getCurrent: () => context.state,
    getProfiles: () => context.profilesData,
    profileModelOptions: profile => profile.models,
    setProfile: context.setProfile,
    renderModelMenu: context.renderModelMenu,
  });
}

export function installFeature(context, htmlPath, name, selectedNames) {
  context.window ||= {};
  context.document ||= { getElementById() { return null; } };
  if (!vm.isContext(context)) vm.createContext(context);
  const filename = path.join(path.dirname(htmlPath), 'js', `chat_${name}.js`);
  vm.runInContext(fs.readFileSync(filename, 'utf8'), context, { filename });
  const globalName = 'ThomasChat' + name.split('_').map(word => word[0].toUpperCase() + word.slice(1)).join('');
  const feature = context.window[globalName].create(context);
  for (const method of selectedNames || Object.keys(feature)) {
    if (typeof feature[method] !== 'function') throw new Error(`${name} does not export ${method}`);
    context[method] = feature[method];
  }
  return feature;
}

export function inlineFunction(html, name) {
  const start = html.search(new RegExp(`(?:async )?function ${name}\\(`));
  if (start < 0) throw new Error(`Inline shell function ${name} is missing`);
  const tail = html.slice(start + 1);
  const next = tail.search(/\n    (?:(?:async )?function |const |let |window\.)/);
  return html.slice(start, next < 0 ? html.indexOf('  })();', start) : start + 1 + next);
}

export function installInlineCore(context, htmlPath) {
  if (!vm.isContext(context)) vm.createContext(context);
  const html = fs.readFileSync(htmlPath, 'utf8');
  for (const name of ['esc', 'deMd', 'captureConversation']) {
    vm.runInContext(inlineFunction(html, name), context);
  }
}

export function readChatFeatures(htmlPath) {
  const html = fs.readFileSync(htmlPath, 'utf8');
  const sources = [html];
  for (const match of html.matchAll(/<script src="\/static\/js\/(chat_[^?"/]+\.js)(?:\?[^"<>]*)?"><\/script>/g)) {
    sources.push(fs.readFileSync(path.join(path.dirname(htmlPath), 'js', match[1]), 'utf8'));
  }
  return sources.join('\n');
}
