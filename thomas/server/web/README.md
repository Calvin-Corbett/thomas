# Web - Frontend Runtime and UI

This directory contains the entire Thomas web interface: HTML, CSS, and the JavaScript runtime. It's delivered to browsers and handles all user interaction.

## What This Directory Does

The web frontend is the **user-facing interface** to Thomas. When a user opens Thomas in their browser, they get HTML from here. All JavaScript execution runs through the runtime. All CSS styles come from here.

## Critical File Structure

| Item | Status | Size | Purpose |
|---|---|---|---|
| `js/runtime/*.js` | **ACTIVE** | 94 split files | **THE ONLY ACTIVE RUNTIME**—ordered files loaded by app_runtime_loader.js |
| `js/app_runtime_loader.js` | ACTIVE | ~150 lines | Fetches all runtime files in parallel, then executes them in declared order in global scope |
| `js/app.js` | ACTIVE | ~100 lines | Entrypoint—loads app_runtime_loader.js |
| `js/app_parts/` | **DEAD CODE** | Hundreds of files | **DO NOT EDIT**—never loaded at runtime |
| `js/app_runtime_primary.mjs` | **DEAD CODE** (LEGACY) | 41,470 lines | Pre-split monolith—not loaded by index.html—replaced by js/runtime/ split |
| `index.html` | ACTIVE | 78K | Main chat interface |
| `settings.html` | ACTIVE | 45K | Settings UI |
| `mission.html` | ACTIVE | 10K | Mission/task display |
| `index.html#officeWorkspace` + `js/runtime/office_*.js` | ACTIVE | Embedded | Canonical Virtual Office workspace and live office runtime |
| `companion.html` | ACTIVE | 7.5K | Mobile companion app |
| `css/` | ACTIVE | Multiple files | Stylesheets |
| `static/` | ACTIVE | Assets | Icons, images, etc. |

## CRITICAL: The Split Runtime Architecture

**The classic JavaScript runtime executes through 94 ordered files in `js/runtime/`:**

```
app_runtime_loader.js (parallel fetch, declared-order execution)
├── runtime/001_preamble.js
├── runtime/002_dom_setup.js
├── runtime/003_event_handlers.js
├── runtime/... (004–044)
├── runtime/045_model_setup_settings_06.js
└── All run in global scope (combined ~41K lines)
```

**`js/app_parts/` directory and `app_runtime_primary.mjs`:**
- Legacy dead code from pre-split architecture
- `app_parts/` contains dozens of unused files
- `app_runtime_primary.mjs` is the old monolith—NOT LOADED
- **DO NOT EDIT THEM**

**When you edit the frontend:**
1. Edit the appropriate file in `js/runtime/` (or standalone scripts if needed: token_economy.js, theme_rules.js, templates/tpl_settings.js)
2. Clear your browser cache (Ctrl+Shift+Delete)
3. Hard-reload the page (Ctrl+Shift+R or Cmd+Shift+R)
4. Check the browser console for errors

## How the Frontend Works

```
Browser loads /
        ↓
Serves index.html
        ↓
Loads <script src="js/app.js"></script>
        ↓
app.js loads js/app_runtime_loader.js
        ↓
app_runtime_loader.js queues every declared runtime file for parallel fetch and ordered execution
        ↓
All runtime files initialize in global scope:
    ├── Event listeners
    ├── WebSocket connection
    ├── DOM elements
    ├── Chat interface
    └── Settings UI
        ↓
User types message → Runtime handlers process it
                  → Sends to /chat endpoint
                  → Receives response stream
                  → Updates DOM
```

## Key HTML Files

| File | What It Is |
|---|---|
| `index.html` | Main page. User sees this when they visit "/" |
| `settings.html` | Settings page. Loaded in sidebar or modal |
| `mission.html` | Task/mission display and tracking |
| `index.html#officeWorkspace` | Virtual Office workspace; behavior is implemented by the active `js/runtime/office_*.js` files |
| `companion.html` | Mobile app version |

The classic HTML shell loads the ordered `js/runtime/` files through `app_runtime_loader.js`. The former standalone `virtual_office*` shells were retired because the embedded workspace is the only canonical Office surface.

## Inside js/runtime/ (The Split Runtime)

The 94 ordered runtime files collectively contain the classic frontend logic:

```javascript
// runtime/001_preamble.js — Global state and utilities
let globalState = {
    messages: [],
    user: null,
    settings: { ... },
    ...
}

// runtime/002-010.js — Event listeners, DOM setup
window.addEventListener('load', init)
document.addEventListener('submit', handleChat)

// runtime/011-020.js — WebSocket, messaging
socket.addEventListener('message', handleMessage)

// runtime/021-035.js — UI rendering, settings
function renderChatMessage(msg) { ... }
function updateUI(state) { ... }
function saveSetting(key, value) { ... }

// runtime/036-045.js — Initialization and final setup
```

**Note:** `app_runtime_primary.mjs` is the legacy pre-split monolith and is NOT loaded.

## CSS Styling

Located in `css/`:

| File | What It Styles |
|---|---|
| `index.css` | Main chat interface |
| `settings.css` | Settings page |
| `mission.css` | Mission UI |
| `responsive.css` | Mobile/responsive design |
| `dark-mode.css` | Dark mode colors |

CSS is imported in the HTML files. Edit these directly—no monolith splitting.

## Static Assets

Located in `static/`:
- Images, icons, SVG files
- Logo, avatars, UI graphics
- Media files

Reference them in HTML as `static/image.png`.

## Common Mistakes with Frontend

### ✗ Don't do this:

1. **Edit `app_parts/*.js`** — They don't run. Edit the numbered files in `js/runtime/`.
2. **Edit `app_runtime_primary.mjs`** — It's dead code. Use `js/runtime/` instead.
3. **Forget to clear browser cache** — Old code stays cached.
4. **Assume CSS loads from one file** — Multiple CSS files are imported.
5. **Call LLM directly from frontend** — Always use `/chat` endpoint.

### ✓ Do this:

1. Edit the appropriate file in `js/runtime/` for logic changes
2. Edit standalone scripts if needed: `token_economy.js`, `theme_rules.js`, `templates/tpl_settings.js`
3. Edit `css/*.css` for styling changes
4. Add new assets to `static/`
5. Hard-reload the browser after changes (Ctrl+Shift+R)
6. Check browser console (F12) for errors

## Debugging the Frontend

### Browser Console (F12)

Open DevTools:
- Windows/Linux: F12 or Ctrl+Shift+I
- Mac: Cmd+Shift+I

Check for:
- JavaScript errors (red text)
- Network requests (Network tab)
- WebSocket messages (Network → WS)
- Local storage (Application → Local Storage)

### Common Frontend Issues

**Issue:** Chat messages not appearing
→ Check browser console for JavaScript errors
→ Verify `/chat` endpoint is responding (Network tab)
→ Check that one of the `js/runtime/*.js` files has `renderChatMessage()` function

**Issue:** UI looks broken after edit
→ Clear browser cache: Ctrl+Shift+Delete
→ Hard-reload: Ctrl+Shift+R
→ Check CSS file imports in HTML
→ Verify that `app_runtime_loader.js` is loading all 94 declared runtime files in order

**Issue:** WebSocket not connecting
→ Check browser console for connection errors
→ Verify server is running (curl localhost:8000/health)
→ Check firewall/CORS settings
→ Ensure WebSocket handler is in the loaded runtime files

## Frontend Architecture Patterns

### State Management
```javascript
// Global state (in app_runtime_primary.mjs)
let globalState = {
    messages: [],
    user: null,
    settings: {}
};

// Update
globalState.messages.push(newMessage);
updateUI();  // Re-render
```

### Event Handling
```javascript
// Listen for user actions
document.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = document.querySelector('#input').value;
    await sendChat(text);
});
```

### Server Communication
```javascript
// Fetch from /chat
const response = await fetch('/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text })
});

// Stream events (SSE)
const events = new EventSource('/events');
events.addEventListener('message', (e) => {
    const data = JSON.parse(e.data);
    updateUI(data);
});
```

## For AI Agents

### To add a new UI element:
1. Add HTML to `index.html` (or another .html file)
2. Add CSS to `css/index.css` (or appropriate .css file)
3. Add JavaScript handler to `js/app_runtime_primary.mjs`
4. Hard-reload browser to see changes

### To change chat rendering:
1. Find `renderChatMessage()` in the `js/runtime/` files (likely in a file numbered 020–035)
2. Modify the DOM construction logic
3. Hard-reload to test

### To add a new settings option:
1. Add HTML input to `settings.html`
2. Add CSS styling to `css/settings.css`
3. Add JS handler in the appropriate `js/runtime/` file to save/load the setting
4. Hard-reload to test

### To fix a broken feature:
1. Open browser console (F12)
2. Look for red error messages
3. Trace the error to the function in one of the `js/runtime/` files
4. Fix and test

### To optimize performance:
- Minimize DOM updates (batch changes)
- Use `requestAnimationFrame()` for animations
- Lazy-load images (use `loading="lazy"`)
- Cache API responses in localStorage

## Mobile Responsive Design

The frontend is responsive and works on mobile. Key patterns:

```css
/* Mobile-first */
.chat-container {
    width: 100%;
}

/* Tablet and up */
@media (min-width: 768px) {
    .chat-container {
        width: 80%;
    }
}

/* Desktop and up */
@media (min-width: 1024px) {
    .chat-container {
        width: 60%;
    }
}
```

## Accessibility

The frontend includes accessibility features:
- ARIA labels on interactive elements
- Keyboard navigation support
- Color contrast compliance
- Screen reader compatibility

When adding new elements, follow:
- Add `role` attributes (button, link, etc.)
- Add `aria-label` for icon-only buttons
- Use semantic HTML (button, link, form, etc.)
- Test with keyboard navigation (Tab key)

## See Also

- `thomas/server/routes/chat_aiohttp_part02.py` — Backend chat endpoint
- `thomas/agent/dispatch.py` — Chat message classification
- `thomas/orchestrator/brain.py` — Work delegation
- `docs/CHAT_EXECUTION_MODEL.md` — How frontend talks to backend
