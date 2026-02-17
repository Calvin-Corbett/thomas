import crypto from "node:crypto";
import type { Db } from "./db.js";

function sha256hex(s: string){
  return crypto.createHash("sha256").update(s, "utf8").digest("hex");
}

export type AuditEvent = {
  ts: string;
  eventType: string;
  actor: string;
  ref?: string | null;
  scope?: string | null;
  sensitivity?: string | null;
  purpose?: string | null;
  decision: "allow"|"deny";
};

export function appendAudit(db: Db, ev: AuditEvent): string {
  const last = db.prepare("SELECT entry_hash FROM audit_log ORDER BY id DESC LIMIT 1").get() as any;
  const prev = last?.entry_hash ?? null;

  const line = JSON.stringify({
    ts: ev.ts,
    eventType: ev.eventType,
    actor: ev.actor,
    ref: ev.ref ?? null,
    scope: ev.scope ?? null,
    sensitivity: ev.sensitivity ?? null,
    purpose: ev.purpose ?? null,
    decision: ev.decision,
    prev: prev
  });
  const entryHash = sha256hex(line);

  db.prepare(`
    INSERT INTO audit_log(ts,event_type,actor,ref,scope,sensitivity,purpose,decision,prev_hash,entry_hash)
    VALUES(?,?,?,?,?,?,?,?,?,?)
  `).run(ev.ts, ev.eventType, ev.actor, ev.ref ?? null, ev.scope ?? null, ev.sensitivity ?? null, ev.purpose ?? null, ev.decision, prev, entryHash);

  return entryHash;
}

export function verifyAudit(db: Db): { ok: boolean; badAtId?: number }{
  const rows = db.prepare("SELECT id, ts, event_type, actor, ref, scope, sensitivity, purpose, decision, prev_hash, entry_hash FROM audit_log ORDER BY id ASC").all() as any[];
  let prev: string | null = null;
  for (const r of rows){
    const line = JSON.stringify({
      ts: r.ts,
      eventType: r.event_type,
      actor: r.actor,
      ref: r.ref ?? null,
      scope: r.scope ?? null,
      sensitivity: r.sensitivity ?? null,
      purpose: r.purpose ?? null,
      decision: r.decision,
      prev: prev
    });
    const h = sha256hex(line);
    if (r.prev_hash !== prev) return { ok: false, badAtId: r.id };
    if (r.entry_hash !== h) return { ok: false, badAtId: r.id };
    prev = h;
  }
  return { ok: true };
}
