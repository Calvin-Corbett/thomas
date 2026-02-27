"""Animation system with tweening, state machines, and sprite animation."""

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from thomas.gaming_platform._types import (
    AnimationClip,
    Entity,
    Sprite,
)
from thomas.gaming_platform.ecs import EntityComponentSystem


class EasingFunction(Enum):
    """Easing function types."""

    LINEAR = auto()
    EASE_IN_QUAD = auto()
    EASE_OUT_QUAD = auto()
    EASE_IN_OUT_QUAD = auto()
    EASE_IN_CUBIC = auto()
    EASE_OUT_CUBIC = auto()
    EASE_IN_OUT_CUBIC = auto()
    EASE_IN_SINE = auto()
    EASE_OUT_SINE = auto()
    EASE_IN_OUT_SINE = auto()
    EASE_IN_EXPO = auto()
    EASE_OUT_EXPO = auto()
    EASE_IN_OUT_EXPO = auto()
    EASE_IN_ELASTIC = auto()
    EASE_OUT_ELASTIC = auto()
    EASE_IN_OUT_ELASTIC = auto()
    EASE_IN_BOUNCE = auto()
    EASE_OUT_BOUNCE = auto()
    EASE_IN_OUT_BOUNCE = auto()
    EASE_IN_BACK = auto()
    EASE_OUT_BACK = auto()
    EASE_IN_OUT_BACK = auto()


class Easing:
    """Easing function implementations."""

    @staticmethod
    def linear(t: float) -> float:
        """Linear interpolation."""
        return t

    @staticmethod
    def ease_in_quad(t: float) -> float:
        """Quadratic ease-in."""
        return t * t

    @staticmethod
    def ease_out_quad(t: float) -> float:
        """Quadratic ease-out."""
        return 1.0 - (1.0 - t) ** 2

    @staticmethod
    def ease_in_out_quad(t: float) -> float:
        """Quadratic ease-in-out."""
        if t < 0.5:
            return 2.0 * t * t
        else:
            return -1.0 + (4.0 - 2.0 * t) * t

    @staticmethod
    def ease_in_cubic(t: float) -> float:
        """Cubic ease-in."""
        return t**3

    @staticmethod
    def ease_out_cubic(t: float) -> float:
        """Cubic ease-out."""
        return 1.0 - (1.0 - t) ** 3

    @staticmethod
    def ease_in_out_cubic(t: float) -> float:
        """Cubic ease-in-out."""
        if t < 0.5:
            return 4.0 * t**3
        else:
            return 1.0 - ((-2.0 * t + 2.0) ** 3) / 2.0

    @staticmethod
    def ease_in_sine(t: float) -> float:
        """Sine ease-in."""
        return 1.0 - math.cos((t * math.pi) / 2.0)

    @staticmethod
    def ease_out_sine(t: float) -> float:
        """Sine ease-out."""
        return math.sin((t * math.pi) / 2.0)

    @staticmethod
    def ease_in_out_sine(t: float) -> float:
        """Sine ease-in-out."""
        return -(math.cos(math.pi * t) - 1.0) / 2.0

    @staticmethod
    def ease_in_expo(t: float) -> float:
        """Exponential ease-in."""
        if t == 0:
            return 0.0
        return 2.0 ** (10.0 * t - 10.0)

    @staticmethod
    def ease_out_expo(t: float) -> float:
        """Exponential ease-out."""
        if t == 1:
            return 1.0
        return 1.0 - 2.0 ** (-10.0 * t)

    @staticmethod
    def ease_in_out_expo(t: float) -> float:
        """Exponential ease-in-out."""
        if t == 0:
            return 0.0
        if t == 1:
            return 1.0
        if t < 0.5:
            return 2.0 ** (20.0 * t - 10.0) / 2.0
        else:
            return (2.0 - 2.0 ** (-20.0 * t + 10.0)) / 2.0

    @staticmethod
    def ease_in_elastic(t: float) -> float:
        """Elastic ease-in."""
        c4 = (2.0 * math.pi) / 3.0
        if t == 0:
            return 0.0
        if t == 1:
            return 1.0
        return -(2.0 ** (10.0 * t - 10.0)) * math.sin((t * 10.0 - 10.75) * c4)

    @staticmethod
    def ease_out_elastic(t: float) -> float:
        """Elastic ease-out."""
        c4 = (2.0 * math.pi) / 3.0
        if t == 0:
            return 0.0
        if t == 1:
            return 1.0
        return 2.0 ** (-10.0 * t) * math.sin((t * 10.0 - 0.75) * c4) + 1.0

    @staticmethod
    def ease_in_out_elastic(t: float) -> float:
        """Elastic ease-in-out."""
        c5 = (2.0 * math.pi) / 4.5
        if t == 0:
            return 0.0
        if t == 1:
            return 1.0
        if t < 0.5:
            return -(2.0 ** (20.0 * t - 10.0) * math.sin((20.0 * t - 11.125) * c5)) / 2.0
        else:
            return (2.0 ** (-20.0 * t + 10.0) * math.sin((20.0 * t - 11.125) * c5)) / 2.0 + 1.0

    @staticmethod
    def ease_in_bounce(t: float) -> float:
        """Bounce ease-in."""
        return 1.0 - Easing.ease_out_bounce(1.0 - t)

    @staticmethod
    def ease_out_bounce(t: float) -> float:
        """Bounce ease-out."""
        n1 = 7.5625
        d1 = 2.75

        if t < 1.0 / d1:
            return n1 * t * t
        elif t < 2.0 / d1:
            t -= 1.5 / d1
            return n1 * t * t + 0.75
        elif t < 2.5 / d1:
            t -= 2.25 / d1
            return n1 * t * t + 0.9375
        else:
            t -= 2.625 / d1
            return n1 * t * t + 0.984375

    @staticmethod
    def ease_in_out_bounce(t: float) -> float:
        """Bounce ease-in-out."""
        if t < 0.5:
            return (1.0 - Easing.ease_out_bounce(1.0 - 2.0 * t)) / 2.0
        else:
            return (1.0 + Easing.ease_out_bounce(2.0 * t - 1.0)) / 2.0

    @staticmethod
    def ease_in_back(t: float) -> float:
        """Back ease-in."""
        c1 = 1.70158
        c3 = c1 + 1.0
        return c3 * t**3 - c1 * t**2

    @staticmethod
    def ease_out_back(t: float) -> float:
        """Back ease-out."""
        c1 = 1.70158
        c3 = c1 + 1.0
        return 1.0 + c3 * (t - 1.0) ** 3 + c1 * (t - 1.0) ** 2

    @staticmethod
    def ease_in_out_back(t: float) -> float:
        """Back ease-in-out."""
        c1 = 1.70158
        c2 = c1 * 1.525
        if t < 0.5:
            return ((2.0 * t) ** 2 * ((c2 + 1.0) * 2.0 * t - c2)) / 2.0
        else:
            return ((2.0 * t - 2.0) ** 2 * ((c2 + 1.0) * (t * 2.0 - 2.0) + c2) + 2.0) / 2.0

    @staticmethod
    def apply(function: EasingFunction, t: float) -> float:
        """Apply easing function."""
        if function == EasingFunction.LINEAR:
            return Easing.linear(t)
        elif function == EasingFunction.EASE_IN_QUAD:
            return Easing.ease_in_quad(t)
        elif function == EasingFunction.EASE_OUT_QUAD:
            return Easing.ease_out_quad(t)
        elif function == EasingFunction.EASE_IN_OUT_QUAD:
            return Easing.ease_in_out_quad(t)
        elif function == EasingFunction.EASE_IN_CUBIC:
            return Easing.ease_in_cubic(t)
        elif function == EasingFunction.EASE_OUT_CUBIC:
            return Easing.ease_out_cubic(t)
        elif function == EasingFunction.EASE_IN_OUT_CUBIC:
            return Easing.ease_in_out_cubic(t)
        elif function == EasingFunction.EASE_IN_SINE:
            return Easing.ease_in_sine(t)
        elif function == EasingFunction.EASE_OUT_SINE:
            return Easing.ease_out_sine(t)
        elif function == EasingFunction.EASE_IN_OUT_SINE:
            return Easing.ease_in_out_sine(t)
        elif function == EasingFunction.EASE_IN_EXPO:
            return Easing.ease_in_expo(t)
        elif function == EasingFunction.EASE_OUT_EXPO:
            return Easing.ease_out_expo(t)
        elif function == EasingFunction.EASE_IN_OUT_EXPO:
            return Easing.ease_in_out_expo(t)
        elif function == EasingFunction.EASE_IN_ELASTIC:
            return Easing.ease_in_elastic(t)
        elif function == EasingFunction.EASE_OUT_ELASTIC:
            return Easing.ease_out_elastic(t)
        elif function == EasingFunction.EASE_IN_OUT_ELASTIC:
            return Easing.ease_in_out_elastic(t)
        elif function == EasingFunction.EASE_IN_BOUNCE:
            return Easing.ease_in_bounce(t)
        elif function == EasingFunction.EASE_OUT_BOUNCE:
            return Easing.ease_out_bounce(t)
        elif function == EasingFunction.EASE_IN_OUT_BOUNCE:
            return Easing.ease_in_out_bounce(t)
        elif function == EasingFunction.EASE_IN_BACK:
            return Easing.ease_in_back(t)
        elif function == EasingFunction.EASE_OUT_BACK:
            return Easing.ease_out_back(t)
        elif function == EasingFunction.EASE_IN_OUT_BACK:
            return Easing.ease_in_out_back(t)
        else:
            return t


@dataclass
class PropertyTween:
    """
    Animate numeric property over time.

    Attributes:
        target: Target object.
        property_name: Property name to animate.
        start_value: Starting value.
        end_value: Ending value.
        duration: Animation duration in seconds.
        elapsed: Elapsed time in seconds.
        easing: Easing function to use.
        on_complete: Callback when tween finishes.
    """

    target: Any
    property_name: str
    start_value: float
    end_value: float
    duration: float
    elapsed: float = 0.0
    easing: EasingFunction = EasingFunction.LINEAR
    on_complete: Callable[[], None] | None = None

    def update(self, dt: float) -> bool:
        """
        Update tween.

        Returns:
            True if tween is still running.
        """
        self.elapsed += dt

        if self.elapsed >= self.duration:
            setattr(self.target, self.property_name, self.end_value)
            if self.on_complete:
                self.on_complete()
            return False

        t = self.elapsed / self.duration
        eased_t = Easing.apply(self.easing, t)
        value = self.start_value + (self.end_value - self.start_value) * eased_t
        setattr(self.target, self.property_name, value)

        return True


@dataclass
class AnimationState:
    """Represents an animation state in state machine."""

    name: str
    animation: AnimationClip
    transitions: dict[str, str] = field(default_factory=dict)
    transition_conditions: dict[str, Callable[[], bool]] = field(default_factory=dict)


class SpriteAnimator:
    """Animates sprite using animation clips."""

    def __init__(self, entity: Entity, ecs: EntityComponentSystem) -> None:
        """
        Initialize sprite animator.

        Args:
            entity: Entity to animate.
            ecs: Entity component system.
        """
        self.entity = entity
        self.ecs = ecs
        self.current_animation: AnimationClip | None = None
        self.frame_index = 0
        self.frame_time = 0.0

    def play(self, animation: AnimationClip) -> None:
        """
        Play animation.

        Args:
            animation: Animation clip to play.
        """
        self.current_animation = animation
        self.frame_index = 0
        self.frame_time = 0.0
        self._update_sprite()

    def update(self, dt: float) -> None:
        """Update animation."""
        if self.current_animation is None:
            return

        if self.current_animation.frame_rate <= 0 or not self.current_animation.frames:
            return

        self.frame_time += dt
        frame_duration = 1.0 / self.current_animation.frame_rate

        # Advance one or more frames when dt is large.
        # Use strict '>' so boundary times stay on the current frame.
        while self.current_animation is not None and self.frame_time > frame_duration:
            self.frame_time -= frame_duration
            self.frame_index += 1

            # Check looping
            if self.frame_index >= len(self.current_animation.frames):
                if self.current_animation.looping:
                    self.frame_index = 0
                else:
                    self.frame_index = len(self.current_animation.frames) - 1
                    self._update_sprite()
                    self.current_animation = None
                    return

            # Trigger frame events
            if self.frame_index in self.current_animation.events:
                for callback in self.current_animation.events[self.frame_index]:
                    callback()

            self._update_sprite()

    def _update_sprite(self) -> None:
        """Update sprite texture to current frame."""
        if self.current_animation is None or self.frame_index >= len(self.current_animation.frames):
            return

        sprite = self.ecs.get_component(self.entity, Sprite)
        if sprite is None:
            return

        sprite.texture_id = self.current_animation.frames[self.frame_index]


class AnimationStateMachine:
    """State machine for complex animation transitions."""

    def __init__(self, entity: Entity, ecs: EntityComponentSystem) -> None:
        """
        Initialize animation state machine.

        Args:
            entity: Entity to animate.
            ecs: Entity component system.
        """
        self.entity = entity
        self.ecs = ecs
        self.states: dict[str, AnimationState] = {}
        self.current_state: AnimationState | None = None
        self.animator: SpriteAnimator | None = None

    def add_state(self, name: str, animation: AnimationClip) -> AnimationState:
        """
        Add animation state.

        Args:
            name: State name.
            animation: Animation clip.

        Returns:
            Animation state.
        """
        state = AnimationState(name=name, animation=animation)
        self.states[name] = state
        if self.current_state is None:
            self.current_state = state
            self.animator = SpriteAnimator(self.entity, self.ecs)
            self.animator.play(animation)
        return state

    def add_transition(self, from_state: str, to_state: str, condition: Callable[[], bool]) -> None:
        """
        Add state transition.

        Args:
            from_state: Source state name.
            to_state: Destination state name.
            condition: Condition function.
        """
        if from_state not in self.states:
            return

        state = self.states[from_state]
        state.transitions[to_state] = to_state
        state.transition_conditions[to_state] = condition

    def update(self, dt: float) -> None:
        """Update state machine."""
        if self.current_state is None or self.animator is None:
            return

        self.animator.update(dt)

        # Check transitions
        for to_state_name, condition in self.current_state.transition_conditions.items():
            if condition():
                self.set_state(to_state_name)
                break

    def set_state(self, state_name: str) -> None:
        """
        Set current state.

        Args:
            state_name: State name.
        """
        if state_name not in self.states:
            return

        self.current_state = self.states[state_name]
        if self.animator is None:
            self.animator = SpriteAnimator(self.entity, self.ecs)
        self.animator.play(self.current_state.animation)


class AnimationEngine:
    """
    Animation system managing tweens and sprite animations.

    Features:
    - Property tweening with easing functions
    - Sprite animation with frame events
    - Animation state machines with transitions
    - Multiple simultaneous animations
    """

    def __init__(self) -> None:
        """Initialize animation engine."""
        self.tweens: list[PropertyTween] = []
        self.animators: dict[int, SpriteAnimator] = {}
        self.state_machines: dict[int, AnimationStateMachine] = {}

    def create_tween(
        self,
        target: Any,
        property_name: str,
        end_value: float,
        duration: float,
        easing: EasingFunction = EasingFunction.LINEAR,
        on_complete: Callable[[], None] | None = None,
    ) -> PropertyTween:
        """
        Create property tween.

        Args:
            target: Target object.
            property_name: Property to animate.
            end_value: Final value.
            duration: Duration in seconds.
            easing: Easing function.
            on_complete: Completion callback.

        Returns:
            Property tween.
        """
        start_value = getattr(target, property_name, 0.0)
        tween = PropertyTween(
            target=target,
            property_name=property_name,
            start_value=start_value,
            end_value=end_value,
            duration=duration,
            easing=easing,
            on_complete=on_complete,
        )
        self.tweens.append(tween)
        return tween

    def kill_tween(self, tween: PropertyTween) -> None:
        """Kill a tween."""
        if tween in self.tweens:
            self.tweens.remove(tween)

    def kill_all_tweens(self) -> None:
        """Kill all tweens."""
        self.tweens.clear()

    def create_animator(self, entity: Entity, ecs: EntityComponentSystem) -> SpriteAnimator:
        """Create sprite animator."""
        animator = SpriteAnimator(entity, ecs)
        self.animators[entity.index] = animator
        return animator

    def create_state_machine(self, entity: Entity, ecs: EntityComponentSystem) -> AnimationStateMachine:
        """Create animation state machine."""
        sm = AnimationStateMachine(entity, ecs)
        self.state_machines[entity.index] = sm
        return sm

    def update(self, dt: float) -> None:
        """Update all animations."""
        # Update tweens
        finished_tweens = []
        for tween in self.tweens:
            if not tween.update(dt):
                finished_tweens.append(tween)

        for tween in finished_tweens:
            self.tweens.remove(tween)

        # Update sprite animators
        for animator in self.animators.values():
            animator.update(dt)

        # Update state machines
        for sm in self.state_machines.values():
            sm.update(dt)

    def get_active_tween_count(self) -> int:
        """Get number of active tweens."""
        return len(self.tweens)
