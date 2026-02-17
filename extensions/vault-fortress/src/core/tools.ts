import crypto from "node:crypto";
import type { Db } from "./db.js";
import { appendAudit } from "./audit.js";
import { nanoid } from "nanoid";

export function registerTool(db: Db, toolId: string, allowedScopes: string[]): { toolId: string; hmacKey: string }{
  const existing = db.prepare("SELECT tool_id FROM tool_registry WHERE tool_id=?").get(toolId);
  if (existing) throw new Error("Tool already exists");
  const key = crypto.randomBytes(32);
  const hmacKeyB64 = key.toString("base64");
  db.prepare("INSERT INTO tool_registry(tool_id,allowed_scopes,hmac_key_b64,created_at) VALUES(?,?,?,?)")
    .run(toolId, JSON.stringify(allowedScopes), hmacKeyB64, new Date().toISOString());
  appendAudit(db, { ts: new Date().toISOString(), eventType: "tool_add", actor: "ui", decision: "allow" });
  return { toolId, hmacKey: hmacKeyB64 };
}

export function getTool(db: Db, toolId: string): { toolId: string; allowedScopes: string[]; hmacKeyB64: string } | null{
  const row = db.prepare("SELECT tool_id,allowed_scopes,hmac_key_b64 FROM tool_registry WHERE tool_id=?").get(toolId) as any;
  if (!row) return null;
  return { toolId: row.tool_id, allowedScopes: JSON.parse(row.allowed_scopes), hmacKeyB64: row.hmac_key_b64 };
}

export function verifyAndConsumeNonce(db: Db, toolId: string, nonce: string){
  const exists = db.prepare("SELECT nonce FROM used_nonces WHERE tool_id=? AND nonce=?").get(toolId, nonce);
  if (exists) throw new Error("nonce_replay");
  db.prepare("INSERT INTO used_nonces(tool_id,nonce,used_at) VALUES(?,?,?)").run(toolId, nonce, new Date().toISOString());
}

export function hmacSha256B64u(keyB64: string, data: Buffer): string{
  const key = Buffer.from(keyB64, "base64");
  const mac = crypto.createHmac("sha256", key).update(data).digest("base64");
  return mac.replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/g,"");
}

export function mintConfirmPayloadB64u(ref: string, purpose: string, ttlSeconds: number): string{
  const tokenId = nanoid(22);
  const now = Date.now();
  const payload = {
    tokenId,
    issuedAt: new Date(now).toISOString(),
    expiresAt: new Date(now + ttlSeconds * 1000).toISOString(),
    purpose,
    ref,
  };
  return Buffer.from(JSON.stringify(payload), "utf8").toString("base64url");
}

export function consumeConfirmToken(db: Db, tokenId: string){
  const used = db.prepare("SELECT token_id FROM used_confirm_tokens WHERE token_id=?").get(tokenId);
  if (used) throw new Error("confirm_replay");
  db.prepare("INSERT INTO used_confirm_tokens(token_id,used_at) VALUES(?,?)").run(tokenId, new Date().toISOString());
}
