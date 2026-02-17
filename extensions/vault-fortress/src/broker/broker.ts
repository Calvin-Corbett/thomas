import net from "node:net";
import crypto from "node:crypto";
import { decodeFrames, encodeFrame, EnvelopeSchema, type Reply } from "./protocol.js";
import { brokerEndpoint, cleanupUnixSocket } from "./ipc.js";
import { openDb } from "../core/db.js";
import { initVault, unlockMasterKey, upsertSecret, listMeta, readSecret, createSession, deleteSession, isSessionActive, nowIso, cleanupExpiredSessions, touchSession } from "../core/vault.js";
import { registerTool, getTool, verifyAndConsumeNonce, hmacSha256B64u, consumeConfirmToken } from "../core/tools.js";
import { appendAudit } from "../core/audit.js";
import { SecretRefSchema } from "../core/types.js";

type BrokerState = {
  masterKey: Uint8Array | null;
  sessionId: string | null;
  expiresAt: string | null;
  scopes: string[];
  inactivityMinutes: number;
  confirmServerKey: Buffer;
};

function b64uToBuf(s: string){
  const pad = s.length % 4 === 0 ? "" : "=".repeat(4 - (s.length % 4));
  const b64 = s.replace(/-/g,"+").replace(/_/g,"/") + pad;
  return Buffer.from(b64, "base64");
}

function safeJsonParseBody(bodyB64u: string){
  const buf = b64uToBuf(bodyB64u);
  return JSON.parse(buf.toString("utf8"));
}

function signConfirm(state: BrokerState, payloadB64u: string){
  return hmacSha256B64u(state.confirmServerKey.toString("base64"), Buffer.from(payloadB64u, "utf8"));
}

function verifyConfirm(state: BrokerState, payloadB64u: string, sig: string){
  const expected = signConfirm(state, payloadB64u);
  if (expected !== sig) throw new Error("bad_confirm_sig");
}

export async function startBroker(opts: { dbPath: string; endpointName?: string }){
  const endpoint = brokerEndpoint(opts.endpointName ?? "thomas-vault-broker");
  cleanupUnixSocket(endpoint);

  const db = openDb(opts.dbPath);
  const state: BrokerState = {
    masterKey: null,
    sessionId: null,
    expiresAt: null,
    scopes: [],
    inactivityMinutes: 10,
    confirmServerKey: crypto.randomBytes(32),
  };

  function reply(s: net.Socket, r: Reply){
    s.write(encodeFrame(r));
  }

  const server = net.createServer((socket) => {
    let buf = Buffer.alloc(0);
    socket.on("data", (chunk) => {
      buf = Buffer.concat([buf, chunk]);
      const out = decodeFrames(buf);
      buf = out.rest;
      for (const raw of out.frames){
        let env: any;
        try{
          env = EnvelopeSchema.parse(raw);
        } catch {
          reply(socket, { id: raw?.id ?? "?", ok: false, error: "bad_envelope" });
          continue;
        }
        handleEnvelope(socket, env).catch(err => {
          reply(socket, { id: env.id, ok: false, error: err?.message ?? "error" });
        });
      }
    });
  });

  async function handleEnvelope(socket: net.Socket, env: any){
    cleanupExpiredSessions(db);

    if (env.role === "ui"){
      if (env.op === "status"){
        const locked = state.masterKey === null || state.sessionId === null;
        reply(socket, { id: env.id, ok: true, data: { locked, expiresAt: state.expiresAt, scopes: state.scopes, inactivityMinutes: state.inactivityMinutes }});
        return;
      }
      if (env.op === "init"){
        const body = safeJsonParseBody(env.bodyB64u);
        await initVault(db, body.password);
        reply(socket, { id: env.id, ok: true, data: { ok: true }});
        return;
      }
      if (env.op === "unlock"){
        const body = safeJsonParseBody(env.bodyB64u);
        const mk = await unlockMasterKey(db, body.password);
        const sess = createSession(db, body.ttlMinutes, body.inactivityMinutes, body.scopes);
        state.masterKey = mk;
        state.sessionId = sess.sessionId;
        state.expiresAt = sess.expiresAt;
        state.scopes = body.scopes;
        state.inactivityMinutes = body.inactivityMinutes;
        reply(socket, { id: env.id, ok: true, data: { expiresAt: sess.expiresAt, scopes: state.scopes, inactivityMinutes: state.inactivityMinutes }});
        return;
      }
      if (env.op === "lock"){
        if (state.sessionId) deleteSession(db, state.sessionId);
        if (state.masterKey) state.masterKey.fill(0);
        state.masterKey = null;
        state.sessionId = null;
        state.expiresAt = null;
        state.scopes = [];
        reply(socket, { id: env.id, ok: true, data: { locked: true }});
        return;
      }
      if (env.op === "list"){
        const metas = listMeta(db);
        reply(socket, { id: env.id, ok: true, data: { metas }});
        return;
      }
      if (env.op === "put"){
        if (!state.sessionId || !state.masterKey) throw new Error("locked");
        const active = isSessionActive(db, state.sessionId);
        if (!active.ok) throw new Error("locked_" + active.reason);
        touchSession(db, state.sessionId);
        const body = safeJsonParseBody(env.bodyB64u);
        if (!active.scopes!.includes(body.scope)) throw new Error("scope_not_unlocked");
        await upsertSecret(db, state.masterKey, body.ref, body.scope, body.sensitivity, body.label, body.secret);
        reply(socket, { id: env.id, ok: true, data: { ok: true }});
        return;
      }
      if (env.op === "mintConfirm"){
        if (!state.sessionId || !state.masterKey) throw new Error("locked");
        const active = isSessionActive(db, state.sessionId);
        if (!active.ok) throw new Error("locked_" + active.reason);
        touchSession(db, state.sessionId);
        const body = safeJsonParseBody(env.bodyB64u);
        const payloadB64u = String(body.payloadB64u ?? "");
        const sig = signConfirm(state, payloadB64u);
        reply(socket, { id: env.id, ok: true, data: { token: `${payloadB64u}.${sig}` }});
        return;
      }
      if (env.op === "toolAdd"){
        if (!state.sessionId || !state.masterKey) throw new Error("locked");
        const active = isSessionActive(db, state.sessionId);
        if (!active.ok) throw new Error("locked_" + active.reason);
        touchSession(db, state.sessionId);
        const body = safeJsonParseBody(env.bodyB64u);
        const reg = registerTool(db, body.toolId, body.allowedScopes);
        reply(socket, { id: env.id, ok: true, data: reg });
        return;
      }
      reply(socket, { id: env.id, ok: false, error: "unknown_ui_op" });
      return;
    }

    // TOOL role
    if (!env.auth?.toolId || !env.auth?.nonce || !env.auth?.sig){
      appendAudit(db, { ts: nowIso(), eventType: "tool_req", actor: "tool:unknown", decision: "deny" });
      throw new Error("missing_tool_auth");
    }
    const toolId = String(env.auth.toolId);
    const nonce = String(env.auth.nonce);
    const sig = String(env.auth.sig);

    const tool = getTool(db, toolId);
    if (!tool){
      appendAudit(db, { ts: nowIso(), eventType: "tool_req", actor: `tool:${toolId}`, decision: "deny" });
      throw new Error("unknown_tool");
    }
    verifyAndConsumeNonce(db, toolId, nonce);

    const signed = Buffer.from(`${env.ts}.${env.bodyB64u}.${nonce}.${env.op}`, "utf8");
    const expected = hmacSha256B64u(tool.hmacKeyB64, signed);
    if (expected !== sig){
      appendAudit(db, { ts: nowIso(), eventType: "tool_req", actor: `tool:${toolId}`, decision: "deny" });
      throw new Error("bad_sig");
    }

    if (env.op === "resolve"){
      if (!state.sessionId || !state.masterKey) {
        appendAudit(db, { ts: nowIso(), eventType: "resolve", actor: `tool:${toolId}`, decision: "deny" });
        throw new Error("locked");
      }
      const active = isSessionActive(db, state.sessionId);
      if (!active.ok){
        appendAudit(db, { ts: nowIso(), eventType: "resolve", actor: `tool:${toolId}`, decision: "deny" });
        throw new Error("locked_" + active.reason);
      }
      touchSession(db, state.sessionId);

      const body = safeJsonParseBody(env.bodyB64u);
      const ref = SecretRefSchema.parse(body.ref);
      const purpose = String(body.purpose ?? "");
      const confirmToken = body.confirmToken ? String(body.confirmToken) : null;

      const { secret, meta } = await readSecret(db, state.masterKey, ref);

      if (!tool.allowedScopes.includes(meta.scope)){
        appendAudit(db, { ts: nowIso(), eventType: "resolve", actor: `tool:${toolId}`, ref, scope: meta.scope, sensitivity: meta.sensitivity, purpose, decision: "deny" });
        throw new Error("tool_scope_denied");
      }
      if (!active.scopes!.includes(meta.scope)){
        appendAudit(db, { ts: nowIso(), eventType: "resolve", actor: `tool:${toolId}`, ref, scope: meta.scope, sensitivity: meta.sensitivity, purpose, decision: "deny" });
        throw new Error("scope_not_unlocked");
      }

      if (meta.sensitivity !== "low"){
        if (!confirmToken) {
          appendAudit(db, { ts: nowIso(), eventType: "resolve", actor: `tool:${toolId}`, ref, scope: meta.scope, sensitivity: meta.sensitivity, purpose, decision: "deny" });
          throw new Error("confirm_required");
        }
        const [payloadB64u, confirmSig] = confirmToken.split(".");
        verifyConfirm(state, payloadB64u, confirmSig);
        const payload = JSON.parse(b64uToBuf(payloadB64u).toString("utf8"));
        if (payload.ref !== ref) throw new Error("confirm_ref_mismatch");
        if (payload.purpose !== purpose) throw new Error("confirm_purpose_mismatch");
        if (Date.now() > Date.parse(payload.expiresAt)) throw new Error("confirm_expired");
        consumeConfirmToken(db, payload.tokenId);
      }

      const receiptId = appendAudit(db, { ts: nowIso(), eventType: "resolve", actor: `tool:${toolId}`, ref, scope: meta.scope, sensitivity: meta.sensitivity, purpose, decision: "allow" });
      reply(socket, { id: env.id, ok: true, data: { ref, secret, receiptId }});
      return;
    }

    reply(socket, { id: env.id, ok: false, error: "unknown_tool_op" });
  }

  await new Promise<void>((resolve, reject) => {
    server.listen(endpoint, () => resolve());
    server.on("error", reject);
  });

  console.log(`[broker] listening on ${endpoint}`);
}
