"""
Squad and group AI for formation-based movement and tactics.

Supports formations (line, wedge, circle), formation maintenance,
squad tactics (advance, retreat, flank), and communication.
"""

import math
from dataclasses import dataclass
from enum import Enum

from thomas.game_ai._types import GameEntity, Vec2


class FormationType(Enum):
    """Types of squad formations."""

    LINE = "line"
    WEDGE = "wedge"
    CIRCLE = "circle"
    COLUMN = "column"


@dataclass
class FormationSlot:
    """A position in a formation."""

    entity_id: int
    offset: Vec2
    entity: GameEntity | None = None

    def get_target_position(self, formation_center: Vec2) -> Vec2:
        """Get target world position for this slot.

        Args:
            formation_center: Center of formation

        Returns:
            Target world position
        """
        return formation_center + self.offset


class Formation:
    """Base class for squad formations."""

    def __init__(self, formation_type: FormationType, spacing: float = 2.0) -> None:
        """Initialize formation.

        Args:
            formation_type: Type of formation
            spacing: Space between members
        """
        self.type = formation_type
        self.spacing = spacing
        self.slots: list[FormationSlot] = []

    def get_slot_offset(self, index: int, total_members: int) -> Vec2:
        """Get position offset for slot in formation.

        Args:
            index: Member index
            total_members: Total number of members

        Returns:
            Position offset from formation center
        """
        if self.type == FormationType.LINE:
            return self._get_line_offset(index, total_members)
        elif self.type == FormationType.WEDGE:
            return self._get_wedge_offset(index, total_members)
        elif self.type == FormationType.CIRCLE:
            return self._get_circle_offset(index, total_members)
        elif self.type == FormationType.COLUMN:
            return self._get_column_offset(index, total_members)
        else:
            return Vec2(0, 0)

    def _get_line_offset(self, index: int, total: int) -> Vec2:
        """Line formation: spread horizontally."""
        offset_x = (index - total / 2) * self.spacing
        return Vec2(offset_x, 0)

    def _get_wedge_offset(self, index: int, total: int) -> Vec2:
        """Wedge formation: triangular arrangement."""
        if index == 0:
            return Vec2(0, 0)  # Leader at front

        row = int(math.sqrt(index))
        col = index - row * row - 1

        offset_x = (col - row / 2) * self.spacing
        offset_y = row * self.spacing

        return Vec2(offset_x, offset_y)

    def _get_circle_offset(self, index: int, total: int) -> Vec2:
        """Circle formation: arranged in circle."""
        if index == 0:
            return Vec2(0, 0)

        angle = (index / total) * 2 * math.pi
        radius = (total / 4) * self.spacing

        return Vec2(
            radius * math.cos(angle),
            radius * math.sin(angle),
        )

    def _get_column_offset(self, index: int, total: int) -> Vec2:
        """Column formation: single-file line."""
        offset_y = index * self.spacing
        return Vec2(0, offset_y)


class Squadron:
    """Squad of units with formation and tactics."""

    def __init__(self, leader_id: int, formation: Formation) -> None:
        """Initialize squadron.

        Args:
            leader_id: ID of squad leader
            formation: Formation for squad
        """
        self.leader_id = leader_id
        self.formation = formation
        self.members: dict[int, GameEntity] = {}
        self.formation_center = Vec2(0, 0)
        self.formation_heading = Vec2(1, 0)
        self.is_holding_formation = True

    def add_member(self, entity: GameEntity) -> None:
        """Add member to squad.

        Args:
            entity: Entity to add
        """
        self.members[entity.id] = entity
        self._rebuild_formation()

    def remove_member(self, entity_id: int) -> None:
        """Remove member from squad.

        Args:
            entity_id: ID of entity to remove
        """
        if entity_id in self.members:
            del self.members[entity_id]
            self._rebuild_formation()

    def set_formation(self, formation: Formation) -> None:
        """Change formation.

        Args:
            formation: New formation
        """
        self.formation = formation
        self._rebuild_formation()

    def set_formation_center(self, center: Vec2) -> None:
        """Set new formation center (move formation).

        Args:
            center: New center position
        """
        self.formation_center = center

    def set_formation_heading(self, heading: Vec2) -> None:
        """Set formation heading direction.

        Args:
            heading: New heading direction
        """
        if heading.magnitude() > 0:
            self.formation_heading = heading.normalize()

    def get_target_position(self, entity_id: int) -> Vec2 | None:
        """Get target position for squad member in formation.

        Args:
            entity_id: ID of entity

        Returns:
            Target world position, or None if entity not in squad
        """
        if entity_id not in self.members:
            return None

        # Find entity's index
        index = list(self.members.keys()).index(entity_id)
        offset = self.formation.get_slot_offset(index, len(self.members))

        # Rotate offset by formation heading
        angle = math.atan2(self.formation_heading.y, self.formation_heading.x)
        rotated_offset = offset.rotate(angle)

        return self.formation_center + rotated_offset

    def update_formation(self, delta_time: float = 0.016) -> None:
        """Update formation (maintain positions).

        Args:
            delta_time: Time since last update
        """
        if not self.is_holding_formation:
            return

        for entity_id, entity in self.members.items():
            target = self.get_target_position(entity_id)
            if target:
                # Move toward target position
                direction = target - entity.position
                distance = direction.magnitude()

                if distance > 0.1:
                    desired_velocity = direction.normalize() * 5.0  # Movement speed
                    # Smooth approach
                    entity.velocity = entity.velocity.lerp(desired_velocity, 0.1)

        # Update formation center based on leader
        leader = self.members.get(self.leader_id)
        if leader:
            self.formation_center = leader.position

    def execute_tactic(self, tactic: str, target: Vec2, delta_time: float = 0.016) -> None:
        """Execute a squad tactic.

        Args:
            tactic: Tactic name ("advance", "retreat", "flank", "surround")
            target: Target position or enemy
            delta_time: Time since last update
        """
        if tactic == "advance":
            self._execute_advance(target, delta_time)
        elif tactic == "retreat":
            self._execute_retreat(target, delta_time)
        elif tactic == "flank":
            self._execute_flank(target, delta_time)
        elif tactic == "surround":
            self._execute_surround(target, delta_time)

    def _execute_advance(self, target: Vec2, delta_time: float) -> None:
        """Execute advance tactic - move toward target."""
        self.set_formation_center(
            self.formation_center + (target - self.formation_center).normalize() * 5.0 * delta_time
        )

    def _execute_retreat(self, target: Vec2, delta_time: float) -> None:
        """Execute retreat tactic - move away from target."""
        direction = self.formation_center - target
        if direction.magnitude() > 0:
            self.set_formation_center(self.formation_center + direction.normalize() * 5.0 * delta_time)

    def _execute_flank(self, target: Vec2, delta_time: float) -> None:
        """Execute flank tactic - move to side of target."""
        direction = target - self.formation_center
        if direction.magnitude() > 0:
            # Move perpendicular to enemy
            perpendicular = Vec2(-direction.y, direction.x).normalize()
            self.set_formation_center(self.formation_center + perpendicular * 5.0 * delta_time)

    def _execute_surround(self, target: Vec2, delta_time: float) -> None:
        """Execute surround tactic - spread around target."""
        # Spread formation wider
        self.formation.spacing *= 1.01  # Gradually increase spacing

    def broadcast_order(self, order: str, payload: dict | None = None) -> None:
        """Broadcast order to all squad members.

        Args:
            order: Order type
            payload: Optional order payload
        """
        # Would send to squad members' decision systems
        pass

    def get_formation_bounds(self) -> tuple[Vec2, Vec2]:
        """Get bounding box of formation.

        Returns:
            Tuple of (min_pos, max_pos)
        """
        if not self.members:
            return self.formation_center, self.formation_center

        positions = []
        for entity_id in self.members.keys():
            target = self.get_target_position(entity_id)
            if target:
                positions.append(target)

        if not positions:
            return self.formation_center, self.formation_center

        min_x = min(p.x for p in positions)
        min_y = min(p.y for p in positions)
        max_x = max(p.x for p in positions)
        max_y = max(p.y for p in positions)

        return Vec2(min_x, min_y), Vec2(max_x, max_y)

    def _rebuild_formation(self) -> None:
        """Rebuild formation slots."""
        self.formation.slots.clear()

        for i, entity_id in enumerate(self.members.keys()):
            offset = self.formation.get_slot_offset(i, len(self.members))
            slot = FormationSlot(entity_id, offset, self.members[entity_id])
            self.formation.slots.append(slot)

    def get_member_count(self) -> int:
        """Get number of squad members.

        Returns:
            Member count
        """
        return len(self.members)

    def get_average_position(self) -> Vec2:
        """Get average position of squad.

        Returns:
            Average world position
        """
        if not self.members:
            return self.formation_center

        avg_x = sum(e.position.x for e in self.members.values()) / len(self.members)
        avg_y = sum(e.position.y for e in self.members.values()) / len(self.members)

        return Vec2(avg_x, avg_y)

    def get_cohesion(self) -> float:
        """Get squad cohesion (how tightly grouped).

        Returns:
            Cohesion value 0-1 (1 is perfectly grouped)
        """
        if len(self.members) <= 1:
            return 1.0

        avg_pos = self.get_average_position()
        total_distance = sum(e.position.distance_to(avg_pos) for e in self.members.values())
        avg_distance = total_distance / len(self.members)

        # Simple heuristic: cohesion decreases with distance
        max_distance = self.formation.spacing * len(self.members)
        return max(0.0, 1.0 - (avg_distance / max_distance))
