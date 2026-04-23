"""
Quest generation including templates, chains, and NPC dialogue.
"""

import random
from dataclasses import dataclass, field
from enum import Enum, auto

from thomas.marketplace.procgen._exceptions import InvalidConfigError


class QuestType(Enum):
    """Enumeration of quest types."""

    FETCH = auto()
    KILL = auto()
    ESCORT = auto()
    EXPLORE = auto()
    DELIVER = auto()
    DEFEND = auto()
    INVESTIGATE = auto()
    RESCUE = auto()


class QuestStatus(Enum):
    """Enumeration of quest status."""

    NOT_STARTED = auto()
    IN_PROGRESS = auto()
    COMPLETE = auto()
    FAILED = auto()


@dataclass
class QuestObjective:
    """Represents a single objective in a quest."""

    description: str
    objective_type: str  # "collect", "kill", "reach", "talk"
    target: str
    target_count: int = 1
    current_count: int = 0
    complete: bool = False

    def advance(self, amount: int = 1) -> None:
        """Advance objective progress."""
        self.current_count += amount
        if self.current_count >= self.target_count:
            self.complete = True

    @property
    def progress_string(self) -> str:
        """Get progress as a string."""
        if self.target_count == 1:
            return "Complete" if self.complete else "In Progress"
        return f"{self.current_count}/{self.target_count}"


@dataclass
class Quest:
    """Represents a complete quest."""

    title: str
    description: str
    quest_type: QuestType
    giver_name: str
    objectives: list[QuestObjective] = field(default_factory=list)
    rewards_gold: int = 0
    rewards_experience: int = 0
    status: QuestStatus = QuestStatus.NOT_STARTED
    level_requirement: int = 1
    prerequisites: list[str] = field(default_factory=list)
    parent_quest: str | None = None
    follow_up_quests: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """Check if all objectives are complete."""
        return all(obj.complete for obj in self.objectives)

    def start(self) -> None:
        """Start the quest."""
        self.status = QuestStatus.IN_PROGRESS

    def complete(self) -> None:
        """Mark quest as complete."""
        if self.is_complete:
            self.status = QuestStatus.COMPLETE


@dataclass
class QuestGiver:
    """Represents an NPC who gives quests."""

    name: str
    location: str
    personality: str  # "gruff", "friendly", "mysterious", "noble"
    known_quests: list[str] = field(default_factory=list)

    def get_greeting(self) -> str:
        """Get a greeting from the NPC."""
        greetings = {
            "gruff": [
                "What do you want?",
                "State your business.",
                "Well? Speak up.",
            ],
            "friendly": [
                "Welcome, friend!",
                "Good to see you!",
                "How can I help you today?",
            ],
            "mysterious": [
                "I've been expecting you...",
                "Something brings you here.",
                "Curious, you should arrive now.",
            ],
            "noble": [
                "Greetings, adventurer.",
                "I am pleased to make your acquaintance.",
                "Well met.",
            ],
        }

        options = greetings.get(self.personality, greetings["friendly"])
        return random.choice(options)

    def get_quest_pitch(self, quest: Quest) -> str:
        """Get the NPC's pitch for a quest."""
        pitches = {
            "gruff": f"I've got a job that needs doing. {quest.description}",
            "friendly": f"I could really use your help with something. {quest.description}",
            "mysterious": f"There's something I need taken care of. {quest.description}",
            "noble": f"I would be most grateful if you could assist me. {quest.description}",
        }

        return pitches.get(
            self.personality,
            f"Can you help me with this? {quest.description}",
        )


@dataclass
class QuestGenerator:
    """Generate quests and quest chains."""

    seed: int = 42
    world_state: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize generator."""
        random.seed(self.seed)

    def generate_quest(
        self,
        quest_type: QuestType | None = None,
        level: int = 1,
        giver_name: str = "Unknown",
    ) -> Quest:
        """
        Generate a single quest.

        Args:
            quest_type: Type of quest (random if None)
            level: Character level for scaling
            giver_name: Name of quest giver

        Returns:
            Generated Quest object
        """
        if quest_type is None:
            quest_type = random.choice(list(QuestType))

        if quest_type == QuestType.FETCH:
            return self._generate_fetch_quest(level, giver_name)
        elif quest_type == QuestType.KILL:
            return self._generate_kill_quest(level, giver_name)
        elif quest_type == QuestType.ESCORT:
            return self._generate_escort_quest(level, giver_name)
        elif quest_type == QuestType.EXPLORE:
            return self._generate_explore_quest(level, giver_name)
        elif quest_type == QuestType.DELIVER:
            return self._generate_deliver_quest(level, giver_name)
        elif quest_type == QuestType.DEFEND:
            return self._generate_defend_quest(level, giver_name)
        elif quest_type == QuestType.INVESTIGATE:
            return self._generate_investigate_quest(level, giver_name)
        else:  # RESCUE
            return self._generate_rescue_quest(level, giver_name)

    def generate_quest_chain(self, num_quests: int = 3, starting_level: int = 1) -> list[Quest]:
        """
        Generate a chain of related quests.

        Args:
            num_quests: Number of quests in the chain
            starting_level: Starting level for progression

        Returns:
            List of connected Quest objects
        """
        if num_quests < 1:
            raise InvalidConfigError("Must generate at least 1 quest", "num_quests")

        quests = []
        giver_name = self._generate_npc_name()

        for i in range(num_quests):
            level = starting_level + i
            quest = self.generate_quest(level=level, giver_name=giver_name)

            if i > 0:
                quest.parent_quest = quests[i - 1].title
                quests[i - 1].follow_up_quests.append(quest.title)
                quest.prerequisites.append(quests[i - 1].title)

            quests.append(quest)

        return quests

    def _generate_fetch_quest(self, level: int, giver_name: str) -> Quest:
        """Generate a fetch/collect quest."""
        items = [
            "Golden Amulet",
            "Ancient Scroll",
            "Rare Herbs",
            "Shimmering Crystal",
            "Ancient Artifact",
        ]
        item = random.choice(items)
        quantity = random.randint(1, 5)

        quest = Quest(
            title=f"Retrieve the {item}",
            description=f"I need you to retrieve {quantity} {item}(s). This task is important to me.",
            quest_type=QuestType.FETCH,
            giver_name=giver_name,
            level_requirement=level,
        )

        quest.objectives.append(
            QuestObjective(
                description=f"Retrieve {item}",
                objective_type="collect",
                target=item,
                target_count=quantity,
            )
        )

        quest.rewards_gold = level * 50 + quantity * 10
        quest.rewards_experience = level * 100 + quantity * 20

        return quest

    def _generate_kill_quest(self, level: int, giver_name: str) -> Quest:
        """Generate a kill/combat quest."""
        enemies = [
            "Bandits",
            "Goblins",
            "Wolves",
            "Undead",
            "Cultists",
            "Thugs",
        ]
        enemy = random.choice(enemies)
        quantity = random.randint(3, 10)

        quest = Quest(
            title=f"Slay the {enemy}",
            description=f"The {enemy} have been causing trouble. Deal with {quantity} of them.",
            quest_type=QuestType.KILL,
            giver_name=giver_name,
            level_requirement=level,
        )

        quest.objectives.append(
            QuestObjective(
                description=f"Defeat {enemy}",
                objective_type="kill",
                target=enemy,
                target_count=quantity,
            )
        )

        quest.rewards_gold = level * 75
        quest.rewards_experience = level * 150

        return quest

    def _generate_escort_quest(self, level: int, giver_name: str) -> Quest:
        """Generate an escort quest."""
        destinations = ["Village", "Castle", "Temple", "Outpost", "Port"]
        destination = random.choice(destinations)

        quest = Quest(
            title=f"Escort to {destination}",
            description=f"I need safe passage to {destination}. Can you protect me?",
            quest_type=QuestType.ESCORT,
            giver_name=giver_name,
            level_requirement=level,
        )

        quest.objectives.append(
            QuestObjective(
                description=f"Escort {giver_name} to {destination}",
                objective_type="reach",
                target=destination,
                target_count=1,
            )
        )

        quest.rewards_gold = level * 100
        quest.rewards_experience = level * 200

        return quest

    def _generate_explore_quest(self, level: int, giver_name: str) -> Quest:
        """Generate an exploration quest."""
        locations = [
            "Abandoned Ruins",
            "Dark Forest",
            "Mountain Peak",
            "Underground Caverns",
            "Lost Temple",
        ]
        location = random.choice(locations)

        quest = Quest(
            title=f"Explore {location}",
            description=f"I've heard tales of {location}. Can you investigate?",
            quest_type=QuestType.EXPLORE,
            giver_name=giver_name,
            level_requirement=level,
        )

        quest.objectives.append(
            QuestObjective(
                description=f"Map out {location}",
                objective_type="reach",
                target=location,
                target_count=1,
            )
        )

        quest.rewards_gold = level * 60
        quest.rewards_experience = level * 120

        return quest

    def _generate_deliver_quest(self, level: int, giver_name: str) -> Quest:
        """Generate a delivery quest."""
        recipient = self._generate_npc_name()
        locations = ["Village", "Town", "Castle", "Inn", "Temple"]
        location = random.choice(locations)

        quest = Quest(
            title=f"Deliver Message to {recipient}",
            description=f"Please deliver this message to {recipient} at the {location}.",
            quest_type=QuestType.DELIVER,
            giver_name=giver_name,
            level_requirement=level,
        )

        quest.objectives.append(
            QuestObjective(
                description=f"Deliver message to {recipient}",
                objective_type="talk",
                target=recipient,
                target_count=1,
            )
        )

        quest.rewards_gold = level * 40
        quest.rewards_experience = level * 80

        return quest

    def _generate_defend_quest(self, level: int, giver_name: str) -> Quest:
        """Generate a defend/protect quest."""
        targets = ["Village", "Outpost", "Caravan", "Settlement", "Fortress"]
        target = random.choice(targets)
        duration = random.randint(3, 7)

        quest = Quest(
            title=f"Defend {target}",
            description=f"We need protection. Can you defend {target} for {duration} days?",
            quest_type=QuestType.DEFEND,
            giver_name=giver_name,
            level_requirement=level,
        )

        quest.objectives.append(
            QuestObjective(
                description=f"Defend {target}",
                objective_type="reach",
                target=target,
                target_count=1,
            )
        )

        quest.rewards_gold = level * 150
        quest.rewards_experience = level * 250

        return quest

    def _generate_investigate_quest(self, level: int, giver_name: str) -> Quest:
        """Generate an investigation quest."""
        mysteries = [
            "Missing Persons",
            "Strange Happenings",
            "Mysterious Disappearances",
            "Unusual Deaths",
            "Theft",
        ]
        mystery = random.choice(mysteries)

        quest = Quest(
            title=f"Investigate {mystery}",
            description=f"There has been a case of {mystery} in the area. Please look into it.",
            quest_type=QuestType.INVESTIGATE,
            giver_name=giver_name,
            level_requirement=level,
        )

        quest.objectives.append(
            QuestObjective(
                description=f"Find the cause of {mystery}",
                objective_type="collect",
                target="Clues",
                target_count=3,
            )
        )

        quest.rewards_gold = level * 80
        quest.rewards_experience = level * 160

        return quest

    def _generate_rescue_quest(self, level: int, giver_name: str) -> Quest:
        """Generate a rescue quest."""
        captive = self._generate_npc_name()
        captors = random.choice(["Bandits", "Cult", "Monsters", "Evil Wizard"])

        quest = Quest(
            title=f"Rescue {captive}",
            description=f"{captive} has been captured by the {captors}! Please save them!",
            quest_type=QuestType.RESCUE,
            giver_name=giver_name,
            level_requirement=level,
        )

        quest.objectives.append(
            QuestObjective(
                description=f"Defeat the {captors}",
                objective_type="kill",
                target=captors,
                target_count=5,
            )
        )

        quest.objectives.append(
            QuestObjective(
                description=f"Free {captive}",
                objective_type="talk",
                target=captive,
                target_count=1,
            )
        )

        quest.rewards_gold = level * 120
        quest.rewards_experience = level * 200

        return quest

    def _generate_npc_name(self) -> str:
        """Generate a random NPC name."""
        first_names = [
            "Aldric",
            "Beatrice",
            "Cedric",
            "Diana",
            "Edmund",
            "Fiona",
            "Gregory",
            "Helena",
        ]
        last_names = [
            "Smith",
            "Johnson",
            "Miller",
            "Davis",
            "Wilson",
            "Moore",
            "Taylor",
            "Anderson",
        ]

        return f"{random.choice(first_names)} {random.choice(last_names)}"

    def generate_dialogue(self, quest_giver: QuestGiver, quest: Quest, stage: str = "offer") -> str:
        """
        Generate NPC dialogue for quest interaction.

        Args:
            quest_giver: The NPC giving the quest
            quest: The quest being discussed
            stage: Stage of quest ("offer", "accept", "progress", "complete")

        Returns:
            Dialogue string
        """
        if stage == "offer":
            return quest_giver.get_quest_pitch(quest)
        elif stage == "accept":
            responses = [
                f"Excellent! I knew I could count on you. {quest.description}",
                f"Thank you! {quest.description}",
                f"Wonderful! Please, {quest.description}",
            ]
            return random.choice(responses)
        elif stage == "progress":
            return f"Any progress on the {quest.title}?"
        else:  # complete
            return f"You did it! Thank you so much. Here's your reward: {quest.rewards_gold} gold."
