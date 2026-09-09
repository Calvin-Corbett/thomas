# Memory System - Context and Retrieval

This directory manages Thomas's long-term memory: storing conversations, retrieving relevant context, embeddings, and episodic memory for learning from past interactions.

## What This Directory Does

The memory system has three layers:

1. **Episodic Memory** — Stores past interactions, events, outcomes
2. **Retrieval** — Finds relevant context when needed
3. **Embeddings** — Semantic search via vector similarity

```
User message arrives
        ↓
MemoryCoordinator.get_context()
        ↓
episodic_retrieval.search(user_intent)
        ↓
Find similar past conversations via embeddings
        ↓
Return most relevant context to specialist
```

## Key Files and Status

| File | Status | What It Does |
|---|---|---|
| `__init__.py` | ACTIVE | MemoryCoordinator entry point |
| `autonomy.py` | ACTIVE | Autonomy memory—agent state and claims |
| `curator.py` | ACTIVE | Memory curator—manages retention, cleanup, compaction |
| `retrieval.py` | ACTIVE | Retrieval logic—fetch context by similarity |
| `embedder.py` | ACTIVE | Generate embeddings for semantic search |
| `episodic.py` | **PLACEHOLDER** | Episodic memory storage—mostly stubbed |
| `episodic_store.py` | **PLACEHOLDER** | Long-term episodic store—mostly stubbed |
| `episodic_retrieval.py` | **PLACEHOLDER** | Episodic context retrieval—mostly stubbed |
| `episodic_embeddings.py` | **PLACEHOLDER** | Episodic embedding generation—mostly stubbed |
| `summarization.py` | **PLACEHOLDER** | Conversation summarization—mostly stubbed |
| `store.py` | ACTIVE | Low-level storage backend |
| `search.py` | ACTIVE | Search utilities |
| `graph.py` | ACTIVE | Knowledge graph structures |
| `indexer.py` | STABLE | Indexing for fast retrieval |
| `rerank.py` | ACTIVE | Re-ranking retrieved results |
| `listing.py` | ACTIVE | Listing memory contents |
| `compaction.py` | ACTIVE | Memory compression |
| `compiler.py` | ACTIVE | Compile memory to formats |
| `v2/` | EXPERIMENTAL | V2 memory architecture (not integrated) |

## CRITICAL: Placeholder Files

**These files are NOT fully implemented yet:**
- `episodic.py` — Stores episodic memories, but storage is stubbed
- `episodic_store.py` — Long-term episodic storage, partially implemented
- `episodic_retrieval.py` — Retrieving episodic memories, stub functions
- `summarization.py` — Conversation summarization, mostly empty

**What this means:**
- You can import them and call functions, but they may return empty results
- Don't rely on episodic memory for critical logic
- Use `retrieval.py` and `embedder.py` instead (they're complete)

## How Memory Works (Active Components)

### 1. Storing Context

```python
from thomas.memory import MemoryCoordinator

coordinator = MemoryCoordinator()
await coordinator.store_context(
    context_type="conversation",
    content="User asked about X, I replied with Y",
    metadata={"user_id": "12345"}
)
```

### 2. Retrieving Context

```python
relevant_contexts = await coordinator.retrieve_context(
    query="fix database bug",
    max_results=5
)
# Returns list of past relevant interactions
```

### 3. Embedding for Semantic Search

```python
from thomas.memory.embedder import Embedder

embedder = Embedder()
vector = await embedder.embed(
    text="database performance issue"
)
# Vector can be stored and used for similarity search
```

## MemoryCoordinator (Entry Point)

This is the main class you interact with:

```python
class MemoryCoordinator:
    async def get_context(self, query: str) -> MemoryContext:
        """Get relevant context for a query."""
        # Uses retrieval to find similar past interactions

    async def store_context(self, data: dict) -> str:
        """Store new context."""
        # Saves to store.py backend

    async def cleanup(self):
        """Remove old memories."""
        # Uses curator.py

    async def compact(self):
        """Compress memory."""
        # Uses compaction.py
```

## Common Mistakes

### ✗ Don't do this:

1. **Rely on episodic memory for critical features** — It's partially stubbed.
2. **Store unbounded memory** — Call `coordinator.cleanup()` regularly.
3. **Assume all past interactions are stored** — Memory has size limits.
4. **Make raw database calls** — Use `coordinator` API instead.
5. **Embed on every request** — Cache embeddings in `store.py`.

### ✓ Do this:

1. Use `MemoryCoordinator.retrieve_context()` for context
2. Use `Embedder.embed()` for semantic search
3. Call `curator.cleanup()` periodically
4. Store metadata alongside context (user_id, timestamp, relevance)
5. Test retrieval with `search.py` utilities

## Memory Context Structure

```python
class MemoryContext:
    """Context passed to specialists."""
    query: str
    retrieved_memories: list[Memory]
    embeddings: list[float]
    metadata: dict
```

## Episodic Memory (Future Work)

These files exist for future expansion of episodic learning:

- `episodic.py` — Planned: Store individual episodes (conversations, tasks)
- `episodic_store.py` — Planned: Long-term episodic database
- `episodic_retrieval.py` — Planned: Retrieve by episode similarity
- `summarization.py` — Planned: Auto-summarize conversations

**Current status:** Mostly function stubs. Not recommended for production use.

## For AI Agents

### To retrieve context for a task:
```python
coordinator = MemoryCoordinator()
context = await coordinator.get_context(user_query)
# Pass context to specialist
```

### To store a result:
```python
await coordinator.store_context({
    "type": "task_result",
    "content": result_text,
    "metadata": {"task_id": "12345"}
})
```

### To find similar past interactions:
```python
contexts = await coordinator.retrieve_context(
    query=new_request,
    max_results=10
)
```

### To add a new memory module:
1. Create `thomas/memory/my_module.py`
2. Integrate with `MemoryCoordinator` in `__init__.py`
3. Document what it stores and retrieves
4. Add cleanup/compaction logic

### When episodic memory is ready:
1. Check if `episodic_store.py` has real implementation
2. Use `episodic_retrieval.py` to fetch past episodes
3. Apply `summarization.py` to extract patterns
4. Feed learned patterns into specialist decision-making

## For Debugging

- Check what's actually stored: `listing.py`
- Verify retrieval works: `search.py`
- Test embeddings: `embedder.py` with sample text
- Monitor memory size: `curator.py` metrics
- Profile retrieval speed: Add timers to `retrieval.py`

## See Also

- `thomas.chat.memory_layers.py` — How memory integrates with chat
- `thomas.core.rag_search.py` — RAG (Retrieval Augmented Generation)
- `thomas.core.rag_index.py` — Index for fast search
- `thomas.tools/base.py` — Tools can also store to memory
