import sodium from "libsodium-wrappers-sumo";

export type KeyBytes = Uint8Array;

export async function sodiumReady(){
  await sodium.ready;
  return sodium;
}

// paranoid-but-reasonable defaults; stored in DB for consistency
export const KDF_DEFAULT = {
  opsLimit: 4,
  memLimitBytes: 256 * 1024 * 1024,
};

export type KdfParams = { opsLimit: number; memLimitBytes: number; salt: Uint8Array };

export function randomBytes(n: number){
  return sodium.randombytes_buf(n);
}

export function b64u(bytes: Uint8Array){
  return Buffer.from(bytes).toString("base64").replace(/\+/g,"-").replace(/\//g,"_").replace(/=+$/g,"");
}
export function fromB64u(s: string){
  const pad = s.length % 4 === 0 ? "" : "=".repeat(4 - (s.length % 4));
  const b64 = s.replace(/-/g,"+").replace(/_/g,"/") + pad;
  return new Uint8Array(Buffer.from(b64, "base64"));
}

export async function deriveKek(password: string, params: KdfParams): Promise<KeyBytes>{
  await sodiumReady();
  const pw = Buffer.from(password, "utf8");
  const outLen = 32;
  const kek = sodium.crypto_pwhash(
    outLen,
    pw,
    params.salt,
    params.opsLimit,
    params.memLimitBytes,
    sodium.crypto_pwhash_ALG_ARGON2ID13
  );
  pw.fill(0);
  return kek;
}

export async function wrapKey(kek: KeyBytes, masterKey: KeyBytes): Promise<string>{
  await sodiumReady();
  const nonce = randomBytes(sodium.crypto_aead_xchacha20poly1305_ietf_NPUBBYTES);
  const aad = Buffer.from("thomas-vault:wrapkey:v1", "utf8");
  const ct = sodium.crypto_aead_xchacha20poly1305_ietf_encrypt(masterKey, aad, null, nonce, kek);
  return ["v1", b64u(nonce), b64u(ct)].join(".");
}

export async function unwrapKey(kek: KeyBytes, wrapped: string): Promise<KeyBytes>{
  await sodiumReady();
  const [v, n, c] = wrapped.split(".");
  if (v !== "v1") throw new Error("Unsupported wrapped key version");
  const nonce = fromB64u(n);
  const ct = fromB64u(c);
  const aad = Buffer.from("thomas-vault:wrapkey:v1", "utf8");
  const pt = sodium.crypto_aead_xchacha20poly1305_ietf_decrypt(null, ct, aad, nonce, kek);
  return pt;
}

export async function sealSecret(masterKey: KeyBytes, ref: string, plaintext: string): Promise<string>{
  await sodiumReady();
  const nonce = randomBytes(sodium.crypto_aead_xchacha20poly1305_ietf_NPUBBYTES);
  const aad = Buffer.from(`thomas-vault:secret:v1:${ref}`, "utf8");
  const msg = Buffer.from(plaintext, "utf8");
  const ct = sodium.crypto_aead_xchacha20poly1305_ietf_encrypt(msg, aad, null, nonce, masterKey);
  msg.fill(0);
  return ["v1", b64u(nonce), b64u(ct)].join(".");
}

export async function openSecret(masterKey: KeyBytes, ref: string, sealed: string): Promise<string>{
  await sodiumReady();
  const [v,n,c] = sealed.split(".");
  if (v !== "v1") throw new Error("Unsupported secret version");
  const nonce = fromB64u(n);
  const ct = fromB64u(c);
  const aad = Buffer.from(`thomas-vault:secret:v1:${ref}`, "utf8");
  const pt = sodium.crypto_aead_xchacha20poly1305_ietf_decrypt(null, ct, aad, nonce, masterKey);
  const s = Buffer.from(pt).toString("utf8");
  pt.fill(0);
  return s;
}
