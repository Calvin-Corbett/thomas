import crypto from "node:crypto";
import { connect, brokerEndpoint } from "../broker/ipc.js";
import { encodeFrame, decodeFrames } from "../broker/protocol.js";
import { hmacSha256B64u } from "../core/tools.js";

async function callResolve(toolId: string, toolKeyB64: string, ref: string, purpose: string, confirmToken?: string){
  const endpoint = brokerEndpoint("thomas-vault-broker");
  const sock = await connect(endpoint);
  const id = crypto.randomUUID();
  const ts = new Date().toISOString();
  const nonce = crypto.randomBytes(16).toString("hex");

  const body = { ref, purpose, confirmToken };
  const bodyB64u = Buffer.from(JSON.stringify(body), "utf8").toString("base64url");
  const signed = Buffer.from(`${ts}.${bodyB64u}.${nonce}.resolve`, "utf8");
  const sig = hmacSha256B64u(toolKeyB64, signed);

  const env = { id, role: "tool", op: "resolve", ts, bodyB64u, auth: { toolId, nonce, sig } };
  sock.write(encodeFrame(env));

  let buf = Buffer.alloc(0);
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

const [toolId, toolKeyB64, ref, ...rest] = process.argv.slice(2);
const purpose = rest[0] ?? "demo purpose";
const confirmToken = rest[1];
const out = await callResolve(toolId, toolKeyB64, ref, purpose, confirmToken);
console.log(out);
