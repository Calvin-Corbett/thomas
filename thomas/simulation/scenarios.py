"""
Pre-built simulation scenarios demonstrating module capabilities.

Includes: SIR epidemic, supply chain, traffic, predator-prey, and bank queue.
"""

import math
import random
from dataclasses import dataclass

from ._types import AgentAction
from .agent_based import Environment, SimpleAgent
from .monte_carlo import RandomVariableGenerator


@dataclass
class ScenarioConfig:
    """Base configuration for scenarios."""

    duration: float = 1000.0
    random_seed: int | None = None


@dataclass
class EpidemicConfig(ScenarioConfig):
    """SIR epidemic scenario configuration."""

    population: int = 1000
    initial_infected: int = 5
    contact_rate: float = 5.0  # contacts per day
    transmission_prob: float = 0.3
    recovery_rate: float = 0.1
    immunity_loss_rate: float = 0.01


class EpidemicScenario:
    """
    SIR (Susceptible-Infected-Recovered) epidemic model.

    Tracks disease spread through population via agent contacts.
    """

    def __init__(self, config: EpidemicConfig) -> None:
        """Initialize epidemic scenario."""
        self.config = config
        self.population = []
        self.rng = RandomVariableGenerator(config.random_seed)

        # Statistics
        self.susceptible_history: list[int] = []
        self.infected_history: list[int] = []
        self.recovered_history: list[int] = []

    def setup(self) -> Environment:
        """Create epidemic environment and agents."""
        env = Environment(
            width=100.0,
            height=100.0,
            grid_based=False,
            wraparound=True,
        )

        # Create susceptible agents
        for i in range(self.config.population):
            agent = EpidemicAgent("susceptible")
            pos = (
                self.rng.uniform(0, 100),
                self.rng.uniform(0, 100),
            )
            agent.position = pos
            agent.state = {"status": "susceptible", "recovery_time": 0}
            env.add_agent(agent)
            self.population.append(agent)

        # Infect initial cases
        for i in range(self.config.initial_infected):
            agent = random.choice(self.population)
            agent.state["status"] = "infected"

        return env

    def step(self, env: Environment, current_time: float) -> None:
        """Execute one epidemic time step."""
        # Contacts between agents
        for agent in self.population:
            if agent.state["status"] != "infected":
                continue

            # Find nearby agents
            nearby = env.agents_near(agent.position, 5.0)

            for other in nearby:
                if other.agent_id == agent.agent_id:
                    continue

                if other.state["status"] == "susceptible":
                    if random.random() < self.config.transmission_prob:
                        other.state["status"] = "infected"
                        other.state["recovery_time"] = current_time + self.rng.exponential(self.config.recovery_rate)

        # Recovery
        for agent in self.population:
            if agent.state["status"] == "infected":
                if current_time >= agent.state.get("recovery_time", float("inf")):
                    agent.state["status"] = "recovered"

        # Immunity loss
        for agent in self.population:
            if agent.state["status"] == "recovered":
                if random.random() < self.config.immunity_loss_rate * 0.001:
                    agent.state["status"] = "susceptible"

        # Record statistics
        s = sum(1 for a in self.population if a.state["status"] == "susceptible")
        i = sum(1 for a in self.population if a.state["status"] == "infected")
        r = sum(1 for a in self.population if a.state["status"] == "recovered")

        self.susceptible_history.append(s)
        self.infected_history.append(i)
        self.recovered_history.append(r)

    def run(self) -> dict:
        """Run epidemic simulation."""
        env = self.setup()

        for t in range(int(self.config.duration)):
            self.step(env, float(t))

        return {
            "susceptible": self.susceptible_history,
            "infected": self.infected_history,
            "recovered": self.recovered_history,
            "peak_infected": max(self.infected_history),
            "peak_time": self.infected_history.index(max(self.infected_history)),
            "attack_rate": self.recovered_history[-1] / self.config.population,
        }


class EpidemicAgent(SimpleAgent):
    """Agent in epidemic scenario."""

    def decide(self, environment: Environment) -> list[AgentAction]:
        """Random movement."""
        if not self.alive:
            return []

        # Random walk
        angle = random.uniform(0, 2 * math.pi)
        dx = math.cos(angle)
        dy = math.sin(angle)

        action = AgentAction(
            agent_id=self.agent_id,
            action_type="move",
            data={"dx": dx, "dy": dy},
        )

        return [action]


@dataclass
class SupplyChainConfig(ScenarioConfig):
    """Supply chain scenario configuration."""

    factory_capacity: float = 100.0
    warehouse_capacity: float = 200.0
    retail_capacity: float = 50.0
    demand_mean: float = 10.0
    demand_std: float = 2.0
    factory_production_time: float = 1.0
    transport_time: float = 2.0


class SupplyChainScenario:
    """
    Supply chain with factory, warehouse, and retail stores.

    Tracks inventory levels, stockouts, and service levels.
    """

    def __init__(self, config: SupplyChainConfig) -> None:
        """Initialize supply chain scenario."""
        self.config = config
        self.rng = RandomVariableGenerator(config.random_seed)

        # Inventory levels
        self.factory_inventory = config.factory_capacity
        self.warehouse_inventory = config.warehouse_capacity
        self.retail_inventory = config.retail_capacity

        # Statistics
        self.retail_demand_history: list[float] = []
        self.retail_inventory_history: list[float] = []
        self.stockout_events: int = 0

    def step(self, current_time: float) -> None:
        """Execute one supply chain time step."""
        # Generate retail demand
        demand = self.rng.normal(
            self.config.demand_mean,
            self.config.demand_std,
        )
        demand = max(0, demand)

        # Retail fulfillment
        fulfilled = min(demand, self.retail_inventory)
        self.retail_inventory -= fulfilled

        if fulfilled < demand:
            self.stockout_events += 1

        # Replenishment (simple: bring warehouse to capacity)
        if self.warehouse_inventory > 0:
            transfer = min(
                self.warehouse_inventory,
                self.config.retail_capacity - self.retail_inventory,
            )
            self.warehouse_inventory -= transfer
            self.retail_inventory += transfer

        if self.factory_inventory > 0:
            transfer = min(
                self.factory_inventory,
                self.config.warehouse_capacity - self.warehouse_inventory,
            )
            self.factory_inventory -= transfer
            self.warehouse_inventory += transfer

        # Production (simple: linear increase)
        production = min(
            10,
            self.config.factory_capacity - self.factory_inventory,
        )
        self.factory_inventory += production

        self.retail_demand_history.append(demand)
        self.retail_inventory_history.append(self.retail_inventory)

    def run(self) -> dict:
        """Run supply chain simulation."""
        for t in range(int(self.config.duration)):
            self.step(float(t))

        avg_demand = sum(self.retail_demand_history) / len(self.retail_demand_history)
        avg_inventory = sum(self.retail_inventory_history) / len(self.retail_inventory_history)
        service_level = (sum(self.retail_demand_history) - self.stockout_events * avg_demand) / sum(
            self.retail_demand_history
        )

        return {
            "avg_demand": avg_demand,
            "avg_inventory": avg_inventory,
            "service_level": service_level,
            "stockout_events": self.stockout_events,
            "inventory_history": self.retail_inventory_history,
        }


@dataclass
class TrafficConfig(ScenarioConfig):
    """Traffic simulation configuration."""

    num_vehicles: int = 100
    road_length: float = 1000.0
    speed_mean: float = 50.0
    speed_std: float = 10.0
    arrival_rate: float = 0.5
    collision_distance: float = 5.0


class TrafficScenario:
    """
    Traffic simulation with vehicles on road.

    Tracks throughput, average speed, and collision risk.
    """

    def __init__(self, config: TrafficConfig) -> None:
        """Initialize traffic scenario."""
        self.config = config
        self.rng = RandomVariableGenerator(config.random_seed)

        self.vehicles: list[dict] = []
        self.speed_history: list[float] = []
        self.throughput: int = 0
        self.collisions: int = 0

    def step(self, current_time: float) -> None:
        """Execute one traffic time step."""
        # New vehicle arrivals
        if random.random() < self.config.arrival_rate:
            vehicle = {
                "position": 0.0,
                "speed": self.rng.normal(
                    self.config.speed_mean,
                    self.config.speed_std,
                ),
                "id": len(self.vehicles),
            }
            vehicle["speed"] = max(0, vehicle["speed"])
            self.vehicles.append(vehicle)

        # Move vehicles
        for vehicle in self.vehicles:
            vehicle["position"] += vehicle["speed"]

        # Remove vehicles exiting road
        exited = [v for v in self.vehicles if v["position"] >= self.config.road_length]
        self.throughput += len(exited)
        self.vehicles = [v for v in self.vehicles if v["position"] < self.config.road_length]

        # Collision detection
        for i, v1 in enumerate(self.vehicles):
            for v2 in self.vehicles[i + 1 :]:
                dist = abs(v1["position"] - v2["position"])
                if dist < self.config.collision_distance:
                    self.collisions += 1

        # Average speed
        if self.vehicles:
            avg_speed = sum(v["speed"] for v in self.vehicles) / len(self.vehicles)
            self.speed_history.append(avg_speed)

    def run(self) -> dict:
        """Run traffic simulation."""
        for t in range(int(self.config.duration)):
            self.step(float(t))

        avg_speed = sum(self.speed_history) / len(self.speed_history) if self.speed_history else 0

        return {
            "throughput": self.throughput,
            "avg_speed": avg_speed,
            "collisions": self.collisions,
            "collision_rate": self.collisions / max(1, self.throughput),
            "speed_history": self.speed_history,
        }


@dataclass
class PredatorPreyConfig(ScenarioConfig):
    """Predator-prey scenario configuration."""

    initial_prey: int = 100
    initial_predators: int = 10
    prey_birth_rate: float = 0.1
    prey_death_rate: float = 0.05
    predator_birth_efficiency: float = 0.5
    predator_death_rate: float = 0.02
    capture_probability: float = 0.05
    world_width: float = 100.0
    world_height: float = 100.0


class PredatorPreyScenario:
    """
    Lotka-Volterra predator-prey dynamics.

    Tracks population oscillations and species interactions.
    """

    def __init__(self, config: PredatorPreyConfig) -> None:
        """Initialize predator-prey scenario."""
        self.config = config
        self.rng = RandomVariableGenerator(config.random_seed)

        self.prey: list[dict] = []
        self.predators: list[dict] = []

        self.prey_history: list[int] = []
        self.predator_history: list[int] = []

    def setup(self) -> None:
        """Create initial populations."""
        for i in range(self.config.initial_prey):
            self.prey.append(
                {
                    "id": i,
                    "position": (
                        self.rng.uniform(0, self.config.world_width),
                        self.rng.uniform(0, self.config.world_height),
                    ),
                }
            )

        for i in range(self.config.initial_predators):
            self.predators.append(
                {
                    "id": i,
                    "position": (
                        self.rng.uniform(0, self.config.world_width),
                        self.rng.uniform(0, self.config.world_height),
                    ),
                    "energy": 50,
                }
            )

    def step(self) -> None:
        """Execute one time step."""
        # Prey reproduction
        new_prey = []
        for p in self.prey:
            if random.random() < self.config.prey_birth_rate:
                new_prey.append(
                    {
                        "id": len(self.prey) + len(new_prey),
                        "position": (
                            p["position"][0] + self.rng.uniform(-1, 1),
                            p["position"][1] + self.rng.uniform(-1, 1),
                        ),
                    }
                )

        self.prey.extend(new_prey)

        # Prey death
        self.prey = [p for p in self.prey if random.random() > self.config.prey_death_rate]

        # Predation
        for predator in self.predators:
            nearby_prey = [p for p in self.prey if self._distance(predator["position"], p["position"]) < 10]

            for prey in nearby_prey:
                if random.random() < self.config.capture_probability:
                    self.prey.remove(prey)
                    predator["energy"] += self.config.predator_birth_efficiency

        # Predator reproduction
        new_predators = []
        for pred in self.predators:
            if pred["energy"] > 40 and random.random() < 0.1:
                new_predators.append(
                    {
                        "id": len(self.predators) + len(new_predators),
                        "position": (
                            pred["position"][0] + self.rng.uniform(-1, 1),
                            pred["position"][1] + self.rng.uniform(-1, 1),
                        ),
                        "energy": 25,
                    }
                )
                pred["energy"] -= 25

        self.predators.extend(new_predators)

        # Predator death/aging
        self.predators = [
            p for p in self.predators if p["energy"] > 0 and random.random() > self.config.predator_death_rate
        ]

        for pred in self.predators:
            pred["energy"] -= 1

        self.prey_history.append(len(self.prey))
        self.predator_history.append(len(self.predators))

    def _distance(self, pos1: tuple[float, float], pos2: tuple[float, float]) -> float:
        """Compute distance between positions."""
        return math.sqrt((pos1[0] - pos2[0]) ** 2 + (pos1[1] - pos2[1]) ** 2)

    def run(self) -> dict:
        """Run predator-prey simulation."""
        self.setup()

        for t in range(int(self.config.duration)):
            self.step()

        return {
            "prey_history": self.prey_history,
            "predator_history": self.predator_history,
            "final_prey": len(self.prey),
            "final_predators": len(self.predators),
            "prey_mean": sum(self.prey_history) / len(self.prey_history),
            "predator_mean": sum(self.predator_history) / len(self.predator_history),
        }


@dataclass
class BankQueueConfig(ScenarioConfig):
    """Bank queue scenario configuration."""

    num_tellers: int = 3
    customer_arrival_rate: float = 2.0
    service_time_mean: float = 3.0
    service_time_std: float = 1.0
    customer_patience: float = 10.0


class BankQueueScenario:
    """
    Bank with multiple tellers and customer queue.

    Tracks service levels, wait times, and queue length.
    """

    def __init__(self, config: BankQueueConfig) -> None:
        """Initialize bank queue scenario."""
        self.config = config
        self.rng = RandomVariableGenerator(config.random_seed)

        self.queue: list[dict] = []
        self.tellers: list[dict] = [{"busy": False, "service_end": 0} for _ in range(config.num_tellers)]

        self.completed_customers: list[dict] = []
        self.abandoned_customers: int = 0

    def step(self, current_time: float) -> None:
        """Execute one time step."""
        # New arrivals
        if random.random() < self.config.customer_arrival_rate * 0.01:
            customer = {
                "arrival_time": current_time,
                "service_start": None,
                "service_end": None,
            }
            self.queue.append(customer)

        # Check service completion
        for i, teller in enumerate(self.tellers):
            if teller["busy"] and current_time >= teller["service_end"]:
                teller["busy"] = False

        # Assign customers to free tellers
        free_tellers = [i for i, t in enumerate(self.tellers) if not t["busy"]]

        for teller_id in free_tellers:
            if not self.queue:
                break

            customer = self.queue.pop(0)
            customer["service_start"] = current_time
            service_duration = self.rng.normal(
                self.config.service_time_mean,
                self.config.service_time_std,
            )
            service_duration = max(0.5, service_duration)
            customer["service_end"] = current_time + service_duration

            self.tellers[teller_id]["busy"] = True
            self.tellers[teller_id]["service_end"] = customer["service_end"]
            self.completed_customers.append(customer)

        # Customer abandonment (too long wait)
        remaining_queue = []
        for customer in self.queue:
            wait_time = current_time - customer["arrival_time"]
            if wait_time < self.config.customer_patience:
                remaining_queue.append(customer)
            else:
                self.abandoned_customers += 1

        self.queue = remaining_queue

    def run(self) -> dict:
        """Run bank queue simulation."""
        for t in range(int(self.config.duration)):
            self.step(float(t))

        wait_times = [
            c["service_start"] - c["arrival_time"] for c in self.completed_customers if c["service_start"] is not None
        ]

        avg_wait = sum(wait_times) / len(wait_times) if wait_times else 0
        max_wait = max(wait_times) if wait_times else 0

        return {
            "customers_served": len(self.completed_customers),
            "customers_abandoned": self.abandoned_customers,
            "avg_wait_time": avg_wait,
            "max_wait_time": max_wait,
            "service_level_5min": sum(1 for w in wait_times if w <= 5) / len(wait_times) if wait_times else 0,
        }
