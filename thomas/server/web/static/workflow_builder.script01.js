
        const { useState, useReducer, useCallback, useRef, useEffect, useMemo } = React;

        // Constants
        const NODE_TYPES = {
            tool: { icon: '🔧', color: '#3b82f6', label: 'Tool Call' },
            llm: { icon: '🧠', color: '#a855f7', label: 'LLM Prompt' },
            condition: { icon: '◇', color: '#f59e0b', label: 'Condition' },
            loop: { icon: '⟳', color: '#14b8a6', label: 'Loop' },
            parallel: { icon: '⫶', color: '#6366f1', label: 'Parallel' },
            wait: { icon: '⏱', color: '#6b7280', label: 'Wait' },
            approval: { icon: '✓', color: '#22c55e', label: 'Approval' },
            webhook: { icon: '📡', color: '#f97316', label: 'Webhook' },
        };

        const PALETTE_ITEMS = [
            { type: 'condition', category: 'Control Flow', desc: 'Conditional branching' },
            { type: 'loop', category: 'Control Flow', desc: 'Iterate over items' },
            { type: 'parallel', category: 'Control Flow', desc: 'Run branches simultaneously' },
            { type: 'tool', category: 'Actions', desc: 'Call external tool' },
            { type: 'llm', category: 'Actions', desc: 'LLM inference' },
            { type: 'webhook', category: 'Actions', desc: 'HTTP request' },
            { type: 'wait', category: 'Gates', desc: 'Delay execution' },
            { type: 'approval', category: 'Gates', desc: 'Require approval' },
        ];

        // Reducer for workflow state
        const workflowReducer = (state, action) => {
            switch (action.type) {
                case 'ADD_NODE':
                    return {
                        ...state,
                        nodes: [...state.nodes, action.payload],
                    };
                case 'UPDATE_NODE':
                    return {
                        ...state,
                        nodes: state.nodes.map(n => n.id === action.payload.id ? action.payload : n),
                    };
                case 'DELETE_NODE':
                    return {
                        ...state,
                        nodes: state.nodes.filter(n => n.id !== action.payload),
                        connections: state.connections.filter(c => c.from !== action.payload && c.to !== action.payload),
                        selectedNodes: state.selectedNodes.filter(id => id !== action.payload),
                    };
                case 'ADD_CONNECTION':
                    return {
                        ...state,
                        connections: [...state.connections, action.payload],
                    };
                case 'DELETE_CONNECTION':
                    return {
                        ...state,
                        connections: state.connections.filter((c, i) => i !== action.payload),
                    };
                case 'SET_SELECTED_NODES':
                    return { ...state, selectedNodes: action.payload };
                case 'UPDATE_PAN':
                    return { ...state, panX: action.payload.x, panY: action.payload.y };
                case 'UPDATE_ZOOM':
                    return { ...state, zoom: action.payload };
                case 'UPDATE_STATUS':
                    return { ...state, status: action.payload };
                case 'ADD_LOG':
                    return { ...state, logs: [...state.logs, action.payload] };
                case 'CLEAR_LOGS':
                    return { ...state, logs: [] };
                case 'BATCH_UPDATE':
                    return action.payload;
                default:
                    return state;
            }
        };

        // Custom Hooks
        const useHistory = (initialState) => {
            const [history, setHistory] = useState([initialState]);
            const [index, setIndex] = useState(0);

            const push = useCallback((state) => {
                setHistory(h => [...h.slice(0, index + 1), state].slice(-50));
                setIndex(i => Math.min(i + 1, h.length - 1));
            }, [index]);

            const undo = useCallback(() => {
                setIndex(i => Math.max(0, i - 1));
            }, []);

            const redo = useCallback(() => {
                setHistory(h => {
                    setIndex(i => Math.min(i + 1, h.length - 1));
                });
            }, []);

            return { state: history[index], push, undo, canUndo: index > 0, canRedo: index < history.length - 1 };
        };

        const useWorkflow = (initialState) => {
            const [state, dispatch] = useReducer(workflowReducer, initialState);
            const historyRef = useRef(useHistory(state));

            const push = useCallback(() => {
                historyRef.current.push(state);
            }, [state]);

            return { state, dispatch, push, history: historyRef.current };
        };

        // Main App Component
        function WorkflowBuilder() {
            const initialState = {
                nodes: [],
                connections: [],
                selectedNodes: [],
                panX: 0,
                panY: 0,
                zoom: 1,
                status: 'draft',
                logs: [],
                name: 'Untitled Workflow',
            };

            const { state, dispatch, push, history } = useWorkflow(initialState);
            const [showShortcuts, setShowShortcuts] = useState(false);
            const [toasts, setToasts] = useState([]);
            const [isRunning, setIsRunning] = useState(false);
            const [paletteSearch, setPaletteSearch] = useState('');
            const [showDrawer, setShowDrawer] = useState(false);
            const [gridSnapEnabled, setGridSnapEnabled] = useState(true);
            const canvasRef = useRef(null);
            const dragStartRef = useRef(null);
            const selectionBoxRef = useRef(null);

            // Load from localStorage on mount
            useEffect(() => {
                const saved = localStorage.getItem('workflow');
                if (saved) {
                    try {
                        const data = JSON.parse(saved);
                        dispatch({ type: 'BATCH_UPDATE', payload: data });
                        addToast('Workflow loaded', 'success');
                    } catch (e) {
                        console.error('Failed to load workflow:', e);
                    }
                }
            }, []);

            // Auto-save to localStorage
            useEffect(() => {
                const timer = setTimeout(() => {
                    localStorage.setItem('workflow', JSON.stringify(state));
                }, 1000);
                return () => clearTimeout(timer);
            }, [state]);

            const addToast = (message, type = 'success') => {
                const id = Math.random();
                setToasts(t => [...t, { id, message, type }]);
                setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 3000);
            };

            // Keyboard shortcuts
            useEffect(() => {
                const handleKeyDown = (e) => {
                    if (e.key === '?') {
                        setShowShortcuts(!showShortcuts);
                    } else if (e.ctrlKey || e.metaKey) {
                        if (e.key === 'z') {
                            e.preventDefault();
                            if (e.shiftKey) {
                                history.redo();
                            } else {
                                history.undo();
                            }
                        } else if (e.key === 'c') {
                            e.preventDefault();
                            const selected = state.nodes.filter(n => state.selectedNodes.includes(n.id));
                            if (selected.length > 0) {
                                localStorage.setItem('clipboard', JSON.stringify(selected));
                                addToast(`Copied ${selected.length} node(s)`, 'success');
                            }
                        } else if (e.key === 'v') {
                            e.preventDefault();
                            try {
                                const clipboard = JSON.parse(localStorage.getItem('clipboard') || '[]');
                                clipboard.forEach(node => {
                                    const newNode = { ...node, id: Math.random(), x: node.x + 20, y: node.y + 20 };
                                    dispatch({ type: 'ADD_NODE', payload: newNode });
                                });
                                addToast(`Pasted ${clipboard.length} node(s)`, 'success');
                            } catch (e) {
                                console.error('Failed to paste:', e);
                            }
                        }
                    } else if (e.key === 'Escape') {
                        dispatch({ type: 'SET_SELECTED_NODES', payload: [] });
                    } else if (e.key === 'Delete') {
                        state.selectedNodes.forEach(id => dispatch({ type: 'DELETE_NODE', payload: id }));
                        dispatch({ type: 'SET_SELECTED_NODES', payload: [] });
                        addToast('Node(s) deleted', 'success');
                    }
                };

                window.addEventListener('keydown', handleKeyDown);
                return () => window.removeEventListener('keydown', handleKeyDown);
            }, [state, history]);

            const handleCanvasDrag = (e) => {
                if (e.button !== 0) return;
                dragStartRef.current = { x: e.clientX, y: e.clientY, panX: state.panX, panY: state.panY };
            };

            const handleMouseMove = (e) => {
                if (dragStartRef.current) {
                    const dx = e.clientX - dragStartRef.current.x;
                    const dy = e.clientY - dragStartRef.current.y;
                    dispatch({ type: 'UPDATE_PAN', payload: { x: dragStartRef.current.panX + dx, y: dragStartRef.current.panY + dy } });
                }
            };

            const handleMouseUp = () => {
                dragStartRef.current = null;
            };

            const handleWheel = (e) => {
                e.preventDefault();
                const delta = e.deltaY > 0 ? 0.9 : 1.1;
                const newZoom = Math.max(0.25, Math.min(3, state.zoom * delta));
                dispatch({ type: 'UPDATE_ZOOM', payload: newZoom });
            };

            const handleDragFromPalette = (e, type) => {
                e.preventDefault();
                const rect = canvasRef.current.getBoundingClientRect();
                const x = (e.clientX - rect.left - state.panX) / state.zoom;
                const y = (e.clientY - rect.top - state.panY) / state.zoom;

                const newNode = {
                    id: Math.random(),
                    type,
                    x: Math.round(x / 20) * 20,
                    y: Math.round(y / 20) * 20,
                    config: {},
                    status: 'pending',
                };

                dispatch({ type: 'ADD_NODE', payload: newNode });
                push();
                addToast(`Added ${NODE_TYPES[type].label}`, 'success');
            };

            const handleNodeClick = (e, nodeId) => {
                e.stopPropagation();
                if (e.ctrlKey || e.metaKey) {
                    dispatch({ type: 'SET_SELECTED_NODES', payload: state.selectedNodes.includes(nodeId) ? state.selectedNodes.filter(id => id !== nodeId) : [...state.selectedNodes, nodeId] });
                } else {
                    dispatch({ type: 'SET_SELECTED_NODES', payload: [nodeId] });
                }
            };

            const handleNodeDrag = (e, nodeId) => {
                e.preventDefault();
                const startX = e.clientX;
                const startY = e.clientY;
                const nodeY = state.nodes.find(n => n.id === nodeId)?.y || 0;
                const nodeX = state.nodes.find(n => n.id === nodeId)?.x || 0;

                const handleMove = (moveE) => {
                    const dx = (moveE.clientX - startX) / state.zoom;
                    const dy = (moveE.clientY - startY) / state.zoom;
                    const newX = gridSnapEnabled ? Math.round((nodeX + dx) / 20) * 20 : nodeX + dx;
                    const newY = gridSnapEnabled ? Math.round((nodeY + dy) / 20) * 20 : nodeY + dy;

                    const nodesWereSelected = state.selectedNodes.includes(nodeId);
                    if (!nodesWereSelected) {
                        dispatch({ type: 'SET_SELECTED_NODES', payload: [nodeId] });
                    }

                    const selectedToUpdate = nodesWereSelected ? state.selectedNodes : [nodeId];
                    selectedToUpdate.forEach(id => {
                        const node = state.nodes.find(n => n.id === id);
                        if (node) {
                            dispatch({ type: 'UPDATE_NODE', payload: { ...node, x: newX, y: newY } });
                        }
                    });
                };

                const handleUp = () => {
                    window.removeEventListener('mousemove', handleMove);
                    window.removeEventListener('mouseup', handleUp);
                    push();
                };

                window.addEventListener('mousemove', handleMove);
                window.addEventListener('mouseup', handleUp);
            };

            const handleExportJSON = () => {
                const json = JSON.stringify(state, null, 2);
                const blob = new Blob([json], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${state.name}.json`;
                a.click();
                addToast('Workflow exported', 'success');
            };

            const handleImportJSON = async () => {
                const input = document.createElement('input');
                input.type = 'file';
                input.accept = '.json';
                input.onchange = (e) => {
                    const file = e.target.files[0];
                    const reader = new FileReader();
                    reader.onload = (event) => {
                        try {
                            const imported = JSON.parse(event.target.result);
                            dispatch({ type: 'BATCH_UPDATE', payload: imported });
                            push();
                            addToast('Workflow imported', 'success');
                        } catch (err) {
                            addToast('Failed to import workflow', 'error');
                        }
                    };
                    reader.readAsText(file);
                };
                input.click();
            };

            const handleSave = async () => {
                try {
                    const response = await fetch('/api/workflows', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(state),
                    });
                    if (response.ok) {
                        addToast('Workflow saved', 'success');
                    } else {
                        addToast('Failed to save workflow', 'error');
                    }
                } catch (e) {
                    addToast('Failed to save workflow', 'error');
                }
            };

            const handleRun = async () => {
                setIsRunning(true);
                dispatch({ type: 'UPDATE_STATUS', payload: 'running' });
                try {
                    const response = await fetch('/api/workflows/execute', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(state),
                    });
                    if (response.ok) {
                        addToast('Workflow started', 'success');
                        const pollStatus = setInterval(async () => {
                            const statusResponse = await fetch('/api/workflows/status');
                            const statusData = await statusResponse.json();
                            if (statusData.status !== 'running') {
                                clearInterval(pollStatus);
                                dispatch({ type: 'UPDATE_STATUS', payload: statusData.status });
                                setIsRunning(false);
                                addToast(`Workflow ${statusData.status}`, statusData.status === 'completed' ? 'success' : 'error');
                            }
                        }, 1000);
                    }
                } catch (e) {
                    addToast('Failed to start workflow', 'error');
                    setIsRunning(false);
                    dispatch({ type: 'UPDATE_STATUS', payload: 'failed' });
                }
            };

            const filteredPalette = PALETTE_ITEMS.filter(item =>
                item.type.includes(paletteSearch.toLowerCase()) ||
                item.desc.toLowerCase().includes(paletteSearch.toLowerCase())
            );

            const groupedPalette = {};
            filteredPalette.forEach(item => {
                if (!groupedPalette[item.category]) groupedPalette[item.category] = [];
                groupedPalette[item.category].push(item);
            });

            const selectedNode = state.nodes.find(n => state.selectedNodes.includes(n.id));

            return (
                <div className="workflow-builder">
                    {/* Top Bar */}
                    <div className="top-bar">
                        <div className="top-bar-left">
                            <input
                                type="text"
                                className="workflow-name-input"
                                value={state.name}
                                onChange={(e) => dispatch({ type: 'UPDATE_PAN', payload: { ...state, name: e.target.value } })}
                                placeholder="Workflow name"
                            />
                            <div className={`status-badge ${state.status}`}>{state.status}</div>
                        </div>

                        <div className="top-bar-center">
                            <div className="zoom-control">
                                <button className="icon-button" onClick={() => dispatch({ type: 'UPDATE_ZOOM', payload: Math.max(0.25, state.zoom - 0.1) })}>−</button>
                                <span className="zoom-percent">{Math.round(state.zoom * 100)}%</span>
                                <button className="icon-button" onClick={() => dispatch({ type: 'UPDATE_ZOOM', payload: Math.min(3, state.zoom + 0.1) })}>+</button>
                            </div>
                            <button className="icon-button" onClick={() => dispatch({ type: 'UPDATE_ZOOM', payload: 1 })}>Fit</button>
                            <button className="icon-button" onClick={() => setGridSnapEnabled(!gridSnapEnabled)}>Grid {gridSnapEnabled ? '✓' : '○'}</button>
                        </div>

                        <div className="top-bar-right">
                            <button className="icon-button" onClick={() => history.undo()} disabled={!history.canUndo}>↶ Undo</button>
                            <button className="icon-button" onClick={() => history.redo()} disabled={!history.canRedo}>↷ Redo</button>
                            <button className="icon-button" onClick={handleExportJSON}>⬇ Export</button>
                            <button className="icon-button" onClick={handleImportJSON}>⬆ Import</button>
                            <button className="icon-button" onClick={handleSave}>💾 Save</button>
                            {isRunning ? (
                                <button className="icon-button danger" onClick={() => setIsRunning(false)}>⏹ Stop</button>
                            ) : (
                                <button className="icon-button success" onClick={handleRun} disabled={state.nodes.length === 0}>▶ Run</button>
                            )}
                            <button className="icon-button" onClick={() => setShowShortcuts(!showShortcuts)}>?</button>
                        </div>
                    </div>

                    <div className="main-content">
                        {/* Palette Sidebar */}
                        <div className="palette-sidebar">
                            <div className="palette-search">
                                <input
                                    type="text"
                                    placeholder="Search nodes..."
                                    value={paletteSearch}
                                    onChange={(e) => setPaletteSearch(e.target.value)}
                                />
                            </div>
                            <div className="palette-content">
                                {Object.entries(groupedPalette).map(([category, items]) => (
                                    <div key={category} className="palette-category">
                                        <div className="palette-category-title">{category}</div>
                                        {items.map(item => (
                                            <div
                                                key={item.type}
                                                className="palette-item"
                                                draggable
                                                onDragEnd={(e) => handleDragFromPalette(e, item.type)}
                                            >
                                                <div className="node-header">
                                                    <span className="node-icon">{NODE_TYPES[item.type].icon}</span>
                                                    <div>
                                                        <div className="node-title">{NODE_TYPES[item.type].label}</div>
                                                        <div className="node-subtitle">{item.desc}</div>
                                                    </div>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                ))}
                            </div>
                        </div>

                        {/* Canvas */}
                        <div className="canvas-container" ref={canvasRef} onMouseDown={handleCanvasDrag} onMouseMove={handleMouseMove} onMouseUp={handleMouseUp} onWheel={handleWheel} style={{ cursor: isRunning ? 'default' : 'grab' }}>
                            <div className="canvas-background">
                                <div className="grid-dots" style={{ backgroundSize: `${20 * state.zoom}px ${20 * state.zoom}px` }}></div>
                            </div>

                            {state.nodes.length === 0 && (
                                <div className="empty-state">
                                    <div className="empty-state-icon">⬚</div>
                                    <div className="empty-state-text">No nodes yet</div>
                                    <div className="empty-state-subtext">Drag a node from the palette to get started</div>
                                </div>
                            )}

                            <svg className="svg-connections" style={{ transform: `translate(${state.panX}px, ${state.panY}px) scale(${state.zoom})` }}>
                                {state.connections.map((conn, idx) => {
                                    const fromNode = state.nodes.find(n => n.id === conn.from);
                                    const toNode = state.nodes.find(n => n.id === conn.to);
                                    if (!fromNode || !toNode) return null;

                                    const x1 = fromNode.x + 110;
                                    const y1 = fromNode.y + 220;
                                    const x2 = toNode.x + 110;
                                    const y2 = toNode.y;
                                    const dx = x2 - x1;
                                    const dy = y2 - y1;
                                    const path = `M ${x1} ${y1} C ${x1} ${y1 + dy * 0.5}, ${x2} ${y2 - dy * 0.5}, ${x2} ${y2}`;

                                    return (
                                        <path
                                            key={idx}
                                            d={path}
                                            className={`connection-curve ${isRunning ? 'connection-flow' : ''}`}
                                            onClick={() => dispatch({ type: 'DELETE_CONNECTION', payload: idx })}
                                            style={{ cursor: 'pointer' }}
                                        />
                                    );
                                })}
                            </svg>

                            <div className="nodes-container" style={{ transform: `translate(${state.panX}px, ${state.panY}px) scale(${state.zoom})` }}>
                                {state.nodes.map((node) => (
                                    <div
                                        key={node.id}
                                        className={`node type-${node.type} ${state.selectedNodes.includes(node.id) ? 'selected' : ''} ${isRunning && node.status === 'running' ? 'running' : ''}`}
                                        style={{ left: node.x, top: node.y }}
                                        onMouseDown={(e) => handleNodeClick(e, node.id)}
                                        onDragStart={(e) => handleNodeDrag(e, node.id)}
                                        draggable
                                    >
                                        {node.status === 'completed' && <div className="node-status-icon">✓</div>}
                                        {node.status === 'failed' && <div className="node-status-icon">✕</div>}

                                        <div className="node-header">
                                            <span className="node-icon">{NODE_TYPES[node.type].icon}</span>
                                            <div>
                                                <div className="node-title">{NODE_TYPES[node.type].label}</div>
                                                <div className="node-subtitle">{node.config?.name || node.config?.expression || node.config?.tool || 'Configure'}</div>
                                            </div>
                                        </div>

                                        <div className="node-ports top">
                                            <div className="node-port" />
                                        </div>

                                        {node.type === 'condition' && (
                                            <div className="node-ports bottom">
                                                <div className="node-port true" style={{ marginRight: 20 }} />
                                                <div className="node-port false" style={{ marginLeft: 20 }} />
                                            </div>
                                        )}
                                        {node.type !== 'condition' && (
                                            <div className="node-ports bottom">
                                                <div className="node-port" />
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>

                            {/* Minimap */}
                            <div className="minimap">
                                <canvas width="160" height="120" style={{ display: 'block', cursor: 'grab' }} ref={(canvas) => {
                                    if (canvas) {
                                        const ctx = canvas.getContext('2d');
                                        ctx.fillStyle = '#0f1117';
                                        ctx.fillRect(0, 0, 160, 120);

                                        const bounds = { minX: 0, minY: 0, maxX: 800, maxY: 600 };
                                        if (state.nodes.length > 0) {
                                            bounds.minX = Math.min(...state.nodes.map(n => n.x));
                                            bounds.minY = Math.min(...state.nodes.map(n => n.y));
                                            bounds.maxX = Math.max(...state.nodes.map(n => n.x + 220));
                                            bounds.maxY = Math.max(...state.nodes.map(n => n.y + 120));
                                        }

                                        const scaleX = 160 / (bounds.maxX - bounds.minX || 1);
                                        const scaleY = 120 / (bounds.maxY - bounds.minY || 1);

                                        state.nodes.forEach(node => {
                                            const x = (node.x - bounds.minX) * scaleX;
                                            const y = (node.y - bounds.minY) * scaleY;
                                            const w = 220 * scaleX;
                                            const h = 120 * scaleY;

                                            ctx.fillStyle = state.selectedNodes.includes(node.id) ? '#6366f1' : '#2a2d37';
                                            ctx.fillRect(x, y, w, h);
                                        });

                                        ctx.strokeStyle = '#6366f1';
                                        ctx.lineWidth = 1;
                                        const vpX = (-state.panX / state.zoom - bounds.minX) * scaleX;
                                        const vpY = (-state.panY / state.zoom - bounds.minY) * scaleY;
                                        const vpW = (canvasRef.current?.clientWidth || 800) / state.zoom * scaleX;
                                        const vpH = (canvasRef.current?.clientHeight || 600) / state.zoom * scaleY;
                                        ctx.strokeRect(vpX, vpY, vpW, vpH);
                                    }
                                }} />
                            </div>
                        </div>

                        {/* Properties Panel */}
                        <div className={`properties-panel ${state.selectedNodes.length > 0 ? 'open' : ''}`}>
                            {selectedNode && (
                                <>
                                    <div className="properties-header">
                                        <div className="properties-title">{NODE_TYPES[selectedNode.type].label}</div>
                                        <div className="properties-subtitle">Configure node properties</div>
                                    </div>
                                    <div className="properties-content">
                                        <div className="property-section">
                                            <div className="property-section-title">
                                                <span className="property-section-toggle">▼</span>
                                                Basic
                                            </div>
                                            <div className="property-fields">
                                                <div className="property-field">
                                                    <label className="property-label">Name</label>
                                                    <input
                                                        type="text"
                                                        className="property-input"
                                                        value={selectedNode.config?.name || ''}
                                                        onChange={(e) => dispatch({ type: 'UPDATE_NODE', payload: { ...selectedNode, config: { ...selectedNode.config, name: e.target.value } } })}
                                                        placeholder="Node name"
                                                    />
                                                </div>
                                            </div>
                                        </div>

                                        {selectedNode.type === 'condition' && (
                                            <div className="property-section">
                                                <div className="property-section-title">
                                                    <span className="property-section-toggle">▼</span>
                                                    Condition
                                                </div>
                                                <div className="property-fields">
                                                    <div className="property-field">
                                                        <label className="property-label">Expression</label>
                                                        <input
                                                            type="text"
                                                            className="property-input"
                                                            value={selectedNode.config?.expression || ''}
                                                            onChange={(e) => dispatch({ type: 'UPDATE_NODE', payload: { ...selectedNode, config: { ...selectedNode.config, expression: e.target.value } } })}
                                                            placeholder="e.g., input.value > 100"
                                                        />
                                                    </div>
                                                </div>
                                            </div>
                                        )}

                                        {selectedNode.type === 'tool' && (
                                            <div className="property-section">
                                                <div className="property-section-title">
                                                    <span className="property-section-toggle">▼</span>
                                                    Tool
                                                </div>
                                                <div className="property-fields">
                                                    <div className="property-field">
                                                        <label className="property-label">Tool Name</label>
                                                        <select
                                                            className="property-select"
                                                            value={selectedNode.config?.tool || ''}
                                                            onChange={(e) => dispatch({ type: 'UPDATE_NODE', payload: { ...selectedNode, config: { ...selectedNode.config, tool: e.target.value } } })}
                                                        >
                                                            <option value="">Select tool...</option>
                                                            <option value="email">Send Email</option>
                                                            <option value="slack">Send Slack Message</option>
                                                            <option value="webhook">HTTP Request</option>
                                                        </select>
                                                    </div>
                                                    <div className="property-field">
                                                        <label className="property-label">Parameters (JSON)</label>
                                                        <textarea
                                                            className="property-input property-textarea"
                                                            value={selectedNode.config?.params || '{}'}
                                                            onChange={(e) => dispatch({ type: 'UPDATE_NODE', payload: { ...selectedNode, config: { ...selectedNode.config, params: e.target.value } } })}
                                                            placeholder="{}"
                                                        />
                                                    </div>
                                                </div>
                                            </div>
                                        )}

                                        {selectedNode.type === 'llm' && (
                                            <div className="property-section">
                                                <div className="property-section-title">
                                                    <span className="property-section-toggle">▼</span>
                                                    LLM
                                                </div>
                                                <div className="property-fields">
                                                    <div className="property-field">
                                                        <label className="property-label">Model</label>
                                                        <select
                                                            className="property-select"
                                                            value={selectedNode.config?.model || ''}
                                                            onChange={(e) => dispatch({ type: 'UPDATE_NODE', payload: { ...selectedNode, config: { ...selectedNode.config, model: e.target.value } } })}
                                                        >
                                                            <option value="">Select model...</option>
                                                            <option value="gpt4">GPT-4</option>
                                                            <option value="gpt35">GPT-3.5 Turbo</option>
                                                            <option value="claude">Claude</option>
                                                        </select>
                                                    </div>
                                                    <div className="property-field">
                                                        <label className="property-label">Prompt</label>
                                                        <textarea
                                                            className="property-input property-textarea"
                                                            value={selectedNode.config?.prompt || ''}
                                                            onChange={(e) => dispatch({ type: 'UPDATE_NODE', payload: { ...selectedNode, config: { ...selectedNode.config, prompt: e.target.value } } })}
                                                            placeholder="Enter prompt..."
                                                        />
                                                    </div>
                                                </div>
                                            </div>
                                        )}

                                        {selectedNode.type === 'wait' && (
                                            <div className="property-section">
                                                <div className="property-section-title">
                                                    <span className="property-section-toggle">▼</span>
                                                    Duration
                                                </div>
                                                <div className="property-fields">
                                                    <div className="property-field">
                                                        <label className="property-label">Seconds</label>
                                                        <input
                                                            type="number"
                                                            className="property-input"
                                                            value={selectedNode.config?.duration || 0}
                                                            onChange={(e) => dispatch({ type: 'UPDATE_NODE', payload: { ...selectedNode, config: { ...selectedNode.config, duration: parseInt(e.target.value) } } })}
                                                            min="0"
                                                        />
                                                    </div>
                                                </div>
                                            </div>
                                        )}

                                        <button
                                            className="delete-button"
                                            onClick={() => {
                                                if (confirm('Delete this node?')) {
                                                    dispatch({ type: 'DELETE_NODE', payload: selectedNode.id });
                                                    dispatch({ type: 'SET_SELECTED_NODES', payload: [] });
                                                    addToast('Node deleted', 'success');
                                                }
                                            }}
                                        >
                                            Delete Node
                                        </button>
                                    </div>
                                </>
                            )}
                        </div>
                    </div>

                    {/* Bottom Drawer */}
                    <div className={`bottom-drawer ${showDrawer ? 'open' : ''}`}>
                        <div className="drawer-header">
                            <div className="drawer-title">Execution Log</div>
                            <button className="icon-button" onClick={() => setShowDrawer(false)}>✕</button>
                        </div>
                        <div className="drawer-content">
                            {state.logs.map((log, idx) => (
                                <div key={idx} className={`log-entry ${log.type}`}>
                                    {new Date(log.timestamp).toLocaleTimeString()} - {log.message}
                                </div>
                            ))}
                        </div>
                    </div>

                    {/* Keyboard Shortcuts Overlay */}
                    {showShortcuts && (
                        <div className="shortcuts-overlay" onClick={() => setShowShortcuts(false)}>
                            <div className="shortcuts-panel" onClick={(e) => e.stopPropagation()}>
                                <div className="shortcuts-title">Keyboard Shortcuts</div>

                                <div className="shortcuts-group">
                                    <div className="shortcuts-group-title">Editing</div>
                                    <div className="shortcut-item">
                                        <span>Copy selected nodes</span>
                                        <span className="shortcut-key">Ctrl+C</span>
                                    </div>
                                    <div className="shortcut-item">
                                        <span>Paste nodes</span>
                                        <span className="shortcut-key">Ctrl+V</span>
                                    </div>
                                    <div className="shortcut-item">
                                        <span>Delete selected</span>
                                        <span className="shortcut-key">Delete</span>
                                    </div>
                                    <div className="shortcut-item">
                                        <span>Undo</span>
                                        <span className="shortcut-key">Ctrl+Z</span>
                                    </div>
                                    <div className="shortcut-item">
                                        <span>Redo</span>
                                        <span className="shortcut-key">Ctrl+Shift+Z</span>
                                    </div>
                                </div>

                                <div className="shortcuts-group">
                                    <div className="shortcuts-group-title">Canvas</div>
                                    <div className="shortcut-item">
                                        <span>Pan canvas</span>
                                        <span className="shortcut-key">Mouse drag</span>
                                    </div>
                                    <div className="shortcut-item">
                                        <span>Zoom in/out</span>
                                        <span className="shortcut-key">Scroll wheel</span>
                                    </div>
                                    <div className="shortcut-item">
                                        <span>Deselect all</span>
                                        <span className="shortcut-key">Escape</span>
                                    </div>
                                </div>

                                <div className="shortcuts-group">
                                    <div className="shortcuts-group-title">Nodes</div>
                                    <div className="shortcut-item">
                                        <span>Drag node from palette</span>
                                        <span className="shortcut-key">Drag</span>
                                    </div>
                                    <div className="shortcut-item">
                                        <span>Multi-select nodes</span>
                                        <span className="shortcut-key">Ctrl+Click</span>
                                    </div>
                                    <div className="shortcut-item">
                                        <span>Open node properties</span>
                                        <span className="shortcut-key">Click node</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Toast Notifications */}
                    <div className="toast-container">
                        {toasts.map(toast => (
                            <div key={toast.id} className={`toast ${toast.type}`}>
                                {toast.message}
                            </div>
                        ))}
                    </div>
                </div>
            );
        }

        // Error Boundary
        class ErrorBoundary extends React.Component {
            constructor(props) {
                super(props);
                this.state = { hasError: false, error: null };
            }

            static getDerivedStateFromError(error) {
                return { hasError: true, error };
            }

            render() {
                if (this.state.hasError) {
                    return (
                        <div style={{ padding: '20px', color: '#ef4444', fontFamily: 'system-ui' }}>
                            <h2>Something went wrong</h2>
                            <p>{this.state.error?.message}</p>
                        </div>
                    );
                }
                return this.props.children;
            }
        }

        // Render
        const root = ReactDOM.createRoot(document.getElementById('root'));
        root.render(
            <ErrorBoundary>
                <WorkflowBuilder />
            </ErrorBoundary>
        );
    
