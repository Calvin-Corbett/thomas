"""
Tests for dungeon generation.
"""

import pytest

from thomas.procgen._exceptions import InvalidConfigError
from thomas.procgen._types import Room, RoomType, Tile
from thomas.procgen.dungeons import (
    BSPDungeonGenerator,
    CellularDungeonGenerator,
    DungeonGenerator,
)


class TestDungeonGenerator:
    """Test base dungeon generator."""

    def test_dungeon_generator_initialization(self):
        """Test dungeon generator initializes."""
        gen = DungeonGenerator(width=128, height=128, seed=42)
        assert gen.width == 128
        assert gen.height == 128
        assert gen.seed == 42

    def test_dungeon_generator_invalid_dimensions(self):
        """Test dungeon generator rejects small dimensions."""
        with pytest.raises(InvalidConfigError):
            DungeonGenerator(width=5, height=5, seed=42)

    def test_carve_path(self):
        """Test path carving between points."""
        gen = DungeonGenerator(width=128, height=128, seed=42)
        tiles = {}
        start = (10, 10)
        end = (50, 50)

        path = gen._carve_path(tiles, start, end)

        assert isinstance(path, list)
        assert len(path) > 0
        # Path should have tiles created
        assert len(tiles) > 0
        # Path should end near the target
        assert path[-1] == end


class TestBSPDungeonGenerator:
    """Test BSP dungeon generation."""

    def test_bsp_generator_initialization(self):
        """Test BSP generator initializes."""
        gen = BSPDungeonGenerator(width=256, height=256, min_room_size=6, max_room_size=15)
        assert gen.width == 256
        assert gen.height == 256

    def test_bsp_generate_returns_dungeon(self):
        """Test BSP generation returns a dungeon."""
        gen = BSPDungeonGenerator(width=128, height=128, seed=42)
        dungeon = gen.generate()

        assert dungeon is not None
        assert dungeon.width == 128
        assert dungeon.height == 128
        assert hasattr(dungeon, "rooms")
        assert hasattr(dungeon, "corridors")
        assert hasattr(dungeon, "tiles")

    def test_bsp_generate_has_rooms(self):
        """Test BSP generation creates rooms."""
        gen = BSPDungeonGenerator(width=128, height=128, seed=42)
        dungeon = gen.generate()

        assert len(dungeon.rooms) > 0
        for room in dungeon.rooms:
            assert isinstance(room, Room)
            assert room.width > 0
            assert room.height > 0

    def test_bsp_generate_has_corridors(self):
        """Test BSP generation creates corridors."""
        gen = BSPDungeonGenerator(width=128, height=128, seed=42)
        dungeon = gen.generate()

        if len(dungeon.rooms) > 1:
            assert len(dungeon.corridors) > 0

    def test_bsp_generate_has_tiles(self):
        """Test BSP generation creates tiles."""
        gen = BSPDungeonGenerator(width=64, height=64, seed=42)
        dungeon = gen.generate()

        assert len(dungeon.tiles) > 0
        for coord, tile in dungeon.tiles.items():
            assert isinstance(coord, tuple)
            assert isinstance(tile, Tile)

    def test_bsp_create_partition(self):
        """Test partition tree creation."""
        gen = BSPDungeonGenerator(width=128, height=128, seed=42)
        partition = gen._create_partition(0, 0, 128, 128)

        assert partition is not None
        assert "x" in partition
        assert "y" in partition
        assert "width" in partition
        assert "height" in partition

    def test_bsp_extract_rooms(self):
        """Test room extraction from partition."""
        gen = BSPDungeonGenerator(width=128, height=128, seed=42)
        partition = gen._create_partition(0, 0, 128, 128)
        rooms = gen._extract_rooms(partition)

        assert len(rooms) > 0
        for room in rooms:
            assert isinstance(room, Room)


class TestCellularDungeonGenerator:
    """Test cellular automata dungeon generation."""

    def test_cellular_generator_initialization(self):
        """Test cellular generator initializes."""
        gen = CellularDungeonGenerator(width=128, height=128, wall_percentage=45, smooth_iterations=3)
        assert gen.width == 128
        assert gen.height == 128

    def test_cellular_generate_returns_dungeon(self):
        """Test cellular generation returns a dungeon."""
        gen = CellularDungeonGenerator(width=128, height=128, seed=42)
        dungeon = gen.generate()

        assert dungeon is not None
        assert dungeon.width == 128
        assert dungeon.height == 128
        assert hasattr(dungeon, "tiles")

    def test_cellular_generate_has_tiles(self):
        """Test cellular generation creates tiles."""
        gen = CellularDungeonGenerator(width=64, height=64, seed=42)
        dungeon = gen.generate()

        assert len(dungeon.tiles) > 0
        for coord, tile in dungeon.tiles.items():
            assert isinstance(coord, tuple)
            assert isinstance(tile, Tile)

    def test_cellular_create_random_grid(self):
        """Test random grid creation."""
        gen = CellularDungeonGenerator(width=64, height=64, seed=42)
        grid = gen._create_random_grid()

        assert len(grid) == 64
        assert all(len(row) == 64 for row in grid)
        assert all(cell in [0, 1] for row in grid for cell in row)

    def test_cellular_apply_cellular_rules(self):
        """Test cellular automata rules application."""
        gen = CellularDungeonGenerator(width=32, height=32, seed=42)
        grid = gen._create_random_grid()
        new_grid = gen._apply_cellular_rules(grid)

        assert len(new_grid) == 32
        assert all(len(row) == 32 for row in new_grid)

    def test_cellular_count_wall_neighbors(self):
        """Test wall neighbor counting."""
        gen = CellularDungeonGenerator(width=32, height=32, seed=42)
        grid = [[1, 1, 1], [1, 0, 1], [1, 1, 1]]

        # Center cell has 8 neighbors, all walls
        count = gen._count_wall_neighbors(grid, 1, 1)
        assert count == 8

    def test_cellular_flood_fill(self):
        """Test flood fill for connected regions."""
        gen = CellularDungeonGenerator(width=32, height=32, seed=42)
        grid = [[0 for _ in range(32)] for _ in range(32)]
        visited = set()

        region = gen._flood_fill(grid, 5, 5, visited)

        assert len(region) > 0
        assert (5, 5) in region

    def test_cellular_find_rooms(self):
        """Test room finding in grid."""
        gen = CellularDungeonGenerator(width=64, height=64, seed=42)
        grid = gen._create_random_grid()
        # Apply smoothing to create cave-like structures
        for _ in range(3):
            grid = gen._apply_cellular_rules(grid)

        rooms = gen._find_rooms(grid)

        # Should find some rooms
        assert isinstance(rooms, list)
        for room in rooms:
            assert isinstance(room, Room)


class TestRoomAndCorridor:
    """Test room and corridor types."""

    def test_room_creation(self):
        """Test room creation."""
        room = Room(x=10, y=10, width=20, height=20)
        assert room.x == 10
        assert room.y == 10
        assert room.width == 20
        assert room.height == 20

    def test_room_center(self):
        """Test room center calculation."""
        room = Room(x=10, y=10, width=20, height=20)
        center = room.center
        assert center == (20, 20)

    def test_room_area(self):
        """Test room area calculation."""
        room = Room(x=10, y=10, width=20, height=30)
        assert room.area == 600

    def test_room_types(self):
        """Test different room types."""
        for room_type in [RoomType.GENERIC, RoomType.TREASURE, RoomType.BOSS]:
            room = Room(x=0, y=0, width=10, height=10, room_type=room_type)
            assert room.room_type == room_type
