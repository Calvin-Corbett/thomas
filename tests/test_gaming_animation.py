"""Tests for animation system."""

from thomas.gaming_platform._types import AnimationClip, Sprite
from thomas.gaming_platform.animation import (
    AnimationEngine,
    AnimationStateMachine,
    Easing,
    EasingFunction,
    PropertyTween,
    SpriteAnimator,
)
from thomas.gaming_platform.ecs import EntityComponentSystem


class TestEasing:
    """Test easing functions."""

    def test_linear_easing(self) -> None:
        """Test linear easing."""
        assert Easing.linear(0.0) == 0.0
        assert Easing.linear(0.5) == 0.5
        assert Easing.linear(1.0) == 1.0

    def test_ease_in_quad(self) -> None:
        """Test quadratic ease-in."""
        assert Easing.ease_in_quad(0.0) == 0.0
        assert 0.0 < Easing.ease_in_quad(0.5) < 0.5
        assert Easing.ease_in_quad(1.0) == 1.0

    def test_ease_out_quad(self) -> None:
        """Test quadratic ease-out."""
        assert Easing.ease_out_quad(0.0) == 0.0
        assert 0.5 < Easing.ease_out_quad(0.5) < 1.0
        assert Easing.ease_out_quad(1.0) == 1.0

    def test_ease_in_out_quad(self) -> None:
        """Test quadratic ease-in-out."""
        assert Easing.ease_in_out_quad(0.0) == 0.0
        assert Easing.ease_in_out_quad(1.0) == 1.0

    def test_ease_in_cubic(self) -> None:
        """Test cubic ease-in."""
        assert Easing.ease_in_cubic(0.0) == 0.0
        assert Easing.ease_in_cubic(1.0) == 1.0

    def test_ease_in_sine(self) -> None:
        """Test sine ease-in."""
        v = Easing.ease_in_sine(0.5)
        assert 0.0 < v < 1.0

    def test_ease_out_sine(self) -> None:
        """Test sine ease-out."""
        v = Easing.ease_out_sine(0.5)
        assert 0.0 < v < 1.0

    def test_ease_in_expo(self) -> None:
        """Test exponential ease-in."""
        assert Easing.ease_in_expo(0.0) == 0.0
        assert Easing.ease_in_expo(1.0) == 1.0

    def test_ease_out_expo(self) -> None:
        """Test exponential ease-out."""
        assert Easing.ease_out_expo(0.0) == 0.0
        assert Easing.ease_out_expo(1.0) == 1.0

    def test_ease_in_bounce(self) -> None:
        """Test bounce ease-in."""
        assert Easing.ease_in_bounce(0.0) == 0.0
        assert Easing.ease_in_bounce(1.0) == 1.0

    def test_ease_out_bounce(self) -> None:
        """Test bounce ease-out."""
        assert Easing.ease_out_bounce(0.0) == 0.0
        assert Easing.ease_out_bounce(1.0) == 1.0

    def test_apply_easing(self) -> None:
        """Test applying easing function."""
        result = Easing.apply(EasingFunction.LINEAR, 0.5)
        assert result == 0.5

        result = Easing.apply(EasingFunction.EASE_IN_QUAD, 0.5)
        assert result == 0.25


class TestPropertyTween:
    """Test property tweening."""

    def test_tween_creation(self) -> None:
        """Test creating property tween."""
        target = {"value": 0.0}
        tween = PropertyTween(
            target=target,
            property_name="value",
            start_value=0.0,
            end_value=100.0,
            duration=1.0,
        )

        assert tween.duration == 1.0
        assert tween.start_value == 0.0
        assert tween.end_value == 100.0

    def test_tween_update(self) -> None:
        """Test updating tween."""

        class Target:
            def __init__(self) -> None:
                self.value = 0.0

        target = Target()
        tween = PropertyTween(
            target=target,
            property_name="value",
            start_value=0.0,
            end_value=100.0,
            duration=1.0,
        )

        tween.update(0.5)
        assert target.value == 50.0

    def test_tween_completion(self) -> None:
        """Test tween completion."""

        class Target:
            def __init__(self) -> None:
                self.value = 0.0

        target = Target()
        completed = False

        def on_complete() -> None:
            nonlocal completed
            completed = True

        tween = PropertyTween(
            target=target,
            property_name="value",
            start_value=0.0,
            end_value=100.0,
            duration=1.0,
            on_complete=on_complete,
        )

        tween.update(1.5)
        assert completed
        assert target.value == 100.0

    def test_tween_with_easing(self) -> None:
        """Test tween with easing function."""

        class Target:
            def __init__(self) -> None:
                self.value = 0.0

        target = Target()
        tween = PropertyTween(
            target=target,
            property_name="value",
            start_value=0.0,
            end_value=100.0,
            duration=1.0,
            easing=EasingFunction.EASE_IN_QUAD,
        )

        tween.update(0.5)
        # With ease-in-quad, should be less than 50
        assert target.value < 50.0


class TestSpriteAnimator:
    """Test sprite animation."""

    def test_animator_creation(self) -> None:
        """Test animator initialization."""
        ecs = EntityComponentSystem()
        entity = ecs.create_entity()

        animator = SpriteAnimator(entity, ecs)
        assert animator.entity == entity
        assert animator.current_animation is None

    def test_play_animation(self) -> None:
        """Test playing animation."""
        ecs = EntityComponentSystem()
        entity = ecs.create_entity()

        ecs.add_component(entity, Sprite(texture_id="frame_0"))
        animator = SpriteAnimator(entity, ecs)

        animation = AnimationClip(
            name="walk",
            frames=["frame_0", "frame_1", "frame_2"],
            frame_rate=10.0,
            looping=True,
        )

        animator.play(animation)
        assert animator.current_animation == animation
        assert animator.frame_index == 0

    def test_animation_frame_advance(self) -> None:
        """Test animation frame advancement."""
        ecs = EntityComponentSystem()
        entity = ecs.create_entity()
        ecs.add_component(entity, Sprite(texture_id="frame_0"))

        animator = SpriteAnimator(entity, ecs)
        animation = AnimationClip(
            name="run",
            frames=["frame_0", "frame_1", "frame_2"],
            frame_rate=10.0,
            looping=False,
        )

        animator.play(animation)
        animator.update(0.15)  # Move to next frame

        assert animator.frame_index == 1

    def test_animation_loop(self) -> None:
        """Test looping animation."""
        ecs = EntityComponentSystem()
        entity = ecs.create_entity()
        ecs.add_component(entity, Sprite())

        animator = SpriteAnimator(entity, ecs)
        animation = AnimationClip(
            name="loop",
            frames=["frame_0", "frame_1"],
            frame_rate=10.0,
            looping=True,
        )

        animator.play(animation)
        animator.update(0.3)  # Past end

        assert animator.frame_index == 0  # Should loop back

    def test_animation_events(self) -> None:
        """Test animation frame events."""
        ecs = EntityComponentSystem()
        entity = ecs.create_entity()
        ecs.add_component(entity, Sprite())

        animator = SpriteAnimator(entity, ecs)
        event_triggered = False

        def on_frame_event() -> None:
            nonlocal event_triggered
            event_triggered = True

        animation = AnimationClip(
            name="event",
            frames=["frame_0", "frame_1"],
            frame_rate=10.0,
            looping=False,
            events={1: [on_frame_event]},
        )

        animator.play(animation)
        animator.update(0.15)  # Frame 1

        assert event_triggered


class TestAnimationStateMachine:
    """Test animation state machine."""

    def test_state_machine_creation(self) -> None:
        """Test creating state machine."""
        ecs = EntityComponentSystem()
        entity = ecs.create_entity()

        sm = AnimationStateMachine(entity, ecs)
        assert sm.current_state is None

    def test_add_state(self) -> None:
        """Test adding animation state."""
        ecs = EntityComponentSystem()
        entity = ecs.create_entity()
        ecs.add_component(entity, Sprite())

        sm = AnimationStateMachine(entity, ecs)
        animation = AnimationClip(name="idle", frames=["idle_0"])

        state = sm.add_state("idle", animation)
        assert state is not None
        assert sm.current_state == state

    def test_state_transition(self) -> None:
        """Test state transitions."""
        ecs = EntityComponentSystem()
        entity = ecs.create_entity()
        ecs.add_component(entity, Sprite())

        sm = AnimationStateMachine(entity, ecs)

        idle = AnimationClip(name="idle", frames=["idle_0"])
        run = AnimationClip(name="run", frames=["run_0", "run_1"])

        sm.add_state("idle", idle)
        sm.add_state("run", run)

        is_moving = False

        def check_moving() -> bool:
            return is_moving

        sm.add_transition("idle", "run", check_moving)

        sm.update(0.016)
        assert sm.current_state.name == "idle"

        is_moving = True
        sm.update(0.016)
        assert sm.current_state.name == "run"


class TestAnimationEngine:
    """Test animation engine."""

    def test_engine_creation(self) -> None:
        """Test creating animation engine."""
        engine = AnimationEngine()
        assert len(engine.tweens) == 0

    def test_create_tween(self) -> None:
        """Test creating tween in engine."""

        class Target:
            def __init__(self) -> None:
                self.position = 0.0

        engine = AnimationEngine()
        target = Target()

        tween = engine.create_tween(
            target=target,
            property_name="position",
            end_value=100.0,
            duration=1.0,
        )

        assert tween in engine.tweens

    def test_kill_tween(self) -> None:
        """Test killing tween."""

        class Target:
            def __init__(self) -> None:
                self.x = 0.0

        engine = AnimationEngine()
        target = Target()
        tween = engine.create_tween(target, "x", 100.0, 1.0)

        engine.kill_tween(tween)
        assert tween not in engine.tweens

    def test_update_tweens(self) -> None:
        """Test updating tweens."""

        class Target:
            def __init__(self) -> None:
                self.x = 0.0

        engine = AnimationEngine()
        target = Target()
        engine.create_tween(target, "x", 100.0, 1.0)

        engine.update(0.5)
        assert target.x == 50.0

    def test_get_active_tween_count(self) -> None:
        """Test getting tween count."""

        class Target:
            def __init__(self) -> None:
                self.x = 0.0

        engine = AnimationEngine()
        target = Target()

        engine.create_tween(target, "x", 100.0, 1.0)
        engine.create_tween(target, "x", 200.0, 1.0)

        assert engine.get_active_tween_count() == 2

        engine.update(1.5)
        assert engine.get_active_tween_count() == 0
