declare module "libsodium-wrappers-sumo" {
  interface SodiumModule {
    readonly ready: Promise<void>;
    readonly crypto_pwhash_ALG_ARGON2ID13: number;
    readonly crypto_aead_xchacha20poly1305_ietf_NPUBBYTES: number;

    randombytes_buf(length: number): Uint8Array;
    crypto_pwhash(
      outputLength: number,
      password: Uint8Array,
      salt: Uint8Array,
      opsLimit: number,
      memLimit: number,
      algorithm: number,
    ): Uint8Array;
    crypto_aead_xchacha20poly1305_ietf_encrypt(
      message: Uint8Array,
      additionalData: Uint8Array | null,
      secretNonce: null,
      publicNonce: Uint8Array,
      key: Uint8Array,
    ): Uint8Array;
    crypto_aead_xchacha20poly1305_ietf_decrypt(
      secretNonce: null,
      ciphertext: Uint8Array,
      additionalData: Uint8Array | null,
      publicNonce: Uint8Array,
      key: Uint8Array,
    ): Uint8Array;
  }

  const sodium: SodiumModule;
  export default sodium;
}
