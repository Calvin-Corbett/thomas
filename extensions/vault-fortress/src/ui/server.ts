import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";
import crypto from "node:crypto";
import { connect, brokerEndpoint } from "../broker/ipc.js";
import { encodeFrame, decodeFrames } from "../broker/protocol.js";
import { mintConfirmPayloadB64u } from "../core/tools.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const publicDir = path.join(__dirname, "public");

function parseArgs(){
  const args = process.argv.slice(2);
  const out: any = { port: 4318 };
  for (let i=0;i<args.length;i++){
    const a = args[i];
    if (a === "--port") out.port = Number(args[++i]);
    if (a === "--name") out.name = args[++i];
  }
  return out;
}

async function brokerCall(op: string, body: any, name?: string){
  const endpoint = brokerEndpoint(name ?? "thomas-vault-broker");
  const sock = await connect(endpoint);
  let buf = Buffer.alloc(0);

  const id = crypto.randomUUID();
  const bodyB64u = Buffer.from(JSON.stringify(body), "utf8").toString("base64url");
  const env = { id, role: "ui", op, ts: new Date().toISOString(), bodyB64u };
  sock.write(encodeFrame(env));

  return await new Promise<any>((resolve, reject) => {
    sock.on("data", (chunk) => {
      buf = Buffer.concat([buf, chunk]);
      const out = decodeFrames(buf);
      buf = out.rest;
      for (const frame of out.frames){
        if (frame.id === id){
          sock.end();
          if (!frame.ok) reject(new Error(frame.error ?? "error"));
          else resolve(frame.data);
        }
      }
    });
    sock.on("error", reject);
  });
}

const { port, name } = parseArgs();
const app = express();
app.use(express.json({ limit: "1mb" }));

app.get("/vault", (_, res) => res.sendFile(path.join(publicDir, "index.html")));
app.use("/static", express.static(publicDir));

app.get("/api/status", async (_, res) => {
  try{
    const data = await brokerCall("status", {}, name);
    res.json({ ok: true, ...data });
  } catch(e: any){
    res.status(500).json({ ok: false, error: e.message });
  }
});

app.post("/api/init", async (req, res) => {
  try{
    const data = await brokerCall("init", { password: String(req.body.password ?? "") }, name);
    res.json({ ok: true, data });
  } catch(e: any){
    res.status(400).json({ ok: false, error: e.message });
  }
});

app.post("/api/unlock", async (req, res) => {
  try{
    const body = {
      password: String(req.body.password ?? ""),
      ttlMinutes: Number(req.body.ttlMinutes ?? 30),
      scopes: Array.isArray(req.body.scopes) ? req.body.scopes : [],
      inactivityMinutes: Number(req.body.inactivityMinutes ?? 10),
    };
    const data = await brokerCall("unlock", body, name);
    res.json({ ok: true, data });
  } catch(e: any){
    res.status(400).json({ ok: false, error: e.message });
  }
});

app.post("/api/lock", async (req, res) => {
  try{
    const data = await brokerCall("lock", {}, name);
    res.json({ ok: true, data });
  } catch(e: any){
    res.status(400).json({ ok: false, error: e.message });
  }
});

app.get("/api/list", async (_, res) => {
  try{
    const data = await brokerCall("list", {}, name);
    res.json({ ok: true, ...data });
  } catch(e: any){
    res.status(500).json({ ok: false, error: e.message });
  }
});

app.post("/api/put", async (req, res) => {
  try{
    const body = {
      ref: String(req.body.ref ?? ""),
      scope: String(req.body.scope ?? ""),
      sensitivity: String(req.body.sensitivity ?? "low"),
      label: String(req.body.label ?? ""),
      secret: String(req.body.secret ?? ""),
    };
    const data = await brokerCall("put", body, name);
    res.json({ ok: true, data });
  } catch(e: any){
    res.status(400).json({ ok: false, error: e.message });
  }
});

app.post("/api/tool-add", async (req, res) => {
  try{
    const body = {
      toolId: String(req.body.toolId ?? ""),
      allowedScopes: Array.isArray(req.body.allowedScopes) ? req.body.allowedScopes : [],
    };
    const data = await brokerCall("toolAdd", body, name);
    res.json({ ok: true, data });
  } catch(e: any){
    res.status(400).json({ ok: false, error: e.message });
  }
});

app.post("/api/mint-confirm", async (req, res) => {
  try{
    const ref = String(req.body.ref ?? "");
    const purpose = String(req.body.purpose ?? "");
    const payloadB64u = mintConfirmPayloadB64u(ref, purpose, 120);
    const data = await brokerCall("mintConfirm", { payloadB64u }, name);
    res.json({ ok: true, token: data.token });
  } catch(e: any){
    res.status(400).json({ ok: false, error: e.message });
  }
});

app.listen(port, () => {
  console.log(`[ui] http://127.0.0.1:${port}/vault`);
});
