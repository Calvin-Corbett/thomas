                this.vy = worldY * this.zoom - mouseY;
                this.clampView();
            }

            clampView() {
                const maxX = WORLD_WIDTH * TILE_SIZE * this.zoom - this.viewWidth;
                const maxY = WORLD_HEIGHT * TILE_SIZE * this.zoom - this.viewHeight;
                this.vx = Math.max(0, Math.min(this.vx, maxX));
                this.vy = Math.max(0, Math.min(this.vy, maxY));
            }

            getScreenPos(worldX, worldY) {
                return {
                    x: worldX * this.zoom - this.vx,
                    y: worldY * this.zoom - this.vy
                };
            }

            getWorldPos(screenX, screenY) {
                return {
                    x: (screenX + this.vx) / this.zoom,
                    y: (screenY + this.vy) / this.zoom
                };
            }
        }

        // ============================================================================
        // RENDERER
        // ============================================================================
        class OfficeRenderer {
            constructor(canvas) {
                this.canvas = canvas;
                this.ctx = canvas.getContext('2d');
                this.spriteAtlas = new SpriteAtlas();
                this.tileMap = null;
                this.camera = null;
                this.frameCount = 0;
                this.lastFrameTime = Date.now();
                this.fps = 0;
            }

            initialize(tileMap, camera) {
                this.tileMap = tileMap;
                this.camera = camera;
                this.resizeCanvas();
            }

            resizeCanvas() {
                const rect = this.canvas.parentElement.getBoundingClientRect();
                this.canvas.width = rect.width;
                this.canvas.height = rect.height;
                this.camera.viewWidth = this.canvas.width;
                this.camera.viewHeight = this.canvas.height;
                this.camera.clampView();
            }

            drawSprite(spriteKey, screenX, screenY, width = TILE_SIZE, height = TILE_SIZE) {
                const sprite = this.spriteAtlas.tiles[spriteKey];
                if (!sprite) return;
                this.ctx.drawImage(
                    this.spriteAtlas.canvas,
                    sprite.x, sprite.y, TILE_SIZE, TILE_SIZE,
                    screenX, screenY, width, height
                );
            }

            drawTiles() {
                for (let ty = 0; ty < this.tileMap.height; ty++) {
                    for (let tx = 0; tx < this.tileMap.width; tx++) {
                        const tile = this.tileMap.getTile(tx, ty);
                        const worldX = tx * TILE_SIZE;
                        const worldY = ty * TILE_SIZE;
                        const screen = this.camera.getScreenPos(worldX, worldY);

                        if (screen.x + TILE_SIZE < 0 || screen.x > this.canvas.width ||
                            screen.y + TILE_SIZE < 0 || screen.y > this.canvas.height) {
                            continue;
                        }

                        let spriteKey = 'floor';
                        if (tile === 'corridor') spriteKey = 'corridor';
                        if (tile === 'wall') spriteKey = 'wall';
                        if (tile === 'door') spriteKey = 'door';
                        if (tile === 'floor') spriteKey = 'floor';

                        const scaledSize = TILE_SIZE * this.camera.zoom;
                        this.drawSprite(spriteKey, screen.x, screen.y, scaledSize, scaledSize);
                    }
                }
            }

            drawFurniture() {
                for (const room of this.tileMap.rooms) {
                    for (const item of room.furniture) {
                        const worldX = item.tx * TILE_SIZE;
                        const worldY = item.ty * TILE_SIZE;
                        const screen = this.camera.getScreenPos(worldX, worldY);

                        if (screen.x + TILE_SIZE < 0 || screen.x > this.canvas.width ||
                            screen.y + TILE_SIZE < 0 || screen.y > this.canvas.height) {
                            continue;
                        }

                        const scaledSize = TILE_SIZE * this.camera.zoom;
                        this.drawSprite(item.type, screen.x, screen.y, scaledSize, scaledSize);
                    }
                }
            }

            drawAgents(agents) {
                const sortedAgents = [...agents].sort((a, b) => a.position.y - b.position.y);

                sortedAgents.forEach(agent => {
                    const screen = this.camera.getScreenPos(agent.position.x, agent.position.y);

                    if (screen.x < -50 || screen.x > this.canvas.width + 50 ||
                        screen.y < -50 || screen.y > this.canvas.height + 50) {
                        return;
                    }

                    if (agent.spriteCache[agent.direction]) {
                        const sprite = agent.spriteCache[agent.direction];
                        const scaledSize = AGENT_SIZE * this.camera.zoom;
                        this.ctx.drawImage(
                            sprite,
                            screen.x - scaledSize / 2,
                            screen.y - scaledSize / 2,
                            scaledSize,
                            scaledSize
                        );
                    }

                    this.ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
                    this.ctx.fillRect(screen.x - 25, screen.y - 35, 50, 12);
                    this.ctx.fillStyle = '#FFF';
                    this.ctx.font = '10px Arial';
                    this.ctx.textAlign = 'center';
                    this.ctx.fillText(agent.name, screen.x, screen.y - 27);
                });
            }

            drawUI() {
                this.ctx.fillStyle = 'rgba(10, 14, 26, 0.3)';
                this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
            }

            render(agents = []) {
                this.ctx.fillStyle = PALETTE.darkBg;
                this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);

                this.drawTiles();
                this.drawFurniture();
                this.drawAgents(agents);
                this.drawUI();

                this.frameCount++;
                const now = Date.now();
                if (now - this.lastFrameTime >= 1000) {
                    this.fps = this.frameCount;
                    this.frameCount = 0;
                    this.lastFrameTime = now;
                }
            }
        }

        // ============================================================================
        // OFFICE BUILDER
        // ============================================================================
        function buildDefaultOffice() {
            const tileMap = new TileMap(WORLD_WIDTH, WORLD_HEIGHT);

            const rooms = {
                lobby: new Room('lobby', 'Lobby', 30, 20, 16, 14, 'modern'),
                engineering: new Room('engineering', 'Engineering Bay', 48, 8, 20, 16, 'tech'),
                research: new Room('research', 'Research Lab', 48, 30, 20, 14, 'academic'),
                creative: new Room('creative', 'Creative Studio', 8, 30, 16, 14, 'artistic'),
                ops: new Room('ops', 'Ops Center', 8, 8, 16, 16, 'industrial'),
                break: new Room('break', 'Break Room', 30, 50, 14, 12, 'casual'),
                conference: new Room('conference', 'Conference Room', 68, 20, 18, 14, 'professional'),
                game: new Room('game', 'Game Room', 68, 50, 16, 12, 'casual'),
                executive: new Room('executive', 'Executive Suite', 8, 50, 16, 12, 'premium'),
                agentA: new Room('agent_a', 'Agent A Office', 52, 50, 8, 8, 'personal'),
                agentB: new Room('agent_b', 'Agent B Office', 62, 50, 8, 8, 'personal'),
                agentC: new Room('agent_c', 'Agent C Office', 72, 50, 8, 8, 'personal'),
                agentD: new Room('agent_d', 'Agent D Office', 82, 50, 8, 8, 'personal'),
            };

            for (const room of Object.values(rooms)) {
                tileMap.addRoom(room);
            }

            rooms.lobby.setDoorPosition(30, 27);
            rooms.engineering.setDoorPosition(48, 14);
            rooms.research.setDoorPosition(48, 37);
            rooms.creative.setDoorPosition(24, 37);
            rooms.ops.setDoorPosition(24, 14);
            rooms.break.setDoorPosition(37, 62);
            rooms.conference.setDoorPosition(68, 27);
            rooms.game.setDoorPosition(75, 62);
            rooms.executive.setDoorPosition(24, 62);
            rooms.agentA.setDoorPosition(52, 58);
            rooms.agentB.setDoorPosition(62, 58);
            rooms.agentC.setDoorPosition(72, 58);
            rooms.agentD.setDoorPosition(82, 58);

            tileMap.addCorridor(30, 27, 50, 27);
            tileMap.addCorridor(50, 27, 68, 27);
            tileMap.addCorridor(37, 27, 37, 50);
            tileMap.addCorridor(50, 14, 50, 27);
            tileMap.addCorridor(50, 37, 50, 27);
            tileMap.addCorridor(24, 37, 37, 37);
            tileMap.addCorridor(37, 37, 37, 27);
            tileMap.addCorridor(24, 14, 30, 14);
            tileMap.addCorridor(30, 14, 30, 20);
            tileMap.addCorridor(37, 50, 37, 62);
            tileMap.addCorridor(37, 62, 45, 62);
            tileMap.addCorridor(68, 27, 68, 50);
            tileMap.addCorridor(68, 50, 75, 50);
            tileMap.addCorridor(75, 50, 75, 62);
            tileMap.addCorridor(24, 62, 24, 50);
            tileMap.addCorridor(45, 62, 52, 62);
            tileMap.addCorridor(52, 58, 52, 62);
            tileMap.addCorridor(62, 58, 62, 62);
            tileMap.addCorridor(72, 58, 72, 62);
            tileMap.addCorridor(82, 58, 82, 62);

            for (const room of Object.values(rooms)) {
                tileMap.surroundRoomWithWalls(room);
            }

            populateLobbly(rooms.lobby);
            populateEngineering(rooms.engineering);
            populateResearch(rooms.research);
            populateCreative(rooms.creative);
            populateOps(rooms.ops);
            populateBreakRoom(rooms.break);
            populateConference(rooms.conference);
            populateGameRoom(rooms.game);
            populateExecutive(rooms.executive);
            populateAgentOffices(rooms.agentA, rooms.agentB, rooms.agentC, rooms.agentD);

            return tileMap;
        }

        function populateLobbly(room) {
            room.addFurniture('reception_desk', room.x + 4, room.y + 3);
            room.addFurniture('sofa', room.x + 2, room.y + 8);
            room.addFurniture('plant', room.x + 12, room.y + 9);
            room.addFurniture('plant', room.x + 13, room.y + 4);
            room.addFurniture('presentation_screen', room.x + 8, room.y + 4);
        }

        function populateEngineering(room) {
            for (let i = 0; i < 4; i++) {
                const col = i % 2;
                const row = Math.floor(i / 2);
                room.addFurniture('desk', room.x + 2 + col * 10, room.y + 2 + row * 7);
                room.addFurniture('chair', room.x + 3 + col * 10, room.y + 10 + row * 7);
            }
            room.addFurniture('server_rack', room.x + 16, room.y + 8);
        }

        function populateResearch(room) {
            room.addFurniture('conf_table', room.x + 4, room.y + 3);
            room.addFurniture('bookshelf', room.x + 2, room.y + 8);
            room.addFurniture('monitoring_board', room.x + 14, room.y + 8);
            room.addFurniture('plant', room.x + 12, room.y + 4);
        }

        function populateCreative(room) {
            room.addFurniture('desk', room.x + 2, room.y + 3);
            room.addFurniture('chair', room.x + 3, room.y + 10);
            room.addFurniture('desk', room.x + 10, room.y + 3);
            room.addFurniture('chair', room.x + 11, room.y + 10);
            room.addFurniture('bookshelf', room.x + 2, room.y + 8);
        }

        function populateOps(room) {
            room.addFurniture('monitoring_board', room.x + 2, room.y + 2);
            room.addFurniture('server_rack', room.x + 10, room.y + 2);
            room.addFurniture('monitoring_board', room.x + 2, room.y + 8);
            room.addFurniture('server_rack', room.x + 10, room.y + 8);
        }

        function populateBreakRoom(room) {
            room.addFurniture('coffee_machine', room.x + 2, room.y + 2);
            room.addFurniture('vending_machine', room.x + 8, room.y + 2);
            room.addFurniture('sofa', room.x + 2, room.y + 7);
            room.addFurniture('arcade_machine', room.x + 10, room.y + 7);
        }

        function populateConference(room) {
            room.addFurniture('conf_table', room.x + 3, room.y + 2);
            room.addFurniture('presentation_screen', room.x + 14, room.y + 3);
        }

        function populateGameRoom(room) {
            room.addFurniture('arcade_machine', room.x + 1, room.y + 2);
            room.addFurniture('arcade_machine', room.x + 9, room.y + 2);
            room.addFurniture('arcade_machine', room.x + 4, room.y + 8);
            room.addFurniture('trophy_case', room.x + 4, room.y + 4);
        }

        function populateExecutive(room) {
            room.addFurniture('exec_desk', room.x + 2, room.y + 3);
            room.addFurniture('chair', room.x + 3, room.y + 10);
            room.addFurniture('bookshelf', room.x + 10, room.y + 3);
            room.addFurniture('trophy_case', room.x + 10, room.y + 8);
        }

        function populateAgentOffices(a, b, c, d) {
            const offices = [a, b, c, d];
            offices.forEach(office => {
                office.addFurniture('desk', office.x + 1, office.y + 1);
                office.addFurniture('chair', office.x + 2, office.y + 4);
                office.addFurniture('trophy_case', office.x + 5, office.y + 2);
            });
        }

        // ============================================================================
        // ROBOT CUSTOMIZATION PANEL
        // ============================================================================

        class RobotCustomizationPanel {
            constructor(agents, onCustomize) {
                this.agents = agents;
                this.onCustomize = onCustomize;
                this.selectedAgent = agents.length > 0 ? agents[0] : null;
                this.isOpen = false;

                this.container = document.getElementById('customization-panel') || document.createElement('div');
                if (!document.getElementById('customization-panel')) {
                    this.container.id = 'customization-panel';
                    document.body.appendChild(this.container);
                }

                this.createPanel();
            }

            createPanel() {
                this.container.innerHTML = `
                    <div style="margin-bottom: 15px;">
                        <button id="close-customizer" style="position: absolute; top: 5px; right: 5px; background-color: #0ff; color: #1a1a2e; border: none; padding: 5px 10px; cursor: pointer; font-weight: bold;">X</button>
                        <h3 style="margin: 0 0 10px 0; color: #0ff; font-size: 14px;">ROBOT CUSTOMIZER</h3>
                    </div>

                    <div style="margin-bottom: 12px;">
                        <label>SELECT AGENT:</label>
                        <select id="agent-selector" style="width: 100%; padding: 5px; background-color: #2a2a4e; color: #0ff; border: 1px solid #0ff;">
                            ${this.agents.map(a => `<option value="${a.id}">${a.name} (${a.role})</option>`).join('')}
                        </select>
                    </div>

                    <div style="margin-bottom: 12px;">
                        <label>BODY COLOR:</label>
                        <input type="color" id="body-color" style="width: 100%; height: 30px; cursor: pointer;">
                    </div>

                    <div style="margin-bottom: 12px;">
                        <label>ACCENT COLOR:</label>
                        <input type="color" id="accent-color" style="width: 100%; height: 30px; cursor: pointer;">
                    </div>

                    <div style="margin-bottom: 12px;">
                        <label>HAT TYPE:</label>
                        <select id="hat-type" style="width: 100%; padding: 5px; background-color: #2a2a4e; color: #0ff; border: 1px solid #0ff;">
                            <option value="none">None</option>
                            <option value="hardhat">Hard Hat</option>
                            <option value="crown">Crown</option>
                            <option value="beanie">Beanie</option>
                            <option value="tophat">Top Hat</option>
                            <option value="party">Party Hat</option>
                        </select>
                    </div>

                    <div style="margin-bottom: 12px;">
                        <label>ANTENNA STYLE:</label>
                        <select id="antenna-style" style="width: 100%; padding: 5px; background-color: #2a2a4e; color: #0ff; border: 1px solid #0ff;">
                            <option value="none">None</option>
                            <option value="straight">Straight</option>
                            <option value="curved">Curved</option>
                            <option value="forked">Forked</option>
                            <option value="ball">Ball</option>
                        </select>
                    </div>

                    <div style="margin-bottom: 12px;">
                        <label>ACCESSORY:</label>
                        <select id="accessory" style="width: 100%; padding: 5px; background-color: #2a2a4e; color: #0ff; border: 1px solid #0ff;">
                            <option value="none">None</option>
                            <option value="glasses">Glasses</option>
                            <option value="bowtie">Bow Tie</option>
                            <option value="badge">Badge</option>
                            <option value="headphones">Headphones</option>
                            <option value="cape">Cape</option>
                        </select>
                    </div>

                    <div style="display: flex; gap: 10px; margin-bottom: 12px;">
                        <button id="randomize-btn" style="flex: 1; padding: 8px; background-color: #4A90E2; color: white; border: 1px solid #0ff; cursor: pointer; font-weight: bold;">RANDOMIZE</button>
                        <button id="save-btn" style="flex: 1; padding: 8px; background-color: #2ecc71; color: white; border: 1px solid #0ff; cursor: pointer; font-weight: bold;">SAVE</button>
                    </div>

                    <div id="preview-container" style="border: 1px solid #0ff; padding: 10px; text-align: center; min-height: 120px;">
                        <canvas id="preview-canvas" width="100" height="100" style="image-rendering: pixelated; background-color: #2a2a4e;"></canvas>
                    </div>
                `;

                document.getElementById('close-customizer').addEventListener('click', () => this.close());

                document.getElementById('agent-selector').addEventListener('change', (e) => {
                    this.selectedAgent = this.agents.find(a => a.id === e.target.value);
                    this.updateInputs();
                    this.updatePreview();
                });

                const colorInputs = ['body-color', 'accent-color'];
                colorInputs.forEach(id => {
                    document.getElementById(id).addEventListener('change', () => this.updatePreview());
                });

                const dropdowns = ['hat-type', 'antenna-style', 'accessory'];
                dropdowns.forEach(id => {
                    document.getElementById(id).addEventListener('change', () => this.updatePreview());
                });

                document.getElementById('randomize-btn').addEventListener('click', () => this.randomize());
                document.getElementById('save-btn').addEventListener('click', () => this.save());

                this.updateInputs();
                this.updatePreview();
            }

            updateInputs() {
                if (!this.selectedAgent) return;
                const c = this.selectedAgent.customization;
                document.getElementById('body-color').value = this.rgbToHex(c.bodyColor);
                document.getElementById('accent-color').value = this.rgbToHex(c.accentColor);
                document.getElementById('hat-type').value = c.hatType;
                document.getElementById('antenna-style').value = c.antennaStyle;
                document.getElementById('accessory').value = c.accessory;
            }

            updatePreview() {
                const canvas = document.getElementById('preview-canvas');
                if (!canvas) return;
                const ctx = canvas.getContext('2d');

                ctx.fillStyle = '#2a2a4e';
                ctx.fillRect(0, 0, canvas.width, canvas.height);

                const customization = {
                    bodyColor: document.getElementById('body-color').value,
                    accentColor: document.getElementById('accent-color').value,
                    eyeColor: '#FFFFFF',
                    hatType: document.getElementById('hat-type').value,
                    antennaStyle: document.getElementById('antenna-style').value,
                    accessory: document.getElementById('accessory').value
                };

                ctx.save();
                ctx.scale(2, 2);

                const tempAgent = new AgentRobot('preview', 'Preview', 'Preview', customization);
                tempAgent.drawRobotBody(ctx, 16, 'down', 0);

                ctx.restore();
            }

            randomize() {
                const colors = ['#FF6B6B', '#4A90E2', '#50C878', '#FFD700', '#FF9500', '#9B59B6', '#FF69B4', '#00CED1'];
                const hats = ['none', 'hardhat', 'crown', 'beanie', 'tophat', 'party'];
                const antennas = ['none', 'straight', 'curved', 'forked', 'ball'];
                const accessories = ['none', 'glasses', 'bowtie', 'badge', 'headphones', 'cape'];

                document.getElementById('body-color').value = colors[Math.floor(Math.random() * colors.length)];
                document.getElementById('accent-color').value = colors[Math.floor(Math.random() * colors.length)];
                document.getElementById('hat-type').value = hats[Math.floor(Math.random() * hats.length)];
                document.getElementById('antenna-style').value = antennas[Math.floor(Math.random() * antennas.length)];
                document.getElementById('accessory').value = accessories[Math.floor(Math.random() * accessories.length)];

                this.updatePreview();
            }

            save() {
                if (!this.selectedAgent) return;

                const customization = {
                    bodyColor: document.getElementById('body-color').value,
                    accentColor: document.getElementById('accent-color').value,
                    eyeColor: '#FFFFFF',
                    hatType: document.getElementById('hat-type').value,
                    antennaStyle: document.getElementById('antenna-style').value,
                    accessory: document.getElementById('accessory').value
                };

                this.selectedAgent.customizeRobot(customization);
                this.onCustomize && this.onCustomize(this.selectedAgent);
                alert('Robot customization saved!');
            }

            rgbToHex(color) {
                if (color.startsWith('#')) return color;
                const colorMap = {
                    '#4A90E2': '#4A90E2',
                    '#2E5C8A': '#2E5C8A'
                };
                return colorMap[color] || '#4A90E2';
            }

            toggle() {
                this.isOpen ? this.close() : this.open();
            }

            open() {
                this.isOpen = true;
                this.container.style.left = '0';
            }

            close() {
                this.isOpen = false;
                this.container.style.left = '-350px';
            }
        }

        // ============================================================================
        // MAIN APPLICATION
        // ============================================================================
        class VirtualOfficeApp {
            constructor() {
                this.canvas = document.getElementById('gameCanvas');
                this.roomListEl = document.getElementById('roomList');
                this.agentListEl = document.getElementById('agentList');
                this.minimapCanvas = document.getElementById('minimap');
                this.statusSize = document.getElementById('statusSize');
                this.statusRooms = document.getElementById('statusRooms');
                this.statusAgents = document.getElementById('statusAgents');
                this.statusFps = document.getElementById('statusFps');
                this.zoomDisplay = document.getElementById('zoomDisplay');

                this.tileMap = buildDefaultOffice();
                this.camera = new Camera(this.canvas.parentElement.clientWidth,
                                       this.canvas.parentElement.clientHeight);
                this.renderer = new OfficeRenderer(this.canvas);
                this.renderer.initialize(this.tileMap, this.camera);

                this.isDragging = false;
                this.dragStart = { x: 0, y: 0 };

                this.agents = [];
                this.highScores = new HighScoreManager();
                this.customizer = null;

                this.lastUpdateTime = Date.now();

                this.setupEventListeners();
                this.initializeAgents();
                this.registerGames();
                this.renderRoomList();
                this.renderAgentList();
                this.startGameLoop();
            }

            initializeAgents() {
                const demoAgents = [
                    {
                        id: 'agent_1',
                        name: 'Atlas',
                        role: 'Engineering Lead',
                        customization: {
                            bodyColor: '#4A90E2',
                            accentColor: '#2E5C8A',
                            eyeColor: '#FFFFFF',
                            hatType: 'hardhat',
                            accessory: 'glasses',
                            antennaStyle: 'straight'
                        }
                    },
                    {
                        id: 'agent_2',
                        name: 'Nova',
                        role: 'Research Specialist',
                        customization: {
                            bodyColor: '#9B59B6',
                            accentColor: '#6C3A7D',
                            eyeColor: '#FFD700',
                            hatType: 'none',
                            accessory: 'none',
                            antennaStyle: 'ball'
                        }
                    },
                    {
                        id: 'agent_3',
                        name: 'Spark',
                        role: 'Creative Director',
                        customization: {
                            bodyColor: '#FF9500',
                            accentColor: '#CC7700',
                            eyeColor: '#FFFFFF',
                            hatType: 'beanie',
                            accessory: 'none',
                            antennaStyle: 'curved'
                        }
                    },
                    {
                        id: 'agent_4',
                        name: 'Cipher',
                        role: 'Ops Engineer',
                        customization: {
                            bodyColor: '#50C878',
                            accentColor: '#2E7D4E',
                            eyeColor: '#000000',
                            hatType: 'none',
                            accessory: 'headphones',
                            antennaStyle: 'none'
                        }
                    },
                    {
                        id: 'agent_5',
                        name: 'Echo',
                        role: 'Support Lead',
                        customization: {
                            bodyColor: '#00CED1',
                            accentColor: '#008B8B',
                            eyeColor: '#FFFFFF',
                            hatType: 'crown',
                            accessory: 'badge',
                            antennaStyle: 'forked'
                        }
                    },
                    {
                        id: 'agent_6',
                        name: 'Pixel',
                        role: 'Game Master',
                        customization: {
                            bodyColor: '#FF6B6B',
                            accentColor: '#CC3333',
                            eyeColor: '#FFFF00',
                            hatType: 'party',
                            accessory: 'none',
                            antennaStyle: 'straight'
                        }
                    }
                ];

                this.agents = demoAgents.map(config => new AgentRobot(config.id, config.name, config.role, config.customization));

                this.agents.forEach((agent, idx) => {
                    agent.position = { x: 300 + idx * 50, y: 300 + idx * 30 };
                    agent.targetPosition = { ...agent.position };
                });

                this.customizer = new RobotCustomizationPanel(this.agents, (agent) => {
                    console.log('Customized agent:', agent.name);
                });
            }

            registerGames() {
                this.highScores.registerGame('cloud_jump', 'Cloud Jump', '#87CEEB');
                this.highScores.registerGame('jetpack_joyride', 'Jetpack Joyride', '#FF6B35');
                this.highScores.registerGame('dino_run', 'Dino Run', '#4CAF50');
            }

            setupEventListeners() {
                window.addEventListener('resize', () => this.renderer.resizeCanvas());

                this.canvas.addEventListener('mousedown', (e) => {
                    this.isDragging = true;
                    this.dragStart = { x: e.clientX, y: e.clientY };
                    this.canvas.style.cursor = 'grabbing';
                });

                document.addEventListener('mousemove', (e) => {
                    if (this.isDragging) {
                        const dx = this.dragStart.x - e.clientX;
                        const dy = this.dragStart.y - e.clientY;
                        this.camera.panBy(dx, dy);
                        this.dragStart = { x: e.clientX, y: e.clientY };
                    }
                });

                document.addEventListener('mouseup', () => {
                    this.isDragging = false;
                    this.canvas.style.cursor = 'grab';
                });

                this.canvas.addEventListener('wheel', (e) => {
                    e.preventDefault();
                    const rect = this.canvas.getBoundingClientRect();
                    const x = e.clientX - rect.left;
                    const y = e.clientY - rect.top;
                    this.camera.zoomAt(e.deltaY > 0 ? -1 : 1, x, y);
                });

                this.roomListEl.addEventListener('click', (e) => {
                    if (e.target.classList.contains('room-item')) {
                        const roomId = e.target.dataset.roomId;
                        this.focusRoom(roomId);
                    }
                });

                document.getElementById('customizer-toggle').addEventListener('click', () => {
                    this.customizer.toggle();
                });

                document.addEventListener('keydown', (e) => {
                    if (e.key === 'c' || e.key === 'C') {
                        this.customizer && this.customizer.toggle();
                    }
                });
            }

            renderRoomList() {
                this.roomListEl.innerHTML = '';
                for (const room of this.tileMap.rooms) {
                    const item = document.createElement('div');
                    item.className = 'room-item';
                    item.dataset.roomId = room.id;
                    item.textContent = room.label;
                    this.roomListEl.appendChild(item);
                }
            }

            renderAgentList() {
                this.agentListEl.innerHTML = '';
                for (const agent of this.agents) {
                    const item = document.createElement('div');
                    item.className = 'agent-item';
                    item.textContent = `${agent.name} (${agent.status})`;
                    this.agentListEl.appendChild(item);
                }
            }

            focusRoom(roomId) {
                const room = this.tileMap.rooms.find(r => r.id === roomId);
                if (room) {
                    const centerX = (room.x + room.w / 2) * TILE_SIZE;
                    const centerY = (room.y + room.h / 2) * TILE_SIZE;
                    this.camera.vx = centerX * this.camera.zoom - this.canvas.width / 2;
                    this.camera.vy = centerY * this.camera.zoom - this.canvas.height / 2;
                    this.camera.clampView();

                    for (const item of this.roomListEl.querySelectorAll('.room-item')) {
                        item.classList.remove('active');
                        if (item.dataset.roomId === roomId) {
                            item.classList.add('active');
                        }
                    }
                }
            }

            renderMinimap() {
                const minimapScale = 2;
                const mapWidth = WORLD_WIDTH;
                const mapHeight = WORLD_HEIGHT;
                const minimapCanvas = this.minimapCanvas;
                const minimapCtx = minimapCanvas.getContext('2d');

                minimapCanvas.width = mapWidth * minimapScale;
                minimapCanvas.height = mapHeight * minimapScale;

                minimapCtx.fillStyle = PALETTE.darkBg;
                minimapCtx.fillRect(0, 0, minimapCanvas.width, minimapCanvas.height);

                for (const room of this.tileMap.rooms) {
                    minimapCtx.fillStyle = PALETTE.accent;
                    minimapCtx.fillRect(room.x * minimapScale, room.y * minimapScale,
                                       room.w * minimapScale, room.h * minimapScale);
                    minimapCtx.strokeStyle = PALETTE.accentBright;
                    minimapCtx.lineWidth = 1;
                    minimapCtx.strokeRect(room.x * minimapScale, room.y * minimapScale,
                                         room.w * minimapScale, room.h * minimapScale);
                }

                for (const agent of this.agents) {
                    const agentX = (agent.position.x / TILE_SIZE) * minimapScale;
                    const agentY = (agent.position.y / TILE_SIZE) * minimapScale;
                    minimapCtx.fillStyle = agent.customization.bodyColor;
                    minimapCtx.beginPath();
                    minimapCtx.arc(agentX, agentY, 2, 0, Math.PI * 2);
                    minimapCtx.fill();
                }

                const viewportX = this.camera.vx / this.camera.zoom / TILE_SIZE;
                const viewportY = this.camera.vy / this.camera.zoom / TILE_SIZE;
                const viewportW = this.canvas.width / this.camera.zoom / TILE_SIZE;
                const viewportH = this.canvas.height / this.camera.zoom / TILE_SIZE;

                minimapCtx.strokeStyle = PALETTE.gold;
                minimapCtx.lineWidth = 2;
                minimapCtx.strokeRect(viewportX * minimapScale, viewportY * minimapScale,
                                     viewportW * minimapScale, viewportH * minimapScale);
            }

            updateStatus() {
                this.statusSize.textContent = `${WORLD_WIDTH}x${WORLD_HEIGHT} tiles`;
                this.statusRooms.textContent = this.tileMap.rooms.length;
                this.statusAgents.textContent = this.agents.length;
                this.statusFps.textContent = this.renderer.fps;
                this.zoomDisplay.textContent = Math.round(this.camera.zoom * 100) + '%';
            }

            updateAgents() {
                const now = Date.now();
                const deltaTime = now - this.lastUpdateTime;
                this.lastUpdateTime = now;

                this.agents.forEach(agent => {
                    agent.updateAnimation(deltaTime);
                    agent.updateMovement(deltaTime, this.tileMap);
                });

                if (Math.random() < 0.02) {
                    const agent = this.agents[Math.floor(Math.random() * this.agents.length)];
                    if (agent.status === 'idle') {
                        const room = this.tileMap.rooms[Math.floor(Math.random() * this.tileMap.rooms.length)];
                        agent.setTargetRoom(room.id, this.tileMap);
                    }
                }

                if (Math.random() < 0.01) {
                    const agent = this.agents.find(a => a.status === 'idle');
                    if (agent) {
                        const games = ['cloud_jump', 'jetpack_joyride', 'dino_run'];
                        const gameId = games[Math.floor(Math.random() * games.length)];
                        const score = Math.floor(Math.random() * 10000) + 1000;

                        this.highScores.recordScore(gameId, agent.id, score);
                        agent.recordScore(gameId, this.highScores.gameInfo[gameId].name, score);
                    }
                }
            }

            startGameLoop() {
                const loop = () => {
                    this.updateAgents();
                    this.renderer.render(this.agents);
                    this.renderMinimap();
                    this.renderAgentList();
                    this.updateStatus();
                    requestAnimationFrame(loop);
                };
                loop();
            }
        }

        // ============================================================================
        // STARTUP
        // ============================================================================
        window.addEventListener('DOMContentLoaded', () => {
            new VirtualOfficeApp();
        });
    
