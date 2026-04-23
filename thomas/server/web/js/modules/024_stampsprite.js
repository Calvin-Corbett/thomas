// Extracted from part-012b.js
// From stampsprite

                if (((x + (y * 2)) % 7) === 0) {
                    ctx.fillStyle = accent;
                    ctx.fillRect(ox + x, oy + y, 1, 1);
                } else if (((x * 3) + y) % 13 === 0) {
                    ctx.fillStyle = accentTwo;
                    ctx.fillRect(ox + x, oy + y, 1, 1);
                }
            }
        }
        if (line) {
            ctx.fillStyle = line;
            ctx.fillRect(ox, oy + (tile / 2) - 1, tile, 1);
            ctx.fillRect(ox + (tile / 2) - 1, oy, 1, tile);
        }
    };

    const stampSprite = (col, row, pixels, palette, scale = 3) => {
        const ox = col * tile;
        const oy = row * tile;