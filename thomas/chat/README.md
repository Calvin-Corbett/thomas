# Chat - Conversation Management

This directory manages conversation state, multi-turn context, memory layers, session storage, and event streaming for chat interactions.

## What This Directory Does

Chat infrastructure keeps track of the conversation:

```
User sends message
        ↓
ConversationManager loads context (past messages, memory)
        ↓
Message is processed
        ↓
Response is generated
        ↓
EventDispatcher streams events to UI
        ↓
SessionStore saves state
```

## Key Files

| File | Purpose |
|---|---|
| `conversation.py` | **CRITICAL**. ConversationManager—manages multi-turn context |
| `memory_layers.py` | MemoryContext and MemoryCoordinator—integrate memory system |
| `session_store.py` | SessionStore—save/load conversation state |
| `event_stream.py` | EventDispatcher—stream events to UI |
| `thinking.py` | ThinkingTracker—track extended thinking |

## ConversationManager (conversation.py)

This is the entry point for chat state:

```python
from thomas.chat.conversation import ConversationManager

# Create/load conversation
manager = ConversationManager(
    conversation_id='user-123-session-456',
    user_id='user-123'
)

# Load past context
context = await manager.load_context()
print(f"Previous messages: {len(context.messages)}")
print(f"Previous turns: {context.turns}")

# Add new message
await manager.add_message(
    role='user',
    content='What is 2+2?'
)

# Generate response
response = await manager.generate_response(
    model='claude-opus-4.6',
    max_tokens=1000
)

# Save state
await manager.save()
```

## Memory Layers (memory_layers.py)

Integrates the memory system with chat:

```python
from thomas.chat.memory_layers import MemoryCoordinator, MemoryContext

coordinator = MemoryCoordinator()

# Get context for current request
context = await coordinator.get_context(
    query="user's message",
    max_results=5
)

# Context includes:
# - Relevant past conversations
# - Learned patterns
# - User preferences
# - Domain knowledge

# Use in specialist
result = await specialist.execute(
    contract=contract,
    context=context
)
```

## Session Store (session_store.py)

Saves and loads conversation sessions:

```python
from thomas.chat.session_store import SessionStore

store = SessionStore()

# Save a session
await store.save_session({
    'session_id': 'sess-123',
    'user_id': 'user-123',
    'messages': [...],
    'metadata': {'last_accessed': time.time()}
})

# Load a session
session = await store.load_session('sess-123')
print(f"Messages: {len(session['messages'])}")

# List user's sessions
sessions = await store.list_sessions('user-123')
for sess in sessions:
    print(f"{sess['session_id']}: {len(sess['messages'])} messages")

# Delete old session
await store.delete_session('old-session-id')
```

## Event Stream (event_stream.py)

Streams events to the browser UI in real-time:

```python
from thomas.chat.event_stream import EventDispatcher

dispatcher = EventDispatcher()

# Emit an event
await dispatcher.emit('message', {
    'text': 'Hello, user!',
    'role': 'assistant'
})

# Different event types
await dispatcher.emit('thinking', {'text': 'Let me analyze...'})
await dispatcher.emit('tool_use', {'tool': 'web_search', 'query': '...'})
await dispatcher.emit('progress', {'percent': 50})
await dispatcher.emit('done', {'text': 'Final response'})
```

The browser receives these as Server-Sent Events:

```javascript
const events = new EventSource('/chat-events');
events.addEventListener('message', (e) => {
    const data = JSON.parse(e.data);
    console.log(data);
});
```

## Thinking Tracker (thinking.py)

Tracks extended thinking (if using thinking models):

```python
from thomas.chat.thinking import ThinkingTracker

tracker = ThinkingTracker()

# Start thinking
await tracker.start()

# Log thoughts
await tracker.add_thought("First, I need to understand the problem")
await tracker.add_thought("Then I'll search for relevant information")

# Get thinking for display
thinking_text = tracker.get_thinking()
print(f"Thinking: {thinking_text}")

# Finish thinking
result = await tracker.finish()
print(f"Thinking tokens: {result.tokens_used}")
```

## Chat Flow

```
1. User sends message
   └─→ routes/chat_aiohttp_part02.py

2. Dispatch classification
   └─→ agent/dispatch.py
       └─→ CASUAL or ACTIONABLE

3. If CASUAL (quick reply)
   └─→ Reply immediately
       └─→ No LLM call needed

4. If ACTIONABLE
   └─→ "On it." acknowledgment
   └─→ Load conversation context
   └─→ ConversationManager.load_context()
   └─→ Get memory context
   └─→ Route to orchestrator

5. Orchestrator delegates
   └─→ orchestrator/brain.py
   └─→ Matches to specialists

6. Specialists execute
   └─→ specialists/*.py
   └─→ Use tools and memory
   └─→ Return results

7. Events stream back
   └─→ EventDispatcher.emit()
   └─→ Browser receives via SSE
   └─→ UI updates in real-time

8. Save session
   └─→ ConversationManager.save()
   └─→ SessionStore saves to backend
```

## Message Structure

Messages follow this format:

```python
{
    'id': 'msg-abc-123',
    'role': 'user' or 'assistant',
    'content': 'The actual message text',
    'timestamp': 1710768000,
    'metadata': {
        'intent': 'actionable',  # or 'casual'
        'tokens_used': 250,
        'specialist': 'reasoning',
        'model': 'claude-opus-4.6'
    }
}
```

## Common Mistakes

### ✗ Don't do this:

1. **Create ConversationManager directly in loops** — Reuse instances.
2. **Forget to save sessions** — Call `manager.save()` after changes.
3. **Ignore memory context** — Pass it to specialists for better results.
4. **Emit events without dispatcher** — Use EventDispatcher for consistency.
5. **Assume session data is cached** — Load fresh from SessionStore.

### ✓ Do this:

1. Create one ConversationManager per session
2. Load context at the start: `await manager.load_context()`
3. Add messages as they come: `await manager.add_message()`
4. Save at the end: `await manager.save()`
5. Pass memory context to specialists
6. Emit events via EventDispatcher for UI updates

## Integration with Orchestrator

The chat system feeds context into the orchestrator:

```python
# In routes/chat_aiohttp_part02.py

# 1. Load conversation
manager = ConversationManager(conversation_id)
context = await manager.load_context()

# 2. Get memory context
memory_coordinator = MemoryCoordinator()
memory_context = await memory_coordinator.get_context(user_input)

# 3. Route through dispatch
is_actionable = dispatch.classify(user_input)

if is_actionable:
    # 4. Delegate to orchestrator
    brain = OrchestratorBrain()
    result = await brain.delegate(
        route_decision=route_decision,
        conversation_context=context,
        memory_context=memory_context
    )

    # 5. Add response to conversation
    await manager.add_message(role='assistant', content=result)
    await manager.save()

    # 6. Emit final event
    await dispatcher.emit('response', {'text': result})
```

## For AI Agents

### To manage conversation state:
```python
manager = ConversationManager(conversation_id='user-123-sess-456')
context = await manager.load_context()
# Use context for memory
await manager.add_message(role='assistant', content='Response')
await manager.save()
```

### To emit events to the UI:
```python
from thomas.chat.event_stream import EventDispatcher
dispatcher = EventDispatcher()
await dispatcher.emit('message', {'text': 'Update for user'})
```

### To get memory context:
```python
from thomas.chat.memory_layers import MemoryCoordinator
coordinator = MemoryCoordinator()
context = await coordinator.get_context(query='user input')
```

### To track thinking:
```python
from thomas.chat.thinking import ThinkingTracker
tracker = ThinkingTracker()
await tracker.start()
await tracker.add_thought('Analysis step 1')
result = await tracker.finish()
```

### To save/load sessions:
```python
from thomas.chat.session_store import SessionStore
store = SessionStore()
await store.save_session(session_data)
loaded = await store.load_session('session-id')
```

## Session Lifecycle

```
Session Created
    ↓
User sends first message
    ↓
ConversationManager loads (empty on first message)
    ↓
Message processed, response generated
    ↓
SessionStore saves (new session)
    ↓
User sends second message
    ↓
ConversationManager loads (has context from first message)
    ↓
Response uses past context
    ↓
SessionStore saves (updated session)
    ↓
[repeat]
    ↓
Session expires or user closes
    ↓
SessionStore deletes (after timeout)
```

## See Also

- `thomas/agent/dispatch.py` — Classification (casual vs actionable)
- `thomas/orchestrator/brain.py` — Delegation engine
- `thomas/memory/*.py` — Memory system
- `thomas/server/routes/chat_aiohttp_part02.py` — Main chat route
- `docs/CHAT_EXECUTION_MODEL.md` — Full architecture
