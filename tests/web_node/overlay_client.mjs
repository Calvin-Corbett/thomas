// Runs chat_themes.js and workspace_shell.js in vm contexts with a stub
// document carrying an overlay view, and reports what the merge produced, so
// the Python test asserts behaviour: overlay themes appended in manifest
// order, token records patched into stock payloads, META fields that are
// tokens following their records, and the shell treating overlay names as
// known themes with the right colour scheme.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const [, , chatThemesPath, workspaceShellPath, overlayRuntimePath] = process.argv;
const view = {
  present: true, overlay_id: 'ovl_test', rev: 4, path: 'x',
  themes: {
    ember: { label: 'Ember', tagline: 'Warm dark', derives_from: 'nebula', color_scheme: 'dark', swatches: ['#140a06', '#2a1408', '#ff7a1a'], world: 'nebula', meta: { menuBg: '#1c0f08', rCard: '12px' } },
    paper: { label: 'Paper', tagline: '', derives_from: 'light', color_scheme: 'light' },
    rogue: { label: '<script>', derives_from: 'nebula', color_scheme: 'dark', swatches: ['#000', '#000', '#000;"><img src=x onerror=1>'], meta: { msgRule: '1px solid #000;"><b>', welcome: ['Hi', '<i>x</i>'] } },
  },
  tokens: { nebula: { '--c-accent': '#2ecc71', '--font-head': "'Inter', sans-serif" }, ember: { '--c-bg': '#140a06' }, '*': { '--c-text': '#eeeeee' } },
  elements: {}, anchors: {}, identity: { name: 'Otto' }, default_theme: 'ember', overrides: [], notes: [],
};
const viewScript = { textContent: JSON.stringify(view) };

function context(extra) {
  const style = { length: 0, setProperty() {}, removeProperty() {} };
  const doc = {
    readyState: 'loading', addEventListener() {}, styleSheets: [],
    querySelectorAll: () => [], querySelector: () => null,
    getElementById: (id) => (id === 'thomas-overlay-view' ? viewScript : null),
    documentElement: { dataset: {}, style, classList: { add() {} } }, body: null,
  };
  const win = { addEventListener() {}, dispatchEvent() {}, matchMedia: () => ({ matches: false }) };
  win.parent = win;
  const sandbox = Object.assign({
    window: win, document: doc, localStorage: { getItem: () => null, setItem() {} },
    location: { search: '', pathname: '/', origin: 'http://x', href: 'http://x/' },
    CustomEvent: class {}, URLSearchParams, Promise, setTimeout, queueMicrotask, console,
  }, extra || {});
  vm.createContext(sandbox);
  return sandbox;
}

const themesBox = context();
vm.runInContext(readFileSync(chatThemesPath, 'utf8'), themesBox, { filename: 'chat_themes.js' });
vm.runInContext(readFileSync(overlayRuntimePath, 'utf8'), themesBox, { filename: 'overlay_runtime.js' });
const { THEMES, THEME_META } = themesBox.window.ThomasChatThemes;
const report = {
  theme_order: Object.keys(THEMES),
  nebula_accent: THEMES.nebula.vars['--c-accent'],
  dark_accent_untouched: THEMES.dark.vars['--c-accent'],
  star_text_everywhere: ['nebula', 'dark', 'light', 'aurora', 'sandstone', 'ember'].every((n) => THEMES[n].vars['--c-text'] === '#eeeeee'),
  ember_bg: THEMES.ember.vars['--c-bg'],
  ember_inherits_parent_accent: THEMES.ember.vars['--c-accent'] === THEMES.nebula.vars['--c-accent'],
  ember_label: THEMES.ember.name,
  ember_swatches: THEMES.ember.sw,
  ember_meta_menu_bg: THEME_META.ember.menuBg,
  ember_meta_rcard: THEME_META.ember.rCard,
  ember_meta_bot_inherited: JSON.stringify(THEME_META.ember.bot) === JSON.stringify(THEME_META.nebula.bot),
  nebula_font_head_from_token: THEME_META.nebula.fontHead,
  paper_is_light_copy: THEMES.paper.vars['--c-bg'] === THEMES.light.vars['--c-bg'],
  rogue_label_falls_back_to_name: THEMES.rogue.name === 'rogue',
  rogue_swatches_fall_back_to_parent: JSON.stringify(THEMES.rogue.sw) === JSON.stringify(THEMES.nebula.sw),
  rogue_msg_rule_stays_parent: THEME_META.rogue.msgRule === THEME_META.nebula.msgRule,
  rogue_welcome_stays_parent: JSON.stringify(THEME_META.rogue.welcome) === JSON.stringify(THEME_META.nebula.welcome),
  merge_is_idempotent: (() => { themesBox.window.ThomasChatThemes.mergeOverlay(view); return Object.keys(THEMES).length === 8; })(),
  quoted_font_token_reaches_meta: (() => {
    themesBox.window.ThomasChatThemes.mergeOverlay(Object.assign({}, view, { tokens: { nebula: { '--font-head': '"Playfair Display", serif' } } }));
    return THEME_META.nebula.fontHead === '"Playfair Display", serif';
  })(),
  cleared_token_restores_stock: (() => {
    const stockAccent = JSON.parse(JSON.stringify(THEMES.dark.vars['--c-accent']));
    themesBox.window.ThomasChatThemes.mergeOverlay(Object.assign({}, view, { tokens: { dark: { '--c-accent': '#ff0000' } } }));
    const patched = THEMES.dark.vars['--c-accent'] === '#ff0000';
    themesBox.window.ThomasChatThemes.mergeOverlay(Object.assign({}, view, { tokens: {}, themes: {} }));
    return patched && THEMES.dark.vars['--c-accent'] === stockAccent && !THEMES.ember && THEME_META.nebula.fontHead === "'Manrope', system-ui, sans-serif";
  })(),
  cleared_readded_theme_uses_new_welcome: (() => {
    const overlay = themesBox.window.ThomasOverlay;
    const withWelcome = (word) => Object.assign({}, view, { identity: {}, themes: {
      ember: { label: `Ember ${word}`, derives_from: 'nebula', color_scheme: 'dark', meta: { welcome: [word, 'again'] } },
    } });
    overlay.adopt(withWelcome('Old'));
    overlay.adopt(Object.assign({}, view, { identity: {}, themes: {} }));
    overlay.adopt(withWelcome('New'));
    return THEMES.ember.name === 'Ember New' && THEME_META.ember.welcome[0] === 'New';
  })(),
};

const shellBox = context({ localStorage: { getItem: (k) => (k === 'thomas_chat_theme' ? 'ember' : null), setItem() {} } });
vm.runInContext(readFileSync(workspaceShellPath, 'utf8'), shellBox, { filename: 'workspace_shell.js' });
const shell = shellBox.window.ThomasWorkspaceShell;
report.known_themes = shell.knownThemes();
report.safe_ember = shell.safeTheme('ember');
report.safe_unknown = shell.safeTheme('nope');
report.stored_theme = shell.storedTheme();
report.paper_color_scheme = (() => { shell.applyTheme('paper', { persist: false }); return shellBox.document.documentElement.style.colorScheme; })();
report.ember_color_scheme = (() => { shell.applyTheme('ember', { persist: false }); return shellBox.document.documentElement.style.colorScheme; })();

const defaultBox = context({ localStorage: { getItem: () => null, setItem() {} } });
vm.runInContext(readFileSync(workspaceShellPath, 'utf8'), defaultBox, { filename: 'workspace_shell.js' });
report.default_theme_when_nothing_stored = defaultBox.window.ThomasWorkspaceShell.storedTheme();

process.stdout.write(JSON.stringify(report));
