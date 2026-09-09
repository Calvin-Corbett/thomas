"""HD map management for autonomous vehicles.

Includes road network graph, lane geometry, traffic sign/signal database,
speed limit zones, routing, and map tile management.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from thomas.autonomous_vehicles._types import (
    Lane,
    TrafficLight,
    TrafficLightState,
    TrafficSign,
    TrafficSignType,
    Vector2D,
)


@dataclass
class RoadSegment:
    """Road segment connecting two intersections."""

    segment_id: str
    start_intersection_id: str
    end_intersection_id: str
    lanes: list[Lane]
    speed_limit: float  # m/s
    road_type: str = "driving"  # driving, highway, residential
    length: float = 0.0

    def __post_init__(self: RoadSegment) -> None:
        """Compute segment length if not provided."""
        if self.length == 0.0 and len(self.lanes) > 0:
            self.length = self.lanes[0].length()


@dataclass
class Intersection:
    """Intersection node in road network."""

    intersection_id: str
    position: Vector2D
    incoming_segments: list[str] = field(default_factory=list)
    outgoing_segments: list[str] = field(default_factory=list)
    traffic_lights: list[TrafficLight] = field(default_factory=list)
    turn_restrictions: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class SpeedLimitZone:
    """Speed limit zone."""

    zone_id: str
    polygon_vertices: list[Vector2D]
    speed_limit: float  # m/s
    zone_type: str = "school"  # school, residential, construction, etc.

    def contains_point(self: SpeedLimitZone, point: Vector2D) -> bool:
        """Check if point is in zone using ray casting.

        Args:
            point: Point to check

        Returns:
            True if point is in zone
        """
        n = len(self.polygon_vertices)
        inside = False

        j = n - 1
        for i in range(n):
            xi, yi = self.polygon_vertices[i].x, self.polygon_vertices[i].y
            xj, yj = self.polygon_vertices[j].x, self.polygon_vertices[j].y

            if (yi > point.y) != (yj > point.y) and point.x < (xj - xi) * (point.y - yi) / (yj - yi) + xi:
                inside = not inside

            j = i

        return inside


@dataclass
class MapTile:
    """HD map tile (local region)."""

    tile_id: str
    tile_x: int
    tile_y: int
    tile_size: float  # Size in meters
    origin: Vector2D
    segments: list[RoadSegment] = field(default_factory=list)
    intersections: list[Intersection] = field(default_factory=list)
    traffic_signs: list[TrafficSign] = field(default_factory=list)
    traffic_lights: list[TrafficLight] = field(default_factory=list)

    def get_bounds(self: MapTile) -> tuple[float, float, float, float]:
        """Get tile bounds (min_x, min_y, max_x, max_y)."""
        min_x = self.origin.x
        min_y = self.origin.y
        max_x = self.origin.x + self.tile_size
        max_y = self.origin.y + self.tile_size
        return (min_x, min_y, max_x, max_y)

    def contains_point(self: MapTile, point: Vector2D) -> bool:
        """Check if point is in tile."""
        min_x, min_y, max_x, max_y = self.get_bounds()
        return min_x <= point.x <= max_x and min_y <= point.y <= max_y


class RoadNetwork:
    """Road network graph."""

    def __init__(self: RoadNetwork) -> None:
        """Initialize road network."""
        self.intersections: dict[str, Intersection] = {}
        self.segments: dict[str, RoadSegment] = {}
        self.adjacency: dict[str, list[str]] = {}

    def add_intersection(self: RoadNetwork, intersection: Intersection) -> None:
        """Add intersection to network.

        Args:
            intersection: Intersection to add
        """
        self.intersections[intersection.intersection_id] = intersection

    def add_segment(self: RoadNetwork, segment: RoadSegment) -> None:
        """Add road segment to network.

        Args:
            segment: Road segment to add
        """
        self.segments[segment.segment_id] = segment

        # Update adjacency
        start_id = segment.start_intersection_id
        if start_id not in self.adjacency:
            self.adjacency[start_id] = []

        self.adjacency[start_id].append(segment.segment_id)

        # Update intersections
        if start_id in self.intersections:
            self.intersections[start_id].outgoing_segments.append(segment.segment_id)

        end_id = segment.end_intersection_id
        if end_id in self.intersections:
            self.intersections[end_id].incoming_segments.append(segment.segment_id)

    def get_adjacent_segments(self: RoadNetwork, intersection_id: str) -> list[RoadSegment]:
        """Get segments connected to intersection.

        Args:
            intersection_id: Intersection ID

        Returns:
            List of adjacent segments
        """
        segment_ids = self.adjacency.get(intersection_id, [])
        return [self.segments[sid] for sid in segment_ids if sid in self.segments]

    def shortest_path(self: RoadNetwork, start_id: str, end_id: str) -> list[str] | None:
        """Find shortest path using Dijkstra.

        Args:
            start_id: Start intersection ID
            end_id: End intersection ID

        Returns:
            List of segment IDs forming path, or None
        """
        if start_id not in self.intersections or end_id not in self.intersections:
            return None

        import heapq

        distances: dict[str, float] = {node: float("inf") for node in self.intersections}
        distances[start_id] = 0.0
        previous: dict[str, str | None] = {node: None for node in self.intersections}

        pq = [(0.0, start_id)]
        visited: set[str] = set()

        while pq:
            current_dist, current = heapq.heappop(pq)

            if current in visited:
                continue

            visited.add(current)

            if current == end_id:
                # Reconstruct path
                path = []
                node = current
                while previous[node] is not None:
                    prev_node = previous[node]
                    # Find segment connecting prev_node to node
                    for seg_id in self.adjacency.get(prev_node, []):
                        seg = self.segments[seg_id]
                        if seg.end_intersection_id == node:
                            path.append(seg_id)
                            break
                    node = prev_node

                path.reverse()
                return path

            for seg_id in self.adjacency.get(current, []):
                segment = self.segments[seg_id]
                neighbor = segment.end_intersection_id

                if neighbor not in visited:
                    new_dist = current_dist + segment.length

                    if new_dist < distances[neighbor]:
                        distances[neighbor] = new_dist
                        previous[neighbor] = current
                        heapq.heappush(pq, (new_dist, neighbor))

        return None


class TrafficSignDatabase:
    """Database of traffic signs."""

    def __init__(self: TrafficSignDatabase) -> None:
        """Initialize traffic sign database."""
        self.signs: dict[str, TrafficSign] = {}
        self.spatial_index: list[list[TrafficSign]] = []

    def add_sign(self: TrafficSignDatabase, sign: TrafficSign) -> None:
        """Add traffic sign.

        Args:
            sign: Traffic sign to add
        """
        self.signs[sign.sign_id] = sign

    def get_signs_near(self: TrafficSignDatabase, position: Vector2D, radius: float = 100.0) -> list[TrafficSign]:
        """Get signs within radius of position.

        Args:
            position: Query position
            radius: Search radius in meters

        Returns:
            List of nearby signs
        """
        nearby = []
        for sign in self.signs.values():
            if position.distance_to(sign.position) <= radius:
                nearby.append(sign)

        return nearby

    def get_speed_limits_near(self: TrafficSignDatabase, position: Vector2D, radius: float = 50.0) -> list[float]:
        """Get speed limit signs near position.

        Args:
            position: Query position
            radius: Search radius

        Returns:
            List of speed limits
        """
        limits = []
        for sign in self.get_signs_near(position, radius):
            if sign.sign_type == TrafficSignType.SPEED_LIMIT:
                limits.append(sign.value)

        return limits


class TrafficLightDatabase:
    """Database of traffic lights."""

    def __init__(self: TrafficLightDatabase) -> None:
        """Initialize traffic light database."""
        self.lights: dict[str, TrafficLight] = {}

    def add_light(self: TrafficLightDatabase, light: TrafficLight) -> None:
        """Add traffic light.

        Args:
            light: Traffic light to add
        """
        self.lights[light.light_id] = light

    def update_state(
        self: TrafficLightDatabase,
        light_id: str,
        state: TrafficLightState,
        time_until_change: float,
    ) -> None:
        """Update traffic light state.

        Args:
            light_id: Light ID
            state: New state
            time_until_change: Time until next state change
        """
        if light_id in self.lights:
            self.lights[light_id].state = state
            self.lights[light_id].time_until_change = time_until_change

    def get_lights_near(self: TrafficLightDatabase, position: Vector2D, radius: float = 100.0) -> list[TrafficLight]:
        """Get lights near position.

        Args:
            position: Query position
            radius: Search radius

        Returns:
            List of nearby lights
        """
        nearby = []
        for light in self.lights.values():
            if position.distance_to(light.position) <= radius:
                nearby.append(light)

        return nearby


class MapManager:
    """Complete HD map management system."""

    def __init__(self: MapManager, tile_size: float = 500.0) -> None:
        """Initialize map manager.

        Args:
            tile_size: Size of map tiles in meters
        """
        self.tile_size = tile_size
        self.tiles: dict[str, MapTile] = {}
        self.road_network = RoadNetwork()
        self.sign_database = TrafficSignDatabase()
        self.light_database = TrafficLightDatabase()
        self.speed_zones: dict[str, SpeedLimitZone] = {}

    def add_tile(self: MapManager, tile: MapTile) -> None:
        """Add map tile.

        Args:
            tile: Map tile to add
        """
        self.tiles[tile.tile_id] = tile

        # Add segments and intersections to network
        for intersection in tile.intersections:
            self.road_network.add_intersection(intersection)

        for segment in tile.segments:
            self.road_network.add_segment(segment)

        # Add traffic infrastructure
        for sign in tile.traffic_signs:
            self.sign_database.add_sign(sign)

        for light in tile.traffic_lights:
            self.light_database.add_light(light)

    def add_speed_zone(self: MapManager, zone: SpeedLimitZone) -> None:
        """Add speed limit zone.

        Args:
            zone: Speed limit zone
        """
        self.speed_zones[zone.zone_id] = zone

    def get_tiles_near(self: MapManager, position: Vector2D, padding: float = 0.0) -> list[MapTile]:
        """Get tiles near position.

        Args:
            position: Query position
            padding: Additional padding around tiles

        Returns:
            List of nearby tiles
        """
        nearby = []
        for tile in self.tiles.values():
            min_x, min_y, max_x, max_y = tile.get_bounds()
            if min_x - padding <= position.x <= max_x + padding and min_y - padding <= position.y <= max_y + padding:
                nearby.append(tile)

        return nearby

    def get_lanes_near(self: MapManager, position: Vector2D, radius: float = 50.0) -> list[Lane]:
        """Get lanes near position.

        Args:
            position: Query position
            radius: Search radius

        Returns:
            List of nearby lanes
        """
        lanes = []
        nearby_tiles = self.get_tiles_near(position, padding=radius)

        for tile in nearby_tiles:
            for segment in tile.segments:
                for lane in segment.lanes:
                    # Check if any lane point is within radius
                    for point in lane.centerline:
                        if position.distance_to(point) <= radius:
                            lanes.append(lane)
                            break

        return lanes

    def get_effective_speed_limit(self: MapManager, position: Vector2D) -> float:
        """Get effective speed limit at position.

        Args:
            position: Query position

        Returns:
            Speed limit in m/s
        """
        # Check speed limit zones
        for zone in self.speed_zones.values():
            if zone.contains_point(position):
                return zone.speed_limit

        # Check road signs
        speed_limits = self.sign_database.get_speed_limits_near(position, radius=50.0)
        if speed_limits:
            return min(speed_limits)

        # Default to 25 m/s (90 km/h)
        return 25.0

    def find_route(self: MapManager, start_intersection_id: str, end_intersection_id: str) -> list[RoadSegment] | None:
        """Find route between intersections.

        Args:
            start_intersection_id: Start intersection
            end_intersection_id: End intersection

        Returns:
            List of segments forming route, or None
        """
        path = self.road_network.shortest_path(start_intersection_id, end_intersection_id)

        if path is None:
            return None

        segments = []
        for seg_id in path:
            if seg_id in self.road_network.segments:
                segments.append(self.road_network.segments[seg_id])

        return segments
