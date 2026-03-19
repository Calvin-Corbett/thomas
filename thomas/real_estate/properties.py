"""Property management module for CRUD operations and analysis."""

import math
from datetime import date
from decimal import Decimal

from thomas.real_estate._exceptions import (
    PropertyNotFoundError,
    ValidationError,
)
from thomas.real_estate._types import (
    Address,
    Property,
    PropertyType,
)


class PropertyDatabase:
    """In-memory property database with CRUD operations.

    Provides storage and retrieval of property records with validation.
    """

    def __init__(self) -> None:
        """Initialize empty property database."""
        self._properties: dict[str, Property] = {}
        self._by_address: dict[str, str] = {}

    def create(self, prop: Property) -> None:
        """Create a new property record.

        Args:
            prop: Property instance to create

        Raises:
            ValidationError: If property data is invalid
            ValueError: If property ID already exists
        """
        self._validate_property(prop)
        if prop.property_id in self._properties:
            raise ValueError(f"Property {prop.property_id} already exists")
        self._properties[prop.property_id] = prop
        self._by_address[str(prop.address)] = prop.property_id

    def read(self, property_id: str) -> Property:
        """Read a property record by ID.

        Args:
            property_id: Unique property identifier

        Returns:
            Property instance

        Raises:
            PropertyNotFoundError: If property not found
        """
        if property_id not in self._properties:
            raise PropertyNotFoundError(f"Property {property_id} not found")
        return self._properties[property_id]

    def update(self, prop: Property) -> None:
        """Update an existing property record.

        Args:
            prop: Property instance with updated data

        Raises:
            PropertyNotFoundError: If property not found
            ValidationError: If property data is invalid
        """
        self._validate_property(prop)
        if prop.property_id not in self._properties:
            raise PropertyNotFoundError(f"Property {prop.property_id} not found")
        self._properties[prop.property_id] = prop

    def delete(self, property_id: str) -> None:
        """Delete a property record.

        Args:
            property_id: Unique property identifier

        Raises:
            PropertyNotFoundError: If property not found
        """
        if property_id not in self._properties:
            raise PropertyNotFoundError(f"Property {property_id} not found")
        prop = self._properties.pop(property_id)
        del self._by_address[str(prop.address)]

    def list_all(self) -> list[Property]:
        """Get all properties.

        Returns:
            List of all Property instances
        """
        return list(self._properties.values())

    def find_by_address(self, address: Address) -> Property | None:
        """Find property by address.

        Args:
            address: Address to search for

        Returns:
            Property instance or None if not found
        """
        property_id = self._by_address.get(str(address))
        if property_id:
            return self._properties[property_id]
        return None

    def find_by_type(self, property_type: PropertyType) -> list[Property]:
        """Find all properties of a given type.

        Args:
            property_type: PropertyType to filter by

        Returns:
            List of matching Property instances
        """
        return [p for p in self._properties.values() if p.property_type == property_type]

    def find_by_location(self, city: str, state: str) -> list[Property]:
        """Find properties by city and state.

        Args:
            city: City name
            state: State abbreviation

        Returns:
            List of matching Property instances
        """
        return [p for p in self._properties.values() if p.address.city == city and p.address.state == state]

    @staticmethod
    def _validate_property(prop: Property) -> None:
        """Validate property data.

        Args:
            prop: Property to validate

        Raises:
            ValidationError: If validation fails
        """
        if not prop.property_id:
            raise ValidationError("Property ID is required")
        if prop.bedrooms < 0:
            raise ValidationError("Bedrooms cannot be negative")
        if prop.bathrooms < 0:
            raise ValidationError("Bathrooms cannot be negative")
        if prop.sqft <= 0:
            raise ValidationError("Square footage must be positive")
        if prop.lot_sqft <= 0:
            raise ValidationError("Lot square footage must be positive")
        if prop.year_built < 1800 or prop.year_built > date.today().year + 1:
            raise ValidationError("Year built is invalid")


class PropertyFeatures:
    """Property feature tracking and analysis."""

    COMMON_FEATURES = {
        "garage": "Garage parking",
        "pool": "Swimming pool",
        "fireplace": "Fireplace",
        "deck": "Deck or patio",
        "basement": "Basement",
        "hardwood_floors": "Hardwood floors",
        "air_conditioning": "Air conditioning",
        "heating_system": "Heating system",
        "water_view": "Water view",
        "mountain_view": "Mountain view",
        "renovated_kitchen": "Renovated kitchen",
        "renovated_bathroom": "Renovated bathroom",
        "smart_home": "Smart home features",
        "solar_panels": "Solar panels",
        "gated_community": "Gated community",
    }

    @staticmethod
    def validate_feature(feature: str) -> bool:
        """Check if feature is valid.

        Args:
            feature: Feature name to validate

        Returns:
            True if feature is recognized
        """
        return feature in PropertyFeatures.COMMON_FEATURES

    @staticmethod
    def feature_description(feature: str) -> str | None:
        """Get description of a feature.

        Args:
            feature: Feature name

        Returns:
            Feature description or None if not found
        """
        return PropertyFeatures.COMMON_FEATURES.get(feature)

    @staticmethod
    def features_value_boost(features: list[str]) -> Decimal:
        """Estimate value boost from features.

        Args:
            features: List of property features

        Returns:
            Estimated percentage value increase (as decimal, e.g., 0.10 for 10%)
        """
        boost_map = {
            "pool": Decimal("0.08"),
            "water_view": Decimal("0.15"),
            "mountain_view": Decimal("0.10"),
            "renovated_kitchen": Decimal("0.05"),
            "solar_panels": Decimal("0.07"),
            "smart_home": Decimal("0.03"),
        }
        total_boost = Decimal("0")
        for feature in features:
            total_boost += boost_map.get(feature, Decimal("0"))
        return total_boost


class PropertyHistory:
    """Property ownership and transaction history tracking."""

    @staticmethod
    def add_owner(prop: Property, owner_name: str, acquisition_date: date, sale_date: date) -> None:
        """Add ownership record to property history.

        Args:
            prop: Property instance to update
            owner_name: Owner name
            acquisition_date: When owner acquired property
            sale_date: When owner sold property
        """
        prop.ownership_history.append((owner_name, acquisition_date, sale_date))

    @staticmethod
    def get_ownership_duration(acquisition_date: date, sale_date: date) -> tuple[int, int]:
        """Calculate ownership duration.

        Args:
            acquisition_date: Purchase date
            sale_date: Sale date

        Returns:
            Tuple of (years, months)
        """
        delta = sale_date - acquisition_date
        years = delta.days // 365
        months = (delta.days % 365) // 30
        return (years, months)

    @staticmethod
    def estimate_holding_cost(
        purchase_price: Decimal,
        annual_tax: Decimal,
        holding_years: int,
        maintenance_rate: Decimal = Decimal("0.01"),
    ) -> Decimal:
        """Estimate total cost of holding property.

        Args:
            purchase_price: Original purchase price
            annual_tax: Annual property tax
            holding_years: Years held
            maintenance_rate: Annual maintenance as % of value (default 1%)

        Returns:
            Total holding costs
        """
        tax_cost = annual_tax * holding_years
        maintenance_cost = purchase_price * maintenance_rate * holding_years
        return tax_cost + maintenance_cost


class PropertyTax:
    """Property tax estimation and calculation."""

    @staticmethod
    def calculate_annual_tax(assessed_value: Decimal, mill_rate: Decimal) -> Decimal:
        """Calculate annual property tax using mill rate.

        Mill rate is tax per $1000 of assessed value.

        Args:
            assessed_value: Assessed property value
            mill_rate: Mill rate (e.g., 10.5 for 10.5 mills per $1000)

        Returns:
            Annual property tax amount
        """
        tax_per_thousand = mill_rate / Decimal("1000")
        return assessed_value * tax_per_thousand

    @staticmethod
    def estimate_assessment_ratio(market_value: Decimal, assessed_value: Decimal) -> Decimal:
        """Calculate assessment ratio (assessed value / market value).

        Args:
            market_value: Current market value
            assessed_value: Tax-assessed value

        Returns:
            Assessment ratio as decimal
        """
        if market_value == 0:
            return Decimal("0")
        return assessed_value / market_value

    @staticmethod
    def project_tax_increase(current_tax: Decimal, years: int, annual_increase_rate: Decimal) -> Decimal:
        """Project future property tax with annual increases.

        Args:
            current_tax: Current annual tax
            years: Number of years to project
            annual_increase_rate: Annual increase rate (e.g., 0.03 for 3%)

        Returns:
            Projected annual tax after specified years
        """
        return current_tax * ((1 + annual_increase_rate) ** years)


class GeospatialSearch:
    """Geospatial property search using distance calculations."""

    @staticmethod
    def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two coordinates using haversine formula.

        Args:
            lat1: Latitude of first point
            lon1: Longitude of first point
            lat2: Latitude of second point
            lon2: Longitude of second point

        Returns:
            Distance in miles
        """
        earth_radius_miles = 3959

        lat1_rad = math.radians(lat1)
        lon1_rad = math.radians(lon1)
        lat2_rad = math.radians(lat2)
        lon2_rad = math.radians(lon2)

        dlat = lat2_rad - lat1_rad
        dlon = lon2_rad - lon1_rad

        a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        distance = earth_radius_miles * c

        return distance

    @staticmethod
    def search_radius(
        properties: list[Property],
        center_lat: float,
        center_lon: float,
        radius_miles: float,
    ) -> list[Property]:
        """Find properties within radius of coordinates.

        Args:
            properties: List of properties to search
            center_lat: Search center latitude
            center_lon: Search center longitude
            radius_miles: Search radius in miles

        Returns:
            List of properties within radius
        """
        results = []
        for prop in properties:
            if not prop.address.has_coordinates():
                continue
            distance = GeospatialSearch.haversine_distance(
                center_lat,
                center_lon,
                prop.address.latitude,
                prop.address.longitude,
            )
            if distance <= radius_miles:
                results.append(prop)
        return results


class PropertyComparison:
    """Property comparison and scoring."""

    @staticmethod
    def compare_square_footage(prop1: Property, prop2: Property) -> Decimal:
        """Compare properties by square footage.

        Args:
            prop1: First property
            prop2: Second property

        Returns:
            Difference in square footage (prop1 - prop2)
        """
        return Decimal(prop1.sqft - prop2.sqft)

    @staticmethod
    def calculate_price_per_sqft(price: Decimal, sqft: int) -> Decimal:
        """Calculate price per square foot.

        Args:
            price: Property price or value
            sqft: Square footage

        Returns:
            Price per square foot
        """
        if sqft == 0:
            return Decimal("0")
        return price / Decimal(sqft)

    @staticmethod
    def compare_price_per_sqft(price1: Decimal, sqft1: int, price2: Decimal, sqft2: int) -> Decimal:
        """Compare two properties by price per square foot.

        Args:
            price1: First property price
            sqft1: First property square footage
            price2: Second property price
            sqft2: Second property square footage

        Returns:
            Difference in price per square foot
        """
        ppsf1 = PropertyComparison.calculate_price_per_sqft(price1, sqft1)
        ppsf2 = PropertyComparison.calculate_price_per_sqft(price2, sqft2)
        return ppsf1 - ppsf2


class PropertyScoring:
    """Property scoring system using weighted features."""

    def __init__(self) -> None:
        """Initialize property scoring with default weights."""
        self.weights = {
            "location": Decimal("0.25"),
            "condition": Decimal("0.20"),
            "size": Decimal("0.20"),
            "features": Decimal("0.15"),
            "age": Decimal("0.10"),
            "price": Decimal("0.10"),
        }

    def set_weights(self, weights: dict[str, Decimal]) -> None:
        """Set custom scoring weights.

        Args:
            weights: Dictionary of weights (must sum to 1.0)

        Raises:
            ValueError: If weights don't sum to 1.0
        """
        total = sum(weights.values())
        if abs(total - Decimal("1")) > Decimal("0.001"):
            raise ValueError("Weights must sum to 1.0")
        self.weights = weights

    def score_location(self, address: Address) -> Decimal:
        """Score property location (0-100).

        Args:
            address: Address to score

        Returns:
            Location score
        """
        score = Decimal("50")
        if address.has_coordinates():
            score += Decimal("25")
        if address.county:
            score += Decimal("25")
        return min(score, Decimal("100"))

    def score_condition(self, age: int) -> Decimal:
        """Score property condition based on age (0-100).

        Args:
            age: Property age in years

        Returns:
            Condition score
        """
        if age < 10:
            return Decimal("100")
        elif age < 25:
            return Decimal("85")
        elif age < 50:
            return Decimal("70")
        else:
            return Decimal("50")

    def score_size(self, sqft: int, median_sqft: int = 2000) -> Decimal:
        """Score property size relative to median (0-100).

        Args:
            sqft: Property square footage
            median_sqft: Median property size (default 2000)

        Returns:
            Size score
        """
        if sqft == 0:
            return Decimal("0")
        ratio = Decimal(sqft) / Decimal(median_sqft)
        if ratio >= Decimal("0.8") and ratio <= Decimal("1.2"):
            return Decimal("100")
        elif ratio < Decimal("0.8"):
            return Decimal("100") * ratio
        else:
            return Decimal("100") * (Decimal("2") - ratio)

    def score_features(self, features: list[str]) -> Decimal:
        """Score property based on features (0-100).

        Args:
            features: List of property features

        Returns:
            Feature score
        """
        if not features:
            return Decimal("50")
        score = Decimal("50") + Decimal(len(features)) * Decimal("5")
        return min(score, Decimal("100"))

    def score_price(self, price: Decimal, market_median: Decimal = Decimal("500000")) -> Decimal:
        """Score property price (0-100).

        Args:
            price: Property price
            market_median: Market median price (default $500k)

        Returns:
            Price score
        """
        if price == 0:
            return Decimal("50")
        ratio = price / market_median
        if ratio >= Decimal("0.8") and ratio <= Decimal("1.2"):
            return Decimal("100")
        elif ratio < Decimal("0.8"):
            return Decimal("100") * (ratio + Decimal("0.2"))
        else:
            return max(Decimal("50"), Decimal("120") - Decimal("100") * ratio)

    def overall_score(
        self,
        prop: Property,
        price: Decimal | None = None,
        market_median: Decimal | None = None,
    ) -> Decimal:
        """Calculate overall property score (0-100).

        Args:
            prop: Property to score
            price: Property price (if None, uses last_sale_price)
            market_median: Market median price

        Returns:
            Overall score weighted by category
        """
        location_score = self.score_location(prop.address)
        condition_score = self.score_condition(prop.age_years())
        size_score = self.score_size(prop.sqft)
        feature_score = self.score_features(prop.features)
        price_val = price or prop.last_sale_price or Decimal("500000")
        price_score = self.score_price(price_val, market_median or Decimal("500000"))

        total = (
            location_score * self.weights["location"]
            + condition_score * self.weights["condition"]
            + size_score * self.weights["size"]
            + feature_score * self.weights["features"]
            + price_score * self.weights["price"]
        )
        return total
