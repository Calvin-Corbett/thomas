# Module: memory

| Field            | Value                                                    |
|------------------|----------------------------------------------------------|
| Status           | wip (v2 Fabric has real architecture, key subsystems placeholder) |
| Last assessed    | 2026-03-18                                               |
| Assessed by      | claude-opus-4-6 (Cowork session) + the product owner|
| Used in prod     | partially — v2 Fabric is wired, episodic layer not yet   |
| Has real tests   | partial (fabric FTS fallback tested, others unclear)      |
| Blocking issues  | 4 core files are source placeholders                     |

## What This Is

Thomas's memory system. 7,300 lines across 33 files in two generations:
a v1 layer (top-level files) and a v2 "Memory Fabric" (in `v2/`).

## Product Vision (from the product owner, 2026-03-18)

**Memory is PRIORITY #2 for the entire project** (after security).
It is Thomas's #1 differentiator as a product. The vision:

- The most advanced personal memory system available in any assistant
- A combination of every strong memory approach that exists — episodic,
  semantic, knowledge graph, profile hints, contradiction detection,
  retrieval-augmented, reranked, time-decayed, compiled
- AI-researched architecture: the product owner had AI study memory systems deeply
  and designed this to be the best-of-everything approach
- Cross-session, detailed, personal — Thomas should remember everything
  you tell it and surface relevant context unprompted

**This is the most important module in the entire project to get right
(after security is solid).**

### Connection to Preferences

Memory and preferences are deeply connected. the product owner's vision includes a
background AI model (cloud or local, user's choice) that processes
conversations and extracts important information into an indexed preference
profile. This profile feeds back into memory retrieval — so Thomas doesn't
just remember what you said, it understands what matters to you.

See `thomas/preferences/STATUS.md` for the preference-side of this vision.
The `memory/curator.py` background pipeline and a future preference
extraction model would work in parallel.

## What Actually Works (verified or high confidence)

**v2 Memory Fabric** (`v2/` — the active system):
- `schema.py` — Real SQLite schema (v3) with episodes, semantic_facts,
  profile_hints tables. Well-designed with proper indexes, foreign keys,
  and columns for salience scoring, decay, retrieval counting.
- `db.py` — Database layer. Real code.
- `fabric.py` → monolith-loaded from `fabric_part01-04.py` — The main
  Fabric runtime. fabric_part02 (980 lines) handles FTS search with
  fallback to LIKE mode (bug fixed in 0.14.34). Real and tested.
- `types.py` — RetrievalItem/RetrievalResult dataclasses. Real.
- `scoring.py` — Scoring logic for retrieval. Real.
- `token.py` — Token counting for context packing. Real.
- `profile_hints.py` — Profile hint extraction/storage. Real.
- `contradiction_review.py` / `contradictions.py` — Contradiction detection
  between stored facts. Real code exists.

**v1 layer** (top-level files, some real, some placeholder):
- `store.py` (846 lines) — SQLite storage with blob store, meta DB,
  derived DB. Real, well-documented code with WAL mode, batch queries,
  embeddings columns, graph edges.
- `retrieval.py` (336 lines) — Multi-source search pipeline: FTS + sparse
  vectors + graph → RRF merge → rerank → context pack. Real architecture.
- `curator.py` (1134 lines) — Background pipeline for promoting facts
  from chat episodes into durable memory. Real code.
- `compiler.py` (245 lines) — Delta ingestion and base rebuild. Real code.
- `graph.py` (277 lines) — Knowledge graph with entity extraction. Real code.
- `embedder.py` (268 lines) — Embedding generation. Real code.
- `indexer.py` — Indexing pipeline. Real code.
- `search.py` (149 lines) — Search interface. Real code.
- `rerank.py` (209 lines) — Reranking pipeline. Real code.
- `listing.py` (131 lines) — Memory listing/display. Real code.
- `autonomy.py` (954 lines) — Memory autonomy behaviors. Real code.

## What Is Placeholder / Not Working

**WARNING: These files EXIST but are source placeholders:**

- `episodic.py` — **PLACEHOLDER.** Episodic memory system — the part that
  stores and retrieves conversation episodes as experiences. Not implemented.
  This is one of the most important missing pieces.
- `episodic_store.py` — **PLACEHOLDER.** Storage backend for episodic memory.
  Not implemented.
- `summarization.py` — **PLACEHOLDER.** Conversation/memory summarization.
  Not implemented.
- `thought_signatures.py` — **PLACEHOLDER.** Thought pattern fingerprinting.
  Not implemented.

**These are also listed in AGENTS.md as "Do Not Touch" — they are reserved
for a specific future implementation, not abandoned.**

## Architecture Overview

The memory system is designed as a multi-layer pipeline:

1. **Ingest**: Conversations → episodes (with tokens, salience, decay params)
2. **Extract**: Episodes → semantic facts (subject-predicate-object triples)
   + profile hints (key-value user facts)
3. **Index**: Facts → FTS index + embeddings + knowledge graph
4. **Retrieve**: Query → multi-source search → RRF fusion → rerank → pack
5. **Curate**: Background promotion of high-confidence facts to durable storage
6. **Compile**: Delta ingestion + periodic base rebuilds
7. **Contradict**: Detect and flag conflicting stored facts

This is a genuinely ambitious architecture. The v2 Fabric implements the
retrieval side reasonably well. The ingest/extract side (episodic) is the
main gap.

## Known Gaps

- Episodic memory system not implemented (placeholder)
- Episodic store not implemented (placeholder)
- Summarization not implemented (placeholder)
- Thought signatures not implemented (placeholder)
- curator.py is 1134 lines (over 800 limit — needs split)
- End-to-end memory flow has not been tested as a complete pipeline
- No STATUS.md existed before this one (added 2026-03-18)

## Do Not Touch

- `episodic.py`, `episodic_store.py`, `summarization.py` — AGENTS.md
  explicitly lists these as frozen. Reserved for planned implementation.
  Do not fill with placeholder logic or stub implementations.
- `v2/schema.py` — Schema changes require migration planning.
- `store.py` — Core storage layer, production-critical.
