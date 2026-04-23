# Workflow Builder - Quick Start Guide

## 30-Second Setup

1. Start Thomas server: `thomas serve --port 8899`
2. Open browser: `http://localhost:8899/static/workflow_builder.html`
3. Start building!

## Basic Workflow (2 minutes)

### Step 1: Add First Node
- Drag "Tool Call" from left sidebar
- Drop anywhere on canvas
- Node appears with grid alignment

### Step 2: Add Second Node
- Drag "LLM Prompt" from sidebar
- Drop to the right of first node
- Auto-snaps to grid

### Step 3: Connect Nodes
- Click the output port (right side) of Tool Call node
- Click the input port (left side) of LLM Prompt node
- Line connects the two nodes

### Step 4: Edit Properties
- Click on Tool Call node
- Right panel shows properties
- Enter tool_name: "code_search"
- Enter arguments as JSON: `{"query": "async function"}`

### Step 5: Run Workflow
- Click "Run" button in top bar
- Watch nodes highlight as they execute
- Green = running, grey = completed

### Step 6: Save Workflow
- Enter name in top-left input
- Click "Save" button
- Workflow saved to `/api/workflows`

## Common Tasks

### Export Workflow as JSON
1. Click "Export" button
2. File downloads as `{workflow_name}.json`
3. Share or version control

### Import Workflow from JSON
1. Click "Import" button
2. Select JSON file
3. Workflow loads on canvas

### Delete a Node
1. Click node to select
2. Press Delete key (or click × button)
3. Node and connected edges removed

### Delete a Connection
1. Click on connection line
2. Connection is removed

### Pan the Canvas
- Hold middle-mouse button and drag
- Or hold right-mouse button and drag

### Zoom the Canvas
- Hold Ctrl (or Cmd on Mac)
- Scroll mouse wheel up/down
- Zoom range: 0.5x to 2.0x

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Delete | Remove selected node |
| Ctrl+S (Windows/Linux) | Save workflow |
| Cmd+S (Mac) | Save workflow |
| Ctrl+Scroll | Zoom canvas |

## Node Types Reference

| Type | Icon | Purpose | Key Fields |
|------|------|---------|-----------|
| Tool Call | ⚙️ | Execute tools | tool_name, arguments |
| LLM Prompt | 🧠 | Query models | prompt, model, temperature |
| Condition | ◆ | Branch logic | expression, true_label, false_label |
| Loop | 🔄 | Iterate | collection, max_iterations |
| Parallel | \|\| | Concurrent | (connect multiple children) |
| Wait | ⏱️ | Pause | duration (seconds) |
| Approval | ✓ | Manual gate | message, approver, timeout |
| Webhook | 📡 | HTTP call | url, method, headers, body |

## Example Workflow

### "Search and Analyze" Workflow

```
Tool Call (code_search)
  ↓
LLM Prompt (analyze results)
  ↓
Approval (manual review)
  ↓
Webhook (send to Slack)
```

**Setup**:

1. **Tool Call Node**
   - Label: "Search Code"
   - tool_name: `code_search`
   - arguments: `{"query": "TODO", "limit": 10}`

2. **LLM Prompt Node**
   - Label: "Analyze Results"
   - prompt: `Analyze these code findings: {{results}}`
   - model: `gpt-4`
   - temperature: `0.7`

3. **Approval Node**
   - Label: "Review"
   - message: `Please review the analysis`
   - approver: `admin@example.com`
   - timeout: `3600` (1 hour)

4. **Webhook Node**
   - Label: "Notify"
   - url: `https://hooks.slack.com/services/...`
   - method: `POST`
   - body: `{"text": "Analysis complete: {{result}}"}`

## Troubleshooting

### Issue: Nodes not appearing on canvas
**Solution**: Ensure you're dropping in the white canvas area, not the sidebar

### Issue: Can't create connection
**Solution**: Click output port (right) of source → click input port (left) of target

### Issue: Save not working
**Solution**: Check browser console for API errors. Ensure `/api/workflows` endpoint exists

### Issue: Nodes not snapping to grid
**Solution**: They snap automatically. Try zooming in (Ctrl+Scroll) to see grid

### Issue: Properties panel not updating
**Solution**: Click node again to refresh. JSON fields require valid JSON syntax

## Tips & Tricks

### Organize Large Workflows
- Use labels to identify each node
- Space nodes horizontally for better visibility
- Use "Export" to save, then "Import" different versions

### Reuse Workflows
- Export as JSON
- Import in new workflow
- Modify and save as new workflow

### Debug Execution
- Watch node colors during run
- Check browser console (F12) for errors
- Add approval nodes as checkpoints

### Build Complex Logic
- Use Condition nodes for branches
- Use Loop nodes for batch processing
- Use Parallel nodes for concurrent tasks
- Use Wait nodes to slow execution for testing

## API Endpoints (Reference)

Once integrated with backend:

```
POST   /api/workflows              # Save workflow
GET    /api/workflows              # List workflows
GET    /api/workflows/{id}         # Load workflow
POST   /api/workflows/{id}/run     # Run workflow
GET    /api/workflows/{id}/run     # Check status
```

See `WORKFLOW_API_EXAMPLE.md` for implementation.

## Resources

- **Full Documentation**: `WORKFLOW_BUILDER_README.md`
- **API Integration**: `WORKFLOW_API_EXAMPLE.md`
- **Feature Reference**: `WORKFLOW_BUILDER_FEATURES.md`
- **Implementation Details**: View HTML source at `workflow_builder.html`

## Support

- Check browser console (F12) for JavaScript errors
- Verify `/api/workflows` endpoint is available
- Review CORS headers if using different domain
- Check file permissions on HTML file

---

**Tip**: Start with simple 2-3 node workflows before building complex ones. Each node type is independent and can be tested individually.

Happy workflow building! 🚀
