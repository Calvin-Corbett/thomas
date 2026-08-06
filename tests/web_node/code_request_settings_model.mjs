// Drives ThomasCodeLifecycle.requestSettings the way unified_code_mode.js does:
// build the settings object, then JSON round-trip it exactly like the fetch body
// (JSON.stringify drops undefined keys, which is the mechanism the empty-model
// fix relies on). Prints one JSON report for the python test to assert on.
import fs from 'node:fs';
import vm from 'node:vm';

const sourcePath = process.argv[2];
const sandbox = {};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(sourcePath, 'utf8'), sandbox, { filename: sourcePath });

const requestSettings = sandbox.window.ThomasCodeLifecycle.requestSettings;
const wire = (context) => JSON.parse(JSON.stringify(requestSettings(context)));

process.stdout.write(JSON.stringify({
  // The measured defect: client model state lost, modelId "".
  empty: wire({ modelId: '', dials: {} }),
  missing: wire({ dials: {} }),
  gpt: wire({ modelId: 'gpt-5.6-terra', dials: {} }),
  // Named-but-non-gpt keeps today's routing (a separate known design issue).
  qwen: wire({ modelId: 'qwen2.5-coder:7b', dials: {} }),
}));
