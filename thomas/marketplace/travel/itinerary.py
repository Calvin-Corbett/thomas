"""Itinerary management with optimization and conflict detection."""

from datetime import date, datetime, timedelta
from decimal import Decimal

from thomas.marketplace.travel._exceptions import BookingError, ItineraryConflictError
from thomas.marketplace.travel._types import Activity, CarRental, Flight, Hotel, Itinerary, Trip
from thomas.marketplace.travel.geography import DistanceCalculator


class MultiSegmentAssembler:
    """Assemble multi-segment trips (flights + hotels + activities)."""

    def __init__(self) -> None:
        """Initialize assembler."""
        self._itineraries: dict[str, Itinerary] = {}

    def assemble_trip(
        self,
        trip: Trip,
        flights: list[Flight],
        hotels: list[Hotel],
        activities: list[Activity],
        car_rentals: list[CarRental] = None,
    ) -> Itinerary:
        """
        Assemble complete itinerary from segments.

        Args:
            trip: Trip object
            flights: List of flights
            hotels: List of hotels
            activities: List of activities
            car_rentals: Optional car rentals

        Returns:
            Complete Itinerary

        Raises:
            BookingError: If segments don't fit together
        """
        itinerary_id = self._generate_itinerary_id()

        itinerary = Itinerary(
            itinerary_id=itinerary_id,
            trip=trip,
            flights=flights,
            hotels=hotels,
            activities=activities or [],
            car_rentals=car_rentals or [],
        )

        # Validate segments fit together
        self._validate_segment_continuity(itinerary)

        self._itineraries[itinerary_id] = itinerary
        return itinerary

    def _validate_segment_continuity(self, itinerary: Itinerary) -> None:
        """
        Validate that segments connect properly.

        Args:
            itinerary: Itinerary to validate

        Raises:
            BookingError: If segments don't connect
        """
        if not itinerary.flights:
            return

        # Check first flight departure matches trip start
        first_flight = itinerary.flights[0]
        trip_start = itinerary.trip.start_date

        if first_flight.departure_time.date() > trip_start.date():
            raise BookingError("First flight departs after trip start")

        # Check sequential flights connect
        for i in range(len(itinerary.flights) - 1):
            current = itinerary.flights[i]
            next_flight = itinerary.flights[i + 1]

            if current.arrival_time > next_flight.departure_time:
                raise BookingError(
                    f"Flights overlap: arrival {current.arrival_time} > departure {next_flight.departure_time}"
                )

    def _generate_itinerary_id(self) -> str:
        """Generate unique itinerary ID."""
        import random
        import string

        return "IT-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=10))

    def get_itinerary(self, itinerary_id: str) -> Itinerary | None:
        """
        Get itinerary by ID.

        Args:
            itinerary_id: Itinerary identifier

        Returns:
            Itinerary, or None
        """
        return self._itineraries.get(itinerary_id)


class ItineraryOptimizer:
    """Optimize itinerary to minimize wait times and distances."""

    def __init__(self) -> None:
        """Initialize optimizer."""
        self.distance_calc = DistanceCalculator()

    def minimize_wait_times(self, itinerary: Itinerary) -> Itinerary:
        """
        Optimize activities and transfers to minimize wait times.

        Args:
            itinerary: Original itinerary

        Returns:
            Optimized itinerary
        """
        if not itinerary.activities:
            return itinerary

        # Group activities by location and date
        activities_by_date: dict[date, list[Activity]] = {}
        for activity in itinerary.activities:
            activity_date = activity.start_time.date()
            if activity_date not in activities_by_date:
                activities_by_date[activity_date] = []
            activities_by_date[activity_date].append(activity)

        # Sort activities by start time within each day
        for date_key in activities_by_date:
            activities_by_date[date_key].sort(key=lambda a: a.start_time)

        # Rebuild itinerary with optimized order
        optimized_activities = []
        for date_key in sorted(activities_by_date.keys()):
            optimized_activities.extend(activities_by_date[date_key])

        itinerary.activities = optimized_activities
        return itinerary

    def group_by_location(self, itinerary: Itinerary) -> dict[str, list[Activity]]:
        """
        Group activities by location.

        Args:
            itinerary: Itinerary

        Returns:
            Dictionary of location -> activities
        """
        grouped: dict[str, list[Activity]] = {}
        for activity in itinerary.activities:
            if activity.location not in grouped:
                grouped[activity.location] = []
            grouped[activity.location].append(activity)
        return grouped

    def calculate_distance_matrix(self, locations: list[str]) -> dict[tuple[str, str], float]:
        """
        Calculate distances between locations.

        Args:
            locations: List of location names

        Returns:
            Distance matrix as dictionary
        """
        distances: dict[tuple[str, str], float] = {}

        for i, loc1 in enumerate(locations):
            for loc2 in locations[i + 1 :]:
                # Simplified: use string similarity as proxy for distance
                distance = len(set(loc1) - set(loc2)) * 100  # Rough approximation
                distances[(loc1, loc2)] = float(distance)
                distances[(loc2, loc1)] = float(distance)

        return distances


class DayPlanner:
    """Plan daily activities within operating hours."""

    def __init__(self) -> None:
        """Initialize day planner."""
        self._daily_schedules: dict[date, list[dict]] = {}

    def plan_day(
        self,
        plan_date: date,
        activities: list[Activity],
    ) -> dict[str, any]:
        """
        Plan activities for a single day.

        Args:
            plan_date: Date to plan
            activities: Available activities for day

        Returns:
            Daily plan with scheduled activities
        """
        if not activities:
            return {
                "date": plan_date,
                "activities": [],
                "total_time": timedelta(0),
            }

        # Sort activities by start time
        sorted_activities = sorted(activities, key=lambda a: a.start_time)

        # Check for overlaps
        schedule = []
        for activity in sorted_activities:
            # Verify no overlap with previous activity
            if schedule:
                last_activity = schedule[-1]
                if activity.start_time < last_activity["end_time"]:
                    continue  # Skip overlapping activity

            schedule.append(
                {
                    "activity": activity,
                    "start_time": activity.start_time,
                    "end_time": activity.end_time,
                    "duration": activity.duration_minutes,
                }
            )

        # Calculate total day time
        if schedule:
            total_time = schedule[-1]["end_time"] - schedule[0]["start_time"]
        else:
            total_time = timedelta(0)

        plan = {
            "date": plan_date,
            "activities": schedule,
            "total_time": total_time,
            "packed": len(schedule) > 0,
        }

        self._daily_schedules[plan_date] = schedule
        return plan

    def get_daily_schedule(self, plan_date: date) -> list[dict]:
        """
        Get scheduled activities for day.

        Args:
            plan_date: Date

        Returns:
            List of scheduled activities
        """
        return self._daily_schedules.get(plan_date, [])

    def suggest_activities(
        self,
        available_time: timedelta,
        activities: list[Activity],
    ) -> list[Activity]:
        """
        Suggest activities that fit available time.

        Args:
            available_time: Available time
            activities: All available activities

        Returns:
            Activities that fit in available time
        """
        fitting = []
        total_time = timedelta(0)

        for activity in sorted(activities, key=lambda a: a.duration_minutes):
            if total_time + timedelta(minutes=activity.duration_minutes) <= available_time:
                fitting.append(activity)
                total_time += timedelta(minutes=activity.duration_minutes)

        return fitting


class ItinerarySharing:
    """Share and collaborate on itineraries."""

    def __init__(self) -> None:
        """Initialize sharing manager."""
        self._shared_itineraries: dict[str, set[str]] = {}
        self._share_tokens: dict[str, dict] = {}

    def share_itinerary(
        self,
        itinerary_id: str,
        share_with_emails: list[str],
    ) -> dict[str, any]:
        """
        Share itinerary with others.

        Args:
            itinerary_id: Itinerary to share
            share_with_emails: Emails to share with

        Returns:
            Sharing record

        Raises:
            BookingError: If itinerary not found
        """
        if itinerary_id not in self._shared_itineraries:
            self._shared_itineraries[itinerary_id] = set()

        for email in share_with_emails:
            self._shared_itineraries[itinerary_id].add(email)

        return {
            "itinerary_id": itinerary_id,
            "shared_with": share_with_emails,
            "share_date": datetime.utcnow(),
        }

    def get_shared_users(self, itinerary_id: str) -> set[str]:
        """
        Get users itinerary is shared with.

        Args:
            itinerary_id: Itinerary identifier

        Returns:
            Set of user emails
        """
        return self._shared_itineraries.get(itinerary_id, set())

    def generate_share_link(self, itinerary_id: str) -> str:
        """
        Generate shareable link for itinerary.

        Args:
            itinerary_id: Itinerary identifier

        Returns:
            Share token/link
        """
        import secrets

        # Capability token guarding access to a shared itinerary -- must be
        # unguessable, so use a CSPRNG (secrets) not random's Mersenne Twister.
        token = secrets.token_urlsafe(16)

        self._share_tokens[token] = {
            "itinerary_id": itinerary_id,
            "created": datetime.utcnow(),
        }

        return f"itinerary.travel/share/{token}"


class ItineraryVersioning:
    """Track itinerary versions and changes."""

    def __init__(self) -> None:
        """Initialize versioning."""
        self._versions: dict[str, list[dict]] = {}

    def create_version(
        self,
        itinerary_id: str,
        itinerary: Itinerary,
        description: str = "",
    ) -> dict[str, any]:
        """
        Create new itinerary version.

        Args:
            itinerary_id: Itinerary identifier
            itinerary: Itinerary object
            description: Version description

        Returns:
            Version record
        """
        if itinerary_id not in self._versions:
            self._versions[itinerary_id] = []

        version_number = len(self._versions[itinerary_id]) + 1

        version = {
            "version": version_number,
            "created": datetime.utcnow(),
            "description": description,
            "flights_count": len(itinerary.flights),
            "hotels_count": len(itinerary.hotels),
            "activities_count": len(itinerary.activities),
            "total_cost": itinerary.calculate_total_cost(),
        }

        self._versions[itinerary_id].append(version)
        return version

    def get_versions(self, itinerary_id: str) -> list[dict]:
        """
        Get all versions of itinerary.

        Args:
            itinerary_id: Itinerary identifier

        Returns:
            List of versions
        """
        return self._versions.get(itinerary_id, [])


class ConflictDetector:
    """Detect overlapping bookings in itinerary."""

    def __init__(self) -> None:
        """Initialize conflict detector."""
        self._conflict_log: dict[str, list[str]] = {}

    def check_conflicts(self, itinerary: Itinerary) -> tuple[bool, list[str]]:
        """
        Check for booking conflicts.

        Args:
            itinerary: Itinerary to check

        Returns:
            Tuple of (has_conflicts, list of conflict descriptions)

        Raises:
            ItineraryConflictError: If critical conflicts found
        """
        conflicts = []

        # Collect all time-bound events
        events: list[tuple[datetime, datetime, str, str]] = []

        # Add flights
        for flight in itinerary.flights:
            events.append((flight.departure_time, flight.arrival_time, "flight", f"{flight.flight_number}"))

        # Add hotel stays (convert to datetime)
        for hotel in itinerary.hotels:
            # Note: hotels don't have exact times, use check-in/out times
            start_dt = datetime.combine(itinerary.trip.start_date.date(), datetime.min.time())
            end_dt = datetime.combine(itinerary.trip.end_date.date(), datetime.max.time())
            events.append((start_dt, end_dt, "hotel", hotel.name))

        # Add activities
        for activity in itinerary.activities:
            events.append((activity.start_time, activity.end_time, "activity", activity.name))

        # Check for overlaps
        for i in range(len(events)):
            for j in range(i + 1, len(events)):
                start1, end1, type1, name1 = events[i]
                start2, end2, type2, name2 = events[j]

                # Skip if different days
                if start1.date() != start2.date():
                    continue

                # Check for overlap
                if start1 < end2 and start2 < end1:
                    conflict_msg = f"Conflict: {type1} ({name1}) overlaps with {type2} ({name2})"
                    conflicts.append(conflict_msg)

                    # Critical conflicts
                    if type1 == "flight" or type2 == "flight":
                        raise ItineraryConflictError(conflict_msg)

        if itinerary.itinerary_id not in self._conflict_log:
            self._conflict_log[itinerary.itinerary_id] = []

        self._conflict_log[itinerary.itinerary_id].extend(conflicts)

        return len(conflicts) > 0, conflicts

    def get_conflicts(self, itinerary_id: str) -> list[str]:
        """
        Get conflicts for itinerary.

        Args:
            itinerary_id: Itinerary identifier

        Returns:
            List of conflicts
        """
        return self._conflict_log.get(itinerary_id, [])


class BudgetTracker:
    """Track itinerary spending against trip budget."""

    def __init__(self) -> None:
        """Initialize budget tracker."""
        self._budget_allocations: dict[str, dict] = {}

    def allocate_budget(
        self,
        itinerary_id: str,
        trip_budget: Decimal,
        allocations: dict[str, Decimal],
    ) -> dict[str, any]:
        """
        Allocate trip budget across categories.

        Args:
            itinerary_id: Itinerary identifier
            trip_budget: Total budget
            allocations: Category -> budget mapping

        Returns:
            Budget allocation plan
        """
        total_allocated = sum(allocations.values())

        if total_allocated > trip_budget:
            raise BookingError(f"Allocated budget ${total_allocated} exceeds trip budget ${trip_budget}")

        allocation = {
            "itinerary_id": itinerary_id,
            "total_budget": trip_budget,
            "allocations": allocations.copy(),
            "unallocated": trip_budget - total_allocated,
            "created": datetime.utcnow(),
        }

        self._budget_allocations[itinerary_id] = allocation
        return allocation

    def track_spending(
        self,
        itinerary_id: str,
        category: str,
        amount: Decimal,
    ) -> dict[str, any]:
        """
        Record spending against budget.

        Args:
            itinerary_id: Itinerary identifier
            category: Spending category
            amount: Amount spent

        Returns:
            Updated budget tracking
        """
        if itinerary_id not in self._budget_allocations:
            raise BookingError(f"No budget allocated for {itinerary_id}")

        allocation = self._budget_allocations[itinerary_id]
        category_budget = allocation["allocations"].get(category, Decimal("0"))
        spent = allocation.get("spent", {}).get(category, Decimal("0"))
        new_spent = spent + amount

        if new_spent > category_budget:
            raise BookingError(f"Category {category} budget exceeded: ${new_spent} > ${category_budget}")

        if "spent" not in allocation:
            allocation["spent"] = {}

        allocation["spent"][category] = new_spent
        allocation["last_updated"] = datetime.utcnow()

        return allocation

    def get_budget_status(self, itinerary_id: str) -> dict[str, any]:
        """
        Get budget status for itinerary.

        Args:
            itinerary_id: Itinerary identifier

        Returns:
            Budget status
        """
        if itinerary_id not in self._budget_allocations:
            return {}

        allocation = self._budget_allocations[itinerary_id]
        spent = allocation.get("spent", {})
        remaining = {}

        for category, budget in allocation["allocations"].items():
            spent_amount = spent.get(category, Decimal("0"))
            remaining[category] = budget - spent_amount

        total_spent = sum(spent.values())

        return {
            "total_budget": allocation["total_budget"],
            "total_spent": total_spent,
            "remaining": allocation["total_budget"] - total_spent,
            "by_category": remaining,
        }
