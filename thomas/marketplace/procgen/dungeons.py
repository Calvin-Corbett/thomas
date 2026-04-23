"""
Dungeon generation using BSP trees, cellular automata, and random walks.
"""

import random
from dataclasses import dataclass

from thomas.marketplace.procgen._exceptions import InvalidConfigError
from thomas.marketplace.procgen._types import Corridor, Dungeon, Room, RoomType, Tile


@dataclass
class DungeonGenerator:
    """Base class for dungeon generation."""

    width: int
    height: int
    seed: int = 42

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.width < 10 or self.height < 10:
            raise InvalidConfigError("Dungeon dimensions must be at least 10x10", "dimensions")
        random.seed(self.seed)

    def _carve_path(
        self,
        tiles: dict[tuple[int, int], Tile],
        start: tuple[int, int],
        end: tuple[int, int],
    ) -> list[tuple[int, int]]:
        """
        Carve a corridor using A* algorithm.

        Args:
            tiles: Tile dictionary
            start: Starting coordinate
            end: Ending coordinate

        Returns:
            List of coordinates forming the path
        """
        path = []
        x, y = start
        end_x, end_y = end

        # Simple pathfinding (not full A*, but good enough)
        while (x, y) != (end_x, end_y):
            # Move toward target
            if x < end_x:
                x += 1
            elif x > end_x:
                x -= 1

            if y < end_y:
                y += 1
            elif y > end_y:
                y -= 1

            if 0 <= x < self.width and 0 <= y < self.height:
                path.append((x, y))
                if (x, y) not in tiles:
                    tiles[(x, y)] = Tile(x=x, y=y, walkable=True)
                else:
                    tiles[(x, y)].walkable = True

        return path


@dataclass
class BSPDungeonGenerator(DungeonGenerator):
    """
    Generate dungeons using Binary Space Partition tree.

    Recursively splits space into rooms connected by corridors.
    """

    min_room_size: int = 6
    max_room_size: int = 15

    def generate(self) -> Dungeon:
        """
        Generate a complete dungeon using BSP.

        Returns:
            Dungeon object with rooms and corridors
        """
        dungeon = Dungeon(width=self.width, height=self.height)
        random.seed(self.seed)

        # Create BSP tree
        root = self._create_partition(0, 0, self.width, self.height)

        # Extract rooms from leaves
        rooms = self._extract_rooms(root)
        dungeon.rooms = rooms

        # Create tiles for rooms
        for room in rooms:
            for x in range(room.x, room.x + room.width):
                for y in range(room.y, room.y + room.height):
                    if (x, y) not in dungeon.tiles:
                        dungeon.tiles[(x, y)] = Tile(x=x, y=y, walkable=True)

        # Connect rooms with corridors
        corridors = self._connect_rooms(rooms, dungeon.tiles)
        dungeon.corridors = corridors

        # Place treasures and monsters
        self._place_encounters(rooms, dungeon.difficulty)

        return dungeon

    def _create_partition(self, x: int, y: int, width: int, height: int) -> dict:
        """Create a BSP node."""
        node = {
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "left": None,
            "right": None,
        }

        # Base case: room is small enough
        if width < self.min_room_size * 2 or height < self.min_room_size * 2:
            return node

        # Decide horizontal or vertical split
        if random.choice([True, False]):
            # Vertical split
            split_x = random.randint(x + self.min_room_size, x + width - self.min_room_size)
            node["left"] = self._create_partition(x, y, split_x - x, height)
            node["right"] = self._create_partition(split_x, y, x + width - split_x, height)
        else:
            # Horizontal split
            split_y = random.randint(y + self.min_room_size, y + height - self.min_room_size)
            node["left"] = self._create_partition(x, y, width, split_y - y)
            node["right"] = self._create_partition(x, split_y, width, y + height - split_y)

        return node

    def _extract_rooms(self, node: dict) -> list[Room]:
        """Extract rooms from BSP tree leaves."""
        if node["left"] is None and node["right"] is None:
            # Leaf node - create room
            max_width = min(self.max_room_size, max(self.min_room_size, node["width"] - 3))
            max_height = min(self.max_room_size, max(self.min_room_size, node["height"] - 3))

            if max_width < self.min_room_size or max_height < self.min_room_size:
                # Room too small, return empty
                return []

            room_width = random.randint(self.min_room_size, max_width)
            room_height = random.randint(self.min_room_size, max_height)

            room_x = random.randint(node["x"], max(node["x"], node["x"] + node["width"] - room_width - 1))
            room_y = random.randint(node["y"], max(node["y"], node["y"] + node["height"] - room_height - 1))

            return [Room(x=room_x, y=room_y, width=room_width, height=room_height)]

        rooms = []
        if node["left"]:
            rooms.extend(self._extract_rooms(node["left"]))
        if node["right"]:
            rooms.extend(self._extract_rooms(node["right"]))
        return rooms

    def _connect_rooms(self, rooms: list[Room], tiles: dict[tuple[int, int], Tile]) -> list[Corridor]:
        """Connect rooms with corridors."""
        corridors = []

        for i in range(len(rooms) - 1):
            start = rooms[i].center
            end = rooms[i + 1].center

            path = self._carve_path(tiles, start, end)
            corridor = Corridor(start=start, end=end, tiles=path)
            corridors.append(corridor)

        return corridors

    def _place_encounters(self, rooms: list[Room], difficulty: float) -> None:
        """Place treasures and monsters in rooms."""
        for room in rooms:
            room_size = room.area
            if room_size > 50:
                room.room_type = random.choice([RoomType.TREASURE, RoomType.BOSS, RoomType.GUARD])
                room.treasure_value = int(100 + room_size * (difficulty * 10))
                room.monster_count = int(1 + room_size / 30)


@dataclass
class CellularDungeonGenerator(DungeonGenerator):
    """
    Generate dungeons using cellular automata.

    Creates cave-like structures through birth/death rules.
    """

    wall_percentage: int = 45
    smooth_iterations: int = 3

    def generate(self) -> Dungeon:
        """
        Generate dungeon using cellular automata.

        Returns:
            Dungeon object
        """
        dungeon = Dungeon(width=self.width, height=self.height)
        random.seed(self.seed)

        # Initialize grid with random walls
        grid = self._create_random_grid()

        # Apply cellular automata rules
        for _ in range(self.smooth_iterations):
            grid = self._apply_cellular_rules(grid)

        # Extract walkable regions
        self._fill_tiles(grid, dungeon.tiles)

        # Find rooms in walkable regions
        rooms = self._find_rooms(grid)
        dungeon.rooms = rooms

        # Connect largest rooms
        if len(rooms) > 1:
            corridors = self._connect_largest_rooms(rooms, dungeon.tiles)
            dungeon.corridors = corridors

        return dungeon

    def _create_random_grid(self) -> list[list[int]]:
        """Create initial random grid (0=floor, 1=wall)."""
        grid = []
        for _ in range(self.height):
            row = []
            for _ in range(self.width):
                if random.randint(0, 100) < self.wall_percentage:
                    row.append(1)
                else:
                    row.append(0)
            grid.append(row)
        return grid

    def _apply_cellular_rules(self, grid: list[list[int]]) -> list[list[int]]:
        """Apply cellular automata rules for cave smoothing."""
        new_grid = [row[:] for row in grid]

        for y in range(1, self.height - 1):
            for x in range(1, self.width - 1):
                neighbors = self._count_wall_neighbors(grid, x, y)

                # Cellular cave rules
                if grid[y][x] == 1:  # Wall
                    if neighbors < 4:
                        new_grid[y][x] = 0  # Become floor
                else:  # Floor
                    if neighbors >= 5:
                        new_grid[y][x] = 1  # Become wall

        return new_grid

    def _count_wall_neighbors(self, grid: list[list[int]], x: int, y: int) -> int:
        """Count wall neighbors (including diagonals)."""
        count = 0
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                if dx == 0 and dy == 0:
                    continue
                nx, ny = x + dx, y + dy
                if 0 <= nx < self.width and 0 <= ny < self.height:
                    if grid[ny][nx] == 1:
                        count += 1
        return count

    def _fill_tiles(self, grid: list[list[int]], tiles: dict) -> None:
        """Convert grid to tiles."""
        for y in range(self.height):
            for x in range(self.width):
                walkable = grid[y][x] == 0
                tiles[(x, y)] = Tile(x=x, y=y, walkable=walkable)

    def _find_rooms(self, grid: list[list[int]]) -> list[Room]:
        """Find connected regions of floor tiles."""
        visited = set()
        rooms = []

        for y in range(self.height):
            for x in range(self.width):
                if (x, y) not in visited and grid[y][x] == 0:
                    region = self._flood_fill(grid, x, y, visited)
                    if len(region) > 20:  # Only consider large regions as rooms
                        min_x = min(coord[0] for coord in region)
                        max_x = max(coord[0] for coord in region)
                        min_y = min(coord[1] for coord in region)
                        max_y = max(coord[1] for coord in region)

                        room = Room(
                            x=min_x,
                            y=min_y,
                            width=max_x - min_x + 1,
                            height=max_y - min_y + 1,
                        )
                        rooms.append(room)

        return rooms

    def _flood_fill(self, grid: list[list[int]], start_x: int, start_y: int, visited: set) -> list[tuple[int, int]]:
        """Flood fill to find connected region."""
        region = []
        stack = [(start_x, start_y)]

        while stack:
            x, y = stack.pop()

            if (x, y) in visited:
                continue
            if x < 0 or x >= self.width or y < 0 or y >= self.height:
                continue
            if grid[y][x] != 0:
                continue

            visited.add((x, y))
            region.append((x, y))

            for dx, dy in [(0, 1), (1, 0), (0, -1), (-1, 0)]:
                stack.append((x + dx, y + dy))

        return region

    def _connect_largest_rooms(self, rooms: list[Room], tiles: dict[tuple[int, int], Tile]) -> list[Corridor]:
        """Connect the largest rooms with corridors."""
        if len(rooms) < 2:
            return []

        # Sort by area
        rooms.sort(key=lambda r: r.area, reverse=True)

        corridors = []
        for i in range(len(rooms) - 1):
            start = rooms[i].center
            end = rooms[i + 1].center

            path = self._carve_path(tiles, start, end)
            corridor = Corridor(start=start, end=end, tiles=path)
            corridors.append(corridor)

        return corridors
