"""
Tests for animation: keyframes, skeletal animation, blending, and state machines.

Tests:
- Keyframe interpolation (linear, cubic Bézier, Catmull-Rom)
- Skeletal animation
- Animation blending and cross-fading
- Animation state machines
- Morph targets
"""

from thomas.marketplace.graphics3d import animation
from thomas.marketplace.graphics3d._types import Vec3, Vertex


class TestKeyframe:
    """Tests for keyframe operations."""

    def test_keyframe_creation(self) -> None:
        """Test creating keyframe."""
        kf = animation.Keyframe(0.5, Vec3(1, 2, 3))
        assert kf.time == 0.5
        assert kf.value == Vec3(1, 2, 3)

    def test_keyframe_comparison(self) -> None:
        """Test keyframe comparison."""
        kf1 = animation.Keyframe(0.5, Vec3(0, 0, 0))
        kf2 = animation.Keyframe(1.0, Vec3(0, 0, 0))

        assert kf1 < kf2


class TestKeyframeTrack:
    """Tests for keyframe tracks."""

    def test_track_creation(self) -> None:
        """Test creating keyframe track."""
        track = animation.KeyframeTrack("position")
        assert track.name == "position"
        assert len(track.keyframes) == 0

    def test_add_keyframe(self) -> None:
        """Test adding keyframes."""
        track = animation.KeyframeTrack("position")
        track.add_keyframe(0.0, Vec3(0, 0, 0))
        track.add_keyframe(1.0, Vec3(1, 1, 1))

        assert len(track.keyframes) == 2

    def test_keyframes_sorted(self) -> None:
        """Test that keyframes are kept sorted."""
        track = animation.KeyframeTrack("position")
        track.add_keyframe(1.0, Vec3(1, 1, 1))
        track.add_keyframe(0.0, Vec3(0, 0, 0))
        track.add_keyframe(0.5, Vec3(0.5, 0.5, 0.5))

        for i in range(len(track.keyframes) - 1):
            assert track.keyframes[i].time <= track.keyframes[i + 1].time

    def test_evaluate_before_first(self) -> None:
        """Test evaluation before first keyframe."""
        track = animation.KeyframeTrack("position")
        track.add_keyframe(1.0, Vec3(1, 1, 1))
        track.add_keyframe(2.0, Vec3(2, 2, 2))

        result = track.evaluate(0.5)
        assert result == Vec3(1, 1, 1)

    def test_evaluate_after_last(self) -> None:
        """Test evaluation after last keyframe."""
        track = animation.KeyframeTrack("position")
        track.add_keyframe(0.0, Vec3(0, 0, 0))
        track.add_keyframe(1.0, Vec3(1, 1, 1))

        result = track.evaluate(2.0)
        assert result == Vec3(1, 1, 1)

    def test_evaluate_linear(self) -> None:
        """Test linear interpolation."""
        track = animation.KeyframeTrack("position")
        track.add_keyframe(0.0, Vec3(0, 0, 0))
        track.add_keyframe(1.0, Vec3(2, 2, 2))

        result = track.evaluate(0.5, "linear")
        assert result == Vec3(1, 1, 1)

    def test_evaluate_bezier(self) -> None:
        """Test cubic Bézier interpolation."""
        track = animation.KeyframeTrack("position")
        track.add_keyframe(0.0, Vec3(0, 0, 0))
        track.add_keyframe(1.0, Vec3(1, 1, 1))

        result = track.evaluate(0.5, "bezier")
        # Should be within range
        assert 0 <= result.x <= 1

    def test_evaluate_catmull(self) -> None:
        """Test Catmull-Rom spline interpolation."""
        track = animation.KeyframeTrack("position")
        track.add_keyframe(0.0, Vec3(0, 0, 0))
        track.add_keyframe(1.0, Vec3(1, 1, 1))
        track.add_keyframe(2.0, Vec3(2, 2, 2))

        result = track.evaluate(0.5, "catmull")
        # Should be within interpolation range
        assert result.x >= 0


class TestAnimationClip:
    """Tests for animation clips."""

    def test_clip_creation(self) -> None:
        """Test creating animation clip."""
        clip = animation.AnimationClip("walk", duration=2.0)
        assert clip.name == "walk"
        assert clip.duration == 2.0

    def test_add_track_to_clip(self) -> None:
        """Test adding track to clip."""
        clip = animation.AnimationClip("walk")
        track = animation.KeyframeTrack("position")
        track.add_keyframe(0.0, Vec3(0, 0, 0))
        track.add_keyframe(1.0, Vec3(1, 0, 0))

        clip.add_track(track)
        assert "position" in clip.tracks

    def test_evaluate_clip(self) -> None:
        """Test evaluating clip."""
        clip = animation.AnimationClip("walk", duration=1.0)

        track = animation.KeyframeTrack("position")
        track.add_keyframe(0.0, Vec3(0, 0, 0))
        track.add_keyframe(1.0, Vec3(1, 0, 0))
        clip.add_track(track)

        result = clip.evaluate(0.5)
        assert "position" in result
        assert result["position"].x == 0.5


class TestBone:
    """Tests for skeleton bones."""

    def test_bone_creation(self) -> None:
        """Test creating bone."""
        bone = animation.Bone("armature")
        assert bone.name == "armature"
        assert bone.position == Vec3(0, 0, 0)

    def test_bone_hierarchy(self) -> None:
        """Test bone parent-child relationships."""
        animation.Bone("parent")
        child = animation.Bone("child", parent_idx=0)

        assert child.parent_idx == 0


class TestSkeleton:
    """Tests for skeletal animation."""

    def test_skeleton_creation(self) -> None:
        """Test creating skeleton."""
        skeleton = animation.Skeleton("armature")
        assert skeleton.name == "armature"
        assert len(skeleton.bones) == 0

    def test_add_bone(self) -> None:
        """Test adding bones to skeleton."""
        skeleton = animation.Skeleton("armature")

        root = animation.Bone("root")
        idx0 = skeleton.add_bone(root)
        assert idx0 == 0

        child = animation.Bone("child", parent_idx=0)
        idx1 = skeleton.add_bone(child)
        assert idx1 == 1

    def test_skeleton_pose(self) -> None:
        """Test skeleton pose."""
        skeleton = animation.Skeleton("armature")

        root = animation.Bone("root")
        skeleton.add_bone(root)

        # Apply pose
        poses = {"root": Vec3(0.5, 0.5, 0.5)}
        skeleton.apply_pose(poses)

        assert skeleton.pose_bones[0].position == Vec3(0.5, 0.5, 0.5)


class TestAnimationBlender:
    """Tests for animation blending."""

    def test_blender_creation(self) -> None:
        """Test creating animation blender."""
        blender = animation.AnimationBlender()
        assert blender.active_clip is None
        assert blender.next_clip is None

    def test_play_clip(self) -> None:
        """Test playing animation clip."""
        blender = animation.AnimationBlender()

        clip = animation.AnimationClip("walk", 1.0)
        blender.play_clip(clip, fade_duration=0.5)

        assert blender.active_clip is clip

    def test_update_blender(self) -> None:
        """Test updating blender."""
        blender = animation.AnimationBlender()

        clip = animation.AnimationClip("walk", 2.0)
        track = animation.KeyframeTrack("position")
        track.add_keyframe(0.0, Vec3(0, 0, 0))
        track.add_keyframe(2.0, Vec3(2, 0, 0))
        clip.add_track(track)

        blender.play_clip(clip)

        pose = blender.update(1.0)
        assert "position" in pose

    def test_cross_fade(self) -> None:
        """Test cross-fading between clips."""
        blender = animation.AnimationBlender()

        clip1 = animation.AnimationClip("walk", 1.0)
        track1 = animation.KeyframeTrack("position")
        track1.add_keyframe(0.0, Vec3(0, 0, 0))
        track1.add_keyframe(1.0, Vec3(1, 0, 0))
        clip1.add_track(track1)

        clip2 = animation.AnimationClip("run", 1.0)
        track2 = animation.KeyframeTrack("position")
        track2.add_keyframe(0.0, Vec3(0, 0, 0))
        track2.add_keyframe(1.0, Vec3(3, 0, 0))
        clip2.add_track(track2)

        blender.play_clip(clip1)
        blender.update(0.5)

        # Transition to next clip
        blender.next_clip = clip2
        blender.blend_time = 0.0
        blender.blend_duration = 0.5

        pose = blender.update(0.25)
        # Should be blending
        assert "position" in pose


class TestAnimationStateMachine:
    """Tests for animation state machines."""

    def test_state_creation(self) -> None:
        """Test creating animation state."""
        clip = animation.AnimationClip("walk")
        state = animation.AnimationState("walk", clip=clip)

        assert state.name == "walk"
        assert state.clip is clip

    def test_fsm_creation(self) -> None:
        """Test creating state machine."""
        fsm = animation.AnimationStateMachine()
        assert fsm.current_state is None

    def test_add_state_to_fsm(self) -> None:
        """Test adding states to FSM."""
        fsm = animation.AnimationStateMachine()

        clip = animation.AnimationClip("idle")
        state = animation.AnimationState("idle", clip=clip)
        fsm.add_state(state)

        assert "idle" in fsm.states
        assert fsm.current_state == "idle"

    def test_add_transition(self) -> None:
        """Test adding transitions."""
        fsm = animation.AnimationStateMachine()

        idle_clip = animation.AnimationClip("idle")
        walk_clip = animation.AnimationClip("walk")

        fsm.add_state(animation.AnimationState("idle", clip=idle_clip))
        fsm.add_state(animation.AnimationState("walk", clip=walk_clip))

        fsm.add_transition("idle", "walk", fade_duration=0.5)

        assert "walk" in fsm.states["idle"].transitions

    def test_transition_to_state(self) -> None:
        """Test transitioning between states."""
        fsm = animation.AnimationStateMachine()

        idle_clip = animation.AnimationClip("idle")
        walk_clip = animation.AnimationClip("walk")

        fsm.add_state(animation.AnimationState("idle", clip=idle_clip))
        fsm.add_state(animation.AnimationState("walk", clip=walk_clip))

        fsm.add_transition("idle", "walk")

        assert fsm.transition_to("walk")
        assert fsm.current_state == "walk"


class TestMorphTarget:
    """Tests for morph targets."""

    def test_morph_target_creation(self) -> None:
        """Test creating morph target."""
        positions = [Vec3(0, 0, 0), Vec3(1, 1, 1)]
        target = animation.MorphTarget("smile", positions=positions)

        assert target.name == "smile"
        assert len(target.positions) == 2

    def test_morph_target_weight(self) -> None:
        """Test morph target weight."""
        target = animation.MorphTarget("smile")
        target.weight = 0.5

        assert target.weight == 0.5


class TestMorphAnimation:
    """Tests for morph target animation."""

    def test_morph_animation_creation(self) -> None:
        """Test creating morph animation."""
        mesh = animation.Mesh(
            [
                Vertex(Vec3(0, 0, 0)),
                Vertex(Vec3(1, 0, 0)),
                Vertex(Vec3(0, 1, 0)),
            ]
        )

        morph = animation.MorphAnimation(mesh)
        assert morph.base_mesh is mesh

    def test_add_morph_target(self) -> None:
        """Test adding morph targets."""
        mesh = animation.Mesh(
            [
                Vertex(Vec3(0, 0, 0)),
                Vertex(Vec3(1, 0, 0)),
            ]
        )

        morph = animation.MorphAnimation(mesh)
        target = animation.MorphTarget("smile", positions=[Vec3(0.1, 0.1, 0), Vec3(1.1, 0.1, 0)])

        morph.add_morph_target(target)
        assert "smile" in morph.target_weights

    def test_morph_animation_compute(self) -> None:
        """Test computing morphed positions."""
        mesh = animation.Mesh(
            [
                Vertex(Vec3(0, 0, 0)),
                Vertex(Vec3(1, 0, 0)),
            ]
        )

        morph = animation.MorphAnimation(mesh)
        target = animation.MorphTarget("smile", positions=[Vec3(0.1, 0.1, 0), Vec3(1.1, 0.1, 0)])
        morph.add_morph_target(target)
        morph.set_weight("smile", 1.0)

        positions = morph.compute_morphed_positions()
        assert len(positions) == 2
