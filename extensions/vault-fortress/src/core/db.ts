import Database from "better-sqlite3";
export type Db = Database.Database;

export function openDb(path: string): Db {
  const db = new Database(path);
  db.pragma("journal_mode = WAL");
  db.pragma("foreign_keys = ON");
  return db;
}

export function migrate(db: Db){
  db.exec(`
    CREATE TABLE IF NOT EXISTS vault_keyset(
      id INTEGER PRIMARY KEY CHECK (id = 1),
      created_at TEXT NOT NULL,
      kdf_salt_b64 TEXT NOT NULL,
      kdf_ops_limit INTEGER NOT NULL,
      kdf_mem_limit INTEGER NOT NULL,
      wrapped_master_key TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS secrets(
      ref TEXT PRIMARY KEY,
      scope TEXT NOT NULL,
      sensitivity TEXT NOT NULL,
      label TEXT NOT NULL,
      sealed TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS tool_registry(
      tool_id TEXT PRIMARY KEY,
      allowed_scopes TEXT NOT NULL,
      hmac_key_b64 TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS used_nonces(
      tool_id TEXT NOT NULL,
      nonce TEXT NOT NULL,
      used_at TEXT NOT NULL,
      PRIMARY KEY(tool_id, nonce)
    );
    CREATE TABLE IF NOT EXISTS used_confirm_tokens(
      token_id TEXT PRIMARY KEY,
      used_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sessions(
      id TEXT PRIMARY KEY,
      expires_at TEXT NOT NULL,
      inactivity_minutes INTEGER NOT NULL,
      scopes TEXT NOT NULL,
      last_activity TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS audit_log(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT NOT NULL,
      event_type TEXT NOT NULL,
      actor TEXT NOT NULL,
      ref TEXT,
      scope TEXT,
      sensitivity TEXT,
      purpose TEXT,
      decision TEXT NOT NULL,
      prev_hash TEXT,
      entry_hash TEXT NOT NULL
    );
  `);
}
