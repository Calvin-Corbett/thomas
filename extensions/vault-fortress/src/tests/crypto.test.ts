import test from "node:test";
import assert from "node:assert/strict";
import { sodiumReady, deriveKek, wrapKey, unwrapKey, sealSecret, openSecret, randomBytes } from "../core/crypto.js";

test("wrap/unwrap master key", async () => {
  await sodiumReady();
  const salt = randomBytes(16);
  const kek = await deriveKek("correct horse battery staple", { salt, opsLimit: 3, memLimitBytes: 64*1024*1024 });
  const mk = randomBytes(32);
  const wrapped = await wrapKey(kek, mk);
  const mk2 = await unwrapKey(kek, wrapped);
  assert.equal(Buffer.from(mk).toString("hex"), Buffer.from(mk2).toString("hex"));
  mk.fill(0); mk2.fill(0); kek.fill(0);
});

test("seal/open binds to ref", async () => {
  const mk = randomBytes(32);
  const ref = "vault://api/openai";
  const sealed = await sealSecret(mk, ref, "supersecret");
  const opened = await openSecret(mk, ref, sealed);
  assert.equal(opened, "supersecret");
  let failed = false;
  try { await openSecret(mk, "vault://api/other", sealed); } catch { failed = true; }
  assert.equal(failed, true);
  mk.fill(0);
});
