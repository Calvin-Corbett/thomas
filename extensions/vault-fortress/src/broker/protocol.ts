import { z } from "zod";

export const Role = z.enum(["tool","ui"]);
export type Role = z.infer<typeof Role>;

export const EnvelopeSchema = z.object({
  id: z.string().min(1),
  role: Role,
  op: z.string().min(1),
  ts: z.string().min(1),
  bodyB64u: z.string().min(1),
  auth: z.object({
    toolId: z.string().optional(),
    nonce: z.string().optional(),
    sig: z.string().optional(),
  }).optional(),
});
export type Envelope = z.infer<typeof EnvelopeSchema>;

export type Reply = {
  id: string;
  ok: boolean;
  error?: string;
  data?: any;
};

export function encodeFrame(obj: any): Buffer{
  const js = JSON.stringify(obj);
  const payload = Buffer.from(js, "utf8");
  const len = Buffer.alloc(4);
  len.writeUInt32BE(payload.length, 0);
  return Buffer.concat([len, payload]);
}

export function decodeFrames(buf: Buffer): { frames: any[]; rest: Buffer }{
  let offset = 0;
  const frames: any[] = [];
  while (offset + 4 <= buf.length){
    const len = buf.readUInt32BE(offset);
    if (offset + 4 + len > buf.length) break;
    const payload = buf.slice(offset + 4, offset + 4 + len);
    frames.push(JSON.parse(payload.toString("utf8")));
    offset += 4 + len;
  }
  return { frames, rest: buf.slice(offset) };
}
