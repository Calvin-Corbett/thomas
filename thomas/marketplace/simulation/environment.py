"""
Simulation environment with grid world, diffusion, and spatial properties.

Implements 2D grid-based and continuous environments with resource
mechanics, terrain types, and dynamic processes.
"""

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ._exceptions import EnvironmentError
from ._types import EnvironmentCell


class TerrainType(str, Enum):
    """Terrain types in environment."""

    EMPTY = "empty"
    GRASS = "grass"
    WATER = "water"
    MOUNTAIN = "mountain"
    FOREST = "forest"
    URBAN = "urban"


class ResourceType(str, Enum):
    """Resource types."""

    FOOD = "food"
    WATER = "water"
    ENERGY = "energy"
    MATERIAL = "material"


@dataclass
class ResourcePatch:
    """
    Resource patch in environment.

    Attributes:
        resource_id: Unique identifier
        resource_type: Type of resource
        center: (x, y) center position
        amount: Current amount
        capacity: Maximum capacity
        regeneration_rate: Rate per time unit
        depletion_rate: Rate per time unit
        active: Whether patch exists
    """

    resource_id: str
    resource_type: ResourceType
    center: tuple[float, float]
    amount: float = 100.0
    capacity: float = 100.0
    regeneration_rate: float = 0.1
    depletion_rate: float = 0.0
    active: bool = True


class GridEnvironment:
    """
    2D grid-based environment.

    Each cell can contain terrain, resources, agents, and values for diffusion.
    """

    def __init__(self, width: int, height: int, cell_size: float = 1.0) -> None:
        """
        Initialize grid environment.

        Args:
            width: Grid width in cells
            height: Grid height in cells
            cell_size: Physical size of each cell
        """
        self.width = width
        self.height = height
        self.cell_size = cell_size

        # Grid cells
        self.grid: dict[tuple[int, int], EnvironmentCell] = {}
        self._initialize_grid()

        # Resources
        self.resource_patches: dict[str, ResourcePatch] = {}

        # Diffusion state
        self.diffusion_values: dict[str, list[list[float]]] = {}

    def _initialize_grid(self) -> None:
        """Initialize all grid cells."""
        for x in range(self.width):
            for y in range(self.height):
                self.grid[(x, y)] = EnvironmentCell(
                    x=x,
                    y=y,
                    cell_type=TerrainType.EMPTY.value,
                    properties={},
                    agents=[],
                    value=0.0,
                )

    def set_terrain(self, x: int, y: int, terrain_type: TerrainType, properties: dict[str, Any] | None = None) -> None:
        """Set terrain type at cell."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise EnvironmentError(f"Position ({x}, {y}) out of bounds")

        cell = self.grid[(x, y)]
        cell.cell_type = terrain_type.value
        if properties:
            cell.properties.update(properties)

    def get_terrain(self, x: int, y: int) -> EnvironmentCell | None:
        """Get cell at position."""
        return self.grid.get((x, y))

    def set_cell_value(self, x: int, y: int, value: float) -> None:
        """Set scalar value in cell."""
        if (x, y) in self.grid:
            self.grid[(x, y)].value = value

    def get_cell_value(self, x: int, y: int) -> float:
        """Get scalar value from cell."""
        cell = self.grid.get((x, y))
        return cell.value if cell else 0.0

    def add_agent_to_cell(self, x: int, y: int, agent_id: int) -> bool:
        """Add agent ID to cell."""
        if (x, y) not in self.grid:
            return False

        cell = self.grid[(x, y)]
        if agent_id not in cell.agents:
            cell.agents.append(agent_id)
        return True

    def remove_agent_from_cell(self, x: int, y: int, agent_id: int) -> bool:
        """Remove agent ID from cell."""
        if (x, y) not in self.grid:
            return False

        cell = self.grid[(x, y)]
        if agent_id in cell.agents:
            cell.agents.remove(agent_id)
            return True
        return False

    def get_agents_in_cell(self, x: int, y: int) -> list[int]:
        """Get agent IDs in cell."""
        cell = self.grid.get((x, y))
        return cell.agents if cell else []

    def add_resource_patch(self, patch: ResourcePatch) -> None:
        """Add resource patch to environment."""
        self.resource_patches[patch.resource_id] = patch

    def update_resources(self, time_delta: float) -> None:
        """Update resource amounts (regeneration/depletion)."""
        for patch in self.resource_patches.values():
            if not patch.active:
                continue

            # Regeneration
            patch.amount += patch.regeneration_rate * time_delta

            # Depletion
            patch.amount -= patch.depletion_rate * time_delta

            # Clamp to capacity
            patch.amount = max(0, min(patch.amount, patch.capacity))

            # Deactivate if empty
            if patch.amount <= 0:
                patch.active = False

    def extract_resource(self, resource_id: str, amount: float) -> float:
        """
        Extract resource from patch.

        Args:
            resource_id: Resource patch ID
            amount: Amount to extract

        Returns:
            Actual amount extracted
        """
        if resource_id not in self.resource_patches:
            return 0.0

        patch = self.resource_patches[resource_id]
        extracted = min(amount, patch.amount)
        patch.amount -= extracted

        return extracted

    def diffuse(self, field_name: str, rate: float = 0.1, iterations: int = 1) -> None:
        """
        Apply diffusion to scalar field.

        Spreads values from high-density to low-density cells.

        Args:
            field_name: Name of field to diffuse
            rate: Diffusion rate (0 = no diffusion, 1 = complete mixing)
            iterations: Number of diffusion steps per call
        """
        if field_name not in self.diffusion_values:
            self.diffusion_values[field_name] = [[0.0 for _ in range(self.height)] for _ in range(self.width)]

            # Initialize from grid values
            for x in range(self.width):
                for y in range(self.height):
                    cell = self.grid.get((x, y))
                    if cell:
                        self.diffusion_values[field_name][x][y] = cell.value

        field = self.diffusion_values[field_name]

        for _ in range(iterations):
            new_field = [row[:] for row in field]

            for x in range(self.width):
                for y in range(self.height):
                    center = field[x][y]
                    neighbors = []

                    for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < self.width and 0 <= ny < self.height:
                            neighbors.append(field[nx][ny])

                    if neighbors:
                        avg_neighbor = sum(neighbors) / len(neighbors)
                        new_field[x][y] = center * (1 - rate) + avg_neighbor * rate

            field = new_field

        self.diffusion_values[field_name] = field

        # Update grid values
        for x in range(self.width):
            for y in range(self.height):
                self.set_cell_value(x, y, field[x][y])

    def get_neighborhood(self, x: int, y: int, radius: int = 1, include_center: bool = False) -> list[tuple[int, int]]:
        """
        Get cells in neighborhood (Moore or Von Neumann).

        Args:
            x: Center x
            y: Center y
            radius: Neighborhood radius
            include_center: Include center cell

        Returns:
            List of (x, y) coordinates
        """
        cells = []

        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if not include_center and dx == 0 and dy == 0:
                    continue

                nx, ny = x + dx, y + dy

                if 0 <= nx < self.width and 0 <= ny < self.height:
                    cells.append((nx, ny))

        return cells


class ContinuousEnvironment:
    """
    Continuous 2D environment.

    Supports arbitrary positions, distance-based queries, and resource regions.
    """

    def __init__(
        self,
        x_bounds: tuple[float, float],
        y_bounds: tuple[float, float],
        wraparound: bool = False,
    ) -> None:
        """
        Initialize continuous environment.

        Args:
            x_bounds: (min_x, max_x)
            y_bounds: (min_y, max_y)
            wraparound: Toroidal topology
        """
        self.x_min, self.x_max = x_bounds
        self.y_min, self.y_max = y_bounds
        self.wraparound = wraparound

        self.width = self.x_max - self.x_min
        self.height = self.y_max - self.y_min

        # Spatial index (grid cells for fast queries)
        self.cell_size = 10.0
        self.spatial_index: dict[tuple[int, int], list[int]] = {}
        self.agent_positions: dict[int, tuple[float, float]] = {}

        # Resources
        self.resource_patches: dict[str, ResourcePatch] = {}

    def add_agent(self, agent_id: int, position: tuple[float, float]) -> None:
        """Add agent at position."""
        if not self._is_valid(position):
            raise EnvironmentError(f"Invalid position: {position}")

        self.agent_positions[agent_id] = position
        cell_key = self._get_cell_key(position)

        if cell_key not in self.spatial_index:
            self.spatial_index[cell_key] = []

        self.spatial_index[cell_key].append(agent_id)

    def move_agent(self, agent_id: int, new_position: tuple[float, float]) -> bool:
        """Move agent to new position."""
        if not self._is_valid(new_position):
            return False

        if agent_id not in self.agent_positions:
            return False

        old_position = self.agent_positions[agent_id]
        old_cell = self._get_cell_key(old_position)
        new_cell = self._get_cell_key(new_position)

        # Update spatial index
        if old_cell in self.spatial_index and agent_id in self.spatial_index[old_cell]:
            self.spatial_index[old_cell].remove(agent_id)

        if new_cell not in self.spatial_index:
            self.spatial_index[new_cell] = []

        self.spatial_index[new_cell].append(agent_id)

        # Update position
        self.agent_positions[agent_id] = new_position
        return True

    def remove_agent(self, agent_id: int) -> None:
        """Remove agent from environment."""
        if agent_id in self.agent_positions:
            position = self.agent_positions[agent_id]
            cell_key = self._get_cell_key(position)

            if cell_key in self.spatial_index:
                self.spatial_index[cell_key].remove(agent_id)

            del self.agent_positions[agent_id]

    def agents_in_radius(self, position: tuple[float, float], radius: float) -> list[int]:
        """Get agent IDs within radius of position."""
        result = []

        for agent_id, agent_pos in self.agent_positions.items():
            if self.distance(position, agent_pos) <= radius:
                result.append(agent_id)

        return result

    def distance(self, pos1: tuple[float, float], pos2: tuple[float, float]) -> float:
        """Compute distance between positions."""
        x1, y1 = pos1
        x2, y2 = pos2

        if self.wraparound:
            dx = min(abs(x1 - x2), self.width - abs(x1 - x2))
            dy = min(abs(y1 - y2), self.height - abs(y1 - y2))
        else:
            dx = abs(x1 - x2)
            dy = abs(y1 - y2)

        return math.sqrt(dx**2 + dy**2)

    def add_resource_patch(self, patch: ResourcePatch) -> None:
        """Add resource patch."""
        self.resource_patches[patch.resource_id] = patch

    def update_resources(self, time_delta: float) -> None:
        """Update resource amounts."""
        for patch in self.resource_patches.values():
            if not patch.active:
                continue

            patch.amount += patch.regeneration_rate * time_delta
            patch.amount -= patch.depletion_rate * time_delta
            patch.amount = max(0, min(patch.amount, patch.capacity))

            if patch.amount <= 0:
                patch.active = False

    def extract_resource(self, resource_id: str, amount: float) -> float:
        """Extract resource from patch."""
        if resource_id not in self.resource_patches:
            return 0.0

        patch = self.resource_patches[resource_id]
        extracted = min(amount, patch.amount)
        patch.amount -= extracted

        return extracted

    def _is_valid(self, position: tuple[float, float]) -> bool:
        """Check if position is within bounds."""
        x, y = position

        if self.wraparound:
            return True

        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max

    def _get_cell_key(self, position: tuple[float, float]) -> tuple[int, int]:
        """Get spatial index cell key for position."""
        x, y = position
        cell_x = int((x - self.x_min) / self.cell_size)
        cell_y = int((y - self.y_min) / self.cell_size)

        return (cell_x, cell_y)
