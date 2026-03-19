# Web - Frontend Runtime and UI

This directory contains the entire Thomas web interface: HTML, CSS, and the JavaScript runtime. It's delivered to browsers and handles all user interaction.

## What This Directory Does

The web frontend is the **user-facing interface** to Thomas. When a user opens Thomas in their browser, they get HTML from here. All JavaScript execution runs through the runtime. All CSS styles come from here.

## Critical File Structure

| Item | Status | Size | Purpose |
|---|---|---|---|
| `js/app_runtime_primary.mjs` | **ACTIVE** | 41,470 lines | **THE ONLY ACTIVE RUNTIME**—entire app logic |
| `js/app.js` | ACTIVE | ~100 lines | Entrypoint—loads app_runtime_primary.mjs |
| `js/app_modules.js` | ACTIVE | Module system | Helper for module loading |
| `js/app_parts/` | **DEAD CODE** | Hundreds of files | **DO NOT EDIT**—never loaded at runtime |
| `index.html` | ACTIVE | 78K | Main chat interface |
| `settings.html` | ACTIVE | 45K | Settings UI |
| `mission.html` | ACTIVE | 10K | Mission/task display |
| `virtual_office.html` | ACTIVE | 2.7K | Virtual office interface |
| `companion.html` | ACTIVE | 7.5K | Mobile companion app |
| `css/` | ACTIVE | Multiple files | Stylesheets |
| `static/` | ACTIVE | Assets | Icons, images, etc. |

## CRITICAL: The Monolith Runtime

**All JavaScript execution happens through ONE file:**

```
app_runtime_primary.mjs
├── DOM manipulation
├── Event handling
├── WebSocket/SSE listeners
├── State management
├── Chat UI rendering
├── Settings management
├── Mission control
└── Every other feature
```

**`js/app_parts/` directory:**
- Contains dozens of `.js` files (part-001.js, part-002.js, etc.)
- **These are NEVER LOADED**
- They're dead code, probably from an older split architecture
- **DO NOT EDIT THEM**

**When you edit the frontend:**
1. Edit `js/app_runtime_primary.mjs` ONLY
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
app.js imports app_runtime_primary.mjs
        ↓
app_runtime_primary.mjs initializes:
    ├── Event listeners
    ├── WebSocket connection
    ├── DOM elements
    ├── Chat interface
    └── Settings UI
        ↓
User types message → app_runtime_primary.mjs handles it
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
| `virtual_office.html` | Virtual office (multi-user space) |
| `companion.html` | Mobile app version |

Each HTML file is a **shell**—it contains structure and styling, but all logic runs through `app_runtime_primary.mjs`.

## Inside app_runtime_primary.mjs

This monolithic file (41K lines) contains everything:

```javascript
// Event listeners
window.addEventListener('load', init)
document.addEventListener('submit', handleChat)

// WebSocket
socket.addEventListener('message', handleMessage)

// UI rendering
function renderChatMessage(msg) { ... }
function updateUI(state) { ... }

// Settings
function saveSetting(key, value) { ... }

// State
let globalState = {
    messages: [],
    user: null,
    settings: { ... },
    ...
}

// And 41,000 more lines...
```

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

1. **Edit `app_parts/*.js`** — They don't run. Edit `app_runtime_primary.mjs`.
2. **Forget to clear browser cache** — Old code stays cached.
3. **Assume CSS loads from one file** — Multiple CSS files are imported.
4. **Call LLM directly from frontend** — Always use `/chat` endpoint.
5. **Expect `app_modules.js` to load files automatically** — Import or use fetch.

### ✓ Do this:

1. Edit `js/app_runtime_primary.mjs` for logic changes
2. Edit `css/*.css` for styling changes
3. Add new assets to `static/`
4. Hard-reload the browser after changes (Ctrl+Shift+R)
5. Check browser console (F12) for errors

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
→ Check that `app_runtime_primary.mjs` has `renderChatMessage()` function

**Issue:** UI looks broken after edit
→ Clear browser cache: Ctrl+Shift+Delete
→ Hard-reload: Ctrl+Shift+R
→ Check CSS file imports in HTML

**Issue:** WebSocket not connecting
→ Check browser console for connection errors
→ Verify server is running (curl localhost:8000/health)
→ Check firewall/CORS settings

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
1. Find `renderChatMessage()` in `app_runtime_primary.mjs`
2. Modify the DOM construction logic
3. Hard-reload to test

### To add a new settings option:
1. Add HTML input to `settings.html`
2. Add CSS styling to `css/settings.css`
3. Add JS handler in `app_runtime_primary.mjs` to save/load the setting
4. Hard-reload to test

### To fix a broken feature:
1. Open browser console (F12)
2. Look for red error messages
3. Trace the error to the function in `app_runtime_primary.mjs`
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
