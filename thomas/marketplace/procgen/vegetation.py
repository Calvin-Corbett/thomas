"""
Vegetation generation including L-systems, trees, and forests.
"""

import math
import random
from dataclasses import dataclass

from thomas.marketplace.procgen._exceptions import InvalidConfigError
from thomas.marketplace.procgen._types import LSystem, VegetationType


@dataclass
class TreeSpecification:
    """Specification for a tree type."""

    name: str
    lsystem: LSystem
    min_height: float
    max_height: float
    min_spread: float
    max_spread: float
    vegetation_type: VegetationType


@dataclass
class VegetationGenerator:
    """Generate vegetation including trees and forests."""

    width: int
    height: int
    seed: int = 42

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.width < 1 or self.height < 1:
            raise InvalidConfigError("Dimensions must be positive", "dimensions")
        random.seed(self.seed)

    def get_tree_specs(self) -> dict[str, TreeSpecification]:
        """
        Get standard tree type specifications.

        Returns:
            Dictionary of tree type names to TreeSpecification
        """
        return {
            "oak": TreeSpecification(
                name="Oak Tree",
                lsystem=LSystem(
                    axiom="A",
                    rules={
                        "A": "[&FL!A]/////'[&FL!A]///////'[&FL!A]",
                        "L": "['{f+f+f+f|f+f+f+f}]",
                    },
                    angle=20.0,
                    scale=0.95,
                    length=5.0,
                    iterations=4,
                    randomness=0.2,
                ),
                min_height=15.0,
                max_height=25.0,
                min_spread=8.0,
                max_spread=15.0,
                vegetation_type=VegetationType.OAK_TREE,
            ),
            "pine": TreeSpecification(
                name="Pine Tree",
                lsystem=LSystem(
                    axiom="I",
                    rules={
                        "I": "[+++Z][---Z]TS",
                        "Z": "[+LC][-LC]LZ",
                        "S": "FS",
                        "L": "[{f+f+f+f|f+f+f+f}]",
                        "C": "T",
                    },
                    angle=20.0,
                    scale=0.9,
                    length=4.0,
                    iterations=5,
                    randomness=0.1,
                ),
                min_height=10.0,
                max_height=20.0,
                min_spread=5.0,
                max_spread=10.0,
                vegetation_type=VegetationType.PINE_TREE,
            ),
            "palm": TreeSpecification(
                name="Palm Tree",
                lsystem=LSystem(
                    axiom="P",
                    rules={
                        "P": "F[+F][+F][+F][+F][+F]",
                        "F": "FF",
                    },
                    angle=72.0,
                    scale=0.85,
                    length=6.0,
                    iterations=3,
                    randomness=0.3,
                ),
                min_height=12.0,
                max_height=18.0,
                min_spread=3.0,
                max_spread=6.0,
                vegetation_type=VegetationType.PALM_TREE,
            ),
        }

    def place_forest(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        density: float = 0.3,
        tree_type: str = "oak",
    ) -> list[dict]:
        """
        Place trees in a forest area using Poisson disk sampling.

        Args:
            x: Top-left X coordinate
            y: Top-left Y coordinate
            width: Forest width
            height: Forest height
            density: Tree density [0, 1]
            tree_type: Type of tree to place

        Returns:
            List of tree placements {x, y, height, spread, type}
        """
        if not (0 < density <= 1):
            raise InvalidConfigError("Density must be in (0, 1]", "density")

        trees = []
        tree_specs = self.get_tree_specs()

        if tree_type not in tree_specs:
            raise InvalidConfigError(f"Unknown tree type: {tree_type}", "tree_type")

        spec = tree_specs[tree_type]

        # Poisson disk sampling for natural spacing
        min_distance = 1.0 / math.sqrt(density)
        cell_size = min_distance / math.sqrt(2)

        grid_width = int(width / cell_size) + 1
        grid_height = int(height / cell_size) + 1

        grid = [[None for _ in range(grid_width)] for _ in range(grid_height)]
        active = []

        # Place first point
        first_x = x + random.uniform(0, width)
        first_y = y + random.uniform(0, height)
        first_point = (first_x, first_y)
        active.append(first_point)
        trees.append(self._create_tree(first_point, spec))

        # Generate rest of points
        while active:
            idx = random.randint(0, len(active) - 1)
            point = active[idx]
            found = False

            for _ in range(30):  # Maximum attempts
                angle = random.uniform(0, 2 * math.pi)
                distance = random.uniform(min_distance, 2 * min_distance)

                new_x = point[0] + distance * math.cos(angle)
                new_y = point[1] + distance * math.sin(angle)

                if x <= new_x < x + width and y <= new_y < y + height:
                    grid_x = int(new_x / cell_size)
                    grid_y = int(new_y / cell_size)

                    valid = True
                    for dx in [-2, -1, 0, 1, 2]:
                        for dy in [-2, -1, 0, 1, 2]:
                            gx = grid_x + dx
                            gy = grid_y + dy

                            if 0 <= gx < grid_width and 0 <= gy < grid_height:
                                if grid[gy][gx] is not None:
                                    old_point = grid[gy][gx]
                                    dist = math.sqrt((new_x - old_point[0]) ** 2 + (new_y - old_point[1]) ** 2)
                                    if dist < min_distance:
                                        valid = False
                                        break

                    if valid:
                        new_point = (new_x, new_y)
                        grid[grid_y][grid_x] = new_point
                        active.append(new_point)
                        trees.append(self._create_tree(new_point, spec))
                        found = True
                        break

            if not found:
                active.pop(idx)

        return trees

    def _create_tree(self, position: tuple[float, float], spec: TreeSpecification) -> dict:
        """Create a tree at a position."""
        height = random.uniform(spec.min_height, spec.max_height)
        spread = random.uniform(spec.min_spread, spec.max_spread)

        return {
            "x": position[0],
            "y": position[1],
            "height": height,
            "spread": spread,
            "type": spec.vegetation_type.name,
            "spec_name": spec.name,
        }

    def simulate_growth(self, lsystem: LSystem, iterations: int = None) -> str:
        """
        Simulate L-system growth.

        Args:
            lsystem: L-System specification
            iterations: Number of iterations (uses lsystem.iterations if None)

        Returns:
            Final L-system string
        """
        return lsystem.apply(iterations)


@dataclass
class LSystemGenerator:
    """Generate structures using L-systems."""

    seed: int = 42

    def create_plant_lsystem(
        self,
        axiom: str,
        rules: dict[str, str],
        angle: float = 20.0,
        iterations: int = 4,
    ) -> LSystem:
        """
        Create an L-system for plant generation.

        Args:
            axiom: Initial string
            rules: Production rules
            angle: Turning angle
            iterations: Iterations to apply

        Returns:
            LSystem object
        """
        return LSystem(
            axiom=axiom,
            rules=rules,
            angle=angle,
            scale=0.9,
            length=1.0,
            iterations=iterations,
            randomness=0.1,
        )

    def generate_plant_string(self, lsystem: LSystem) -> str:
        """
        Generate plant structure string.

        Args:
            lsystem: L-System to apply

        Returns:
            Generated string
        """
        return lsystem.apply()

    def parse_turtle_graphics(self, command_string: str) -> list[tuple[str, ...]]:
        """
        Parse L-system output to turtle graphics commands.

        Args:
            command_string: L-system output string

        Returns:
            List of turtle commands
        """
        commands = []
        stack = []

        for char in command_string:
            if char == "F":
                commands.append(("forward", 1.0))
            elif char == "f":
                commands.append(("forward_no_draw", 1.0))
            elif char == "+":
                commands.append(("turn_left", 1.0))
            elif char == "-":
                commands.append(("turn_right", 1.0))
            elif char == "[":
                commands.append(("push_state", 1.0))
            elif char == "]":
                commands.append(("pop_state", 1.0))
            elif char == "&":
                commands.append(("pitch_down", 1.0))
            elif char == "^":
                commands.append(("pitch_up", 1.0))
            elif char == "\\":
                commands.append(("roll_left", 1.0))
            elif char == "/":
                commands.append(("roll_right", 1.0))
            elif char == "|":
                commands.append(("turn_around", 1.0))
            elif char == "{":
                commands.append(("start_polygon", 1.0))
            elif char == "}":
                commands.append(("end_polygon", 1.0))

        return commands

    def generate_ground_cover(self, x: int, y: int, width: int, height: int, coverage: float = 0.5) -> list[dict]:
        """
        Generate ground cover (grass, moss, etc.).

        Args:
            x: Top-left X
            y: Top-left Y
            width: Area width
            height: Area height
            coverage: Fraction of area covered [0, 1]

        Returns:
            List of ground cover placements
        """
        if not (0 <= coverage <= 1):
            raise InvalidConfigError("Coverage must be in [0, 1]", "coverage")

        cover = []
        num_patches = int(width * height * coverage / 20)

        for _ in range(num_patches):
            patch_x = x + random.uniform(0, width)
            patch_y = y + random.uniform(0, height)
            patch_size = random.uniform(1, 5)
            cover_type = random.choice(["grass", "moss", "fern"])

            cover.append(
                {
                    "x": patch_x,
                    "y": patch_y,
                    "size": patch_size,
                    "type": cover_type,
                }
            )

        return cover

    def apply_seasonal_variation(self, vegetation: list[dict], season: str = "summer") -> list[dict]:
        """
        Apply seasonal color/appearance changes.

        Args:
            vegetation: List of vegetation objects
            season: Season name (spring, summer, autumn, winter)

        Returns:
            Modified vegetation list
        """
        seasonal_tints = {
            "spring": (0.7, 1.0, 0.7),  # Light green
            "summer": (0.5, 0.9, 0.5),  # Dark green
            "autumn": (1.0, 0.7, 0.3),  # Orange/brown
            "winter": (0.8, 0.8, 0.8),  # Gray/white
        }

        tint = seasonal_tints.get(season, (0.5, 0.9, 0.5))

        for veg in vegetation:
            veg["seasonal_tint"] = tint
            veg["season"] = season

        return vegetation
