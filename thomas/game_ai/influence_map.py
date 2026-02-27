"""
Influence maps for spatial reasoning and heatmap-based AI decisions.

Supports grid-based influence propagation with multiple layers (threat, resources, etc),
diffusion with decay, and influence-based spatial queries.
"""

import math
from dataclasses import dataclass, field

from thomas.game_ai._types import InfluenceCell, Vec2


@dataclass
class InfluenceLayer:
    """A single layer of an influence map (e.g., threat, resource)."""

    name: str
    width: int
    height: int
    cell_size: float
    cells: dict[tuple[int, int], float] = field(default_factory=dict)
    decay_rate: float = 0.95  # How much influence decays per update

    def get_cell(self, x: int, y: int) -> float:
        """Get influence value at cell.

        Args:
            x: Grid X coordinate
            y: Grid Y coordinate

        Returns:
            Influence value (default 0.0)
        """
        return self.cells.get((x, y), 0.0)

    def set_cell(self, x: int, y: int, value: float) -> None:
        """Set influence value at cell.

        Args:
            x: Grid X coordinate
            y: Grid Y coordinate
            value: Influence value
        """
        if 0 <= x < self.width and 0 <= y < self.height:
            if value != 0.0:
                self.cells[(x, y)] = max(0.0, min(1.0, value))
            else:
                self.cells.pop((x, y), None)

    def add_cell(self, x: int, y: int, value: float) -> None:
        """Add to influence value at cell.

        Args:
            x: Grid X coordinate
            y: Grid Y coordinate
            value: Value to add
        """
        current = self.get_cell(x, y)
        self.set_cell(x, y, current + value)

    def world_to_grid(self, world_pos: Vec2) -> tuple[int, int]:
        """Convert world position to grid coordinates.

        Args:
            world_pos: Position in world space

        Returns:
            Tuple of (grid_x, grid_y)
        """
        x = int(world_pos.x / self.cell_size)
        y = int(world_pos.y / self.cell_size)
        return (x, y)

    def grid_to_world(self, x: int, y: int) -> Vec2:
        """Convert grid coordinates to world position.

        Args:
            x: Grid X coordinate
            y: Grid Y coordinate

        Returns:
            World position (center of cell)
        """
        return Vec2(
            x * self.cell_size + self.cell_size / 2,
            y * self.cell_size + self.cell_size / 2,
        )

    def get_world_influence(self, world_pos: Vec2) -> float:
        """Get influence at world position.

        Args:
            world_pos: Position in world space

        Returns:
            Influence value
        """
        x, y = self.world_to_grid(world_pos)
        return self.get_cell(x, y)

    def stamp_circular(self, center: Vec2, radius: float, intensity: float) -> None:
        """Add circular influence stamp.

        Args:
            center: Center of circle in world space
            radius: Radius of influence
            intensity: Intensity of stamp (0-1)
        """
        cx, cy = self.world_to_grid(center)
        radius_cells = radius / self.cell_size

        for x in range(int(cx - radius_cells), int(cx + radius_cells) + 1):
            for y in range(int(cy - radius_cells), int(cy + radius_cells) + 1):
                if 0 <= x < self.width and 0 <= y < self.height:
                    dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)

                    if dist <= radius_cells:
                        # Falloff from center
                        falloff = 1.0 - (dist / radius_cells)
                        influence = intensity * falloff
                        self.add_cell(x, y, influence)

    def propagate(self) -> None:
        """Propagate influence to neighboring cells with decay.

        Spreads influence to neighbors and applies decay.
        """
        new_cells: dict[tuple[int, int], float] = {}

        # Apply decay to existing cells
        for (x, y), value in self.cells.items():
            new_value = value * self.decay_rate
            if new_value > 0.01:
                new_cells[(x, y)] = new_value

        # Spread to neighbors
        for (x, y), value in self.cells.items():
            spread_amount = value * 0.25  # Share with neighbors
            neighbors = [
                (x - 1, y),
                (x + 1, y),
                (x, y - 1),
                (x, y + 1),
                (x - 1, y - 1),
                (x + 1, y - 1),
                (x - 1, y + 1),
                (x + 1, y + 1),
            ]

            for nx, ny in neighbors:
                if 0 <= nx < self.width and 0 <= ny < self.height:
                    key = (nx, ny)
                    current = new_cells.get(key, 0.0)
                    new_cells[key] = min(1.0, current + spread_amount)

        self.cells = new_cells

    def clear(self) -> None:
        """Clear all influence from this layer."""
        self.cells.clear()


class InfluenceMap:
    """Multi-layer influence map for spatial reasoning."""

    def __init__(self, width: float, height: float, cell_size: float = 1.0) -> None:
        """Initialize influence map.

        Args:
            width: World width
            height: World height
            cell_size: Size of each grid cell
        """
        self.world_width = width
        self.world_height = height
        self.cell_size = cell_size
        self.grid_width = int(math.ceil(width / cell_size))
        self.grid_height = int(math.ceil(height / cell_size))
        self.layers: dict[str, InfluenceLayer] = {}

    def create_layer(self, name: str, decay_rate: float = 0.95) -> InfluenceLayer:
        """Create a new influence layer.

        Args:
            name: Unique layer name
            decay_rate: How much influence decays per propagation

        Returns:
            InfluenceLayer object
        """
        layer = InfluenceLayer(
            name=name,
            width=self.grid_width,
            height=self.grid_height,
            cell_size=self.cell_size,
            decay_rate=decay_rate,
        )
        self.layers[name] = layer
        return layer

    def get_layer(self, name: str) -> InfluenceLayer | None:
        """Get layer by name.

        Args:
            name: Layer name

        Returns:
            InfluenceLayer or None if not found
        """
        return self.layers.get(name)

    def add_influence(self, layer_name: str, position: Vec2, radius: float, intensity: float) -> None:
        """Add influence to a layer at position.

        Args:
            layer_name: Target layer name
            position: World position
            radius: Radius of influence
            intensity: Intensity (0-1)
        """
        layer = self.get_layer(layer_name)
        if layer:
            layer.stamp_circular(position, radius, intensity)

    def get_influence(self, layer_name: str, position: Vec2) -> float:
        """Get influence value at position.

        Args:
            layer_name: Layer name
            position: World position

        Returns:
            Influence value
        """
        layer = self.get_layer(layer_name)
        if layer:
            return layer.get_world_influence(position)
        return 0.0

    def get_combined_influence(self, layer_names: list[str], position: Vec2, mode: str = "sum") -> float:
        """Get combined influence from multiple layers.

        Args:
            layer_names: List of layer names to combine
            position: World position
            mode: Combination mode ("sum", "max", "average")

        Returns:
            Combined influence value
        """
        values = []
        for name in layer_names:
            value = self.get_influence(name, position)
            values.append(value)

        if not values:
            return 0.0

        if mode == "sum":
            return min(1.0, sum(values))
        elif mode == "max":
            return max(values)
        elif mode == "average":
            return sum(values) / len(values)
        else:
            return 0.0

    def find_highest_influence_cell(self, layer_name: str) -> InfluenceCell | None:
        """Find cell with highest influence in layer.

        Args:
            layer_name: Layer name

        Returns:
            InfluenceCell with highest value, or None if layer empty
        """
        layer = self.get_layer(layer_name)
        if not layer or not layer.cells:
            return None

        max_key = max(layer.cells, key=layer.cells.get)
        x, y = max_key
        value = layer.cells[max_key]

        return InfluenceCell(x, y, value)

    def find_lowest_influence_cell(self, layer_name: str) -> InfluenceCell | None:
        """Find cell with lowest influence in layer.

        Args:
            layer_name: Layer name

        Returns:
            InfluenceCell with lowest value, or None if layer empty
        """
        layer = self.get_layer(layer_name)
        if not layer or not layer.cells:
            return None

        min_key = min(layer.cells, key=layer.cells.get)
        x, y = min_key
        value = layer.cells[min_key]

        return InfluenceCell(x, y, value)

    def find_highest_influence_position(self, layer_name: str) -> Vec2 | None:
        """Find world position with highest influence.

        Args:
            layer_name: Layer name

        Returns:
            World position with highest influence, or None
        """
        cell = self.find_highest_influence_cell(layer_name)
        if cell:
            layer = self.get_layer(layer_name)
            if layer:
                return cell.position(self.cell_size)
        return None

    def find_lowest_influence_position(self, layer_name: str) -> Vec2 | None:
        """Find world position with lowest influence.

        Args:
            layer_name: Layer name

        Returns:
            World position with lowest influence, or None
        """
        cell = self.find_lowest_influence_cell(layer_name)
        if cell:
            layer = self.get_layer(layer_name)
            if layer:
                return cell.position(self.cell_size)
        return None

    def propagate_layer(self, layer_name: str, iterations: int = 1) -> None:
        """Propagate influence in a layer.

        Args:
            layer_name: Layer name
            iterations: Number of propagation steps
        """
        layer = self.get_layer(layer_name)
        if layer:
            for _ in range(iterations):
                layer.propagate()

    def propagate_all(self, iterations: int = 1) -> None:
        """Propagate all layers.

        Args:
            iterations: Number of propagation steps per layer
        """
        for layer in self.layers.values():
            for _ in range(iterations):
                layer.propagate()

    def clear_layer(self, layer_name: str) -> None:
        """Clear a layer.

        Args:
            layer_name: Layer name
        """
        layer = self.get_layer(layer_name)
        if layer:
            layer.clear()

    def clear_all(self) -> None:
        """Clear all layers."""
        for layer in self.layers.values():
            layer.clear()

    def get_visualization_data(self, layer_name: str) -> dict[tuple[int, int], float]:
        """Get influence data for visualization.

        Args:
            layer_name: Layer name

        Returns:
            Dictionary of grid coordinates to influence values
        """
        layer = self.get_layer(layer_name)
        if layer:
            return dict(layer.cells)
        return {}
