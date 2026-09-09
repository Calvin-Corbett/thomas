# Thomas Observability Dashboard Setup

This document describes how to integrate the real-time observability dashboard into the Thomas server.

## Files Created

### 1. Frontend Dashboard
**File:** `/sessions/intelligent-magical-ptolemy/mnt/Thomas/thomas/server/web/static/observability.html`

A single-file, self-contained HTML application that provides real-time monitoring of the Thomas system. Features include:

- **Live Event Stream** (top-left): Real-time scrolling log of system events with type-based filtering
- **System Metrics** (top-right): Key performance indicators and historical charts
- **Agent Activity** (bottom-left): Current status of active agents
- **Tool Usage Statistics** (bottom-right): Tool execution metrics and recent calls

### 2. Backend Routes
**File:** `/sessions/intelligent-magical-ptolemy/mnt/Thomas/thomas/server/routes/observability.py`

Backend API endpoints and WebSocket handler for the observability system.

## Integration Steps

### Step 1: Register Routes in app.py

Add the following imports at the top of `app.py`:

```python
from thomas.server.routes.observability import register_observability_routes
```

Then add this line in the main route setup section (around line 1860, after other routes):

```python
# Register observability routes
register_observability_routes(app)
```

### Step 2: Optional - Connect Event Tracking

To make the dashboard show real data, integrate event recording throughout the Thomas codebase:

```python
from thomas.server.routes.observability import record_event, update_metrics

# When a tool is called:
record_event(
    event_type="tool",
    source_agent="agent_name",
    message=f"Calling {tool_name}",
    details={"tool": tool_name, "params": {...}}
)

# When updating metrics:
update_metrics({
    "active_agents": count,
    "tasks_queued": queue_size,
    "memory_usage": mem_mb,
})
```

## Accessing the Dashboard

Once integrated and the server is running, visit:

```
http://localhost:8899/static/observability.html
```

(Replace port 8899 with your actual Thomas server port)

## Features

### Real-Time Updates
- WebSocket connection for live event streaming with automatic reconnection
- Graceful fallback to polling if WebSocket is unavailable
- Auto-refresh toggle for metrics (default: ON, every 2 seconds)

### Interactive Controls
- **Time Range Selector**: View data from last 1/5/15/60 minutes or 24 hours
- **Event Filters**: Toggle visibility of specific event types (tools, llm, agent, error, system)
- **Pause/Resume**: Pause event streaming to review specific events
- **Theme Toggle**: Switch between dark mode (default) and light theme
- **Auto-Refresh**: Enable/disable automatic metric updates

### Visual Design
- Responsive grid layout (adapts to screen size)
- Thomas-themed color scheme (navy #0a0e1a with cyan accents)
- Chart.js for historical data visualization
- Color-coded event types and agent status indicators
- Smooth animations and transitions

### Data Visualization
- Request rate chart (last 60 seconds)
- LLM token usage bar chart
- Tool usage bar chart (horizontal)
- Success rate pie chart
- Error rate indicator with visual status

## API Endpoints

### GET /api/events
Returns recent events with optional filtering.

**Query Parameters:**
- `type`: Comma-separated filter (e.g., "tool,llm,error")
- `limit`: Max events to return (default: 100, max: 500)
- `minutes`: Only events from last N minutes (default: 60)

**Response:**
```json
{
  "success": true,
  "events": [
    {
      "timestamp": "2024-02-26T21:30:00Z",
      "type": "tool",
      "source_agent": "agent_1",
      "message": "Calling file_read",
      "details": {...}
    }
  ],
  "count": 50,
  "total_available": 500
}
```

### GET /api/metrics
Returns current system metrics.

**Response:**
```json
{
  "success": true,
  "metrics": {
    "active_agents": 5,
    "tasks_queued": 12,
    "memory_usage": 256.3,
    "uptime_seconds": 3600,
    "request_rate": 15.5,
    "error_rate": 2.3,
    "llm_tokens": {"input": 50000, "output": 25000},
    "tools_called": 150,
    "timestamp": "2024-02-26T21:30:00Z"
  }
}
```

### GET /api/agents/activity
Returns active agent summary.

**Response:**
```json
{
  "success": true,
  "agents": [
    {
      "name": "agent_1",
      "status": "working",
      "current_task": "Processing file upload",
      "active_seconds": 45,
      "progress": 75
    }
  ],
  "active_count": 1
}
```

### GET /api/tools/usage
Returns tool usage statistics.

**Response:**
```json
{
  "success": true,
  "usage": {
    "by_tool": {"file_read": 50, "file_write": 30},
    "success_rate": 98.5,
    "total_calls": 150,
    "recent_calls": [
      {
        "tool": "file_read",
        "duration": 0.25,
        "success": true
      }
    ]
  }
}
```

### WS /ws/events
WebSocket endpoint for real-time event streaming.

**Connection Flow:**
1. Client connects to `/ws/events`
2. Server sends `{"type": "connected", "message": "..."}` on successful connection
3. Server broadcasts events: `{"type": "event", "data": {...}}`
4. Client can send ping: `{"type": "ping"}`
5. Server responds with pong: `{"type": "pong"}`

## Technical Details

### Frontend Architecture
- **Single HTML File**: ~1150 lines, fully self-contained with no external dependencies except Chart.js
- **State Management**: Global `state` object tracks all dashboard state
- **WebSocket First**: Attempts WebSocket connection with fallback to polling
- **Responsive Layout**: CSS Grid with mobile breakpoints
- **Theme Support**: Dark mode by default, light mode toggle with localStorage persistence

### Backend Architecture
- **In-Memory Storage**: Uses Python deque for efficient circular buffer of events (500 max)
- **Metrics Store**: Simple dict for current system metrics
- **WebSocket Management**: Set-based tracking of connected clients for broadcasting
- **Async-Friendly**: Uses aiohttp patterns for async route handlers and WebSocket support

## Troubleshooting

### Dashboard shows "No events yet"
- Ensure events are being recorded via `record_event()` calls
- Check browser console for any JavaScript errors
- Verify the backend routes are registered in `app.py`

### WebSocket connection fails
- Dashboard automatically falls back to polling `/api/events`
- Check browser console for WebSocket connection errors
- Verify WebSocket is enabled on your server/proxy configuration

### Charts not rendering
- Check that Chart.js CDN is accessible
- Verify browser console for Chart.js errors
- Ensure metrics are being updated via `update_metrics()` calls

### Events not appearing in real-time
- If using WebSocket, check that `_WEBSOCKET_CLIENTS` tracking is working
- If using polling, events will appear every 2 seconds
- Verify event timestamps are in UTC ISO format

## Performance Considerations

- **Event Storage**: Circular buffer limited to 500 events in memory
- **WebSocket Broadcasts**: Asynchronous, non-blocking to server operations
- **Chart Updates**: Capped at 30 data points per chart to limit rendering overhead
- **Polling Fallback**: 2-second refresh interval to balance responsiveness and load

## Future Enhancements

- Integration with actual Thomas agent manager for live agent status
- Tool call instrumentation for usage statistics
- Custom time-range queries with database backing
- Export capabilities (CSV/JSON)
- Alerting on error rate thresholds
- Historical data retention with optional database
- Filtering by time windows, agent IDs, tool names
- Performance profiling insights

## Testing

To test the dashboard without full Thomas integration:

1. Manually call the endpoint to create test events:
   ```python
   from thomas.server.routes.observability import record_event
   record_event("tool", "test_agent", "Test event")
   ```

2. Visit `/static/observability.html` to see the dashboard

3. Check `/api/events`, `/api/metrics` endpoints return data

4. Test WebSocket connection with a WebSocket client

## Support

For issues or feature requests related to the observability dashboard, refer to the main Thomas documentation or contact the development team.
