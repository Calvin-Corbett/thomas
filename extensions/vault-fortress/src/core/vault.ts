import { nanoid } from "nanoid";
import type { Db } from "./db.js";
import { migrate } from "./db.js";
import { KDF_DEFAULT, deriveKek, randomBytes, wrapKey, unwrapKey, sealSecret, openSecret, b64u, fromB64u } from "./crypto.js";
import { appendAudit } from "./audit.js";
import type { Scope, Sensitivity, VaultMeta } from "./types.js";

export type VaultKeyset = {
  createdAt: string;
  kdfSalt: Uint8Array;
  kdfOps: number;
  kdfMem: number;
  wrappedMasterKey: string;
};

export function nowIso(){ return new Date().toISOString(); }

export async function initVault(db: Db, password: string){
  migrate(db);
  const exists = db.prepare("SELECT id FROM vault_keyset WHERE id=1").get();
  if (exists) throw new Error("Vault already initialized");

  const salt = randomBytes(16);
  const createdAt = nowIso();
  const kek = await deriveKek(password, { salt, opsLimit: KDF_DEFAULT.opsLimit, memLimitBytes: KDF_DEFAULT.memLimitBytes });
  const masterKey = randomBytes(32);
  const wrapped = await wrapKey(kek, masterKey);

  kek.fill(0);
  masterKey.fill(0);

  db.prepare("INSERT INTO vault_keyset(id,created_at,kdf_salt_b64,kdf_ops_limit,kdf_mem_limit,wrapped_master_key) VALUES(1,?,?,?,?,?)")
    .run(createdAt, b64u(salt), KDF_DEFAULT.opsLimit, KDF_DEFAULT.memLimitBytes, wrapped);

  appendAudit(db, { ts: createdAt, eventType: "vault_init", actor: "system", decision: "allow" });
}

export function getKeyset(db: Db): VaultKeyset {
  const row = db.prepare("SELECT created_at,kdf_salt_b64,kdf_ops_limit,kdf_mem_limit,wrapped_master_key FROM vault_keyset WHERE id=1").get() as any;
  if (!row) throw new Error("Vault not initialized");
  return {
    createdAt: row.created_at,
    kdfSalt: fromB64u(row.kdf_salt_b64),
    kdfOps: row.kdf_ops_limit,
    kdfMem: row.kdf_mem_limit,
    wrappedMasterKey: row.wrapped_master_key,
  };
}

export async function unlockMasterKey(db: Db, password: string): Promise<Uint8Array>{
  const ks = getKeyset(db);
  const kek = await deriveKek(password, { salt: ks.kdfSalt, opsLimit: ks.kdfOps, memLimitBytes: ks.kdfMem });
  const masterKey = await unwrapKey(kek, ks.wrappedMasterKey);
  kek.fill(0);
  return masterKey;
}

export async function upsertSecret(db: Db, masterKey: Uint8Array, ref: string, scope: Scope, sensitivity: Sensitivity, label: string, secret: string){
  const ts = nowIso();
  const sealed = await sealSecret(masterKey, ref, secret);
  const exists = db.prepare("SELECT ref FROM secrets WHERE ref=?").get(ref);
  if (exists){
    db.prepare("UPDATE secrets SET sealed=?, scope=?, sensitivity=?, label=?, updated_at=? WHERE ref=?")
      .run(sealed, scope, sensitivity, label, ts, ref);
  } else {
    db.prepare("INSERT INTO secrets(ref,scope,sensitivity,label,sealed,created_at,updated_at) VALUES(?,?,?,?,?,?,?)")
      .run(ref, scope, sensitivity, label, sealed, ts, ts);
  }
  appendAudit(db, { ts, eventType: "secret_put", actor: "ui", ref, scope, sensitivity, decision: "allow" });
}

export function listMeta(db: Db): VaultMeta[]{
  const rows = db.prepare("SELECT ref,scope,sensitivity,label,created_at,updated_at FROM secrets ORDER BY ref ASC").all() as any[];
  return rows.map(r => ({
    ref: r.ref,
    scope: r.scope,
    sensitivity: r.sensitivity,
    label: r.label,
    createdAt: r.created_at,
    updatedAt: r.updated_at,
  }));
}

export async function readSecret(db: Db, masterKey: Uint8Array, ref: string): Promise<{secret: string; meta: any}>{
  const row = db.prepare("SELECT ref,scope,sensitivity,label,sealed FROM secrets WHERE ref=?").get(ref) as any;
  if (!row) throw new Error("Secret not found");
  const secret = await openSecret(masterKey, ref, row.sealed);
  return { secret, meta: { ref: row.ref, scope: row.scope, sensitivity: row.sensitivity, label: row.label } };
}

export function createSession(db: Db, ttlMinutes: number, inactivityMinutes: number, scopes: string[]): { sessionId: string; expiresAt: string }{
  const id = nanoid(22);
  const now = new Date();
  const expires = new Date(now.getTime() + ttlMinutes * 60_000);
  const ts = now.toISOString();
  db.prepare("INSERT INTO sessions(id,expires_at,inactivity_minutes,scopes,last_activity) VALUES(?,?,?,?,?)")
    .run(id, expires.toISOString(), inactivityMinutes, JSON.stringify(scopes), ts);
  appendAudit(db, { ts, eventType: "vault_unlock", actor: "ui", decision: "allow" });
  return { sessionId: id, expiresAt: expires.toISOString() };
}

export function touchSession(db: Db, id: string){
  const ts = nowIso();
  db.prepare("UPDATE sessions SET last_activity=? WHERE id=?").run(ts, id);
}

export function getSession(db: Db, id: string): { expiresAt: string; inactivityMinutes: number; scopes: string[]; lastActivity: string } | null{
  const row = db.prepare("SELECT expires_at,inactivity_minutes,scopes,last_activity FROM sessions WHERE id=?").get(id) as any;
  if (!row) return null;
  return { expiresAt: row.expires_at, inactivityMinutes: row.inactivity_minutes, scopes: JSON.parse(row.scopes), lastActivity: row.last_activity };
}

export function deleteSession(db: Db, id: string){
  db.prepare("DELETE FROM sessions WHERE id=?").run(id);
  appendAudit(db, { ts: nowIso(), eventType: "vault_lock", actor: "ui", decision: "allow" });
}

export function cleanupExpiredSessions(db: Db){
  const now = nowIso();
  db.prepare("DELETE FROM sessions WHERE expires_at < ?").run(now);
}

export function isSessionActive(db: Db, id: string): { ok: boolean; reason?: string; scopes?: string[]; inactivityMinutes?: number; expiresAt?: string }{
  const s = getSession(db, id);
  if (!s) return { ok: false, reason: "no_session" };
  const now = Date.now();
  const exp = Date.parse(s.expiresAt);
  if (now > exp){
    deleteSession(db, id);
    return { ok: false, reason: "expired" };
  }
  const last = Date.parse(s.lastActivity);
  const idleMs = now - last;
  if (idleMs > s.inactivityMinutes * 60_000){
    deleteSession(db, id);
    return { ok: false, reason: "inactive" };
  }
  return { ok: true, scopes: s.scopes, inactivityMinutes: s.inactivityMinutes, expiresAt: s.expiresAt };
}
