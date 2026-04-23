import fs from "node:fs";
import { openDb } from "../core/db.js";
import { initVault, unlockMasterKey, upsertSecret, listMeta, readSecret } from "../core/vault.js";
import { registerTool, hmacSha256B64u } from "../core/tools.js";
import { verifyAudit } from "../core/audit.js";

function usage(){
  console.log(`Thomas Vault CLI
Commands:
  init --db <path> --password <pw>
  put --db <path> --password <pw> --ref <vault://scope/name> --scope <scope> --sensitivity <low|high|critical> --label <label> --value <secret>
  list --db <path>
  get --db <path> --password <pw> --ref <ref>
  tool-add --db <path> --tool <toolId> --scopes <comma>
  audit-verify --db <path>
  sign --toolKeyB64 <...> --op resolve --nonce <nonce> --ts <ts> --bodyFile <jsonfile>
`);
}

function arg(name: string, args: string[]){
  const idx = args.indexOf(name);
  if (idx === -1) return null;
  return args[idx+1] ?? null;
}

async function main(){
  const args = process.argv.slice(2);
  const cmd = args[0];
  if (!cmd){ usage(); process.exit(2); }

  if (cmd === "init"){
    const dbPath = arg("--db", args);
    const pw = arg("--password", args);
    if (!dbPath || !pw) throw new Error("missing args");
    const db = openDb(dbPath);
    await initVault(db, pw);
    console.log("Vault initialized");
    return;
  }

  if (cmd === "put"){
    const dbPath = arg("--db", args); const pw = arg("--password", args);
    const ref = arg("--ref", args); const scope = arg("--scope", args) as any;
    const sensitivity = (arg("--sensitivity", args) ?? "low") as any;
    const label = arg("--label", args) ?? "";
    const value = arg("--value", args) ?? "";
    if (!dbPath || !pw || !ref || !scope) throw new Error("missing args");
    const db = openDb(dbPath);
    const mk = await unlockMasterKey(db, pw);
    await upsertSecret(db, mk, ref, scope, sensitivity, label, value);
    mk.fill(0);
    console.log("Saved", ref);
    return;
  }

  if (cmd === "list"){
    const dbPath = arg("--db", args);
    if (!dbPath) throw new Error("missing --db");
    const db = openDb(dbPath);
    console.table(listMeta(db));
    return;
  }

  if (cmd === "get"){
    const dbPath = arg("--db", args); const pw = arg("--password", args); const ref = arg("--ref", args);
    if (!dbPath || !pw || !ref) throw new Error("missing args");
    const db = openDb(dbPath);
    const mk = await unlockMasterKey(db, pw);
    const out = await readSecret(db, mk, ref);
    mk.fill(0);
    console.log(out.secret);
    return;
  }

  if (cmd === "tool-add"){
    const dbPath = arg("--db", args);
    const toolId = arg("--tool", args);
    const scopesCsv = arg("--scopes", args);
    if (!dbPath || !toolId || !scopesCsv) throw new Error("missing args");
    const scopes = scopesCsv.split(",").map(s=>s.trim()).filter(Boolean);
    const db = openDb(dbPath);
    const reg = registerTool(db, toolId, scopes);
    console.log("Tool added:", reg.toolId);
    console.log("HMAC key (base64):", reg.hmacKey);
    return;
  }

  if (cmd === "audit-verify"){
    const dbPath = arg("--db", args);
    if (!dbPath) throw new Error("missing --db");
    const db = openDb(dbPath);
    const res = verifyAudit(db);
    console.log(res.ok ? "AUDIT OK" : `AUDIT BROKEN at id=${res.badAtId}`);
    process.exit(res.ok ? 0 : 1);
  }

  if (cmd === "sign"){
    const toolKeyB64 = arg("--toolKeyB64", args) ?? "";
    const op = arg("--op", args) ?? "";
    const nonce = arg("--nonce", args) ?? "";
    const ts = arg("--ts", args) ?? new Date().toISOString();
    const bodyFile = arg("--bodyFile", args) ?? "";
    if (!toolKeyB64 || !op || !nonce || !bodyFile) throw new Error("missing args");
    const bodyJson = fs.readFileSync(bodyFile, "utf8");
    const bodyB64u = Buffer.from(bodyJson, "utf8").toString("base64url");
    const signed = Buffer.from(`${ts}.${bodyB64u}.${nonce}.${op}`, "utf8");
    const sig = hmacSha256B64u(toolKeyB64, signed);
    console.log(JSON.stringify({ ts, bodyB64u, nonce, op, sig }, null, 2));
    return;
  }

  usage();
  process.exit(2);
}

main().catch(e => {
  console.error("Error:", e.message);
  process.exit(1);
});
