"""Travel geography module for airports, distances, and routing."""

import math
from datetime import datetime, timedelta, timezone

from pytz import timezone as pytz_timezone

from thomas.marketplace.travel._exceptions import InvalidAirportError
from thomas.marketplace.travel._types import Airport


class AirportDatabase:
    """Airport database with IATA codes, coordinates, and timezones."""

    def __init__(self) -> None:
        """Initialize airport database with major airports."""
        self._airports: dict[str, Airport] = {}
        self._load_major_airports()

    def _load_major_airports(self) -> None:
        """Load major world airports."""
        major_airports = [
            Airport(
                iata_code="JFK",
                icao_code="KJFK",
                name="John F. Kennedy",
                city="New York",
                country="USA",
                latitude=40.6413,
                longitude=-73.7781,
                timezone="America/New_York",
                altitude_feet=13,
                is_hub=True,
                terminal_count=7,
            ),
            Airport(
                iata_code="LAX",
                icao_code="KLAX",
                name="Los Angeles",
                city="Los Angeles",
                country="USA",
                latitude=33.9425,
                longitude=-118.4081,
                timezone="America/Los_Angeles",
                altitude_feet=126,
                is_hub=True,
                terminal_count=9,
            ),
            Airport(
                iata_code="ORD",
                icao_code="KORD",
                name="Chicago O'Hare",
                city="Chicago",
                country="USA",
                latitude=41.9742,
                longitude=-87.9073,
                timezone="America/Chicago",
                altitude_feet=682,
                is_hub=True,
                terminal_count=7,
            ),
            Airport(
                iata_code="DFW",
                icao_code="KDFW",
                name="Dallas/Fort Worth",
                city="Dallas",
                country="USA",
                latitude=32.8975,
                longitude=-97.0382,
                timezone="America/Chicago",
                altitude_feet=607,
                is_hub=True,
                terminal_count=7,
            ),
            Airport(
                iata_code="ATL",
                icao_code="KATL",
                name="Atlanta Hartsfield-Jackson",
                city="Atlanta",
                country="USA",
                latitude=33.6407,
                longitude=-84.4277,
                timezone="America/New_York",
                altitude_feet=1027,
                is_hub=True,
                terminal_count=7,
            ),
            Airport(
                iata_code="LHR",
                icao_code="EGLL",
                name="London Heathrow",
                city="London",
                country="UK",
                latitude=51.4700,
                longitude=-0.4543,
                timezone="Europe/London",
                altitude_feet=83,
                is_hub=True,
                terminal_count=7,
            ),
            Airport(
                iata_code="CDG",
                icao_code="LFPG",
                name="Paris Charles de Gaulle",
                city="Paris",
                country="France",
                latitude=49.0097,
                longitude=2.5479,
                timezone="Europe/Paris",
                altitude_feet=390,
                is_hub=True,
                terminal_count=4,
            ),
            Airport(
                iata_code="NRT",
                icao_code="RJAA",
                name="Narita",
                city="Tokyo",
                country="Japan",
                latitude=35.7653,
                longitude=140.3929,
                timezone="Asia/Tokyo",
                altitude_feet=141,
                is_hub=True,
                terminal_count=3,
            ),
            Airport(
                iata_code="SFO",
                icao_code="KSFO",
                name="San Francisco",
                city="San Francisco",
                country="USA",
                latitude=37.6213,
                longitude=-122.3790,
                timezone="America/Los_Angeles",
                altitude_feet=13,
                is_hub=True,
                terminal_count=4,
            ),
            Airport(
                iata_code="MIA",
                icao_code="KMIA",
                name="Miami International",
                city="Miami",
                country="USA",
                latitude=25.7959,
                longitude=-80.2870,
                timezone="America/New_York",
                altitude_feet=7,
                is_hub=True,
                terminal_count=5,
            ),
        ]

        for airport in major_airports:
            self._airports[airport.iata_code] = airport

    def get_airport(self, iata_code: str) -> Airport:
        """
        Get airport by IATA code.

        Args:
            iata_code: IATA airport code

        Returns:
            Airport object

        Raises:
            InvalidAirportError: If airport not found
        """
        airport = self._airports.get(iata_code.upper())
        if not airport:
            raise InvalidAirportError(f"Airport {iata_code} not found")
        return airport

    def list_airports(self) -> list[Airport]:
        """
        List all airports in database.

        Returns:
            List of Airport objects
        """
        return list(self._airports.values())

    def add_airport(self, airport: Airport) -> None:
        """
        Add airport to database.

        Args:
            airport: Airport object to add
        """
        self._airports[airport.iata_code] = airport

    def search_by_city(self, city: str) -> list[Airport]:
        """
        Search airports by city name.

        Args:
            city: City name

        Returns:
            List of Airport objects matching city
        """
        return [a for a in self._airports.values() if a.city.lower() == city.lower()]

    def search_hubs(self) -> list[Airport]:
        """
        Get all major hub airports.

        Returns:
            List of hub Airport objects
        """
        return [a for a in self._airports.values() if a.is_hub]


class DistanceCalculator:
    """Calculate distances between airports using Haversine formula."""

    @staticmethod
    def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        Calculate great-circle distance between two coordinates.

        Uses Haversine formula for accurate distance calculation on Earth.

        Args:
            lat1: Latitude of first point in degrees
            lon1: Longitude of first point in degrees
            lat2: Latitude of second point in degrees
            lon2: Longitude of second point in degrees

        Returns:
            Distance in kilometers
        """
        earth_radius_km = 6371.0

        # Convert to radians
        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)

        # Differences
        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad

        # Haversine formula
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
        c = 2 * math.asin(math.sqrt(a))
        return earth_radius_km * c

    @classmethod
    def distance_between_airports(cls, airport1: Airport, airport2: Airport) -> float:
        """
        Calculate distance between two airports.

        Args:
            airport1: First airport
            airport2: Second airport

        Returns:
            Distance in kilometers
        """
        return cls.haversine_distance(airport1.latitude, airport1.longitude, airport2.latitude, airport2.longitude)


class FlightTimeEstimator:
    """Estimate flight times based on distance and conditions."""

    # Average cruise speed in km/h (accounting for jet aircraft)
    CRUISE_SPEED_KMH = 850

    # Wind factor multiplier (headwind/tailwind average out)
    WIND_FACTOR = 1.0

    # Time for taxi, takeoff, climb, descent, landing (minutes)
    GROUND_OPERATIONS_TIME = 45

    @classmethod
    def estimate_flight_time(cls, distance_km: float, is_direct: bool = True) -> int:
        """
        Estimate flight time for route.

        Args:
            distance_km: Distance in kilometers
            is_direct: Whether flight is direct

        Returns:
            Estimated flight time in minutes
        """
        cruise_time = (distance_km / cls.CRUISE_SPEED_KMH) * 60
        flight_time = cruise_time + cls.GROUND_OPERATIONS_TIME

        # Add time for connections on indirect flights
        if not is_direct:
            flight_time += 120  # 2 hours for connections

        return int(flight_time)


class TimezoneHandler:
    """Handle timezone conversions for flight times."""

    @staticmethod
    def get_local_time(utc_time: datetime, timezone_str: str) -> datetime:
        """
        Convert UTC time to local timezone.

        Args:
            utc_time: UTC datetime
            timezone_str: IANA timezone string

        Returns:
            Local datetime with timezone info
        """
        tz = pytz_timezone(timezone_str)
        if utc_time.tzinfo is None:
            utc_time = utc_time.replace(tzinfo=timezone.utc)
        return utc_time.astimezone(tz)

    @staticmethod
    def get_utc_time(local_time: datetime, timezone_str: str) -> datetime:
        """
        Convert local time to UTC.

        Args:
            local_time: Local datetime
            timezone_str: IANA timezone string

        Returns:
            UTC datetime
        """
        tz = pytz_timezone(timezone_str)
        if local_time.tzinfo is None:
            local_time = tz.localize(local_time)
        return local_time.astimezone(timezone.utc)

    @staticmethod
    def calculate_arrival_time(
        departure_time: datetime,
        origin_tz: str,
        destination_tz: str,
        flight_duration_minutes: int,
    ) -> datetime:
        """
        Calculate arrival time considering timezone offset.

        Args:
            departure_time: Departure time in origin timezone
            origin_tz: Origin timezone string
            destination_tz: Destination timezone string
            flight_duration_minutes: Flight duration in minutes

        Returns:
            Arrival time in destination timezone
        """
        # Convert departure to UTC
        utc_departure = TimezoneHandler.get_utc_time(departure_time, origin_tz)

        # Add flight duration
        utc_arrival = utc_departure + timedelta(minutes=flight_duration_minutes)

        # Convert to destination timezone
        return TimezoneHandler.get_local_time(utc_arrival, destination_tz)

    @staticmethod
    def time_difference_hours(tz1: str, tz2: str) -> float:
        """
        Get time difference between two timezones.

        Args:
            tz1: First timezone string
            tz2: Second timezone string

        Returns:
            Time difference in hours (positive if tz2 is ahead)
        """
        now = datetime.now(timezone.utc)
        local1 = TimezoneHandler.get_local_time(now, tz1)
        local2 = TimezoneHandler.get_local_time(now, tz2)
        return (local2.utcoffset().total_seconds() - local1.utcoffset().total_seconds()) / 3600


class VisaRequirementDatabase:
    """Visa requirement database for travel destinations."""

    def __init__(self) -> None:
        """Initialize visa requirement database."""
        # Simplified visa requirement matrix
        # In production, would have comprehensive data
        self._requirements: dict[tuple[str, str], str] = {
            ("USA", "USA"): "none",
            ("USA", "MEX"): "tourist_card",
            ("USA", "CAN"): "none",
            ("USA", "GBR"): "none",
            ("USA", "FRA"): "schengen",
            ("USA", "JPN"): "none",
            ("GBR", "USA"): "esta",
            ("GBR", "FRA"): "none",
            ("GBR", "JPN"): "none",
        }

    def get_requirement(self, from_country: str, to_country: str) -> str:
        """
        Get visa requirement for travel route.

        Args:
            from_country: Origin country code
            to_country: Destination country code

        Returns:
            Visa requirement type: "none", "visa_on_arrival", "visa_required", etc.
        """
        return self._requirements.get((from_country, to_country), "visa_required")

    def requires_visa(self, from_country: str, to_country: str) -> bool:
        """
        Check if visa is required.

        Args:
            from_country: Origin country code
            to_country: Destination country code

        Returns:
            True if visa is required
        """
        requirement = self.get_requirement(from_country, to_country)
        return requirement in ("visa_required", "advance_visa", "evisitor")


class TravelAdvisoryDatabase:
    """Travel advisory information by destination."""

    def __init__(self) -> None:
        """Initialize travel advisory database."""
        self._advisories: dict[str, str] = {
            "USA": "safe",
            "CAN": "safe",
            "MEX": "caution",
            "GBR": "safe",
            "FRA": "safe",
            "JPN": "safe",
        }

    def get_advisory(self, country: str) -> str:
        """
        Get travel advisory for country.

        Args:
            country: Country code

        Returns:
            Advisory level: "safe", "caution", "warning", "do_not_travel"
        """
        return self._advisories.get(country, "unknown")

    def is_safe_to_travel(self, country: str) -> bool:
        """
        Check if travel is advisable to country.

        Args:
            country: Country code

        Returns:
            True if travel is safe
        """
        advisory = self.get_advisory(country)
        return advisory == "safe"


class PopularRouteFinder:
    """Identify popular flight routes and hub connectivity."""

    def __init__(self) -> None:
        """Initialize popular route finder."""
        self._route_popularity: dict[tuple[str, str], int] = {
            ("JFK", "LAX"): 1500,
            ("LAX", "SFO"): 1200,
            ("JFK", "ORD"): 900,
            ("LAX", "LHR"): 800,
            ("JFK", "CDG"): 750,
            ("ORD", "DFW"): 700,
        }

    def get_popularity_score(self, origin: str, destination: str) -> int:
        """
        Get popularity score for route.

        Args:
            origin: Origin airport IATA code
            destination: Destination airport IATA code

        Returns:
            Popularity score (higher = more popular)
        """
        return self._route_popularity.get((origin, destination), 0)

    def get_popular_routes(self, limit: int = 10) -> list[tuple[str, str, int]]:
        """
        Get most popular routes.

        Args:
            limit: Number of routes to return

        Returns:
            List of (origin, destination, score) tuples
        """
        sorted_routes = sorted(self._route_popularity.items(), key=lambda x: x[1], reverse=True)
        return [(origin, dest, score) for (origin, dest), score in sorted_routes[:limit]]


class HubConnectivityAnalyzer:
    """Analyze hub connectivity and connection opportunities."""

    def __init__(self, airport_db: AirportDatabase) -> None:
        """
        Initialize hub connectivity analyzer.

        Args:
            airport_db: Airport database instance
        """
        self.airport_db = airport_db

    def get_hub_airports(self) -> list[Airport]:
        """
        Get all hub airports.

        Returns:
            List of major hub airports
        """
        return self.airport_db.search_hubs()

    def is_good_connection_hub(self, airport: Airport, max_distance_km: float = 2000) -> bool:
        """
        Check if airport is good connection hub for pair of routes.

        Args:
            airport: Airport to check
            max_distance_km: Maximum flight distance for good connectivity

        Returns:
            True if airport is a good hub
        """
        return airport.is_hub and airport.terminal_count >= 3
