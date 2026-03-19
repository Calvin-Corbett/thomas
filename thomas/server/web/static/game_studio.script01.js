
        // ========== State Management ==========
        const state = {
            currentGame: 'cloud-jump',
            currentLevel: null,
            selectedTool: 'select',
            gridEnabled: true,
            zoom: 1,
            scrollX: 0,
            gridSize: 40,
            canvas: null,
            ctx: null,
            layers: {
                background: { visible: true, elements: [] },
                midground: { visible: true, elements: [] },
                foreground: { visible: true, elements: [] }
            },
            selectedElement: null,
            draggedAsset: null,
            history: [],
            historyIndex: -1
        };

        const assetColors = {
            'ground-grass': '#27ae60',
            'ground-stone': '#95a5a6',
            'ground-dirt': '#a0522d',
            'platform-small': '#3498db',
            'platform-medium': '#2980b9',
            'platform-large': '#1a5276',
            'spike': '#e74c3c',
            'moving-block': '#f39c12',
            'saw': '#c0392b',
            'walker': '#8e44ad',
            'flyer': '#9b59b6',
            'patrol': '#a569bd',
            'coin': '#f1c40f',
            'gem': '#2ecc71',
            'star': '#f39c12',
            'shield': '#3498db',
            'speed-boost': '#e91e63',
            'invincible': '#ffd700',
            'cloud': '#ecf0f1',
            'tree': '#16a085',
            'bush': '#229954',
            'spawn-point': '#2ecc71',
            'goal-flag': '#e74c3c'
        };

        // ========== Initialization ==========
        function init() {
            state.canvas = document.getElementById('gameCanvas');
            state.ctx = state.canvas.getContext('2d');
            setupCanvasSize();
            setupEventListeners();
            setupKeyboardShortcuts();
            loadLevels();
            render();
        }

        function setupCanvasSize() {
            const container = document.getElementById('canvasContainer');
            state.canvas.width = 4000;
            state.canvas.height = 600;
        }

        function setupEventListeners() {
            // Game selector
            document.getElementById('gameSelector').addEventListener('change', (e) => {
                state.currentGame = e.target.value;
                updateStatus(`Switched to ${e.target.value}`);
                loadLevels();
            });

            // Tool buttons
            document.getElementById('selectTool').addEventListener('click', () => selectTool('select'));
            document.getElementById('paintTool').addEventListener('click', () => selectTool('paint'));
            document.getElementById('eraseTool').addEventListener('click', () => selectTool('erase'));
            document.getElementById('fillTool').addEventListener('click', () => selectTool('fill'));

            // Grid toggle
            document.getElementById('gridToggle').addEventListener('click', () => {
                state.gridEnabled = !state.gridEnabled;
                document.getElementById('gridToggle').classList.toggle('active', state.gridEnabled);
                render();
            });

            // Undo/Redo
            document.getElementById('undoBtn').addEventListener('click', undo);
            document.getElementById('redoBtn').addEventListener('click', redo);

            // Zoom
            document.getElementById('zoomInBtn').addEventListener('click', () => zoomCanvas(1.2));
            document.getElementById('zoomOutBtn').addEventListener('click', () => zoomCanvas(0.833));

            // Actions
            document.getElementById('previewBtn').addEventListener('click', openPreview);
            document.getElementById('saveBtn').addEventListener('click', saveLevel);
            document.getElementById('exportBtn').addEventListener('click', exportLevel);

            // Scroll
            document.getElementById('scrollX').addEventListener('input', (e) => {
                state.scrollX = parseInt(e.target.value);
                updateScrollDisplay();
                render();
            });

            // Canvas events
            state.canvas.addEventListener('click', handleCanvasClick);
            state.canvas.addEventListener('mousemove', handleCanvasMouseMove);
            state.canvas.addEventListener('mousedown', handleCanvasMouseDown);
            state.canvas.addEventListener('mouseup', handleCanvasMouseUp);

            // Asset palette drag and drop
            document.querySelectorAll('.asset-item').forEach(item => {
                item.addEventListener('dragstart', handleAssetDragStart);
                item.addEventListener('dragend', handleAssetDragEnd);
            });

            state.canvas.addEventListener('dragover', (e) => e.preventDefault());
            state.canvas.addEventListener('drop', handleCanvasDrop);
        }

        function setupKeyboardShortcuts() {
            document.addEventListener('keydown', (e) => {
                if (e.key === 's' || e.key === 'S') selectTool('select');
                if (e.key === 'b' || e.key === 'B') selectTool('paint');
                if (e.key === 'e' || e.key === 'E') selectTool('erase');
                if (e.key === 'f' || e.key === 'F') selectTool('fill');
                if (e.key === 'g' || e.key === 'G') {
                    e.preventDefault();
                    state.gridEnabled = !state.gridEnabled;
                    document.getElementById('gridToggle').classList.toggle('active', state.gridEnabled);
                    render();
                }
                if (e.ctrlKey || e.metaKey) {
                    if (e.key === 'z' || e.key === 'Z') {
                        e.preventDefault();
                        undo();
                    }
                    if (e.key === 'y' || e.key === 'Y') {
                        e.preventDefault();
                        redo();
                    }
                }
                if (e.key === '+' || e.key === '=') zoomCanvas(1.2);
                if (e.key === '-' || e.key === '_') zoomCanvas(0.833);
            });
        }

        // ========== Tool Selection ==========
        function selectTool(tool) {
            state.selectedTool = tool;
            document.querySelectorAll('[id$="Tool"]').forEach(btn => btn.classList.remove('active'));
            document.getElementById(tool + 'Tool').classList.add('active');
            updateCursor();
            updateStatus(`Tool: ${tool}`);
        }

        function updateCursor() {
            const cursors = {
                'select': 'pointer',
                'paint': 'crosshair',
                'erase': 'not-allowed',
                'fill': 'cell'
            };
            state.canvas.style.cursor = cursors[state.selectedTool] || 'default';
        }

        // ========== Canvas Events ==========
        function getCanvasCoords(e) {
            const rect = state.canvas.getBoundingClientRect();
            const x = (e.clientX - rect.left) / state.zoom + state.scrollX;
            const y = (e.clientY - rect.top) / state.zoom;
            return { x, y };
        }

        function handleCanvasClick(e) {
            if (state.selectedTool === 'select') {
                const { x, y } = getCanvasCoords(e);
                selectElement(x, y);
            }
        }

        function handleCanvasMouseMove(e) {
            const { x, y } = getCanvasCoords(e);
            document.getElementById('coordDisplay').textContent = `X: ${Math.floor(x)} Y: ${Math.floor(y)}`;
        }

        let isDrawing = false;

        function handleCanvasMouseDown(e) {
            const { x, y } = getCanvasCoords(e);
            isDrawing = true;
            saveHistory();

            if (state.selectedTool === 'paint' && state.draggedAsset) {
                addElement(x, y, state.draggedAsset.type, state.draggedAsset.asset);
            }
        }

        function handleCanvasMouseUp() {
            isDrawing = false;
        }

        function handleAssetDragStart(e) {
            state.draggedAsset = {
                type: e.target.dataset.type,
                asset: e.target.dataset.asset
            };
            e.target.classList.add('dragging');
        }

        function handleAssetDragEnd(e) {
            e.target.classList.remove('dragging');
        }

        function handleCanvasDrop(e) {
            e.preventDefault();
            if (!state.draggedAsset) return;

            const { x, y } = getCanvasCoords(e);
            saveHistory();
            addElement(x, y, state.draggedAsset.type, state.draggedAsset.asset);
            state.draggedAsset = null;
        }

        // ========== Element Management ==========
        function addElement(x, y, type, asset) {
            const element = {
                id: Date.now() + Math.random(),
                x: state.gridEnabled ? Math.round(x / state.gridSize) * state.gridSize : x,
                y: state.gridEnabled ? Math.round(y / state.gridSize) * state.gridSize : y,
                width: state.gridSize * 2,
                height: state.gridSize,
                type,
                asset,
                properties: {
                    speed: 1,
                    direction: 1,
                    collision: true,
                    solid: true
                }
            };

            state.layers.midground.elements.push(element);
            state.selectedElement = element;
            updateProperties();
            render();
        }

        function selectElement(x, y) {
            state.selectedElement = null;
            const allElements = [
                ...state.layers.background.elements,
                ...state.layers.midground.elements,
                ...state.layers.foreground.elements
            ];

            for (let el of allElements.reverse()) {
                if (x >= el.x && x <= el.x + el.width &&
                    y >= el.y && y <= el.y + el.height) {
                    state.selectedElement = el;
                    break;
                }
            }

            updateProperties();
            render();
        }

        function deleteElement(id) {
            ['background', 'midground', 'foreground'].forEach(layer => {
                state.layers[layer].elements = state.layers[layer].elements.filter(el => el.id !== id);
            });
            state.selectedElement = null;
            updateProperties();
            render();
        }

        // ========== Properties Panel ==========
        function updateProperties() {
            const content = document.getElementById('propertiesContent');

            if (!state.selectedElement) {
                content.innerHTML = '<div class="properties-empty">Select an element to edit properties</div>';
                return;
            }

            const el = state.selectedElement;
            content.innerHTML = `
                <div class="property-group">
                    <label class="property-label">Type</label>
                    <div class="property-value">${el.type}</div>
                </div>
                <div class="property-group">
                    <label class="property-label">Asset</label>
                    <div class="property-value">${el.asset}</div>
                </div>
                <div class="property-group">
                    <label class="property-label">Position X</label>
                    <input type="number" class="property-value" value="${Math.floor(el.x)}"
                        onchange="updateElementProperty('x', this.value)">
                </div>
                <div class="property-group">
                    <label class="property-label">Position Y</label>
                    <input type="number" class="property-value" value="${Math.floor(el.y)}"
                        onchange="updateElementProperty('y', this.value)">
                </div>
                <div class="property-group">
                    <label class="property-label">Width</label>
                    <input type="number" class="property-value" value="${Math.floor(el.width)}"
                        onchange="updateElementProperty('width', this.value)">
                </div>
                <div class="property-group">
                    <label class="property-label">Height</label>
                    <input type="number" class="property-value" value="${Math.floor(el.height)}"
                        onchange="updateElementProperty('height', this.value)">
                </div>
                <div class="property-group">
                    <label class="property-label">Speed</label>
                    <input type="number" class="property-value" value="${el.properties.speed}" step="0.1"
                        onchange="updateElementProperty('speed', this.value)">
                </div>
                <div class="property-group">
                    <label class="property-label">Direction</label>
                    <select class="property-value" onchange="updateElementProperty('direction', this.value)">
                        <option value="1" ${el.properties.direction === 1 ? 'selected' : ''}>Right</option>
                        <option value="-1" ${el.properties.direction === -1 ? 'selected' : ''}>Left</option>
                    </select>
                </div>
                <div class="property-group">
                    <label class="property-label">Collision</label>
                    <input type="checkbox" ${el.properties.collision ? 'checked' : ''}
                        onchange="updateElementProperty('collision', this.checked)">
                </div>
                <div style="margin-top: 16px;">
                    <button onclick="deleteElement(${el.id})" style="width: 100%; background: #c0392b; border-color: #e74c3c;">
                        Delete
                    </button>
                </div>
            `;
        }

        function updateElementProperty(prop, value) {
            if (!state.selectedElement) return;

            if (prop in ['x', 'y', 'width', 'height']) {
                state.selectedElement[prop] = parseFloat(value);
            } else {
                state.selectedElement.properties[prop] = isNaN(value) ? (value === 'true' || value === true) : parseFloat(value);
            }

            render();
        }

        // ========== Rendering ==========
        function render() {
            const ctx = state.ctx;
            ctx.fillStyle = '#12161f';
            ctx.fillRect(0, 0, state.canvas.width, state.canvas.height);

            // Draw grid
            if (state.gridEnabled) {
                drawGrid();
            }

            // Draw elements
            ['background', 'midground', 'foreground'].forEach(layer => {
                if (state.layers[layer].visible) {
                    state.layers[layer].elements.forEach(el => drawElement(el));
                }
            });

            // Draw selection
            if (state.selectedElement) {
                drawSelection(state.selectedElement);
            }
        }

        function drawGrid() {
            const ctx = state.ctx;
            ctx.strokeStyle = '#2d3142';
            ctx.lineWidth = 0.5;

            for (let x = -state.scrollX; x < state.canvas.width + state.scrollX; x += state.gridSize) {
                ctx.beginPath();
                ctx.moveTo(x, 0);
                ctx.lineTo(x, state.canvas.height);
                ctx.stroke();
            }

            for (let y = 0; y < state.canvas.height; y += state.gridSize) {
                ctx.beginPath();
                ctx.moveTo(-state.scrollX, y);
                ctx.lineTo(state.canvas.width - state.scrollX, y);
                ctx.stroke();
            }
        }

        function drawElement(el) {
            const ctx = state.ctx;
            const x = el.x - state.scrollX;
            const y = el.y;
            const color = assetColors[el.asset] || '#6c5ce7';

            ctx.fillStyle = color;
            ctx.fillRect(x, y, el.width, el.height);

            ctx.strokeStyle = 'rgba(255, 255, 255, 0.3)';
            ctx.lineWidth = 1;
            ctx.strokeRect(x, y, el.width, el.height);

            // Label
            ctx.fillStyle = '#e8eef5';
            ctx.font = '10px sans-serif';
            ctx.fillText(el.asset.split('-')[0], x + 4, y + 14);
        }

        function drawSelection(el) {
            const ctx = state.ctx;
            const x = el.x - state.scrollX;
            const y = el.y;

            ctx.strokeStyle = '#6c5ce7';
            ctx.lineWidth = 2;
            ctx.strokeRect(x, y, el.width, el.height);

            // Handles
            const handleSize = 6;
            ctx.fillStyle = '#6c5ce7';
            ctx.fillRect(x - handleSize / 2, y - handleSize / 2, handleSize, handleSize);
            ctx.fillRect(x + el.width - handleSize / 2, y - handleSize / 2, handleSize, handleSize);
            ctx.fillRect(x - handleSize / 2, y + el.height - handleSize / 2, handleSize, handleSize);
            ctx.fillRect(x + el.width - handleSize / 2, y + el.height - handleSize / 2, handleSize, handleSize);
        }

        // ========== History (Undo/Redo) ==========
        function saveHistory() {
            state.historyIndex++;
            state.history = state.history.slice(0, state.historyIndex);
            state.history.push(JSON.stringify(state.layers));
        }

        function undo() {
            if (state.historyIndex > 0) {
                state.historyIndex--;
                state.layers = JSON.parse(state.history[state.historyIndex]);
                render();
                updateStatus('Undo');
            }
        }

        function redo() {
            if (state.historyIndex < state.history.length - 1) {
                state.historyIndex++;
                state.layers = JSON.parse(state.history[state.historyIndex]);
                render();
                updateStatus('Redo');
            }
        }

        // ========== Zoom ==========
        function zoomCanvas(factor) {
            const oldZoom = state.zoom;
            state.zoom = Math.max(0.5, Math.min(3, state.zoom * factor));
            document.getElementById('zoomLevel').textContent = Math.floor(state.zoom * 100) + '%';

            const container = document.getElementById('canvasContainer');
            container.style.transform = `scale(${state.zoom})`;
            container.style.transformOrigin = 'top left';
        }

        // ========== Level Management ==========
        function loadLevels() {
            // Mock implementation - in production, fetch from /api/games/levels
            const levelSelector = document.getElementById('levelSelector');
            levelSelector.innerHTML = '<option value="">-- New Level --</option>';
            updateStatus('Levels loaded');
        }

        function saveLevel() {
            const levelName = document.getElementById('levelName').value || `Level_${Date.now()}`;
            const levelData = {
                name: levelName,
                game: state.currentGame,
                layers: state.layers,
                timestamp: new Date().toISOString()
            };

            // In production: POST to /api/games/levels
            console.log('Saving level:', levelData);
            showNotification('Level saved successfully', 'success');
            updateStatus(`Saved: ${levelName}`);
        }

        function exportLevel() {
            const levelName = document.getElementById('levelName').value || `level_${Date.now()}`;
            const levelData = {
                name: levelName,
                game: state.currentGame,
                layers: state.layers,
                exportedAt: new Date().toISOString()
            };

            const json = JSON.stringify(levelData, null, 2);
            const blob = new Blob([json], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${levelName}.json`;
            a.click();
            URL.revokeObjectURL(url);

            showNotification('Level exported as JSON', 'success');
        }

        // ========== Preview ==========
        function openPreview() {
            const modal = document.getElementById('previewModal');
            modal.classList.add('active');
            const frame = document.getElementById('previewFrame');

            const levelData = {
                game: state.currentGame,
                layers: state.layers
            };

            const previewHTML = `
                <!DOCTYPE html>
                <html>
                <head>
                    <title>Level Preview</title>
                    <style>
                        body { margin: 0; background: #12161f; font-family: sans-serif; }
                        canvas { display: block; background: #1a1f2e; }
                        #info { position: absolute; top: 10px; left: 10px; color: #e8eef5; font-size: 12px; }
                    </style>
                </head>
                <body>
                    <div id="info">Game: ${levelData.game}<br>Elements: ${JSON.stringify(levelData.layers).split('id').length - 1}</div>
                    <canvas id="preview"></canvas>
                    <script>
                        const canvas = document.getElementById('preview');
                        const ctx = canvas.getContext('2d');
                        canvas.width = window.innerWidth;
                        canvas.height = window.innerHeight;

                        const levelData = ${JSON.stringify(levelData)};

                        function drawLevel() {
                            ctx.fillStyle = '#12161f';
                            ctx.fillRect(0, 0, canvas.width, canvas.height);

                            ['background', 'midground', 'foreground'].forEach(layer => {
                                levelData.layers[layer].elements.forEach(el => {
                                    const colors = ${JSON.stringify(Object.fromEntries(
                                        Object.entries(assetColors).map(([k, v]) => [k, v])
                                    ))};
                                    ctx.fillStyle = colors[el.asset] || '#6c5ce7';
                                    ctx.fillRect(el.x, el.y, el.width, el.height);
                                    ctx.strokeStyle = 'rgba(255, 255, 255, 0.3)';
                                    ctx.lineWidth = 1;
                                    ctx.strokeRect(el.x, el.y, el.width, el.height);
                                });
                            });
                        }

                        drawLevel();
                    
