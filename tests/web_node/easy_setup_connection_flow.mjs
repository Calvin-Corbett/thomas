// Runs easy_setup_connection_flow.js in a vm context with the globals the
// ChatGPT path touches stubbed, then calls the connection test with no
// ChatGPT profile configured and reports what it did: which addresses it
// fetched, what status it set, and how long it took.
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const fetched = [];
const statuses = [];
const sandbox = {
  console,
  window: {},
  document: { getElementById: () => null, querySelector: () => null, querySelectorAll: () => [] },
  URLSearchParams, encodeURIComponent, Boolean, setTimeout, clearTimeout, Promise,
  easySetupState: { selectedPath: 'codex', verified: false, verifiedProfile: '', codexModels: [], bootstrap: null, dependencyPlan: null },
  easySetupConnectionStatus: {}, easySetupCodexMeta: null, easySetupLocalProfile: null,
  easySetupManualApiKey: null, easySetupManualPersist: null, easySetupManualProfile: null,
  availableModelProfiles: [],
  safeString: v => (v == null ? '' : String(v)).trim(),
  fetchJsonSafe: async (url) => { fetched.push(String(url)); return { ok: false, status: 404, data: {}, text: '404: Not Found' }; },
  setEasySetupStatus: (_el, text, kind) => { statuses.push([kind || 'info', String(text)]); },
  findEasySetupNativeCodexProfile: () => null,
  buildEasySetupDependencyPlan: () => ({}),
  setEasySetupDependencyDefaultStatus: () => {},
  updateEasySetupNavigation: () => {},
  emitOnboardingTelemetry: () => {},
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(readFileSync(process.argv[2], 'utf8'), sandbox, { filename: 'easy_setup_connection_flow.js' });
// The file defines these itself; the test wants the handler alone.
sandbox.persistOnboardingPrefs = async () => {};
sandbox.activateEasySetupProfile = async () => {};
if (typeof sandbox.handleEasySetupConnectionTest !== 'function') {
  process.stderr.write('handleEasySetupConnectionTest missing\n'); process.exit(1);
}
const started = Date.now();
const timer = setTimeout(() => { process.stderr.write('connection test did not settle within 3 s\n'); process.exit(2); }, 3000);
sandbox.handleEasySetupConnectionTest().then(() => {
  clearTimeout(timer);
  process.stdout.write(JSON.stringify({
    fetched, statuses, elapsed_ms: Date.now() - started,
    verified: sandbox.easySetupState.verified, verified_profile: sandbox.easySetupState.verifiedProfile,
  }));
}).catch(err => { clearTimeout(timer); process.stderr.write(String(err && err.stack || err)); process.exit(3); });
