
        const { useReducer, useEffect, useRef, useState, useCallback, useMemo } = React;

        // Custom Hooks
        function useWebSocket(url, onMessage) {
            const [connected, setConnected] = useState(false);
            const wsRef = useRef(null);
            const reconnectCountRef = useRef(0);

            const connect = useCallback(() => {
                try {
                    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                    const wsUrl = `${protocol}//${window.location.host}${url}`;

                    wsRef.current = new WebSocket(wsUrl);

                    wsRef.current.onopen = () => {
                        setConnected(true);
                        reconnectCountRef.current = 0;
                    };

                    wsRef.current.onmessage = (event) => {
                        try {
                            const data = JSON.parse(event.data);
                            onMessage(data);
                        } catch (e) {
                            console.error('WebSocket message parse error:', e);
                        }
                    };

                    wsRef.current.onerror = (error) => {
                        console.error('WebSocket error:', error);
                        setConnected(false);
                    };

                    wsRef.current.onclose = () => {
                        setConnected(false);
                        // Exponential backoff reconnect
                        const delay = Math.min(1000 * Math.pow(2, reconnectCountRef.current), 30000);
                        reconnectCountRef.current++;
                        setTimeout(connect, delay);
                    };
                } catch (e) {
                    console.error('WebSocket connection error:', e);
                    setConnected(false);
                }
            }, [url, onMessage]);

            useEffect(() => {
                connect();
                return () => {
                    if (wsRef.current) {
                        wsRef.current.close();
                    }
                };
            }, [connect]);

            return { connected, ws: wsRef.current };
        }

        function useDashboardState() {
            const initialState = {
                metrics: {
                    cpu: 0,
                    memory: 0,
                    disk: 0,
                    connections: 0,
                    cpuHistory: [],
                    memoryHistory: [],
                },
                agents: [],
                tools: [],
                events: [],
                timeRange: '15m',
                autoRefresh: true,
                refreshInterval: 2000,
                loading: true,
                theme: 'dark',
            };

            const reducer = (state, action) => {
                switch (action.type) {
                    case 'SET_METRICS':
                        return {
                            ...state,
                            metrics: {
                                ...state.metrics,
                                ...action.payload,
                                cpuHistory: [...(state.metrics.cpuHistory || []), action.payload.cpu].slice(-60),
                                memoryHistory: [...(state.metrics.memoryHistory || []), action.payload.memory].slice(-60),
                            },
                            loading: false,
                        };
                    case 'SET_AGENTS':
                        return { ...state, agents: action.payload };
                    case 'SET_TOOLS':
                        return { ...state, tools: action.payload };
                    case 'ADD_EVENT':
                        return {
                            ...state,
                            events: [action.payload, ...state.events].slice(0, 500),
                        };
                    case 'SET_TIME_RANGE':
                        return { ...state, timeRange: action.payload, loading: true };
                    case 'TOGGLE_AUTO_REFRESH':
                        return { ...state, autoRefresh: !state.autoRefresh };
                    case 'SET_THEME':
                        return { ...state, theme: action.payload };
                    default:
                        return state;
                }
            };

            return useReducer(reducer, initialState);
        }

        // Components
        function SystemMetricsPanel({ state, dispatch }) {
            const [cpuChart, setCpuChart] = useState(null);
            const cpuCanvasRef = useRef(null);

            useEffect(() => {
                if (!cpuCanvasRef.current) return;

                if (cpuChart) {
                    cpuChart.data.labels = state.metrics.cpuHistory.map((_, i) => i);
                    cpuChart.data.datasets[0].data = state.metrics.cpuHistory;
                    cpuChart.data.datasets[1].data = state.metrics.memoryHistory;
                    cpuChart.update('none');
                } else {
                    const ctx = cpuCanvasRef.current.getContext('2d');
                    const chart = new Chart(ctx, {
                        type: 'line',
                        data: {
                            labels: Array(state.metrics.cpuHistory.length).fill(''),
                            datasets: [
                                {
                                    label: 'CPU %',
                                    data: state.metrics.cpuHistory,
                                    borderColor: '#58a6ff',
                                    backgroundColor: 'rgba(88, 166, 255, 0.1)',
                                    tension: 0.4,
                                    fill: true,
                                    pointRadius: 0,
                                    yAxisID: 'y',
                                },
                                {
                                    label: 'Memory %',
                                    data: state.metrics.memoryHistory,
                                    borderColor: '#3fb950',
                                    backgroundColor: 'rgba(63, 185, 80, 0.1)',
                                    tension: 0.4,
                                    fill: true,
                                    pointRadius: 0,
                                    yAxisID: 'y1',
                                },
                            ],
                        },
                        options: {
                            responsive: true,
                            maintainAspectRatio: false,
                            interaction: { mode: 'index', intersect: false },
                            plugins: {
                                legend: { display: true, labels: { font: { size: 11 }, boxWidth: 10 } },
                            },
                            scales: {
                                y: {
                                    type: 'linear',
                                    display: true,
                                    position: 'left',
                                    beginAtZero: true,
                                    max: 100,
                                    ticks: { font: { size: 10 }, color: '#8b949e' },
                                },
                                y1: {
                                    type: 'linear',
                                    display: true,
                                    position: 'right',
                                    beginAtZero: true,
                                    max: 100,
                                    ticks: { font: { size: 10 }, color: '#8b949e' },
                                    grid: { drawOnChartArea: false },
                                },
                            },
                        },
                    });
                    setCpuChart(chart);
                }
            }, [state.metrics.cpuHistory, state.metrics.memoryHistory, cpuChart]);

            const getTrendIcon = (value) => value > 50 ? '📈' : '📉';

            return (
                <div className="panel">
                    <div className="panel-header">
                        <div className="panel-title">System Metrics</div>
                    </div>
                    <div className="panel-content">
                        <div className="kpi-cards">
                            <div className="kpi-card">
                                <div className="kpi-label">CPU</div>
                                <div className="kpi-value">{state.metrics.cpu.toFixed(1)}%</div>
                                <div className={`kpi-trend ${state.metrics.cpu > 50 ? 'up' : 'down'}`}>
                                    {getTrendIcon(state.metrics.cpu)}
                                </div>
                            </div>
                            <div className="kpi-card">
                                <div className="kpi-label">Memory</div>
                                <div className="kpi-value">{state.metrics.memory.toFixed(1)}%</div>
                                <div className={`kpi-trend ${state.metrics.memory > 50 ? 'up' : 'down'}`}>
                                    {getTrendIcon(state.metrics.memory)}
                                </div>
                            </div>
                            <div className="kpi-card">
                                <div className="kpi-label">Disk</div>
                                <div className="kpi-value">{state.metrics.disk.toFixed(1)}%</div>
                                <div className="kpi-trend">💾</div>
                            </div>
                            <div className="kpi-card">
                                <div className="kpi-label">Connections</div>
                                <div className="kpi-value">{state.metrics.connections}</div>
                                <div className="kpi-trend">🔗</div>
                            </div>
                        </div>
                        <div className="chart-section">
                            <div className="chart-label">System Performance (Last 60s)</div>
                            <div className="chart-container">
                                <canvas ref={cpuCanvasRef} aria-label="CPU and Memory usage over time"></canvas>
                            </div>
                        </div>
                    </div>
                </div>
            );
        }

        function AgentActivityPanel({ state, dispatch }) {
            const [sortBy, setSortBy] = useState('name');
            const [statusFilter, setStatusFilter] = useState('all');
            const [expandedAgent, setExpandedAgent] = useState(null);

            const filteredAgents = useMemo(() => {
                return state.agents.filter(agent => {
                    if (statusFilter === 'all') return true;
                    return agent.status === statusFilter;
                }).sort((a, b) => {
                    if (sortBy === 'name') return a.name.localeCompare(b.name);
                    if (sortBy === 'status') return a.status.localeCompare(b.status);
                    return 0;
                });
            }, [state.agents, sortBy, statusFilter]);

            return (
                <div className="panel">
                    <div className="panel-header">
                        <div className="panel-title">Agent Activity</div>
                    </div>
                    <div className="panel-content">
                        <div className="tab-group">
                            {['all', 'idle', 'working', 'error'].map(status => (
                                <button
                                    key={status}
                                    className={`tab ${statusFilter === status ? 'active' : ''}`}
                                    onClick={() => setStatusFilter(status)}
                                >
                                    {status.charAt(0).toUpperCase() + status.slice(1)} ({state.agents.filter(a => status === 'all' || a.status === status).length})
                                </button>
                            ))}
                        </div>
                        <table className="agent-table">
                            <thead>
                                <tr>
                                    <th onClick={() => setSortBy('name')} style={{ cursor: 'pointer' }}>
                                        Agent {sortBy === 'name' && '▼'}
                                    </th>
                                    <th onClick={() => setSortBy('status')} style={{ cursor: 'pointer' }}>
                                        Status {sortBy === 'status' && '▼'}
                                    </th>
                                    <th>Current Task</th>
                                    <th>Duration</th>
                                </tr>
                            </thead>
                            <tbody>
                                {filteredAgents.length === 0 ? (
                                    <tr><td colSpan="4" style={{ textAlign: 'center', color: '#8b949e' }}>No agents</td></tr>
                                ) : filteredAgents.map(agent => (
                                    <tr key={agent.id} onClick={() => setExpandedAgent(expandedAgent === agent.id ? null : agent.id)} style={{ cursor: 'pointer' }}>
                                        <td>{agent.name}</td>
                                        <td>
                                            <span className={`status-badge ${agent.status}`}>
                                                <div className={`status-dot-small ${agent.status}`}></div>
                                                {agent.status}
                                            </span>
                                        </td>
                                        <td style={{ fontSize: '11px', color: '#8b949e' }}>{agent.currentTask || 'Idle'}</td>
                                        <td style={{ fontSize: '11px', color: '#8b949e' }}>{formatDuration(agent.duration)}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            );
        }

        function ToolUsagePanel({ state, dispatch }) {
            const [sortBy, setSortBy] = useState('invocations');
            const [searchTerm, setSearchTerm] = useState('');

            const filteredTools = useMemo(() => {
                return state.tools
                    .filter(tool => tool.name.toLowerCase().includes(searchTerm.toLowerCase()))
                    .sort((a, b) => {
                        if (sortBy === 'invocations') return b.invocations - a.invocations;
                        if (sortBy === 'latency') return (b.avgLatency || 0) - (a.avgLatency || 0);
                        if (sortBy === 'errors') return (b.errorRate || 0) - (a.errorRate || 0);
                        return 0;
                    })
                    .slice(0, 10);
            }, [state.tools, sortBy, searchTerm]);

            const maxInvocations = Math.max(...filteredTools.map(t => t.invocations), 1);

            return (
                <div className="panel">
                    <div className="panel-header">
                        <div className="panel-title">Tool Usage</div>
                    </div>
                    <div className="panel-content">
                        <div className="search-input" style={{ marginBottom: '12px' }}>
                            <input
                                type="text"
                                placeholder="Search tools..."
                                value={searchTerm}
                                onChange={(e) => setSearchTerm(e.target.value)}
                                style={{ width: '100%' }}
                            />
                        </div>
                        <div className="chart-label">Top Tools (Last Hour)</div>
                        <div className="tools-bar-chart">
                            {filteredTools.length === 0 ? (
                                <div className="no-data-placeholder">No tools found</div>
                            ) : filteredTools.map(tool => (
                                <div key={tool.name} className="tool-bar">
                                    <div className="tool-label">{tool.name}</div>
                                    <div className="tool-fill" style={{ width: `${(tool.invocations / maxInvocations) * 100}%` }}></div>
                                    <div className="tool-value">{tool.invocations}</div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            );
        }

        function EventStreamPanel({ state, dispatch }) {
            const [levelFilter, setLevelFilter] = useState({ error: true, warn: true, info: true, debug: true });
            const [searchTerm, setSearchTerm] = useState('');
            const [selectedEvent, setSelectedEvent] = useState(null);
            const contentRef = useRef(null);
            const [isPinned, setIsPinned] = useState(true);

            useEffect(() => {
                if (isPinned && contentRef.current) {
                    contentRef.current.scrollTop = contentRef.current.scrollHeight;
                }
            }, [state.events, isPinned]);

            const filteredEvents = useMemo(() => {
                return state.events.filter(event => {
                    const levelMatch = levelFilter[event.level || 'info'];
                    const searchMatch = !searchTerm || event.message.toLowerCase().includes(searchTerm.toLowerCase());
                    return levelMatch && searchMatch;
                });
            }, [state.events, levelFilter, searchTerm]);

            return (
                <>
                    <div className="panel">
                        <div className="panel-header">
                            <div className="panel-title">Event Stream</div>
                            <div className="panel-controls">
                                <button className="panel-btn" onClick={() => setIsPinned(!isPinned)}>
                                    {isPinned ? '📌 Pinned' : '📍 Unpinned'}
                                </button>
                            </div>
                        </div>
                        <div className="panel-content">
                            <div className="filter-bar">
                                <input
                                    type="text"
                                    placeholder="Search events..."
                                    value={searchTerm}
                                    onChange={(e) => setSearchTerm(e.target.value)}
                                    className="search-input"
                                />
                            </div>
                            <div className="filter-bar">
                                {['error', 'warn', 'info', 'debug'].map(level => (
                                    <label key={level} className="filter-checkbox">
                                        <input
                                            type="checkbox"
                                            checked={levelFilter[level]}
                                            onChange={(e) => setLevelFilter({ ...levelFilter, [level]: e.target.checked })}
                                        />
                                        {level.toUpperCase()}
                                    </label>
                                ))}
                            </div>
                            <div className="event-list" ref={contentRef}>
                                {filteredEvents.length === 0 ? (
                                    <div className="no-data-placeholder">No events</div>
                                ) : filteredEvents.map((event, idx) => (
                                    <div
                                        key={idx}
                                        className={`event-item ${event.level || 'info'}`}
                                        onClick={() => setSelectedEvent(event)}
                                    >
                                        <div className="event-timestamp">
                                            {new Date(event.timestamp).toLocaleTimeString()}
                                        </div>
                                        <div>
                                            <span className={`event-level-badge ${event.level || 'info'}`}>
                                                {(event.level || 'INFO').toUpperCase()}
                                            </span>
                                            <span className="event-source">{event.source || 'system'}</span>
                                        </div>
                                        <div className="event-message">{event.message}</div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                    {selectedEvent && (
                        <div className="modal-overlay" onClick={() => setSelectedEvent(null)}>
                            <div className="modal" onClick={(e) => e.stopPropagation()}>
                                <div className="modal-header">
                                    <h3>Event Details</h3>
                                    <button className="modal-close" onClick={() => setSelectedEvent(null)}>×</button>
                                </div>
                                <div className="modal-content">
                                    <div className="json-display">
                                        {JSON.stringify(selectedEvent, null, 2)}
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}
                </>
            );
        }

        function TopBar({ state, dispatch }) {
            const handleThemeToggle = () => {
                const newTheme = state.theme === 'dark' ? 'light' : 'dark';
                dispatch({ type: 'SET_THEME', payload: newTheme });
                document.body.classList.toggle('light-theme');
                localStorage.setItem('theme', newTheme);
            };

            const handleExport = () => {
                const data = {
                    timestamp: new Date().toISOString(),
                    metrics: state.metrics,
                    agents: state.agents,
                    tools: state.tools,
                    events: state.events,
                };
                const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `observability-${new Date().getTime()}.json`;
                a.click();
            };

            return (
                <div className="top-bar">
                    <div className="top-bar-left">
                        <div className="logo">📊 Thomas Observability</div>
                        <div className="connection-status">
                            <div className={`status-dot ${state.wsConnected ? 'connected' : ''}`}></div>
                            <span>{state.wsConnected ? 'Connected' : 'Disconnected'}</span>
                        </div>
                    </div>
                    <div className="top-bar-right">
                        <div className="control-group">
                            <label>Time Range:</label>
                            <select value={state.timeRange} onChange={(e) => dispatch({ type: 'SET_TIME_RANGE', payload: e.target.value })}>
                                <option value="1m">1 minute</option>
                                <option value="5m">5 minutes</option>
                                <option value="15m">15 minutes</option>
                                <option value="1h">1 hour</option>
                                <option value="24h">24 hours</option>
                            </select>
                        </div>
                        <div className="control-group">
                            <button className={`toggle ${state.autoRefresh ? 'active' : ''}`} onClick={() => dispatch({ type: 'TOGGLE_AUTO_REFRESH' })}>
                                {state.autoRefresh ? '🔄 ON' : '⏸ OFF'}
                            </button>
                        </div>
                        <div className="control-group">
                            <button className="export-btn" onClick={handleExport}>📥 Export</button>
                        </div>
                        <div className="control-group">
                            <button className="toggle" onClick={handleThemeToggle}>
                                {state.theme === 'dark' ? '☀️ Light' : '🌙 Dark'}
                            </button>
                        </div>
                    </div>
                </div>
            );
        }

        function App() {
            const [state, dispatch] = useDashboardState();
            const { connected } = useWebSocket('/ws/observability', (data) => {
                if (data.type === 'metrics') {
                    dispatch({ type: 'SET_METRICS', payload: data.data });
                } else if (data.type === 'agents') {
                    dispatch({ type: 'SET_AGENTS', payload: data.data });
                } else if (data.type === 'tools') {
                    dispatch({ type: 'SET_TOOLS', payload: data.data });
                } else if (data.type === 'event') {
                    dispatch({ type: 'ADD_EVENT', payload: data.data });
                }
            });

            useEffect(() => {
                document.body.classList.toggle('light-theme', state.theme === 'light');
            }, [state.theme]);

            useEffect(() => {
                // Load mock data for demo
                const mockMetrics = {
                    cpu: Math.random() * 100,
                    memory: Math.random() * 100,
                    disk: Math.random() * 100,
                    connections: Math.floor(Math.random() * 50),
                };
                dispatch({ type: 'SET_METRICS', payload: mockMetrics });

                const mockAgents = [
                    { id: 1, name: 'Agent-1', status: 'working', currentTask: 'Processing request', duration: 5 },
                    { id: 2, name: 'Agent-2', status: 'idle', currentTask: null, duration: 120 },
                    { id: 3, name: 'Agent-3', status: 'error', currentTask: 'Failed task', duration: 30 },
                ];
                dispatch({ type: 'SET_AGENTS', payload: mockAgents });

                const mockTools = [
                    { name: 'file_read', invocations: 145, avgLatency: 50, errorRate: 0.5 },
                    { name: 'api_call', invocations: 98, avgLatency: 200, errorRate: 2.1 },
                    { name: 'bash_exec', invocations: 67, avgLatency: 150, errorRate: 1.2 },
                    { name: 'json_parse', invocations: 234, avgLatency: 10, errorRate: 0.2 },
                ];
                dispatch({ type: 'SET_TOOLS', payload: mockTools });

                const mockEvents = [
                    { timestamp: new Date().toISOString(), level: 'info', source: 'system', message: 'System started' },
                ];
                mockEvents.forEach(event => dispatch({ type: 'ADD_EVENT', payload: event }));
            }, []);

            useEffect(() => {
                if (!state.autoRefresh) return;
                const interval = setInterval(() => {
                    const newMetrics = {
                        cpu: Math.random() * 100,
                        memory: Math.random() * 100,
                        disk: Math.random() * 100,
                        connections: Math.floor(Math.random() * 50),
                    };
                    dispatch({ type: 'SET_METRICS', payload: newMetrics });
                }, state.refreshInterval);
                return () => clearInterval(interval);
            }, [state.autoRefresh, state.refreshInterval, dispatch]);

            return (
                <div className="app-container">
                    <TopBar state={{ ...state, wsConnected: connected }} dispatch={dispatch} />
                    <div className="main-grid">
                        <SystemMetricsPanel state={state} dispatch={dispatch} />
                        <AgentActivityPanel state={state} dispatch={dispatch} />
                        <ToolUsagePanel state={state} dispatch={dispatch} />
                        <EventStreamPanel state={state} dispatch={dispatch} />
                    </div>
                </div>
            );
        }

        function formatDuration(seconds = 0) {
            if (seconds < 60) return `${Math.floor(seconds)}s`;
            if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
            return `${Math.floor(seconds / 3600)}h`;
        }

        ReactDOM.createRoot(document.getElementById('root')).render(<App />);
    
