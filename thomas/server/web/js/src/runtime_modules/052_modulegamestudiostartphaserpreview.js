// Extracted from part-027.js
// From modulegamestudiostartphaserpreview

            rows.push(`${x},${y},${type}`);
        }
    }
    return rows.join('\n');
}

function moduleGameStudioStartPhaserPreview(wb, mount, { onGoal = null, onHazard = null } = {}) {
    if (!window.Phaser || !(mount instanceof HTMLElement)) return null;
    if (wb.phaserGame?.destroy) {
        try {
            wb.phaserGame.destroy(true);
        } catch (_error) {}
    }
    mount.innerHTML = '';

    const tile = 28;
    const width = Math.max(320, wb.gridWidth * tile);
    const height = Math.max(240, wb.gridHeight * tile);
    const tiles = wb.tiles.map((row) => row.map((item) => moduleWorkbenchClamp(Number(item) || 0, 0, 4)));
    const spawn = moduleGameStudioFindFirstTile(wb, 3) || { x: 1, y: wb.gridHeight - 2 };

    const game = new window.Phaser.Game({
        type: window.Phaser.AUTO,
        width,
        height,
        parent: mount,
        backgroundColor: '#0f2336',
        physics: {
            default: 'arcade',
            arcade: {
                gravity: { y: 850 },
                debug: false,
            },
        },
        scene: {
            create() {
                this.cursors = this.input.keyboard.createCursorKeys();
                this.platforms = this.physics.add.staticGroup();
                this.hazards = this.physics.add.staticGroup();
                this.goals = this.physics.add.staticGroup();
                this.score = 0;
                this.scoreText = this.add.text(10, 8, 'SCORE 0', {
                    fontFamily: 'var(--font-mono, monospace)',
                    fontSize: '12px',
                    color: '#eaf4ff',
                });

                tiles.forEach((row, y) => {
                    row.forEach((tileType, x) => {
                        if (!tileType) return;
                        const px = (x * tile) + (tile / 2);
                        const py = (y * tile) + (tile / 2);
                        if (tileType === 1) {
                            const block = this.add.rectangle(px, py, tile - 4, tile - 4, 0x5ca4f3);
                            this.physics.add.existing(block, true);
                            this.platforms.add(block);
                        } else if (tileType === 2) {
                            const hazard = this.add.rectangle(px, py, tile - 6, tile - 6, 0xf17b8a);
                            this.physics.add.existing(hazard, true);
                            this.hazards.add(hazard);
                        } else if (tileType === 4) {
                            const goal = this.add.rectangle(px, py, tile - 8, tile - 8, 0xf5ce74);
                            this.physics.add.existing(goal, true);
                            this.goals.add(goal);
                        }
                    });
                });

                this.player = this.add.rectangle((spawn.x * tile) + (tile / 2), (spawn.y * tile) + (tile / 2) - 8, tile * 0.56, tile * 0.78, 0x8fd6ff);
                this.physics.add.existing(this.player);
                this.player.body.setCollideWorldBounds(true);
                this.player.body.setBounce(0.02);
                this.player.body.setDragX(500);
                this.player.body.setMaxVelocity(260, 720);

                this.physics.add.collider(this.player, this.platforms);
                this.physics.add.overlap(this.player, this.hazards, () => {
                    if (typeof onHazard === 'function') onHazard();
                    this.scene.restart();
                });
                this.physics.add.overlap(this.player, this.goals, () => {
                    if (typeof onGoal === 'function') onGoal();
                    this.scene.restart();
                });

                this.time.addEvent({
                    delay: 220,
                    loop: true,
                    callback: () => {
                        this.score += 1;
                        wb.previewScore = Math.max(0, Number(this.score) || 0);
                        wb.highScore = Math.max(Number(wb.highScore) || 0, wb.previewScore);
                        this.scoreText.setText(`SCORE ${wb.previewScore}`);
                    },
                });
            },
            update() {
                if (!this.player?.body) return;
                const body = this.player.body;
                if (this.cursors.left.isDown) {
                    body.setVelocityX(-190);
                } else if (this.cursors.right.isDown) {
                    body.setVelocityX(190);
                } else {
                    body.setVelocityX(0);
                }
                const canJump = body.blocked.down || body.touching.down;
                if ((this.cursors.up.isDown || this.cursors.space.isDown) && canJump) {
                    body.setVelocityY(-360);
                }
            },
        },
    });
    wb.phaserGame = game;
    return game;
}

function moduleRenderWorkbenchGameStudioDirector(container, wb) {
    if (!container || !wb) return false;
    moduleGameStudioEnsureDirectorState(wb);