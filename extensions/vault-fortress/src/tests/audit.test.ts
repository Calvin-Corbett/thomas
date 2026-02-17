import test from "node:test";
import assert from "node:assert/strict";
import { openDb } from "../core/db.js";
import { migrate } from "../core/db.js";
import { appendAudit, verifyAudit } from "../core/audit.js";
import fs from "node:fs";

test("audit verifies", async () => {
  const p = "./.tmp_audit.db";
  try { fs.unlinkSync(p); } catch {}
  const db = openDb(p);
  migrate(db);
  appendAudit(db, { ts: new Date().toISOString(), eventType: "a", actor: "x", decision: "allow" });
  appendAudit(db, { ts: new Date().toISOString(), eventType: "b", actor: "y", decision: "deny" });
  const res = verifyAudit(db);
  assert.equal(res.ok, true);
  db.close();
  fs.unlinkSync(p);
});
