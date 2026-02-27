# Workflow Builder API Integration Guide

This guide provides example implementations for integrating the Workflow Builder UI with your Thomas backend.

## Data Model

### Workflow Schema

```json
{
  "id": "workflow_123",
  "name": "My Workflow",
  "created_at": "2026-02-26T21:19:00Z",
  "updated_at": "2026-02-26T21:19:00Z",
  "nodes": [
    {
      "id": "node_1",
      "type": "tool_call",
      "x": 100,
      "y": 100,
      "label": "Search Files",
      "tool_name": "code_search",
      "arguments": {
        "query": "search term",
        "limit": 10
      }
    },
    {
      "id": "node_2",
      "type": "llm_prompt",
      "x": 300,
      "y": 100,
      "label": "Analyze",
      "prompt": "Analyze these files: {{results}}",
      "model": "gpt-4",
      "temperature": 0.7
    },
    {
      "id": "node_3",
      "type": "approval",
      "x": 500,
      "y": 100,
      "label": "Review",
      "message": "Approve the analysis?",
      "approver": "user@example.com",
      "timeout": 3600
    }
  ],
  "edges": [
    {
      "id": "edge_1",
      "from": "node_1",
      "to": "node_2"
    },
    {
      "id": "edge_2",
      "from": "node_2",
      "to": "node_3"
    }
  ]
}
```

### Execution Result Schema

```json
{
  "run_id": "run_456",
  "workflow_id": "workflow_123",
  "status": "running",
  "started_at": "2026-02-26T21:20:00Z",
  "completed_at": null,
  "node_results": {
    "node_1": {
      "status": "completed",
      "output": [{"file": "test.py", "line": 42}],
      "duration_ms": 234
    },
    "node_2": {
      "status": "running",
      "output": null,
      "duration_ms": null
    },
    "node_3": {
      "status": "pending",
      "output": null,
      "duration_ms": null
    }
  },
  "errors": []
}
```

## API Endpoints (Example Implementation)

### 1. Create Workflow

**Endpoint**: `POST /api/workflows`

**Request**:
```json
{
  "name": "My Workflow",
  "nodes": [...],
  "edges": [...]
}
```

**Response** (201 Created):
```json
{
  "id": "workflow_123",
  "name": "My Workflow",
  "created_at": "2026-02-26T21:19:00Z",
  "updated_at": "2026-02-26T21:19:00Z"
}
```

### 2. List Workflows

**Endpoint**: `GET /api/workflows`

**Query Parameters**:
- `limit`: Number of results (default: 50)
- `offset`: Pagination offset (default: 0)
- `search`: Search by name

**Response** (200 OK):
```json
{
  "workflows": [
    {
      "id": "workflow_123",
      "name": "My Workflow",
      "created_at": "2026-02-26T21:19:00Z",
      "node_count": 3,
      "edge_count": 2
    },
    ...
  ],
  "total": 42,
  "limit": 50,
  "offset": 0
}
```

### 3. Get Workflow

**Endpoint**: `GET /api/workflows/{id}`

**Response** (200 OK):
```json
{
  "id": "workflow_123",
  "name": "My Workflow",
  "created_at": "2026-02-26T21:19:00Z",
  "updated_at": "2026-02-26T21:19:00Z",
  "nodes": [...],
  "edges": [...]
}
```

### 4. Update Workflow

**Endpoint**: `PUT /api/workflows/{id}`

**Request**:
```json
{
  "name": "Updated Name",
  "nodes": [...],
  "edges": [...]
}
```

**Response** (200 OK):
```json
{
  "id": "workflow_123",
  "name": "Updated Name",
  "updated_at": "2026-02-26T21:21:00Z"
}
```

### 5. Delete Workflow

**Endpoint**: `DELETE /api/workflows/{id}`

**Response** (204 No Content)

### 6. Run Workflow

**Endpoint**: `POST /api/workflows/{id}/run`

**Request** (optional):
```json
{
  "inputs": {
    "param1": "value1"
  }
}
```

**Response** (202 Accepted):
```json
{
  "run_id": "run_456",
  "workflow_id": "workflow_123",
  "status": "queued",
  "started_at": "2026-02-26T21:20:00Z"
}
```

### 7. Get Run Status

**Endpoint**: `GET /api/workflows/{id}/run/{run_id}`

**Response** (200 OK):
```json
{
  "run_id": "run_456",
  "workflow_id": "workflow_123",
  "status": "running",
  "started_at": "2026-02-26T21:20:00Z",
  "completed_at": null,
  "progress": {
    "total_nodes": 3,
    "completed_nodes": 1,
    "running_nodes": 1,
    "failed_nodes": 0
  },
  "node_results": {
    "node_1": {
      "status": "completed",
      "output": {...},
      "duration_ms": 234
    }
  }
}
```

### 8. Stop Workflow

**Endpoint**: `POST /api/workflows/{id}/run/{run_id}/stop`

**Response** (200 OK):
```json
{
  "run_id": "run_456",
  "status": "cancelled"
}
```

## Example FastAPI Implementation

```python
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime
import uuid

app = FastAPI()

# ============= MODELS =============

class WorkflowNode(BaseModel):
    id: str
    type: str
    x: float
    y: float
    label: str
    tool_name: Optional[str] = None
    arguments: Optional[Dict[str, Any]] = None
    prompt: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    expression: Optional[str] = None
    collection: Optional[str] = None
    duration: Optional[int] = None
    message: Optional[str] = None
    approver: Optional[str] = None
    timeout: Optional[int] = None
    url: Optional[str] = None
    method: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    body: Optional[str] = None

class WorkflowEdge(BaseModel):
    id: str
    from_node: str
    to_node: str

class Workflow(BaseModel):
    name: str
    nodes: List[WorkflowNode]
    edges: List[WorkflowEdge]

# ============= STORAGE (In-Memory for Demo) =============

workflows_db = {}
runs_db = {}

# ============= ENDPOINTS =============

@app.post("/api/workflows")
async def create_workflow(workflow: Workflow):
    """Create a new workflow."""
    workflow_id = f"workflow_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat() + "Z"

    workflows_db[workflow_id] = {
        "id": workflow_id,
        "name": workflow.name,
        "nodes": [node.dict() for node in workflow.nodes],
        "edges": [edge.dict() for edge in workflow.edges],
        "created_at": now,
        "updated_at": now,
    }

    return {
        "id": workflow_id,
        "name": workflow.name,
        "created_at": now,
        "updated_at": now,
    }

@app.get("/api/workflows")
async def list_workflows(limit: int = 50, offset: int = 0, search: str = ""):
    """List all workflows."""
    workflows = list(workflows_db.values())

    if search:
        workflows = [w for w in workflows if search.lower() in w["name"].lower()]

    total = len(workflows)
    workflows = workflows[offset:offset + limit]

    return {
        "workflows": [
            {
                "id": w["id"],
                "name": w["name"],
                "created_at": w["created_at"],
                "node_count": len(w["nodes"]),
                "edge_count": len(w["edges"]),
            }
            for w in workflows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }

@app.get("/api/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    """Get a specific workflow."""
    if workflow_id not in workflows_db:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflows_db[workflow_id]

@app.put("/api/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, workflow: Workflow):
    """Update a workflow."""
    if workflow_id not in workflows_db:
        raise HTTPException(status_code=404, detail="Workflow not found")

    now = datetime.utcnow().isoformat() + "Z"
    workflows_db[workflow_id].update({
        "name": workflow.name,
        "nodes": [node.dict() for node in workflow.nodes],
        "edges": [edge.dict() for edge in workflow.edges],
        "updated_at": now,
    })

    return {"id": workflow_id, "name": workflow.name, "updated_at": now}

@app.delete("/api/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str):
    """Delete a workflow."""
    if workflow_id not in workflows_db:
        raise HTTPException(status_code=404, detail="Workflow not found")
    del workflows_db[workflow_id]
    return JSONResponse(status_code=204, content=None)

@app.post("/api/workflows/{workflow_id}/run")
async def run_workflow(workflow_id: str):
    """Execute a workflow."""
    if workflow_id not in workflows_db:
        raise HTTPException(status_code=404, detail="Workflow not found")

    run_id = f"run_{uuid.uuid4().hex[:12]}"
    now = datetime.utcnow().isoformat() + "Z"

    runs_db[run_id] = {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "status": "queued",
        "started_at": now,
        "node_results": {},
    }

    # TODO: Queue for execution in your workflow engine

    return {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "status": "queued",
        "started_at": now,
    }

@app.get("/api/workflows/{workflow_id}/run/{run_id}")
async def get_run_status(workflow_id: str, run_id: str):
    """Get workflow execution status."""
    if run_id not in runs_db:
        raise HTTPException(status_code=404, detail="Run not found")

    run = runs_db[run_id]
    nodes = workflows_db[workflow_id]["nodes"]

    return {
        "run_id": run["run_id"],
        "workflow_id": run["workflow_id"],
        "status": run["status"],
        "started_at": run["started_at"],
        "completed_at": run.get("completed_at"),
        "progress": {
            "total_nodes": len(nodes),
            "completed_nodes": sum(1 for r in run["node_results"].values() if r.get("status") == "completed"),
            "running_nodes": sum(1 for r in run["node_results"].values() if r.get("status") == "running"),
            "failed_nodes": sum(1 for r in run["node_results"].values() if r.get("status") == "failed"),
        },
        "node_results": run["node_results"],
    }

@app.post("/api/workflows/{workflow_id}/run/{run_id}/stop")
async def stop_workflow(workflow_id: str, run_id: str):
    """Stop a running workflow."""
    if run_id not in runs_db:
        raise HTTPException(status_code=404, detail="Run not found")

    runs_db[run_id]["status"] = "cancelled"
    return {"run_id": run_id, "status": "cancelled"}
```

## Integration Steps

1. **Create Database Schema**
   - Store workflow definitions (name, nodes, edges, timestamps)
   - Store execution runs (run_id, status, node_results, timestamps)

2. **Implement Workflow Executor**
   - Parse workflow graph (topologically sort nodes)
   - Execute nodes in order, respecting edges
   - Handle branching (condition nodes)
   - Handle parallelism (parallel nodes)
   - Store node output for downstream nodes

3. **Add Status Polling**
   - Frontend polls `/api/workflows/{id}/run/{run_id}` every 2 seconds
   - Returns node execution status and results
   - Update UI with color-coded node states

4. **Handle Node Execution**
   - Tool Call: Call tool registry
   - LLM Prompt: Call LLM API with model and prompt
   - Condition: Evaluate expression against previous outputs
   - Loop: Repeat child steps for each item
   - Parallel: Execute children concurrently
   - Wait: Sleep for duration or condition
   - Approval: Block and wait for user approval
   - Webhook: Call external HTTP endpoint

5. **Error Handling**
   - Catch exceptions during node execution
   - Mark node as failed
   - Stop workflow or follow error handling path
   - Store error messages for debugging

## Testing

Use curl to test endpoints:

```bash
# Create workflow
curl -X POST http://localhost:8899/api/workflows \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Workflow",
    "nodes": [...],
    "edges": [...]
  }'

# List workflows
curl http://localhost:8899/api/workflows

# Get workflow
curl http://localhost:8899/api/workflows/workflow_123

# Run workflow
curl -X POST http://localhost:8899/api/workflows/workflow_123/run

# Get run status
curl http://localhost:8899/api/workflows/workflow_123/run/run_456
```
