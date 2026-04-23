import os from "node:os";
import path from "node:path";
import fs from "node:fs";
import net from "node:net";

export function brokerEndpoint(name = "thomas-vault-broker"){
  if (process.platform === "win32"){
    return `\\\\.\\pipe\\${name}`;
  }
  const dir = path.join(os.tmpdir(), "thomas-vault");
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
  return path.join(dir, `${name}.sock`);
}

export function cleanupUnixSocket(p: string){
  if (process.platform !== "win32"){
    try { if (fs.existsSync(p)) fs.unlinkSync(p); } catch {}
  }
}

export function connect(endpoint: string): Promise<net.Socket>{
  return new Promise((resolve, reject) => {
    const s = net.createConnection(endpoint, () => resolve(s));
    s.on("error", reject);
  });
}
