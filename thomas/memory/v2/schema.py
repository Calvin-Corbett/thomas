from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

SCHEMA_VERSION = 2

INIT_SQL = """CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episodes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id TEXT NOT NULL,
  ts_ms INTEGER NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  tokens INTEGER NOT NULL,
  base_salience REAL NOT NULL,
  decay_half_life_hours REAL NOT NULL,
  retrieval_count INTEGER NOT NULL DEFAULT 0,
  last_retrieved_ts_ms INTEGER,
  created_at_ms INTEGER NOT NULL,
  source TEXT NOT NULL DEFAULT 'chat'
);

CREATE INDEX IF NOT EXISTS idx_episodes_thread_ts ON episodes(thread_id, ts_ms DESC);

CREATE TABLE IF NOT EXISTS semantic_facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id TEXT,
  ts_ms INTEGER NOT NULL,
  subject TEXT NOT NULL,
  predicate TEXT NOT NULL,
  obj TEXT NOT NULL,
  polarity INTEGER NOT NULL,
  confidence REAL NOT NULL,
  provenance_episode_id INTEGER,
  base_salience REAL NOT NULL,
  retrieval_count INTEGER NOT NULL DEFAULT 0,
  last_retrieved_ts_ms INTEGER,
  created_at_ms INTEGER NOT NULL,
  FOREIGN KEY (provenance_episode_id) REFERENCES episodes(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_facts_sp ON semantic_facts(subject, predicate);

CREATE TABLE IF NOT EXISTS profile_hints (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  confidence REAL NOT NULL,
  last_seen_ts_ms INTEGER NOT NULL,
  source_episode_id INTEGER,
  pinned INTEGER NOT NULL DEFAULT 0,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL,
  FOREIGN KEY (source_episode_id) REFERENCES episodes(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS pins (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  ref_id TEXT NOT NULL,
  thread_id TEXT,
  note TEXT,
  created_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_pins_thread_kind ON pins(thread_id, kind);

CREATE TABLE IF NOT EXISTS packs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope TEXT NOT NULL,
  thread_id TEXT,
  text TEXT NOT NULL,
  tokens_est INTEGER NOT NULL,
  waste REAL NOT NULL,
  version INTEGER NOT NULL,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_packs_scope_thread ON packs(scope, thread_id);
CREATE INDEX IF NOT EXISTS idx_profile_pinned_conf ON profile_hints(pinned DESC, confidence DESC, last_seen_ts_ms DESC);
CREATE INDEX IF NOT EXISTS idx_pins_thread_created ON pins(thread_id, created_at_ms DESC);

CREATE TABLE IF NOT EXISTS retrieval_traces (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL,
  query TEXT NOT NULL,
  ts_ms INTEGER NOT NULL,
  budget_tokens INTEGER NOT NULL,
  results_json TEXT NOT NULL,
  pack_id INTEGER,
  latency_ms INTEGER NOT NULL,
  FOREIGN KEY (pack_id) REFERENCES packs(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_traces_thread_ts ON retrieval_traces(thread_id, ts_ms DESC);

CREATE TABLE IF NOT EXISTS contradictions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  left_kind TEXT NOT NULL,
  left_id TEXT NOT NULL,
  right_kind TEXT NOT NULL,
  right_id TEXT NOT NULL,
  score REAL NOT NULL,
  reason TEXT NOT NULL,
  created_at_ms INTEGER NOT NULL,
  resolved INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_contra_resolved_created ON contradictions(resolved, created_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_contra_open ON contradictions(resolved, score DESC);

CREATE TABLE IF NOT EXISTS thread_settings (
  thread_id TEXT PRIMARY KEY,
  enabled INTEGER NOT NULL DEFAULT 1,
  include_global INTEGER NOT NULL DEFAULT 1,
  include_profile INTEGER NOT NULL DEFAULT 1,
  pins_only INTEGER NOT NULL DEFAULT 0,
  max_pack_tokens INTEGER NOT NULL DEFAULT 1200,
  max_results INTEGER NOT NULL DEFAULT 30,
  decay_half_life_hours REAL NOT NULL DEFAULT 240,
  auto_compact_enabled INTEGER NOT NULL DEFAULT 1,
  auto_compact_episode_threshold INTEGER NOT NULL DEFAULT 2000,
  auto_compact_min_interval_hours REAL NOT NULL DEFAULT 24,
  auto_optimize_enabled INTEGER NOT NULL DEFAULT 1,
  auto_optimize_waste_threshold REAL NOT NULL DEFAULT 0.22,
  auto_optimize_min_interval_hours REAL NOT NULL DEFAULT 12
);


CREATE TABLE IF NOT EXISTS maintenance_state (
  thread_id TEXT PRIMARY KEY,
  last_compact_ts_ms INTEGER,
  last_optimize_ts_ms INTEGER,
  created_at_ms INTEGER NOT NULL,
  updated_at_ms INTEGER NOT NULL
);

-- Optional FTS5 virtual table for episodes (best effort).

CREATE INDEX IF NOT EXISTS idx_facts_thread_ts ON semantic_facts(thread_id, ts_ms DESC);

CREATE INDEX IF NOT EXISTS idx_facts_thread_sp ON semantic_facts(thread_id, subject, predicate);

CREATE INDEX IF NOT EXISTS idx_hints_pinned_conf ON profile_hints(pinned DESC, confidence DESC);

CREATE INDEX IF NOT EXISTS idx_pins_thread_created ON pins(thread_id, created_at_ms DESC);

CREATE INDEX IF NOT EXISTS idx_contra_resolved_ts ON contradictions(resolved, created_at_ms DESC);
"""

def fts_sql(table_name: str = "episodes_fts") -> str:
    return f"""CREATE VIRTUAL TABLE IF NOT EXISTS {table_name} USING fts5(
  content,
  thread_id UNINDEXED,
  episode_id UNINDEXED
);
"""


def facts_fts_sql(table_name: str = "semantic_facts_fts") -> str:
    return f"""CREATE VIRTUAL TABLE IF NOT EXISTS {table_name} USING fts5(
  subject,
  predicate,
  obj,
  thread_id UNINDEXED,
  fact_id UNINDEXED
);
"""

FTS_TRIGGERS_SQL = """CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
  INSERT INTO episodes_fts(rowid, content, thread_id, episode_id)
  VALUES (new.id, new.content, new.thread_id, new.id);
END;

CREATE TRIGGER IF NOT EXISTS episodes_ad AFTER DELETE ON episodes BEGIN
  DELETE FROM episodes_fts WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS episodes_au AFTER UPDATE ON episodes BEGIN
  UPDATE episodes_fts SET content = new.content, thread_id = new.thread_id WHERE rowid = new.id;
END;
"""


FACTS_FTS_TRIGGERS_SQL = """CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON semantic_facts BEGIN
  INSERT INTO semantic_facts_fts(rowid, subject, predicate, obj, thread_id, fact_id)
  VALUES (new.id, new.subject, new.predicate, new.obj, new.thread_id, new.id);
END;

CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON semantic_facts BEGIN
  DELETE FROM semantic_facts_fts WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON semantic_facts BEGIN
  UPDATE semantic_facts_fts SET subject=new.subject, predicate=new.predicate, obj=new.obj, thread_id=new.thread_id WHERE rowid = new.id;
END;
"""
