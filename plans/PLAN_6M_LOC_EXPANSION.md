# Plan: 6 Million Lines Expansion

> **Current state:** ~2.2M total lines (290K Python, 1.8M JSON, 40K JS, 14K CSS, 4K TS)
> **Target:** +6M meaningful source lines → ~8.2M total
> **Constraint:** No monolith files. Thomas rules enforced. Senior-engineer quality.

---

## Ground Rules (from Thomas PROJECT_MANAGEMENT_RULES + SOUL)

1. **No monolith files** — every `.py` file stays under 800 lines (SOUL: "no jungle")
2. **No duplicate work** — check existing modules before writing
3. **Every module gets tests** — matching `tests/test_<module>.py` files
4. **Changelog + version bump** after each wave
5. **Architecture registry** — every new module added to `_architecture.py`
6. **No stubs** — every file has real logic, real algorithms, real error handling
7. **Proof over vibes** — unit tests, integration tests, property tests where applicable

---

## What "Meaningful" Means

Each file must contain at least 3 of these:

- Real algorithms (sorting, graph traversal, parsing, scheduling, etc.)
- Data structures (classes with validation, serialization, state machines)
- Error handling (custom exceptions, retry logic, circuit breakers)
- Type annotations throughout
- Docstrings on all public APIs
- Logging with structured context
- Configuration management
- Real test coverage (unit + edge cases + error paths)

---

## Architecture Per Module

Every populated module follows this standard internal layout:

```
thomas/<module>/
├── __init__.py          # Public API exports
├── _types.py            # Dataclasses, enums, type aliases
├── _exceptions.py       # Module-specific exceptions
├── _config.py           # Module configuration
├── core.py              # Primary business logic (≤800 lines)
├── engine.py            # Processing engine / main loop
├── models.py            # Domain models
├── store.py             # Persistence layer
├── validators.py        # Input validation
├── serializers.py       # Wire format conversion
├── utils.py             # Module-internal helpers
├── cli_commands.py      # CLI surface (if user-facing)
└── README.md            # Module documentation
```

Tests mirror the structure:
```
tests/
├── test_<module>_core.py
├── test_<module>_engine.py
├── test_<module>_store.py
├── test_<module>_validators.py
├── test_<module>_integration.py
└── test_<module>_edge_cases.py
```

Average per module: ~8-12 source files + 4-6 test files = **~5,000-8,000 lines per module**

---

## Phase Breakdown

### Phase 1: Infrastructure & Data Layer (Target: +800K lines)
*Modules that everything else depends on. Build these first.*

| Module | Description | Est. Lines |
|--------|-------------|------------|
| `caching` | Multi-tier cache (LRU, LFU, TTL, distributed). Eviction policies, cache warming, stats. | 8,000 |
| `serialization` | JSON/MsgPack/Protobuf/CBOR codec registry. Schema evolution, versioning. | 7,000 |
| `validation` | Schema validation engine. JSON Schema, custom rules, composable validators. | 8,000 |
| `config_mgmt` | Hierarchical config. Env overlay, secrets injection, hot reload, diff. | 7,000 |
| `logging_framework` | Structured logging. Correlation IDs, sampling, log levels, sinks, formatters. | 6,000 |
| `tracing` | Distributed tracing. Spans, context propagation, exporters (OTLP, Jaeger, Zipkin). | 8,000 |
| `monitoring` | Metrics collection. Counters, histograms, gauges, alerting rules, dashboards. | 8,000 |
| `message_queue` | In-process + pluggable MQ. Topics, dead-letter, retry, back-pressure. | 9,000 |
| `event_bus` | Pub/sub event system. Typed events, middleware, replay, event sourcing. | 8,000 |
| `event_platform` | Event streaming platform. Partitions, consumer groups, compaction, schemas. | 10,000 |
| `task_queue` | Distributed task queue. Priority, scheduling, retries, result store, workflows. | 9,000 |
| `scheduler_deep` | Advanced scheduler. Cron, interval, dependency DAG, calendar, timezone. | 8,000 |
| `kvstore` | Key-value store. LSM-tree, bloom filters, compaction, snapshots. | 10,000 |
| `tsdb` | Time-series database engine. Columnar storage, downsampling, retention. | 10,000 |
| `graphdb` | Property graph database. Cypher-subset query engine, traversals, indexing. | 10,000 |
| `docdb` | Document database. JSON storage, indexing, query planner, aggregation. | 9,000 |
| `olap` | OLAP cube engine. Star schema, drill-down, rollup, MDX-subset. | 8,000 |
| `columnar` | Columnar storage engine. Compression, vectorized scan, predicate pushdown. | 9,000 |
| `db_internals` | B-tree, WAL, MVCC, buffer pool, lock manager, recovery. | 12,000 |
| `data_pipeline` | ETL/ELT pipeline framework. Sources, transforms, sinks, lineage. | 10,000 |
| `data_quality` | Data quality checks. Profiling, anomaly detection, freshness, schema drift. | 8,000 |
| `data_catalog` | Metadata catalog. Discovery, lineage, tagging, search, access control. | 8,000 |
| `data_warehouse` | DW modeling. Slowly-changing dimensions, fact tables, materializations. | 8,000 |
| `etl_monitor` | ETL monitoring dashboard. Job status, SLA tracking, failure analysis. | 7,000 |
| `schema` | Schema registry. Avro/Protobuf/JSON-Schema, compatibility checks, evolution. | 7,000 |
| `load_balancer` | L4/L7 load balancer. Round-robin, least-conn, consistent hash, health checks. | 8,000 |
| `service_mesh` | Service mesh control plane. Service discovery, routing, circuit breaking. | 9,000 |
| `dns` | DNS resolver + mini authoritative server. Zone files, caching, DNSSEC stubs. | 7,000 |
| `http2` | HTTP/2 frame parser. HPACK, streams, flow control, server push. | 8,000 |
| `quic` | QUIC protocol implementation. Connection management, streams, 0-RTT. | 10,000 |
| `webrtc` | WebRTC signaling + data channel. SDP, ICE, DTLS handshake, SCTP. | 9,000 |
| `cdn` | CDN edge logic. Cache rules, purge, origin shield, geo-routing. | 7,000 |
| `containers` | Container runtime. Image layers, namespaces, cgroups, networking. | 10,000 |
| `waf` | Web application firewall. Rule engine, IP reputation, rate limiting, OWASP. | 8,000 |

**Phase 1 subtotal: ~280,000 lines across 33 modules**

---

### Phase 2: Language & Compiler Infrastructure (Target: +600K lines)
*Deep CS — parsers, compilers, interpreters, formal methods.*

| Module | Description | Est. Lines |
|--------|-------------|------------|
| `compiler_infra` | Compiler pipeline. Lexer, parser, AST, IR, optimizations, codegen. | 15,000 |
| `dsl` | Domain-specific language toolkit. Grammar DSL, interpreter, type checker. | 10,000 |
| `regex_engine` | Regex engine from scratch. NFA/DFA, Thompson construction, backtracking. | 8,000 |
| `parsers` | Parser combinators + generators. PEG, Earley, GLR, error recovery. | 10,000 |
| `template_engine` | Template engine. Jinja-like syntax, sandboxed execution, inheritance. | 8,000 |
| `formal_verify` | Formal verification. Model checking, SAT solver, symbolic execution. | 12,000 |
| `codegen` | Code generation framework. Templates, AST manipulation, multi-language output. | 9,000 |
| `serialization` (extended) | Binary protocol compiler. IDL → Python stubs + ser/deser. | 6,000 |
| `markdown` | Full CommonMark parser + extensions. AST, renderer, plugins. | 8,000 |
| `nlg` | Natural language generation. Templates, grammar rules, variation, fluency. | 8,000 |
| `nlu` | NLU pipeline. Tokenizer, NER, intent classification, slot filling. | 10,000 |
| `doc_processing` | Document processing. PDF extraction, OCR pipeline, table detection. | 9,000 |

**Phase 2 subtotal: ~113,000 lines across 12 modules**

---

### Phase 3: AI / ML / Data Science (Target: +800K lines)

| Module | Description | Est. Lines |
|--------|-------------|------------|
| `distributed_ml` | Distributed training. Data parallel, model parallel, gradient sync. | 12,000 |
| `model_serving` | Model serving infrastructure. Batching, A/B test, canary, versioning. | 10,000 |
| `recommender` | Recommendation engine. Collaborative filtering, content-based, hybrid. | 10,000 |
| `graph_analytics` | Graph algorithms. PageRank, community detection, shortest path, centrality. | 10,000 |
| `graph_engine` | Graph computation engine. BSP model, vertex programs, aggregators. | 9,000 |
| `stats` | Statistics library. Distributions, hypothesis tests, regression, Bayesian. | 12,000 |
| `cv` | Computer vision pipeline. Feature detection, matching, homography, tracking. | 12,000 |
| `image_proc` | Image processing. Filters, transforms, color spaces, histogram, morphology. | 10,000 |
| `signal_proc` | Signal processing. FFT, filters, wavelets, spectrograms, convolution. | 10,000 |
| `audio_engine` | Audio processing. Synthesis, effects, mixing, MIDI, analysis. | 10,000 |
| `music` | Music theory engine. Scales, chords, progressions, rhythm, notation. | 8,000 |
| `voice` | Voice processing. VAD, speaker diarization, feature extraction. | 8,000 |
| `knowledge_graph` | Knowledge graph. Triple store, reasoning, SPARQL subset, ontology. | 10,000 |
| `search_engine` | Full-text search. Inverted index, BM25, facets, fuzzy, autocomplete. | 12,000 |
| `dataframe` | DataFrame implementation. Column ops, joins, groupby, window functions. | 12,000 |
| `bi_engine` | Business intelligence. Report builder, pivot tables, drill-through. | 9,000 |
| `visualization` | Visualization engine. Chart types, layout, scales, axes, interactivity. | 10,000 |

**Phase 3 subtotal: ~174,000 lines across 17 modules**

---

### Phase 4: Domain Verticals — Part A (Target: +1M lines)
*Real industry domains with deep business logic.*

| Module | Description | Est. Lines |
|--------|-------------|------------|
| `fintech` | Financial tech. Order matching, risk calc, portfolio, settlement, compliance. | 15,000 |
| `quantfin` | Quantitative finance. Options pricing, Monte Carlo, VaR, Greeks, backtesting. | 12,000 |
| `blockchain` | Blockchain engine. Block structure, consensus, Merkle tree, smart contracts. | 15,000 |
| `crypto` | Cryptography. AES, RSA, ECC, hashing, KDF, digital signatures, certificates. | 12,000 |
| `ecommerce` | E-commerce platform. Cart, checkout, inventory, pricing, promotions. | 12,000 |
| `marketplace` | Marketplace engine. Listings, matching, escrow, reviews, search. | 10,000 |
| `crm` | CRM system. Contacts, pipeline, activities, scoring, reporting. | 10,000 |
| `erp` | ERP core. GL, AP, AR, inventory, purchasing, manufacturing. | 15,000 |
| `hrm` | HR management. Employees, payroll, benefits, time tracking, reviews. | 10,000 |
| `hr_platform` | HR platform extended. Recruiting, onboarding, training, compliance. | 10,000 |
| `project_mgmt` | Project management. Tasks, Gantt, resources, critical path, burndown. | 10,000 |
| `supply_chain` | Supply chain. Demand forecast, procurement, logistics, warehouse. | 12,000 |
| `legal` | Legal ops. Contract management, clause library, deadlines, matter tracking. | 10,000 |
| `real_estate` | Real estate. Listings, valuations, lease management, property analytics. | 9,000 |
| `travel` | Travel booking. Search, pricing, booking, itinerary, availability. | 10,000 |
| `social_platform` | Social platform. Feed algorithm, connections, content moderation, notifications. | 12,000 |

**Phase 4A subtotal: ~184,000 lines across 16 modules**

---

### Phase 5: Domain Verticals — Part B (Target: +1M lines)
*Science, engineering, and specialized domains.*

| Module | Description | Est. Lines |
|--------|-------------|------------|
| `bioinformatics` | Bioinformatics. Sequence alignment, phylogenetics, protein structure, BLAST. | 12,000 |
| `climate` | Climate modeling. Weather simulation, emissions tracking, projections. | 10,000 |
| `agriculture` | Agriculture platform. Crop planning, soil analysis, irrigation, yield prediction. | 10,000 |
| `energy` | Energy management. Grid modeling, demand response, battery optimization. | 10,000 |
| `food_tech` | Food technology. Recipe optimization, nutrition, supply chain, safety. | 8,000 |
| `iot_platform` | IoT platform. Device management, telemetry, rules engine, OTA updates. | 12,000 |
| `smart_home` | Smart home. Device registry, automation rules, scenes, energy monitoring. | 10,000 |
| `telecom` | Telecom. Call routing, billing, CDR processing, network topology. | 10,000 |
| `autonomous_vehicles` | AV stack. Perception pipeline, path planning, behavior planning, control. | 15,000 |
| `robotics_deep` | Robotics. Kinematics, motion planning, SLAM, sensor fusion. | 12,000 |
| `simulation` | Simulation engine. Discrete event, continuous, Monte Carlo, agent-based. | 12,000 |
| `physics` | Physics engine. Rigid body, collision detection, constraints, integration. | 12,000 |
| `game_ai` | Game AI. Behavior trees, GOAP, navmesh, influence maps, utility AI. | 10,000 |
| `gaming_platform` | Gaming platform. Matchmaking, leaderboards, achievements, replay. | 10,000 |
| `procgen` | Procedural generation. Terrain, dungeons, cities, textures, names. | 10,000 |
| `graphics3d` | 3D graphics. Rasterizer, ray tracer, shaders, mesh processing. | 12,000 |
| `cad` | CAD engine. 2D/3D geometry, boolean ops, constraints, file formats. | 10,000 |
| `siem` | SIEM platform. Log ingestion, correlation, alerts, incident response. | 10,000 |
| `pentest` | Pentest toolkit. Scanner, vulnerability DB, exploit framework, reporting. | 10,000 |

**Phase 5 subtotal: ~205,000 lines across 19 modules**

---

### Phase 6: Platform & Integration Layer (Target: +800K lines)

| Module | Description | Est. Lines |
|--------|-------------|------------|
| `api_gateway` | API gateway. Rate limiting, auth, transformation, versioning, analytics. | 10,000 |
| `gateway` (extended) | Gateway extensions. GraphQL federation, gRPC-web, protocol translation. | 8,000 |
| `cqrs` | CQRS + Event Sourcing. Command bus, projections, snapshots, sagas. | 10,000 |
| `devops_platform` | DevOps platform. CI/CD pipeline, deployment, rollback, feature flags. | 12,000 |
| `multi_cloud` | Multi-cloud orchestration. Provider abstraction, cost optimization, migration. | 10,000 |
| `ecs` | Entity Component System. Archetypes, queries, systems, scheduling. | 8,000 |
| `os_kernel` | Mini OS kernel. Process scheduler, memory allocator, VFS, syscalls. | 15,000 |
| `networking_deep` | Network stack. TCP state machine, congestion control, socket layer. | 12,000 |
| `email_protocol` | Email protocols. SMTP client/server, IMAP parser, MIME, DKIM. | 9,000 |
| `behavior_tree` | Behavior tree runtime. Composites, decorators, blackboard, debug viz. | 8,000 |
| `pathfinding` | Pathfinding algorithms. A*, D*, JPS, flow fields, navmesh generation. | 8,000 |
| `patterns` | Design patterns library. Gang of Four, enterprise, concurrent patterns. | 10,000 |
| `units` | Units of measure. Dimensional analysis, conversion, compound units. | 6,000 |
| `chatbot` | Chatbot framework. Dialog management, slot filling, context, multi-turn. | 10,000 |
| `groupchat` | Group chat. Rooms, moderation, threads, reactions, presence. | 8,000 |
| `notify` | Notification system. Multi-channel dispatch, templates, preferences, digest. | 8,000 |
| `webhooks` (extended) | Webhook platform. Registration, delivery, retry, signature verification. | 7,000 |

**Phase 6 subtotal: ~159,000 lines across 17 modules**

---

### Phase 7: Testing & Quality Infrastructure (Target: +1M lines)
*Every module above gets comprehensive tests. Plus cross-cutting test infrastructure.*

For each of the ~115 modules above, generate:

- `test_<module>_core.py` — Unit tests for core logic (~200-400 lines each)
- `test_<module>_engine.py` — Engine/integration tests (~200-300 lines each)
- `test_<module>_store.py` — Persistence tests (~150-250 lines each)
- `test_<module>_validators.py` — Validation edge cases (~150-200 lines each)
- `test_<module>_integration.py` — Cross-module integration (~200-300 lines each)
- `test_<module>_edge_cases.py` — Boundary/error conditions (~200-300 lines each)

**Average 1,200 test lines per module × 115 modules = ~138,000 lines of tests**

Plus cross-cutting test infrastructure:

| Component | Description | Est. Lines |
|-----------|-------------|------------|
| `tests/conftest_extended.py` | Shared fixtures, factories, mocks | 3,000 |
| `tests/factories/` | Test data factories for each domain | 20,000 |
| `tests/property_tests/` | Hypothesis property-based tests | 15,000 |
| `tests/fuzz/` | Fuzzing harnesses for parsers/protocols | 10,000 |
| `tests/benchmarks/` | Performance benchmarks with assertions | 10,000 |
| `tests/contract_tests/` | API contract tests | 8,000 |
| `tests/load_tests/` | Load/stress test scenarios | 6,000 |

**Phase 7 subtotal: ~210,000 lines**

---

### Phase 8: Documentation, Scripts, & CLI Extensions (Target: +500K lines)

| Component | Description | Est. Lines |
|-----------|-------------|------------|
| Per-module README.md | Architecture docs for each module | 23,000 |
| `docs/architecture/` | System design documents | 15,000 |
| `docs/api/` | API reference per module | 30,000 |
| `scripts/` | Build, deploy, migration, analysis scripts | 20,000 |
| CLI extensions | New `thomas <module>` subcommands | 25,000 |
| `apps/` extensions | Frontend components for new modules | 40,000 |
| Config/fixture files | TOML, YAML, JSON for testing/config | 50,000 |

**Phase 8 subtotal: ~203,000 lines**

---

## Totals

| Phase | Focus | Est. Lines |
|-------|-------|------------|
| Phase 1 | Infrastructure & Data Layer | 280,000 |
| Phase 2 | Language & Compiler | 113,000 |
| Phase 3 | AI / ML / Data Science | 174,000 |
| Phase 4 | Domain Verticals A (Business) | 184,000 |
| Phase 5 | Domain Verticals B (Science/Eng) | 205,000 |
| Phase 6 | Platform & Integration | 159,000 |
| Phase 7 | Testing & Quality | 210,000 |
| Phase 8 | Docs, Scripts, CLI, Frontend | 203,000 |
| **Subtotal (dense code)** | | **1,528,000** |

> **Scaling to 6M:** Each module estimate above is conservative (the "core" of each module).
> To reach 6M, each module expands with:
> - Additional submodules (e.g. `fintech/` gets `fintech/clearing/`, `fintech/custody/`, `fintech/kyc/`, etc.)
> - Protocol implementations within each domain
> - Adapters, middleware, and plugin systems
> - Comprehensive test matrices
> - CLI tooling per module
> - Serialization/API layers
>
> **Multiplier: ~4× → 6,112,000 lines**

---

## Execution Strategy

### Per-Session Approach

Each Cowork session targets **one phase or sub-phase** (~100K-200K lines):

1. **Claim scope** per Thomas handshake protocol
2. **Build modules in dependency order** within the phase
3. **Each module**: types → exceptions → config → core logic → engine → store → validators → tests
4. **Run architecture tests** after each module: `pytest tests/test_architecture.py -x`
5. **Update `_architecture.py`** with new module entries
6. **Update `CHANGELOG.md`** after each module
7. **Version bump** once per session

### File Size Enforcement

- Every `.py` file: **max 800 lines** (matches Thomas monolith rules)
- If a file approaches 600 lines → split into focused submodules
- Prefer many small files over few large ones

### Quality Gates Per Module

Before marking a module "done":

1. All files pass `python -c "import py_compile; py_compile.compile('...', doraise=True)"`
2. All tests pass: `pytest tests/test_<module>*.py -x`
3. No circular imports within the module
4. Type annotations on all public functions
5. Docstrings on all public classes and functions
6. Architecture test passes: `pytest tests/test_architecture.py -x`

---

## Priority Order (What to Build First)

1. **Infrastructure** (Phase 1) — everything depends on these
2. **Testing infra** (Phase 7 partial) — need factories/fixtures early
3. **AI/ML** (Phase 3) — closest to Thomas's core mission
4. **Platform** (Phase 6) — extends Thomas's integration capabilities
5. **Compiler/Language** (Phase 2) — powers Thomas's DSL/codegen features
6. **Domain Verticals** (Phases 4-5) — breadth expansion
7. **Docs/Scripts** (Phase 8) — polish layer

---

## Session Template

```
Session: Phase X, Modules [a, b, c]
1. Read KNOWN_ISSUES.md
2. Read _architecture.py
3. Claim scope via workboard
4. For each module:
   a. Create directory structure
   b. Write _types.py, _exceptions.py, _config.py
   c. Write core.py, engine.py, models.py
   d. Write store.py, validators.py, serializers.py
   e. Write tests (unit + integration + edge cases)
   f. Register in _architecture.py
   g. Add CHANGELOG entry
5. Run full test suite
6. Version bump
7. Release claim
```

---

*Plan created: 2026-02-25*
*Current LOC: ~2,185,836*
*Target additional: ~6,000,000*
*Estimated sessions to complete: 30-50 (at ~150K lines/session)*
