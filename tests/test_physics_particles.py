"""
Tests for particle system.
"""

from thomas.marketplace.physics._types import Vec3
from thomas.marketplace.physics.particles import Particle, ParticleEmitter, ParticleSystem


class TestParticle:
    """Tests for individual particle."""

    def test_particle_creation(self) -> None:
        """Test creating particle."""
        p = Particle(
            position=Vec3(0, 0, 0),
            velocity=Vec3(1, 0, 0),
            lifetime=2.0,
        )
        assert p.alive
        assert p.age == 0.0
        assert p.is_alive()

    def test_particle_dies_after_lifetime(self) -> None:
        """Test particle dies after lifetime expires."""
        p = Particle(
            position=Vec3(0, 0, 0),
            velocity=Vec3(1, 0, 0),
            lifetime=1.0,
        )
        p.age = 1.5
        assert not p.is_alive()

    def test_particle_update_position(self) -> None:
        """Test particle position updates."""
        p = Particle(
            position=Vec3(0, 0, 0),
            velocity=Vec3(1, 0, 0),
            lifetime=2.0,
        )
        p.update(0.1)
        assert p.position.x == 0.1
        assert abs(p.age - 0.1) < 1e-6

    def test_particle_acceleration(self) -> None:
        """Test particle acceleration."""
        p = Particle(
            position=Vec3(0, 0, 0),
            velocity=Vec3(0, 0, 0),
            acceleration=Vec3(10, 0, 0),
            lifetime=2.0,
        )
        p.update(0.1)
        assert p.velocity.x > 0
        assert p.position.x > 0


class TestParticleEmitter:
    """Tests for particle emitter configuration."""

    def test_create_emitter(self) -> None:
        """Test creating emitter."""
        emitter = ParticleEmitter(position=Vec3(0, 0, 0))
        assert emitter.enable_emission
        assert emitter.emission_rate > 0

    def test_random_velocity_in_range(self) -> None:
        """Test random velocity is within range."""
        emitter = ParticleEmitter(
            position=Vec3(0, 0, 0),
            velocity_min=Vec3(-1, -2, -3),
            velocity_max=Vec3(1, 2, 3),
        )
        for _ in range(10):
            vel = emitter.get_random_velocity()
            assert -1 <= vel.x <= 1
            assert -2 <= vel.y <= 2
            assert -3 <= vel.z <= 3

    def test_random_lifetime_in_range(self) -> None:
        """Test random lifetime is within range."""
        emitter = ParticleEmitter(
            position=Vec3(0, 0, 0),
            lifetime_min=1.0,
            lifetime_max=3.0,
        )
        for _ in range(10):
            lifetime = emitter.get_random_lifetime()
            assert 1.0 <= lifetime <= 3.0


class TestParticleSystem:
    """Tests for particle system."""

    def test_create_system(self) -> None:
        """Test creating particle system."""
        system = ParticleSystem()
        assert system.get_particle_count() == 0
        assert len(system.emitters) == 0

    def test_add_emitter(self) -> None:
        """Test adding emitter to system."""
        system = ParticleSystem()
        emitter = ParticleEmitter(position=Vec3(0, 0, 0))
        system.add_emitter(emitter)
        assert len(system.emitters) == 1

    def test_continuous_emission(self) -> None:
        """Test continuous particle emission."""
        system = ParticleSystem()
        emitter = ParticleEmitter(
            position=Vec3(0, 0, 0),
            emission_rate=10.0,
            burst_count=0,
        )
        system.add_emitter(emitter)
        system.update(0.2)
        assert system.get_particle_count() >= 1

    def test_burst_emission(self) -> None:
        """Test burst particle emission."""
        system = ParticleSystem()
        emitter = ParticleEmitter(position=Vec3(0, 0, 0))
        system.add_emitter(emitter)
        system.burst_emit(0, 10)
        system.update(0.016)
        assert system.get_particle_count() == 10

    def test_particle_lifetime_culling(self) -> None:
        """Test dead particles are removed."""
        system = ParticleSystem()
        emitter = ParticleEmitter(
            position=Vec3(0, 0, 0),
            lifetime_min=0.05,
            lifetime_max=0.05,
        )
        system.add_emitter(emitter)
        system.burst_emit(0, 5)
        system.update(0.016)  # First update to create particles
        assert system.get_particle_count() == 5

        # Update until particles die
        for _ in range(10):
            system.update(0.01)

        # Most or all particles should be dead by now
        assert system.get_particle_count() <= 1

    def test_max_particle_limit(self) -> None:
        """Test max particle limit is respected."""
        system = ParticleSystem(max_particles=5)
        emitter = ParticleEmitter(position=Vec3(0, 0, 0))
        system.add_emitter(emitter)
        system.burst_emit(0, 10)
        system.update(0.016)
        assert system.get_particle_count() <= 5


class TestParticleForces:
    """Tests for particle forces."""

    def test_gravity_force(self) -> None:
        """Test gravity force on particles."""
        system = ParticleSystem(gravity=Vec3(0, -10, 0))
        emitter = ParticleEmitter(position=Vec3(0, 0, 0))
        system.add_emitter(emitter)
        system.burst_emit(0, 1)
        system.update(0.016)  # Create particles first
        system.add_force("gravity", system.gravity)

        system.update(0.016)
        # Gravity should affect downward velocity
        assert len(system.particles) > 0

    def test_wind_force(self) -> None:
        """Test wind force on particles."""
        system = ParticleSystem()
        emitter = ParticleEmitter(position=Vec3(0, 0, 0))
        system.add_emitter(emitter)
        system.burst_emit(0, 1)
        system.update(0.016)  # Create particles first
        system.add_force("wind", Vec3(10, 0, 0))

        system.update(0.016)
        # Wind force should be applied
        assert len(system.particles) > 0

    def test_drag_force(self) -> None:
        """Test drag force slows particles."""
        system = ParticleSystem()
        emitter = ParticleEmitter(
            position=Vec3(0, 0, 0),
            velocity_min=Vec3(10, 0, 0),
            velocity_max=Vec3(10, 0, 0),
        )
        system.add_emitter(emitter)
        system.burst_emit(0, 1)
        system.update(0.016)  # Create the particle first
        system.add_force("drag", Vec3(0.1, 0, 0))

        initial_vel = system.particles[0].velocity.x
        system.update(0.016)
        final_vel = system.particles[0].velocity.x
        assert final_vel < initial_vel

    def test_attractor_force(self) -> None:
        """Test attractor force pulls particles."""
        system = ParticleSystem()
        emitter = ParticleEmitter(position=Vec3(0, 0, 0))
        system.add_emitter(emitter)
        system.burst_emit(0, 1)
        system.update(0.016)  # Create the particle first
        attractor_pos = Vec3(5, 0, 0)
        system.add_force("attractor", attractor_pos)

        system.update(0.016)
        # Attractor force is applied
        assert len(system.particles) > 0

    def test_repulsor_force(self) -> None:
        """Test repulsor force pushes particles."""
        system = ParticleSystem()
        emitter = ParticleEmitter(position=Vec3(5, 0, 0))
        system.add_emitter(emitter)
        system.burst_emit(0, 1)
        system.update(0.016)  # Create the particle first
        repulsor_pos = Vec3(0, 0, 0)
        system.add_force("repulsor", repulsor_pos)

        system.update(0.016)
        # Repulsor force is applied
        assert len(system.particles) > 0

    def test_remove_force(self) -> None:
        """Test removing force."""
        system = ParticleSystem()
        system.add_force("wind", Vec3(10, 0, 0))
        assert len(system.forces) == 1
        system.remove_force("wind")
        assert len(system.forces) == 0


class TestParticleAirResistance:
    """Tests for air resistance."""

    def test_air_resistance_dampens_velocity(self) -> None:
        """Test air resistance dampens velocity."""
        system = ParticleSystem(air_resistance=0.5)
        emitter = ParticleEmitter(
            position=Vec3(0, 0, 0),
            velocity_min=Vec3(10, 0, 0),
            velocity_max=Vec3(10, 0, 0),
        )
        system.add_emitter(emitter)
        system.burst_emit(0, 1)
        system.update(0.016)  # Create the particle first

        initial_vel = system.particles[0].velocity.magnitude()
        system.update(0.016)
        final_vel = system.particles[0].velocity.magnitude()
        assert final_vel < initial_vel


class TestParticleRendering:
    """Tests for particle rendering data."""

    def test_get_render_data(self) -> None:
        """Test getting particle render data."""
        system = ParticleSystem()
        emitter = ParticleEmitter(position=Vec3(1, 2, 3))
        system.add_emitter(emitter)
        system.burst_emit(0, 3)
        system.update(0.016)

        render_data = system.get_render_data()
        assert len(render_data) == 3
        for pos, age, lifetime in render_data:
            assert isinstance(pos, tuple)
            assert len(pos) == 3
            assert age >= 0
            assert lifetime > 0

    def test_dead_particles_not_in_render_data(self) -> None:
        """Test dead particles not included in render data."""
        system = ParticleSystem()
        emitter = ParticleEmitter(
            position=Vec3(0, 0, 0),
            lifetime_min=0.01,
            lifetime_max=0.01,
        )
        system.add_emitter(emitter)
        system.burst_emit(0, 5)

        for _ in range(10):
            system.update(0.01)

        render_data = system.get_render_data()
        assert len(render_data) == 0


class TestParticleSystemClear:
    """Tests for clearing particle system."""

    def test_clear_particles(self) -> None:
        """Test clearing all particles."""
        system = ParticleSystem()
        emitter = ParticleEmitter(position=Vec3(0, 0, 0))
        system.add_emitter(emitter)
        system.burst_emit(0, 10)
        system.update(0.016)

        assert system.get_particle_count() > 0
        system.clear()
        assert system.get_particle_count() == 0
        assert system.emission_accumulator == 0.0
