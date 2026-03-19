"""Listing management and MLS operations."""

import statistics
from datetime import date
from decimal import Decimal

from thomas.real_estate._exceptions import (
    ListingNotFoundError,
    ValidationError,
)
from thomas.real_estate._types import Listing, Property


class ListingDatabase:
    """Listing database with CRUD and search operations."""

    def __init__(self) -> None:
        """Initialize empty listing database."""
        self._listings: dict[str, Listing] = {}
        self._by_property: dict[str, list[str]] = {}
        self._by_status: dict[str, list[str]] = {}

    def create(self, listing: Listing) -> None:
        """Create a new listing.

        Args:
            listing: Listing instance to create

        Raises:
            ValidationError: If listing data is invalid
            ValueError: If listing already exists
        """
        self._validate_listing(listing)
        if listing.listing_id in self._listings:
            raise ValueError(f"Listing {listing.listing_id} already exists")

        self._listings[listing.listing_id] = listing
        if listing.property_id not in self._by_property:
            self._by_property[listing.property_id] = []
        self._by_property[listing.property_id].append(listing.listing_id)

        if listing.status not in self._by_status:
            self._by_status[listing.status] = []
        self._by_status[listing.status].append(listing.listing_id)

    def read(self, listing_id: str) -> Listing:
        """Read a listing by ID.

        Args:
            listing_id: Unique listing identifier

        Returns:
            Listing instance

        Raises:
            ListingNotFoundError: If listing not found
        """
        if listing_id not in self._listings:
            raise ListingNotFoundError(f"Listing {listing_id} not found")
        return self._listings[listing_id]

    def update(self, listing: Listing) -> None:
        """Update an existing listing.

        Args:
            listing: Listing instance with updated data

        Raises:
            ListingNotFoundError: If listing not found
            ValidationError: If listing data is invalid
        """
        self._validate_listing(listing)
        if listing.listing_id not in self._listings:
            raise ListingNotFoundError(f"Listing {listing.listing_id} not found")

        old_listing = self._listings[listing.listing_id]
        if old_listing.status != listing.status:
            self._by_status[old_listing.status].remove(listing.listing_id)
            if listing.status not in self._by_status:
                self._by_status[listing.status] = []
            self._by_status[listing.status].append(listing.listing_id)

        self._listings[listing.listing_id] = listing

    def delete(self, listing_id: str) -> None:
        """Delete a listing.

        Args:
            listing_id: Unique listing identifier

        Raises:
            ListingNotFoundError: If listing not found
        """
        if listing_id not in self._listings:
            raise ListingNotFoundError(f"Listing {listing_id} not found")

        listing = self._listings.pop(listing_id)
        self._by_property[listing.property_id].remove(listing_id)
        self._by_status[listing.status].remove(listing_id)

    def find_by_property(self, property_id: str) -> list[Listing]:
        """Find all listings for a property.

        Args:
            property_id: Property identifier

        Returns:
            List of listings for property
        """
        listing_ids = self._by_property.get(property_id, [])
        return [self._listings[lid] for lid in listing_ids]

    def find_by_status(self, status: str) -> list[Listing]:
        """Find listings by status.

        Args:
            status: Listing status

        Returns:
            List of listings with status
        """
        listing_ids = self._by_status.get(status, [])
        return [self._listings[lid] for lid in listing_ids]

    def list_all(self) -> list[Listing]:
        """Get all listings.

        Returns:
            List of all listings
        """
        return list(self._listings.values())

    @staticmethod
    def _validate_listing(listing: Listing) -> None:
        """Validate listing data.

        Args:
            listing: Listing to validate

        Raises:
            ValidationError: If validation fails
        """
        if not listing.listing_id:
            raise ValidationError("Listing ID is required")
        if not listing.property_id:
            raise ValidationError("Property ID is required")
        if listing.list_price < 0:
            raise ValidationError("List price must be non-negative")
        if listing.list_date > date.today():
            raise ValidationError("List date cannot be in future")


class ListingLifecycle:
    """Listing status transitions and lifecycle management."""

    VALID_STATUSES = [
        "pre_market",
        "active",
        "pending",
        "sold",
        "withdrawn",
        "expired",
    ]

    @staticmethod
    def validate_status(status: str) -> bool:
        """Check if status is valid.

        Args:
            status: Status to validate

        Returns:
            True if valid status
        """
        return status in ListingLifecycle.VALID_STATUSES

    @staticmethod
    def can_transition(from_status: str, to_status: str) -> bool:
        """Check if status transition is allowed.

        Args:
            from_status: Current status
            to_status: Target status

        Returns:
            True if transition allowed
        """
        valid_transitions = {
            "pre_market": ["active", "withdrawn"],
            "active": ["pending", "sold", "withdrawn", "expired"],
            "pending": ["sold", "withdrawn", "active"],
            "sold": [],
            "withdrawn": ["active"],
            "expired": ["active"],
        }
        return to_status in valid_transitions.get(from_status, [])

    @staticmethod
    def transition(listing: Listing, new_status: str) -> None:
        """Transition listing to new status.

        Args:
            listing: Listing to transition
            new_status: New status

        Raises:
            ValueError: If transition not allowed
        """
        if not ListingLifecycle.can_transition(listing.status, new_status):
            raise ValueError(f"Cannot transition from {listing.status} to {new_status}")
        listing.status = new_status


class ListingMarketing:
    """Listing marketing and description generation."""

    FEATURE_DESCRIPTIONS = {
        "pool": "Sparkling swimming pool",
        "garage": "Attached garage with space",
        "fireplace": "Cozy fireplace",
        "deck": "Beautiful deck perfect for entertaining",
        "hardwood_floors": "Gorgeous hardwood flooring",
        "renovated_kitchen": "Modern, updated kitchen",
        "smart_home": "Smart home automation features",
        "solar_panels": "Eco-friendly solar power system",
        "gated_community": "Secure gated community",
    }

    @staticmethod
    def generate_description(prop: Property, listing: Listing) -> str:
        """Generate listing description from property data.

        Args:
            prop: Property instance
            listing: Listing instance

        Returns:
            Generated listing description
        """
        description = f"Welcome to {prop.address.city}! "
        description += f"This {prop.property_type.value} property features "
        description += f"{prop.bedrooms} bedrooms, {prop.bathrooms} bathrooms, "
        description += f"and {prop.sqft:,} square feet.\n\n"

        description += "Property Details:\n"
        description += f"- Built in {prop.year_built}\n"
        description += f"- Lot size: {prop.lot_sqft:,} sq ft\n"
        description += f"- List price: ${listing.list_price:,.0f}\n\n"

        if prop.features:
            description += "Features:\n"
            for feature in prop.features:
                feature_desc = ListingMarketing.FEATURE_DESCRIPTIONS.get(feature, feature)
                description += f"- {feature_desc}\n"
            description += "\n"

        description += "Don't miss this opportunity!"
        return description

    @staticmethod
    def generate_keywords(prop: Property) -> list[str]:
        """Generate marketing keywords from property data.

        Args:
            prop: Property instance

        Returns:
            List of marketing keywords
        """
        keywords = []

        keywords.append(prop.property_type.value)
        keywords.append(f"{prop.bedrooms} bedroom")
        keywords.append(f"{prop.bathrooms} bathroom")
        keywords.append(prop.address.city)
        keywords.append(prop.address.county or "")

        if prop.bedrooms >= 4:
            keywords.append("family home")
        if prop.sqft > 3000:
            keywords.append("spacious")
        if prop.sqft < 1500:
            keywords.append("cozy")
        if prop.age_years() < 5:
            keywords.append("new construction")
        if any("pool" in f for f in prop.features):
            keywords.append("pool home")
        if any("water" in f for f in prop.features):
            keywords.append("waterfront")

        return [k for k in keywords if k]


class ListingAnalytics:
    """Listing performance analytics and metrics."""

    @staticmethod
    def calculate_dom(listing: Listing) -> int:
        """Calculate days on market.

        Args:
            listing: Listing instance

        Returns:
            Days on market
        """
        return (date.today() - listing.list_date).days

    @staticmethod
    def calculate_engagement_rate(listing: Listing) -> float:
        """Calculate listing engagement rate.

        Engagement = (Views + Saves + Inquiries) / Days On Market

        Args:
            listing: Listing instance

        Returns:
            Engagement rate (interactions per day)
        """
        dom = max(ListingAnalytics.calculate_dom(listing), 1)
        total_engagement = listing.views_count + listing.saves_count + listing.inquiries_count
        return total_engagement / dom

    @staticmethod
    def calculate_price_per_sqft(listing: Listing, sqft: int) -> Decimal:
        """Calculate listing price per square foot.

        Args:
            listing: Listing instance
            sqft: Property square footage

        Returns:
            Price per square foot
        """
        if sqft == 0:
            return Decimal("0")
        current_price = listing.current_price or listing.list_price
        return current_price / Decimal(sqft)

    @staticmethod
    def get_average_inquiry_rate(listings: list[Listing]) -> float:
        """Calculate average inquiry rate across listings.

        Args:
            listings: List of listings

        Returns:
            Average inquiries per listing
        """
        if not listings:
            return 0.0
        return statistics.mean(l.inquiries_count for l in listings)


class PriceReductions:
    """Price reduction tracking and analysis."""

    @staticmethod
    def add_reduction(listing: Listing, new_price: Decimal, reduction_date: date) -> None:
        """Record a price reduction.

        Args:
            listing: Listing instance
            new_price: New list price
            reduction_date: Date of reduction

        Raises:
            ValueError: If new price is higher than current
        """
        current_price = listing.current_price or listing.list_price
        if new_price > current_price:
            raise ValueError("New price must be lower than current price")

        listing.price_reductions.append((new_price, reduction_date))
        listing.current_price = new_price

    @staticmethod
    def get_total_reduction(listing: Listing) -> Decimal:
        """Calculate total price reduction.

        Args:
            listing: Listing instance

        Returns:
            Total reduction from original list price
        """
        current_price = listing.current_price or listing.list_price
        return listing.list_price - current_price

    @staticmethod
    def get_reduction_percentage(listing: Listing) -> Decimal:
        """Calculate price reduction as percentage.

        Args:
            listing: Listing instance

        Returns:
            Reduction percentage (e.g., 0.05 for 5% reduction)
        """
        if listing.list_price == 0:
            return Decimal("0")
        total_reduction = PriceReductions.get_total_reduction(listing)
        return total_reduction / listing.list_price

    @staticmethod
    def get_reduction_rate(listing: Listing) -> Decimal | None:
        """Calculate average price reduction per day on market.

        Args:
            listing: Listing instance

        Returns:
            Reduction per day or None if no reductions
        """
        if not listing.price_reductions:
            return None

        dom = max((date.today() - listing.list_date).days, 1)
        total_reduction = PriceReductions.get_total_reduction(listing)
        return total_reduction / Decimal(dom)


class OpenHouseManagement:
    """Open house scheduling and tracking."""

    @staticmethod
    def schedule_open_house(listing: Listing, open_house_date: date) -> None:
        """Schedule an open house.

        Args:
            listing: Listing instance
            open_house_date: Date of open house

        Raises:
            ValueError: If date is in past
        """
        if open_house_date < date.today():
            raise ValueError("Open house date cannot be in the past")
        listing.open_houses.append(open_house_date)
        listing.open_houses.sort()

    @staticmethod
    def get_upcoming_open_houses(listing: Listing) -> list[date]:
        """Get upcoming open houses.

        Args:
            listing: Listing instance

        Returns:
            List of upcoming open house dates
        """
        today = date.today()
        return [oh for oh in listing.open_houses if oh >= today]

    @staticmethod
    def get_past_open_houses(listing: Listing) -> list[date]:
        """Get past open houses.

        Args:
            listing: Listing instance

        Returns:
            List of past open house dates
        """
        today = date.today()
        return [oh for oh in listing.open_houses if oh < today]


class ListingSyndication:
    """Listing distribution to multiple platforms."""

    PLATFORMS = [
        "mls",
        "zillow",
        "realtor_com",
        "trulia",
        "redfin",
        "facebook",
        "instagram",
    ]

    def __init__(self) -> None:
        """Initialize syndication tracker."""
        self._syndications: dict[str, dict[str, bool]] = {}

    def register_listing(self, listing_id: str) -> None:
        """Register listing for syndication.

        Args:
            listing_id: Listing identifier
        """
        self._syndications[listing_id] = {platform: False for platform in self.PLATFORMS}

    def syndicate_to_platform(self, listing_id: str, platform: str) -> None:
        """Mark listing as syndicated to platform.

        Args:
            listing_id: Listing identifier
            platform: Platform name

        Raises:
            ValueError: If listing or platform not found
        """
        if listing_id not in self._syndications:
            raise ValueError(f"Listing {listing_id} not registered")
        if platform not in self.PLATFORMS:
            raise ValueError(f"Unknown platform {platform}")

        self._syndications[listing_id][platform] = True

    def get_syndication_status(self, listing_id: str) -> dict[str, bool]:
        """Get syndication status for listing.

        Args:
            listing_id: Listing identifier

        Returns:
            Dictionary of platform syndication status
        """
        return self._syndications.get(listing_id, {})

    def get_syndicated_count(self, listing_id: str) -> int:
        """Get count of platforms listing is syndicated to.

        Args:
            listing_id: Listing identifier

        Returns:
            Number of platforms syndicated to
        """
        status = self.get_syndication_status(listing_id)
        return sum(1 for synced in status.values() if synced)
