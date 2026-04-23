# Thomas Workflow Builder UI

A self-contained, single-file React application for visually building and managing workflows in the Thomas system.

## Access

The workflow builder is served at:
```
http://localhost:8899/static/workflow_builder.html
```

## Features

### Canvas/Layout
- **Left Sidebar**: Palette of 8 draggable node types
- **Center Canvas**: Main workflow design area with SVG connections
- **Right Sidebar**: Properties panel for selected nodes
- **Top Bar**: Workflow controls and file operations
- **Status Bar**: Real-time workflow and node count information

### Node Types

1. **Tool Call** (⚙️)
   - Execute external tools/functions
   - Properties: tool_name, arguments (JSON)

2. **LLM Prompt** (🧠)
   - Query language models
   - Properties: prompt template, model selection, temperature

3. **Condition** (◆)
   - Branch logic based on expressions
   - Properties: expression, true_path label, false_path label

4. **Loop** (🔄)
   - Iterate over collections
   - Properties: collection expression, max_iterations

5. **Parallel** (||)
   - Execute multiple steps concurrently
   - Properties: connect multiple child nodes

6. **Wait** (⏱️)
   - Pause workflow execution
   - Properties: duration (seconds), optional condition

7. **Approval** (✓)
   - Request manual approval to proceed
   - Properties: approver, message, timeout (seconds)

8. **Webhook** (📡)
   - Call external HTTP endpoints
   - Properties: URL, method, headers (JSON), body template

### Canvas Features

- **Drag & Drop**: Drag node types from palette onto canvas
- **Node Connections**: Click output port → click input port to connect
- **SVG Bezier Curves**: Smooth connection visualization
- **Node Selection**: Click node to select and edit properties
- **Node Deletion**: Select node and press Delete, or click × button
- **Canvas Navigation**:
  - Zoom: Ctrl/Cmd + mouse wheel
  - Pan: Middle-click drag or right-click drag
- **Grid Snap**: Nodes automatically align to 20px grid
- **Mini-map**: Bottom-right corner (visible when nodes exist)

### Keyboard Shortcuts

- `Delete`: Remove selected node
- `Ctrl/Cmd + S`: Save workflow

### Save/Load Operations

**Save**
- Click "Save" → POST to `/api/workflows` with workflow JSON
- Saves workflow name, nodes, edges, and timestamp

**Load**
- GET `/api/workflows` to retrieve saved workflows

**Export**
- Click "Export" → Download workflow as JSON file
- Filename: `{workflow_name}.json`

**Import**
- Click "Import" → Select JSON file to upload
- Loads nodes, edges, and workflow name

### Run/Monitor

**Run Workflow**
- Click "Run" button
- Status indicator shows "Running..."
- Simulated node execution (0.8s per node)
- Nodes change color:
  - Green: Currently running
  - Grey: Completed
  - Red: Failed

**Stop Workflow**
- Click "Stop" button while running
- Halts execution and resets state

**Status Bar**
- Current state: Ready or Running
- Node and edge count

## API Integration

The workflow builder expects these endpoints:

```
POST /api/workflows
- Save workflow definition
- Body: { name, nodes, edges, timestamp }
- Returns: { id, ... }

GET /api/workflows
- List all workflows
- Returns: [ { id, name, ... } ]

GET /api/workflows/{id}
- Load specific workflow
- Returns: { id, name, nodes, edges, ... }

POST /api/workflows/{id}/run
- Execute workflow
- Returns: { run_id, status, ... }

GET /api/workflows/{id}/run/status
- Poll workflow execution status
- Returns: { status, running_nodes, completed_nodes, failed_nodes, ... }

POST /api/workflows/{id}/run/stop
- Cancel running workflow
- Returns: { status }
```

## Styling

### Theme
- **Dark Navy**: `#0a0e1a` (background)
- **Panels**: `#0f1420`, `#1a1f2e`
- **Accent**: `#6366f1` (primary indigo)
- **Success**: `#10b981` (green)
- **Error**: `#dc2626` (red)
- **Text**: `#e0e0e0` (light grey)

### Visual Effects
- Smooth node drag animations
- SVG connection bezier curves
- Hover state highlights
- Selection glow effects
- Running state pulse animation

## Browser Support

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+
- Requires modern JavaScript (ES6+)

## File Size

- **Total**: ~50KB (1359 lines)
- Single HTML file with embedded CSS and JSX
- Uses CDN libraries (React, ReactDOM, Babel)

## Development

All code is self-contained in a single HTML file:
- CSS: Lines 12-400
- React Components: Lines 408-1359
- No external dependencies except CDN libraries

### Adding New Node Types

1. Add entry to `NODE_TYPES` constant with icon and name
2. Add properties section in `PropertiesPanel` component
3. Add default properties in `handleCanvasDrop`

Example:
```javascript
const NODE_TYPES = {
    new_type: { name: 'New Type', icon: '🎯', color: '#f59e0b' },
    // ...
};
```

## Notes

- Workflow state is stored in React component state (in-memory)
- Changes persist during session; browser refresh clears unsaved changes
- Grid snapping helps maintain clean, aligned node layouts
- Connections can be deleted by clicking on them
- All node properties support JSON editing for complex structures
