"""
Animation: keyframes, skeletal animation, blending, and state machines.

Provides:
- Keyframe interpolation (linear, cubic Bézier, Catmull-Rom)
- Skeletal animation (bone hierarchy, skinning)
- Animation blending and cross-fading
- Animation state machines with transitions
- Morph targets (vertex animation)
- Timeline management
"""

from __future__ import annotations

from dataclasses import dataclass, field

from thomas.graphics3d._exceptions import MeshError
from thomas.graphics3d._types import Mesh, Quaternion, Vec3


@dataclass
class Keyframe:
    """Single animation keyframe."""

    time: float = 0.0
    value: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))

    def __lt__(self, other: Keyframe) -> bool:
        """Compare keyframes by time."""
        return self.time < other.time


@dataclass
class KeyframeTrack:
    """Track of keyframes for a single property."""

    name: str = ""
    keyframes: list[Keyframe] = field(default_factory=list)

    def add_keyframe(self, time: float, value: Vec3) -> None:
        """Add keyframe to track."""
        self.keyframes.append(Keyframe(time, value))
        self.keyframes.sort()

    def evaluate(self, time: float, interpolation: str = "linear") -> Vec3:
        """Evaluate track at given time.

        Args:
            time: Time to evaluate
            interpolation: Interpolation mode ('linear', 'bezier', 'catmull')

        Returns:
            Interpolated value
        """
        if not self.keyframes:
            return Vec3(0, 0, 0)

        if time <= self.keyframes[0].time:
            return self.keyframes[0].value

        if time >= self.keyframes[-1].time:
            return self.keyframes[-1].value

        # Find surrounding keyframes
        idx = 0
        for i, kf in enumerate(self.keyframes):
            if kf.time > time:
                idx = i - 1
                break
        else:
            idx = len(self.keyframes) - 2

        idx = max(0, idx)
        kf0 = self.keyframes[idx]
        kf1 = self.keyframes[idx + 1]

        t = (time - kf0.time) / (kf1.time - kf0.time)
        t = max(0, min(1, t))

        if interpolation == "linear":
            return kf0.value.lerp(kf1.value, t)

        elif interpolation == "bezier":
            # Simple cubic Bézier (using keyframe values as control points)
            p0 = kf0.value
            p3 = kf1.value
            # Simplified: p1 and p2 are interpolations toward p3/p0
            p1 = p0.lerp(p3, 1.0 / 3.0)
            p2 = p0.lerp(p3, 2.0 / 3.0)

            return self._cubic_bezier(p0, p1, p2, p3, t)

        elif interpolation == "catmull":
            # Catmull-Rom spline
            kf_prev = self.keyframes[max(0, idx - 1)]
            kf_next = self.keyframes[min(len(self.keyframes) - 1, idx + 2)]

            return self._catmull_rom(kf_prev.value, kf0.value, kf1.value, kf_next.value, t)

        else:
            return kf0.value.lerp(kf1.value, t)

    def _cubic_bezier(self, p0: Vec3, p1: Vec3, p2: Vec3, p3: Vec3, t: float) -> Vec3:
        """Evaluate cubic Bézier curve."""
        mt = 1 - t
        mt2 = mt * mt
        mt3 = mt2 * mt
        t2 = t * t
        t3 = t2 * t

        return p0 * mt3 + p1 * (3 * mt2 * t) + p2 * (3 * mt * t2) + p3 * t3

    def _catmull_rom(self, p0: Vec3, p1: Vec3, p2: Vec3, p3: Vec3, t: float) -> Vec3:
        """Evaluate Catmull-Rom spline."""
        t2 = t * t
        t3 = t2 * t

        return (
            p0 * (-0.5 * t3 + t2 - 0.5 * t)
            + p1 * (1.5 * t3 - 2.5 * t2 + 1)
            + p2 * (-1.5 * t3 + 2 * t2 + 0.5 * t)
            + p3 * (0.5 * t3 - 0.5 * t2)
        )


@dataclass
class AnimationClip:
    """Animation clip: collection of tracks."""

    name: str = "Animation"
    duration: float = 1.0
    tracks: dict[str, KeyframeTrack] = field(default_factory=dict)

    def add_track(self, track: KeyframeTrack) -> None:
        """Add track to clip."""
        self.tracks[track.name] = track

    def evaluate(self, time: float, interpolation: str = "linear") -> dict[str, Vec3]:
        """Evaluate all tracks at given time."""
        # Clamp time to duration
        time = max(0, min(self.duration, time))

        result: dict[str, Vec3] = {}
        for name, track in self.tracks.items():
            result[name] = track.evaluate(time, interpolation)

        return result


@dataclass
class Bone:
    """Skeletal bone."""

    name: str = ""
    position: Vec3 = field(default_factory=lambda: Vec3(0, 0, 0))
    rotation: Quaternion = field(default_factory=lambda: Quaternion(1, 0, 0, 0))
    scale: Vec3 = field(default_factory=lambda: Vec3(1, 1, 1))
    parent_idx: int = -1
    children_indices: list[int] = field(default_factory=list)

    def get_local_transform_matrix(self):
        """Get bone's local transformation matrix."""
        from thomas.graphics3d import math3d

        translate = math3d.matrix_translate(self.position)
        rotate = self.rotation.to_rotation_matrix()
        scale = math3d.matrix_scale(self.scale)

        return translate * rotate * scale


@dataclass
class Skeleton:
    """Skeletal animation rig."""

    name: str = "Skeleton"
    bones: list[Bone] = field(default_factory=list)
    pose_bones: list[Bone] = field(default_factory=list)

    def add_bone(self, bone: Bone) -> int:
        """Add bone to skeleton."""
        idx = len(self.bones)
        self.bones.append(bone)
        self.pose_bones.append(
            Bone(
                name=bone.name,
                position=bone.position,
                rotation=bone.rotation,
                scale=bone.scale,
                parent_idx=bone.parent_idx,
            )
        )
        return idx

    def get_bone_world_transform(self, bone_idx: int):
        """Get bone's world transformation."""

        bone = self.pose_bones[bone_idx]
        local_transform = bone.get_local_transform_matrix()

        if bone.parent_idx < 0:
            return local_transform

        parent_transform = self.get_bone_world_transform(bone.parent_idx)
        return parent_transform * local_transform

    def apply_pose(self, poses: dict[str, Vec3]) -> None:
        """Apply pose data (position offsets) to skeleton."""
        for bone in self.pose_bones:
            if bone.name in poses:
                bone.position = poses[bone.name]


@dataclass
class SkinWeight:
    """Vertex skinning weight."""

    bone_idx: int = 0
    weight: float = 1.0


@dataclass
class SkinnedMesh:
    """Mesh with skeletal animation weights."""

    mesh: Mesh
    skeleton: Skeleton
    vertex_weights: list[list[SkinWeight]] = field(default_factory=list)

    def skin_vertex(self, vertex_idx: int, bone_idx: int, weight: float) -> None:
        """Add bone influence to vertex."""
        while len(self.vertex_weights) <= vertex_idx:
            self.vertex_weights.append([])

        self.vertex_weights[vertex_idx].append(SkinWeight(bone_idx, weight))

    def compute_skinned_positions(self) -> list[Vec3]:
        """Compute skinned vertex positions."""
        from thomas.graphics3d import math3d

        skinned_positions: list[Vec3] = []

        for vertex_idx, vertex in enumerate(self.mesh.vertices):
            skinned_pos = Vec3(0, 0, 0)

            if vertex_idx < len(self.vertex_weights):
                weights = self.vertex_weights[vertex_idx]
                total_weight = sum(w.weight for w in weights)

                if total_weight > 0:
                    for skin_weight in weights:
                        bone_transform = self.skeleton.get_bone_world_transform(skin_weight.bone_idx)
                        bone_pos = math3d.vector_transform_position(vertex.position, bone_transform)
                        skinned_pos = skinned_pos + bone_pos * (skin_weight.weight / total_weight)
                else:
                    skinned_pos = vertex.position
            else:
                skinned_pos = vertex.position

            skinned_positions.append(skinned_pos)

        return skinned_positions


class AnimationBlender:
    """Blend multiple animation clips."""

    def __init__(self) -> None:
        """Initialize blender."""
        self.active_clip: AnimationClip | None = None
        self.next_clip: AnimationClip | None = None
        self.blend_time: float = 0.0
        self.blend_duration: float = 0.5
        self.clip_time: float = 0.0

    def play_clip(self, clip: AnimationClip, fade_duration: float = 0.5) -> None:
        """Play animation clip with fade-in.

        Args:
            clip: Clip to play
            fade_duration: Cross-fade duration
        """
        self.next_clip = clip
        self.blend_duration = fade_duration
        self.blend_time = 0.0
        self.clip_time = 0.0

        if self.active_clip is None:
            self.active_clip = clip
            self.next_clip = None

    def update(self, delta_time: float) -> dict[str, Vec3]:
        """Update animation and return current pose.

        Args:
            delta_time: Delta time since last update

        Returns:
            Current pose as property->value mapping
        """
        if self.active_clip is None:
            return {}

        self.clip_time += delta_time

        if self.clip_time > self.active_clip.duration:
            self.clip_time = 0.0

        pose = self.active_clip.evaluate(self.clip_time)

        # Handle blending
        if self.next_clip is not None:
            self.blend_time += delta_time

            if self.blend_time >= self.blend_duration:
                # Blend complete
                self.active_clip = self.next_clip
                self.next_clip = None
                self.blend_time = 0.0
            else:
                # Blend in progress
                blend_factor = self.blend_time / self.blend_duration
                next_pose = self.next_clip.evaluate(0)  # Start of next clip

                for key in pose:
                    if key in next_pose:
                        pose[key] = pose[key].lerp(next_pose[key], blend_factor)

        return pose


@dataclass
class AnimationState:
    """Animation state in state machine."""

    name: str = ""
    clip: AnimationClip = None
    transitions: dict[str, tuple[str, float]] = field(default_factory=dict)


class AnimationStateMachine:
    """Finite state machine for animation playback."""

    def __init__(self) -> None:
        """Initialize state machine."""
        self.states: dict[str, AnimationState] = {}
        self.current_state: str | None = None
        self.blender = AnimationBlender()

    def add_state(self, state: AnimationState) -> None:
        """Add state to machine."""
        self.states[state.name] = state

        if self.current_state is None:
            self.current_state = state.name
            self.blender.play_clip(state.clip)

    def add_transition(self, from_state: str, to_state: str, fade_duration: float = 0.5) -> None:
        """Add transition between states.

        Args:
            from_state: Source state name
            to_state: Destination state name
            fade_duration: Cross-fade duration
        """
        if from_state in self.states:
            self.states[from_state].transitions[to_state] = fade_duration

    def transition_to(self, state_name: str) -> bool:
        """Transition to new state.

        Args:
            state_name: State to transition to

        Returns:
            True if transition was valid
        """
        if self.current_state is None or state_name not in self.states:
            return False

        current = self.states[self.current_state]

        if state_name in current.transitions:
            fade_duration = current.transitions[state_name]
            self.current_state = state_name
            self.blender.play_clip(self.states[state_name].clip, fade_duration)
            return True

        return False

    def update(self, delta_time: float) -> dict[str, Vec3]:
        """Update state machine."""
        return self.blender.update(delta_time)


@dataclass
class MorphTarget:
    """Morph target (blend shape) for vertex animation."""

    name: str = ""
    positions: list[Vec3] = field(default_factory=list)
    weight: float = 0.0


class MorphAnimation:
    """Vertex animation via morph targets."""

    def __init__(self, base_mesh: Mesh) -> None:
        """Initialize morph animation.

        Args:
            base_mesh: Base mesh
        """
        self.base_mesh = base_mesh
        self.morph_targets: list[MorphTarget] = []
        self.target_weights: dict[str, float] = {}

    def add_morph_target(self, target: MorphTarget) -> None:
        """Add morph target."""
        if len(target.positions) != len(self.base_mesh.vertices):
            raise MeshError("Morph target vertex count mismatch")

        self.morph_targets.append(target)
        self.target_weights[target.name] = 0.0

    def set_weight(self, target_name: str, weight: float) -> None:
        """Set morph target weight."""
        if target_name in self.target_weights:
            self.target_weights[target_name] = max(0, min(1, weight))

    def compute_morphed_positions(self) -> list[Vec3]:
        """Compute morphed vertex positions."""
        result: list[Vec3] = []

        for vertex in self.base_mesh.vertices:
            morphed = vertex.position

            for target in self.morph_targets:
                if target.name in self.target_weights:
                    weight = self.target_weights[target.name]
                    target_idx = self.morph_targets.index(target)

                    if target_idx < len(target.positions):
                        morphed = morphed.lerp(target.positions[target_idx], weight)

            result.append(morphed)

        return result
