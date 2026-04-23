
        // ============================================================================
        // CONSTANTS & CONFIGURATION
        // ============================================================================
        const TILE_SIZE = 32;
        const WORLD_WIDTH = 100;
        const WORLD_HEIGHT = 80;
        const AGENT_SIZE = 28;

        const PALETTE = {
            bg: '#0a0e1a',
            darkBg: '#050809',
            surface: '#141b2d',
            accent: '#00d4ff',
            accentBright: '#00ffff',
            gold: '#ffd700',
            goldDim: '#ccaa00',
            wall: '#2a3a52',
            floor: '#1a2532',
            corridor: '#1a2a42',
            green: '#90c890',
            greenBright: '#b0e0b0',
            red: '#ff6b6b',
            redDim: '#cc5555',
            blue: '#5b9bff',
            blueDim: '#4477dd',
            purple: '#c77dff',
            orange: '#ffb347',
        };

        // ============================================================================
        // AGENT/ROBOT CLASS
        // ============================================================================

        class AgentRobot {
            constructor(id, name, role, customization = {}) {
                this.id = id;
                this.name = name;
                this.role = role;

                this.status = 'idle';
                this.currentRoom = 'lobby';
                this.targetRoom = null;
                this.path = [];
                this.pathIndex = 0;

                this.position = { x: 300, y: 300 };
                this.targetPosition = { x: 300, y: 300 };
                this.velocity = { x: 0, y: 0 };

                this.deskPosition = { x: 0, y: 0 };
                this.deskTile = { x: 0, y: 0 };

                this.customization = {
                    bodyColor: customization.bodyColor || '#4A90E2',
                    accentColor: customization.accentColor || '#2E5C8A',
                    eyeColor: customization.eyeColor || '#FFFFFF',
                    hatType: customization.hatType || 'none',
                    accessory: customization.accessory || 'none',
                    antennaStyle: customization.antennaStyle || 'straight'
                };

                this.highScores = {};
                this.trophies = [];

                this.animFrame = 0;
                this.animTimer = 0;
                this.direction = 'down';
                this.spriteCanvas = null;
                this.spriteCache = {};

                this.generateSprite();
            }

            generateSprite() {
                const size = 32;
                this.spriteCache = {};

                ['down', 'up', 'left', 'right'].forEach(direction => {
                    const canvas = document.createElement('canvas');
                    canvas.width = size;
                    canvas.height = size;
                    const ctx = canvas.getContext('2d');
                    ctx.clearRect(0, 0, size, size);
                    this.drawRobotBody(ctx, size, direction, 0);
                    this.spriteCache[direction] = canvas;
                });
            }

            drawRobotBody(ctx, size, direction, animFrame) {
                const c = this.customization;
                const bodyColor = c.bodyColor;
                const accentColor = c.accentColor;
                const eyeColor = c.eyeColor;

                const centerX = size / 2;
                const centerY = size / 2;

                const bodyWidth = 14;
                const bodyHeight = 18;
                const bodyX = centerX - bodyWidth / 2;
                const bodyY = centerY - 2;

                ctx.fillStyle = bodyColor;
                ctx.beginPath();
                ctx.roundRect(bodyX, bodyY, bodyWidth, bodyHeight, 3);
                ctx.fill();

                ctx.fillStyle = accentColor;
                ctx.fillRect(bodyX + 2, bodyY + 6, bodyWidth - 4, 2);

                const armY = bodyY + 5;
                const armLength = 6;
                const armHeight = 3;

                ctx.fillStyle = bodyColor;
                let leftArmAngle = 0;
                let rightArmAngle = 0;

                if (this.status === 'traveling') {
                    leftArmAngle = Math.sin(animFrame * Math.PI / 2) * 0.3;
                    rightArmAngle = Math.sin((animFrame + 2) * Math.PI / 2) * 0.3;
                } else if (this.status === 'working') {
                    leftArmAngle = Math.sin(animFrame * Math.PI) * 0.4;
                    rightArmAngle = Math.sin((animFrame + 1) * Math.PI) * 0.4;
                }

                ctx.save();
                ctx.translate(bodyX - 1, armY);
                ctx.rotate(leftArmAngle);
                ctx.fillRect(-armLength, 0, armLength, armHeight);
                ctx.restore();

                ctx.save();
                ctx.translate(bodyX + bodyWidth + 1, armY);
                ctx.rotate(rightArmAngle);
                ctx.fillRect(0, 0, armLength, armHeight);
                ctx.restore();

                const legY = bodyY + bodyHeight - 1;
                const legWidth = 3;
                const legHeight = 6;

                let leftLegOffset = 0;
                let rightLegOffset = 0;
                if (this.status === 'traveling') {
                    leftLegOffset = Math.sin(animFrame * Math.PI / 2) * 2;
                    rightLegOffset = Math.sin((animFrame + 2) * Math.PI / 2) * 2;
                }

                ctx.fillStyle = accentColor;
                ctx.fillRect(bodyX + 2, legY + leftLegOffset, legWidth, legHeight);
                ctx.fillRect(bodyX + bodyWidth - legWidth - 2, legY + rightLegOffset, legWidth, legHeight);

                const headRadius = 6;
                const headX = centerX;
                const headY = bodyY - 6;

                ctx.fillStyle = bodyColor;
                ctx.beginPath();
                ctx.arc(headX, headY, headRadius, 0, Math.PI * 2);
                ctx.fill();

                ctx.fillStyle = eyeColor;
                ctx.fillRect(headX - 4, headY - 2, 2, 2);
                ctx.fillRect(headX + 2, headY - 2, 2, 2);

                ctx.fillStyle = '#000000';
                let pupilOffsetX = 0;
                let pupilOffsetY = 0;
                if (direction === 'left') pupilOffsetX = -0.5;
                if (direction === 'right') pupilOffsetX = 0.5;
                if (direction === 'up') pupilOffsetY = -0.5;
                if (direction === 'down') pupilOffsetY = 0.5;

                ctx.fillRect(headX - 3.5 + pupilOffsetX, headY - 1.5 + pupilOffsetY, 1, 1);
                ctx.fillRect(headX + 2.5 + pupilOffsetX, headY - 1.5 + pupilOffsetY, 1, 1);

                ctx.strokeStyle = '#000000';
                ctx.lineWidth = 0.5;
                ctx.beginPath();
                ctx.arc(headX, headY + 2, 2, 0, Math.PI);
                ctx.stroke();

                if (c.antennaStyle !== 'none') {
                    ctx.strokeStyle = accentColor;
                    ctx.lineWidth = 1;

                    if (c.antennaStyle === 'straight') {
                        ctx.beginPath();
                        ctx.moveTo(headX, headY - headRadius);
                        ctx.lineTo(headX, headY - headRadius - 8);
                        ctx.stroke();
                        ctx.fillStyle = accentColor;
                        ctx.beginPath();
                        ctx.arc(headX, headY - headRadius - 8, 1.5, 0, Math.PI * 2);
                        ctx.fill();
                    } else if (c.antennaStyle === 'curved') {
                        ctx.beginPath();
                        ctx.moveTo(headX, headY - headRadius);
                        ctx.quadraticCurveTo(headX - 3, headY - headRadius - 6, headX - 2, headY - headRadius - 8);
                        ctx.stroke();
                        ctx.fillStyle = accentColor;
                        ctx.beginPath();
                        ctx.arc(headX - 2, headY - headRadius - 8, 1, 0, Math.PI * 2);
                        ctx.fill();
                    }
                }

                if (c.hatType === 'hardhat') {
                    const hatY = headY - headRadius - 1;
                    ctx.fillStyle = '#FF9800';
                    ctx.beginPath();
                    ctx.ellipse(headX, hatY - 3, 8, 3, 0, 0, Math.PI * 2);
                    ctx.fill();
                    ctx.strokeStyle = '#000000';
                    ctx.lineWidth = 0.5;
                    ctx.stroke();
                    ctx.fillStyle = '#E65100';
                    ctx.fillRect(headX - 8.5, hatY - 1, 17, 1.5);
                } else if (c.hatType === 'crown') {
                    const hatY = headY - headRadius - 1;
                    ctx.fillStyle = '#FFD700';
                    ctx.beginPath();
                    ctx.moveTo(headX - 6, hatY);
                    ctx.lineTo(headX - 4, hatY - 5);
                    ctx.lineTo(headX - 1, hatY - 2);
                    ctx.lineTo(headX, hatY - 6);
                    ctx.lineTo(headX + 1, hatY - 2);
                    ctx.lineTo(headX + 4, hatY - 5);
                    ctx.lineTo(headX + 6, hatY);
                    ctx.closePath();
                    ctx.fill();
                }

                const statusColors = {
                    idle: '#4CAF50',
                    working: '#2196F3',
                    gaming: '#FFC107',
                    traveling: '#FF9800'
                };
                ctx.fillStyle = statusColors[this.status] || '#4CAF50';
                ctx.beginPath();
                ctx.arc(centerX, size - 2, 1.5, 0, Math.PI * 2);
                ctx.fill();
            }

            updateAnimation(deltaTime) {
                if (this.status === 'traveling') {
                    this.animTimer += deltaTime;
                    if (this.animTimer >= 200) {
                        this.animFrame = (this.animFrame + 1) % 4;
                        this.animTimer = 0;
                    }
                } else if (this.status === 'working') {
                    this.animTimer += deltaTime;
                    if (this.animTimer >= 150) {
                        this.animFrame = (this.animFrame + 1) % 4;
                        this.animTimer = 0;
                    }
                } else if (this.status === 'idle') {
                    this.animTimer += deltaTime;
                    this.animFrame = (this.animTimer / 1000) % 1;
                }
            }

            setTargetRoom(roomId, tileMap) {
                this.targetRoom = roomId;
                this.status = 'traveling';

                const currentTile = {
                    x: Math.floor(this.position.x / TILE_SIZE),
                    y: Math.floor(this.position.y / TILE_SIZE)
                };

                const room = tileMap.rooms.find(r => r.id === roomId);
                const targetTile = {
                    x: room.x + Math.floor(room.w / 2),
                    y: room.y + Math.floor(room.h / 2)
                };

                this.path = this.findPath(currentTile, targetTile, tileMap);
                this.pathIndex = 0;
            }

            findPath(start, goal, tileMap) {
                const openSet = [start];
                const cameFrom = new Map();
                const gScore = new Map();
                const fScore = new Map();

                const key = (p) => `${p.x},${p.y}`;
                const heuristic = (p) => Math.abs(p.x - goal.x) + Math.abs(p.y - goal.y);

                gScore.set(key(start), 0);
                fScore.set(key(start), heuristic(start));

                while (openSet.length > 0) {
                    let current = openSet[0];
                    let currentIdx = 0;
                    for (let i = 1; i < openSet.length; i++) {
                        if (fScore.get(key(openSet[i])) < fScore.get(key(current))) {
                            current = openSet[i];
                            currentIdx = i;
                        }
                    }

                    if (current.x === goal.x && current.y === goal.y) {
                        const path = [current];
                        while (cameFrom.has(key(current))) {
                            current = cameFrom.get(key(current));
                            path.unshift(current);
                        }
                        return path;
                    }

                    openSet.splice(currentIdx, 1);

                    const neighbors = [
                        { x: current.x + 1, y: current.y },
                        { x: current.x - 1, y: current.y },
                        { x: current.x, y: current.y + 1 },
                        { x: current.x, y: current.y - 1 }
                    ];

                    for (const neighbor of neighbors) {
                        if (!this.isWalkable(neighbor, tileMap)) continue;

                        const tentativeGScore = gScore.get(key(current)) + 1;

                        if (!gScore.has(key(neighbor)) || tentativeGScore < gScore.get(key(neighbor))) {
                            cameFrom.set(key(neighbor), current);
                            gScore.set(key(neighbor), tentativeGScore);
                            fScore.set(key(neighbor), tentativeGScore + heuristic(neighbor));

                            if (!openSet.some(p => p.x === neighbor.x && p.y === neighbor.y)) {
                                openSet.push(neighbor);
                            }
                        }
                    }
                }

                return [];
            }

            isWalkable(tile, tileMap) {
                const tileType = tileMap.getTile(tile.x, tile.y);
                return tileType !== 'wall';
            }

            updateMovement(deltaTime, tileMap) {
                if (this.status !== 'traveling' || this.path.length === 0) return;

                const nextTile = this.path[this.pathIndex];
                this.targetPosition = {
                    x: nextTile.x * TILE_SIZE + TILE_SIZE / 2,
                    y: nextTile.y * TILE_SIZE + TILE_SIZE / 2
                };

                const speed = 2 * TILE_SIZE / 1000;
                const dx = this.targetPosition.x - this.position.x;
                const dy = this.targetPosition.y - this.position.y;
                const distance = Math.sqrt(dx * dx + dy * dy);

                if (distance < speed * deltaTime) {
                    this.position = { ...this.targetPosition };
                    this.pathIndex++;

                    if (Math.abs(dx) > Math.abs(dy)) {
                        this.direction = dx > 0 ? 'right' : 'left';
                    } else {
                        this.direction = dy > 0 ? 'down' : 'up';
                    }

                    if (this.pathIndex >= this.path.length) {
                        this.status = 'idle';
                        this.path = [];
                    }
                } else {
                    const moveDistance = speed * deltaTime;
                    const ratio = moveDistance / distance;
                    this.position.x += dx * ratio;
                    this.position.y += dy * ratio;

                    if (Math.abs(dx) > Math.abs(dy)) {
                        this.direction = dx > 0 ? 'right' : 'left';
                    } else {
                        this.direction = dy > 0 ? 'down' : 'up';
                    }
                }
            }

            setStatus(status) {
                this.status = status;
            }

            recordScore(gameId, gameName, score) {
                if (!this.highScores[gameId]) {
                    this.highScores[gameId] = 0;
                }

                const previousHigh = this.highScores[gameId];
                this.highScores[gameId] = Math.max(this.highScores[gameId], score);

                if (score > previousHigh) {
                    this.trophies.push({
                        game: gameName,
                        gameId: gameId,
                        score: score,
                        date: new Date().toLocaleDateString()
                    });
                }
            }

            customizeRobot(customization) {
                this.customization = { ...this.customization, ...customization };
                this.generateSprite();
            }
        }

        // ============================================================================
        // HIGH SCORE MANAGER
        // ============================================================================

        class HighScoreManager {
            constructor() {
                this.scores = {};
                this.gameInfo = {};
            }

            registerGame(gameId, name, color = '#FF6B6B') {
                this.gameInfo[gameId] = { name, color };
                if (!this.scores[gameId]) {
                    this.scores[gameId] = {};
                }
            }

            recordScore(gameId, agentId, score) {
                if (!this.scores[gameId]) {
                    this.scores[gameId] = {};
                }
                this.scores[gameId][agentId] = score;
            }

            getTopScores(gameId, limit = 5) {
                const gameScores = this.scores[gameId] || {};
                return Object.entries(gameScores)
                    .sort((a, b) => b[1] - a[1])
                    .slice(0, limit)
                    .map(([agentId, score]) => ({ agentId, score }));
            }
        }

        // ============================================================================
        // SPRITE ATLAS GENERATOR
        // ============================================================================
        class SpriteAtlas {
            constructor() {
                this.canvas = document.createElement('canvas');
                this.canvas.width = 1024;
                this.canvas.height = 1024;
                this.ctx = this.canvas.getContext('2d');
                this.tiles = {};
                this.tileIndex = 0;
                this.tilesPerRow = 32;
                this.generateAllTiles();
            }

            getTilePos(index) {
                const row = Math.floor(index / this.tilesPerRow);
                const col = index % this.tilesPerRow;
                return [col * TILE_SIZE, row * TILE_SIZE];
            }

            drawPixel(x, y, color) {
                this.ctx.fillStyle = color;
                this.ctx.fillRect(x, y, 1, 1);
            }

            drawRect(x, y, w, h, color) {
                this.ctx.fillStyle = color;
                this.ctx.fillRect(x, y, w, h);
            }

            drawLine(x1, y1, x2, y2, color, width = 1) {
                this.ctx.strokeStyle = color;
                this.ctx.lineWidth = width;
                this.ctx.beginPath();
                this.ctx.moveTo(x1, y1);
                this.ctx.lineTo(x2, y2);
                this.ctx.stroke();
            }

            registerTile(name) {
                const [x, y] = this.getTilePos(this.tileIndex);
                this.tiles[name] = { x, y, index: this.tileIndex };
                this.tileIndex++;
                return [x, y];
            }

            drawFloor() {
                const [x, y] = this.registerTile('floor');
                this.drawRect(x, y, TILE_SIZE, TILE_SIZE, PALETTE.floor);
                for (let i = 0; i < 4; i++) {
                    for (let j = 0; j < 4; j++) {
                        if ((i + j) % 2 === 0) {
                            this.drawRect(x + i * 8, y + j * 8, 8, 8, '#1f2a3a');
                        }
                    }
                }
                this.drawLine(x, y, x + TILE_SIZE, y, '#252f42', 1);
            }

            drawCorridor() {
                const [x, y] = this.registerTile('corridor');
                this.drawRect(x, y, TILE_SIZE, TILE_SIZE, PALETTE.corridor);
                for (let i = 0; i < 8; i++) {
                    this.drawLine(x + i * 4, y + i * 4, x + i * 4 + 4, y + i * 4 - 4, '#2a3a52', 1);
                }
                this.drawLine(x, y, x + TILE_SIZE, y, '#3a4a62', 1);
            }

            drawWall() {
                const [x, y] = this.registerTile('wall');
                this.drawRect(x, y, TILE_SIZE, TILE_SIZE, PALETTE.wall);
                this.drawRect(x + 2, y + 2, 12, 12, '#3a4a62');
                this.drawRect(x + 18, y + 2, 12, 12, '#3a4a62');
                this.drawRect(x + 2, y + 18, 12, 12, '#3a4a62');
                this.drawRect(x + 18, y + 18, 12, 12, '#3a4a62');
                this.drawLine(x, y, x + TILE_SIZE, y, '#4a5a72', 1);
                this.drawLine(x, y, x, y + TILE_SIZE, '#4a5a72', 1);
            }

            drawDoor() {
                const [x, y] = this.registerTile('door');
                this.drawRect(x, y, TILE_SIZE, TILE_SIZE, PALETTE.floor);
                this.drawRect(x + 4, y + 4, 24, 24, '#cc8844');
                this.drawRect(x + 6, y + 6, 20, 20, '#aa6633');
                this.drawLine(x + 14, y + 6, x + 14, y + 26, '#dd9955', 2);
                this.drawRect(x + 20, y + 14, 3, 3, PALETTE.gold);
            }

            drawDeskWithMonitors() {
                const [x, y] = this.registerTile('desk');
                this.drawRect(x, y, TILE_SIZE, TILE_SIZE, PALETTE.floor);
                this.drawRect(x + 4, y + 8, 24, 18, '#664433');
                this.drawRect(x + 4, y + 4, 9, 9, '#333333');
                this.drawRect(x + 5, y + 5, 7, 7, PALETTE.blue);
                this.drawRect(x + 19, y + 4, 9, 9, '#333333');
                this.drawRect(x + 20, y + 5, 7, 7, '#ff5555');
                this.drawRect(x + 8, y + 22, 16, 4, '#444444');
                this.drawLine(x + 6, y + 26, x + 6, y + 30, '#553322', 1);
                this.drawLine(x + 26, y + 26, x + 26, y + 30, '#553322', 1);
            }

            drawChair() {
                const [x, y] = this.registerTile('chair');
                this.drawRect(x, y, TILE_SIZE, TILE_SIZE, PALETTE.floor);
                this.drawRect(x + 10, y + 14, 12, 12, '#444444');
                this.drawRect(x + 11, y + 4, 10, 10, '#555555');
                this.drawLine(x + 8, y + 16, x + 8, y + 22, '#555555', 2);
                this.drawLine(x + 24, y + 16, x + 24, y + 22, '#555555', 2);
                this.drawRect(x + 12, y + 26, 8, 3, '#333333');
            }

            drawPlant() {
                const [x, y] = this.registerTile('plant');
                this.drawRect(x, y, TILE_SIZE, TILE_SIZE, PALETTE.floor);
                this.drawRect(x + 10, y + 18, 12, 12, '#884422');
                this.drawLine(x + 9, y + 18, x + 23, y + 18, '#aa5533', 1);
                this.drawRect(x + 11, y + 19, 10, 4, '#663311');
                const leafColor = PALETTE.green;
                this.drawRect(x + 8, y + 12, 3, 6, leafColor);
                this.drawRect(x + 6, y + 8, 5, 8, leafColor);
                this.drawRect(x + 5, y + 5, 3, 5, leafColor);
                this.drawRect(x + 21, y + 12, 3, 6, leafColor);
                this.drawRect(x + 21, y + 8, 5, 8, leafColor);
                this.drawRect(x + 24, y + 5, 3, 5, leafColor);
                this.drawRect(x + 14, y + 4, 4, 10, leafColor);
            }

            drawServerRack() {
                const [x, y] = this.registerTile('server_rack');
                this.drawRect(x, y, TILE_SIZE, TILE_SIZE, PALETTE.floor);
                this.drawRect(x + 4, y + 2, 24, 28, '#222222');
                this.drawLine(x + 4, y + 2, x + 28, y + 2, '#444444', 1);
                this.drawLine(x + 4, y + 30, x + 28, y + 30, '#444444', 1);
                for (let i = 0; i < 5; i++) {
                    this.drawRect(x + 6, y + 4 + i * 5, 20, 4, '#1a1a1a');
                    this.drawRect(x + 8, y + 5 + i * 5, 2, 2, '#ff6666');
                    this.drawRect(x + 12, y + 5 + i * 5, 2, 2, PALETTE.blue);
                    this.drawRect(x + 16, y + 5 + i * 5, 2, 2, PALETTE.blue);
                    this.drawRect(x + 20, y + 5 + i * 5, 2, 2, '#ff6666');
                }
            }

            drawConferenceTable() {
                const [x, y] = this.registerTile('conf_table');
                this.drawRect(x, y, TILE_SIZE, TILE_SIZE, PALETTE.floor);
                this.drawRect(x + 2, y + 6, 28, 20, '#8b4513');
                this.drawLine(x + 2, y + 6, x + 30, y + 6, '#a0522d', 1);
                this.drawLine(x + 2, y + 26, x + 30, y + 26, '#654321', 1);
                this.drawLine(x + 3, y + 7, x + 29, y + 7, '#d2691e', 1);
                this.drawLine(x + 8, y + 26, x + 8, y + 30, '#654321', 2);
                this.drawLine(x + 24, y + 26, x + 24, y + 30, '#654321', 2);
            }

            drawCoffeMachine() {
                const [x, y] = this.registerTile('coffee_machine');
                this.drawRect(x, y, TILE_SIZE, TILE_SIZE, PALETTE.floor);
                this.drawRect(x + 6, y + 4, 20, 24, '#333333');
                this.drawRect(x + 8, y + 6, 16, 8, '#000000');
                this.drawRect(x + 9, y + 7, 14, 6, '#1a1a2e');
                this.drawRect(x + 10, y + 16, 12, 8, '#1a1a1a');
                this.drawRect(x + 12, y + 18, 2, 4, PALETTE.orange);
                this.drawRect(x + 14, y + 26, 4, 2, PALETTE.red);
            }

            drawArcadeMachine() {
                const [x, y] = this.registerTile('arcade_machine');
                this.drawRect(x, y, TILE_SIZE, TILE_SIZE, PALETTE.floor);
                this.drawRect(x + 4, y + 2, 24, 26, '#222222');
                this.drawRect(x + 6, y + 4, 20, 14, '#1a1a1a');
                this.drawRect(x + 7, y + 5, 18, 12, '#0a3a0a');
                for (let i = 0; i < 6; i++) {
                    this.drawLine(x + 7, y + 6 + i * 2, x + 25, y + 6 + i * 2, '#0a5a0a', 1);
                }
                this.drawRect(x + 6, y + 20, 20, 6, '#1a1a1a');
                this.drawRect(x + 8, y + 21, 3, 3, '#444444');
                this.drawRect(x + 15, y + 21, 2, 2, PALETTE.red);
                this.drawRect(x + 19, y + 21, 2, 2, PALETTE.blue);
                this.drawRect(x + 23, y + 21, 2, 2, PALETTE.gold);
            }

            drawBookshelf() {
                const [x, y] = this.registerTile('bookshelf');
                this.drawRect(x, y, TILE_SIZE, TILE_SIZE, PALETTE.floor);
                this.drawRect(x + 2, y + 4, 28, 24, '#704020');
                for (let i = 0; i < 4; i++) {
                    this.drawLine(x + 3, y + 8 + i * 6, x + 29, y + 8 + i * 6, '#8b4513', 1);
                }
                const colors = [PALETTE.red, PALETTE.blue, PALETTE.gold, PALETTE.purple, '#aa0088', PALETTE.green];
                let colorIdx = 0;
                for (let i = 0; i < 4; i++) {
                    for (let j = 0; j < 4; j++) {
                        const bx = x + 4 + j * 6;
                        const by = y + 6 + i * 5;
                        this.drawRect(bx, by, 4, 3, colors[colorIdx % colors.length]);
                        colorIdx++;
                    }
                }
            }

            drawVendingMachine() {
                const [x, y] = this.registerTile('vending_machine');
                this.drawRect(x, y, TILE_SIZE, TILE_SIZE, PALETTE.floor);
                this.drawRect(x + 6, y + 2, 20, 26, '#cc0000');
                this.drawRect(x + 8, y + 4, 16, 16, '#000000');
                this.drawRect(x + 9, y + 5, 14, 14, '#0a0a0a');
                this.drawRect(x + 10, y + 6, 3, 3, PALETTE.orange);
                this.drawRect(x + 14, y + 6, 3, 3, PALETTE.blue);
                this.drawRect(x + 18, y + 6, 3, 3, PALETTE.red);
                this.drawRect(x + 10, y + 11, 3, 3, PALETTE.purple);
                this.drawRect(x + 14, y + 11, 3, 3, PALETTE.gold);
                this.drawRect(x + 18, y + 11, 3, 3, PALETTE.green);
                this.drawRect(x + 8, y + 22, 6, 4, '#333333');
                this.drawRect(x + 20, y + 22, 4, 4, PALETTE.gold);
            }

            drawTrophyCase() {
                const [x, y] = this.registerTile('trophy_case');
                this.drawRect(x, y, TILE_SIZE, TILE_SIZE, PALETTE.floor);
                this.drawRect(x + 4, y + 2, 24, 26, '#1a1a1a');
                this.drawLine(x + 4, y + 2, x + 28, y + 2, '#444444', 1);
                this.drawRect(x + 6, y + 4, 20, 20, '#0a0a0a');
                this.drawLine(x + 7, y + 5, x + 27, y + 5, '#1a1a1a', 1);
                this.drawRect(x + 10, y + 12, 4, 8, PALETTE.gold);
                this.drawRect(x + 9, y + 10, 6, 2, PALETTE.gold);
                this.drawRect(x + 16, y + 11, 4, 9, '#c0c0c0');
                this.drawRect(x + 15, y + 9, 6, 2, '#c0c0c0');
                this.drawRect(x + 22, y + 13, 3, 7, '#cd7f32');
                this.drawRect(x + 21, y + 11, 5, 2, '#cd7f32');
            }

            drawExecutiveDesk() {
                const [x, y] = this.registerTile('exec_desk');
                this.drawRect(x, y, TILE_SIZE, TILE_SIZE, PALETTE.floor);
                this.drawRect(x + 2, y + 8, 28, 18, '#5a3a1a');
                this.drawLine(x + 2, y + 8, x + 30, y + 8, '#8b5a2b', 1);
                this.drawLine(x + 2, y + 26, x + 30, y + 26, '#3a1a0a', 1);
                this.drawRect(x + 8, y + 4, 12, 8, '#1a1a1a');
                this.drawRect(x + 9, y + 5, 10, 6, '#2a5a8a');
                this.drawRect(x + 22, y + 6, 4, 6, PALETTE.gold);
                this.drawRect(x + 4, y + 6, 2, 6, PALETTE.blue);
            }

            drawReceptionDesk() {
                const [x, y] = this.registerTile('reception_desk');
                this.drawRect(x, y, TILE_SIZE, TILE_SIZE, PALETTE.floor);
                this.drawRect(x + 2, y + 10, 28, 14, '#aa8833');
                this.drawLine(x + 2, y + 10, x + 30, y + 10, '#ccaa55', 1);
                this.drawRect(x + 2, y + 24, 28, 6, '#885533');
                this.drawRect(x + 10, y + 4, 12, 6, '#333333');
                this.drawRect(x + 11, y + 5, 10, 4, '#0a0a0a');
                this.drawRect(x + 4, y + 12, 4, 6, '#666666');
                this.drawRect(x + 22, y + 12, 4, 6, '#666666');
            }

            drawSofa() {
                const [x, y] = this.registerTile('sofa');
                this.drawRect(x, y, TILE_SIZE, TILE_SIZE, PALETTE.floor);
                this.drawRect(x + 2, y + 8, 28, 16, '#664455');
                this.drawLine(x + 3, y + 8, x + 29, y + 8, '#8a5a7a', 1);
                this.drawRect(x + 4, y + 12, 6, 8, '#775566');
                this.drawRect(x + 12, y + 12, 8, 8, '#775566');
                this.drawRect(x + 22, y + 12, 6, 8, '#775566');
                this.drawRect(x + 6, y + 24, 2, 6, '#443322');
                this.drawRect(x + 24, y + 24, 2, 6, '#443322');
            }

            drawPresentationScreen() {
                const [x, y] = this.registerTile('presentation_screen');
                this.drawRect(x, y, TILE_SIZE, TILE_SIZE, PALETTE.floor);
                this.drawRect(x + 12, y + 20, 8, 8, '#333333');
                this.drawRect(x + 4, y + 2, 24, 20, '#1a1a1a');
                this.drawRect(x + 6, y + 4, 20, 16, '#000000');
                this.drawLine(x + 7, y + 5, x + 25, y + 5, '#1a3a5a', 1);
                this.drawLine(x + 7, y + 8, x + 25, y + 8, '#1a3a5a', 1);
                this.drawLine(x + 7, y + 11, x + 25, y + 11, '#1a3a5a', 1);
                this.drawLine(x + 7, y + 14, x + 25, y + 14, '#1a3a5a', 1);
            }

            drawMonitoringBoard() {
                const [x, y] = this.registerTile('monitoring_board');
                this.drawRect(x, y, TILE_SIZE, TILE_SIZE, PALETTE.floor);
                this.drawRect(x + 2, y + 2, 28, 28, '#1a1a1a');
                this.drawLine(x + 2, y + 2, x + 30, y + 2, '#444444', 1);
                for (let i = 0; i < 4; i++) {
                    for (let j = 0; j < 4; j++) {
                        const lx = x + 6 + i * 6;
                        const ly = y + 8 + j * 6;
                        const status = (i + j) % 3;
                        const color = status === 0 ? PALETTE.red : status === 1 ? PALETTE.gold : PALETTE.green;
                        this.drawRect(lx, ly, 3, 3, '#0a0a0a');
                        this.drawRect(lx + 1, ly + 1, 2, 2, color);
                    }
                }
            }

            generateAllTiles() {
                this.drawFloor();
                this.drawCorridor();
                this.drawWall();
                this.drawDoor();
                this.drawDeskWithMonitors();
                this.drawChair();
                this.drawPlant();
                this.drawServerRack();
                this.drawConferenceTable();
                this.drawCoffeMachine();
                this.drawArcadeMachine();
                this.drawBookshelf();
                this.drawVendingMachine();
                this.drawTrophyCase();
                this.drawExecutiveDesk();
                this.drawReceptionDesk();
                this.drawSofa();
                this.drawPresentationScreen();
                this.drawMonitoringBoard();
            }
        }

        // ============================================================================
        // TILEMAP & ROOM SYSTEM
        // ============================================================================
        class Room {
            constructor(id, label, x, y, w, h, theme = 'office') {
                this.id = id;
                this.label = label;
                this.x = x;
                this.y = y;
                this.w = w;
                this.h = h;
                this.theme = theme;
                this.furniture = [];
                this.doorPosition = null;
            }

            addFurniture(type, tx, ty) {
                this.furniture.push({ type, tx, ty });
            }

            setDoorPosition(tx, ty) {
                this.doorPosition = { tx, ty };
            }

            isInside(tx, ty) {
                return tx >= this.x && tx < this.x + this.w &&
                       ty >= this.y && ty < this.y + this.h;
            }

            getInteriorTiles() {
                const interior = [];
                for (let y = this.y; y < this.y + this.h; y++) {
                    for (let x = this.x; x < this.x + this.w; x++) {
                        interior.push({ x, y });
                    }
                }
                return interior;
            }
        }

        class TileMap {
            constructor(width, height) {
                this.width = width;
                this.height = height;
                this.tiles = Array(height).fill(null).map(() => Array(width).fill('floor'));
                this.rooms = [];
                this.corridors = [];
            }

            getTile(x, y) {
                if (x < 0 || x >= this.width || y < 0 || y >= this.height) return 'wall';
                return this.tiles[y][x];
            }

            setTile(x, y, type) {
                if (x >= 0 && x < this.width && y >= 0 && y < this.height) {
                    this.tiles[y][x] = type;
                }
            }

            addRoom(room) {
                this.rooms.push(room);
                const interior = room.getInteriorTiles();
                interior.forEach(tile => this.setTile(tile.x, tile.y, 'floor'));
            }

            addCorridor(x1, y1, x2, y2) {
                const corridor = [];
                const minX = Math.min(x1, x2);
                const maxX = Math.max(x1, x2);
                for (let x = minX; x <= maxX; x++) {
                    this.setTile(x, y1, 'corridor');
                    corridor.push({ x, y: y1 });
                }
                const minY = Math.min(y1, y2);
                const maxY = Math.max(y1, y2);
                for (let y = minY; y <= maxY; y++) {
                    this.setTile(x2, y, 'corridor');
                    corridor.push({ x: x2, y });
                }
                this.corridors.push(corridor);
            }

            surroundRoomWithWalls(room) {
                for (let x = room.x - 1; x <= room.x + room.w; x++) {
                    if (this.getTile(x, room.y - 1) !== 'corridor') this.setTile(x, room.y - 1, 'wall');
                    if (this.getTile(x, room.y + room.h) !== 'corridor') this.setTile(x, room.y + room.h, 'wall');
                }
                for (let y = room.y - 1; y <= room.y + room.h; y++) {
                    if (this.getTile(room.x - 1, y) !== 'corridor') this.setTile(room.x - 1, y, 'wall');
                    if (this.getTile(room.x + room.w, y) !== 'corridor') this.setTile(room.x + room.w, y, 'wall');
                }
                if (room.doorPosition) {
                    this.setTile(room.doorPosition.tx, room.doorPosition.ty, 'door');
                }
            }
        }

        // ============================================================================
        // CAMERA (PAN & ZOOM)
        // ============================================================================
        class Camera {
            constructor(width, height) {
                this.vx = 0;
                this.vy = 0;
                this.zoom = 1.0;
                this.viewWidth = width;
                this.viewHeight = height;
                this.minZoom = 0.5;
                this.maxZoom = 3.0;
            }

            panBy(dx, dy) {
                this.vx += dx;
                this.vy += dy;
                this.clampView();
            }

            zoomAt(amount, mouseX, mouseY) {
                const oldZoom = this.zoom;
                const worldX = (mouseX + this.vx) / oldZoom;
                const worldY = (mouseY + this.vy) / oldZoom;

                const zoomFactor = 1.1;
                this.zoom *= amount > 0 ? zoomFactor : 1 / zoomFactor;
                this.zoom = Math.max(this.minZoom, Math.min(this.maxZoom, this.zoom));

                this.vx = worldX * this.zoom - mouseX;
