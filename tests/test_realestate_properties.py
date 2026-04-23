"""Tests for properties module."""

from datetime import date
from decimal import Decimal

import pytest

from thomas.marketplace.real_estate._exceptions import (
    PropertyNotFoundError,
)
from thomas.marketplace.real_estate._types import (
    Address,
    Property,
    PropertyType,
    ZoningType,
)
from thomas.marketplace.real_estate.properties import (
    GeospatialSearch,
    PropertyComparison,
    PropertyDatabase,
    PropertyFeatures,
    PropertyHistory,
    PropertyScoring,
    PropertyTax,
)


class TestPropertyDatabase:
    """Test PropertyDatabase CRUD operations."""

    def setup_method(self):
        """Set up test fixtures."""
        self.db = PropertyDatabase()
        self.address = Address(
            street="123 Main St",
            city="Springfield",
            state="IL",
            zip_code="62701",
        )
        self.property = Property(
            property_id="prop001",
            address=self.address,
            property_type=PropertyType.SINGLE_FAMILY,
            zoning_type=ZoningType.RESIDENTIAL,
            bedrooms=3,
            bathrooms=Decimal("2"),
            sqft=1800,
            lot_sqft=7500,
            year_built=2005,
        )

    def test_create_property(self):
        """Test creating a property."""
        self.db.create(self.property)
        assert len(self.db.list_all()) == 1

    def test_create_duplicate_raises_error(self):
        """Test creating duplicate property raises error."""
        self.db.create(self.property)
        with pytest.raises(ValueError):
            self.db.create(self.property)

    def test_read_property(self):
        """Test reading a property."""
        self.db.create(self.property)
        retrieved = self.db.read("prop001")
        assert retrieved.property_id == "prop001"
        assert retrieved.bedrooms == 3

    def test_read_nonexistent_raises_error(self):
        """Test reading nonexistent property raises error."""
        with pytest.raises(PropertyNotFoundError):
            self.db.read("nonexistent")

    def test_update_property(self):
        """Test updating a property."""
        self.db.create(self.property)
        self.property.bedrooms = 4
        self.db.update(self.property)
        retrieved = self.db.read("prop001")
        assert retrieved.bedrooms == 4

    def test_delete_property(self):
        """Test deleting a property."""
        self.db.create(self.property)
        self.db.delete("prop001")
        with pytest.raises(PropertyNotFoundError):
            self.db.read("prop001")

    def test_find_by_type(self):
        """Test finding properties by type."""
        self.db.create(self.property)
        results = self.db.find_by_type(PropertyType.SINGLE_FAMILY)
        assert len(results) == 1

    def test_find_by_location(self):
        """Test finding properties by location."""
        self.db.create(self.property)
        results = self.db.find_by_location("Springfield", "IL")
        assert len(results) == 1


class TestPropertyFeatures:
    """Test property features."""

    def test_validate_feature(self):
        """Test feature validation."""
        assert PropertyFeatures.validate_feature("pool")
        assert not PropertyFeatures.validate_feature("nonexistent")

    def test_feature_description(self):
        """Test getting feature description."""
        desc = PropertyFeatures.feature_description("pool")
        assert desc is not None
        assert "pool" in desc.lower()

    def test_features_value_boost(self):
        """Test calculating feature value boost."""
        features = ["pool", "water_view"]
        boost = PropertyFeatures.features_value_boost(features)
        assert boost > Decimal("0")


class TestPropertyHistory:
    """Test property ownership history."""

    def test_add_owner(self):
        """Test adding ownership record."""
        address = Address(
            street="123 Main St",
            city="Springfield",
            state="IL",
            zip_code="62701",
        )
        prop = Property(
            property_id="prop001",
            address=address,
            property_type=PropertyType.SINGLE_FAMILY,
            zoning_type=ZoningType.RESIDENTIAL,
            bedrooms=3,
            bathrooms=Decimal("2"),
            sqft=1800,
            lot_sqft=7500,
            year_built=2005,
        )
        PropertyHistory.add_owner(prop, "John Doe", date(2010, 1, 1), date(2020, 1, 1))
        assert len(prop.ownership_history) == 1

    def test_ownership_duration(self):
        """Test calculating ownership duration."""
        years, months = PropertyHistory.get_ownership_duration(date(2010, 1, 1), date(2020, 6, 1))
        assert years == 10
        assert months >= 5

    def test_holding_cost(self):
        """Test estimating holding costs."""
        cost = PropertyHistory.estimate_holding_cost(
            Decimal("500000"),
            Decimal("5000"),
            10,
        )
        assert cost > Decimal("0")


class TestPropertyTax:
    """Test property tax calculations."""

    def test_annual_tax_calculation(self):
        """Test calculating annual tax from mill rate."""
        tax = PropertyTax.calculate_annual_tax(Decimal("500000"), Decimal("10"))
        assert tax == Decimal("5000")

    def test_assessment_ratio(self):
        """Test calculating assessment ratio."""
        ratio = PropertyTax.estimate_assessment_ratio(Decimal("500000"), Decimal("400000"))
        assert ratio == Decimal("0.8")

    def test_tax_projection(self):
        """Test projecting future taxes."""
        future_tax = PropertyTax.project_tax_increase(Decimal("5000"), 10, Decimal("0.03"))
        assert future_tax > Decimal("5000")


class TestGeospatialSearch:
    """Test geospatial search operations."""

    def test_haversine_distance(self):
        """Test haversine distance calculation."""
        distance = GeospatialSearch.haversine_distance(
            39.7817,
            -89.6501,
            39.7817,
            -89.6501,
        )
        assert distance == pytest.approx(0, abs=0.1)

    def test_haversine_distance_real(self):
        """Test haversine with real coordinates."""
        distance = GeospatialSearch.haversine_distance(
            40.7128,
            -74.0060,
            34.0522,
            -118.2437,
        )
        assert 2400 < distance < 2500

    def test_search_radius(self):
        """Test radius search."""
        address = Address(
            street="123 Main St",
            city="Springfield",
            state="IL",
            zip_code="62701",
            latitude=39.7817,
            longitude=-89.6501,
        )
        prop = Property(
            property_id="prop001",
            address=address,
            property_type=PropertyType.SINGLE_FAMILY,
            zoning_type=ZoningType.RESIDENTIAL,
            bedrooms=3,
            bathrooms=Decimal("2"),
            sqft=1800,
            lot_sqft=7500,
            year_built=2005,
        )
        results = GeospatialSearch.search_radius([prop], 39.7817, -89.6501, 1.0)
        assert len(results) == 1


class TestPropertyComparison:
    """Test property comparison."""

    def test_compare_square_footage(self):
        """Test comparing square footage."""
        addr = Address(street="1 Main", city="City", state="ST", zip_code="12345")
        prop1 = Property(
            property_id="1",
            address=addr,
            property_type=PropertyType.SINGLE_FAMILY,
            zoning_type=ZoningType.RESIDENTIAL,
            bedrooms=3,
            bathrooms=Decimal("2"),
            sqft=2000,
            lot_sqft=7500,
            year_built=2005,
        )
        prop2 = Property(
            property_id="2",
            address=addr,
            property_type=PropertyType.SINGLE_FAMILY,
            zoning_type=ZoningType.RESIDENTIAL,
            bedrooms=3,
            bathrooms=Decimal("2"),
            sqft=1800,
            lot_sqft=7500,
            year_built=2005,
        )
        diff = PropertyComparison.compare_square_footage(prop1, prop2)
        assert diff == Decimal("200")

    def test_price_per_sqft(self):
        """Test calculating price per square foot."""
        ppsf = PropertyComparison.calculate_price_per_sqft(Decimal("500000"), 2000)
        assert ppsf == Decimal("250")


class TestPropertyScoring:
    """Test property scoring."""

    def test_scoring_weights(self):
        """Test setting custom scoring weights."""
        scorer = PropertyScoring()
        weights = {
            "location": Decimal("0.3"),
            "condition": Decimal("0.3"),
            "size": Decimal("0.2"),
            "features": Decimal("0.1"),
            "age": Decimal("0.05"),
            "price": Decimal("0.05"),
        }
        scorer.set_weights(weights)
        assert scorer.weights == weights

    def test_invalid_weights(self):
        """Test that invalid weights raise error."""
        scorer = PropertyScoring()
        bad_weights = {
            "location": Decimal("0.5"),
            "condition": Decimal("0.3"),
        }
        with pytest.raises(ValueError):
            scorer.set_weights(bad_weights)

    def test_location_score(self):
        """Test location scoring."""
        scorer = PropertyScoring()
        address = Address(
            street="123 Main",
            city="City",
            state="ST",
            zip_code="12345",
            county="County",
            latitude=40.0,
            longitude=-75.0,
        )
        score = scorer.score_location(address)
        assert 50 <= score <= 100

    def test_overall_score(self):
        """Test overall property score."""
        scorer = PropertyScoring()
        address = Address(
            street="123 Main",
            city="City",
            state="ST",
            zip_code="12345",
            county="County",
            latitude=40.0,
            longitude=-75.0,
        )
        prop = Property(
            property_id="prop1",
            address=address,
            property_type=PropertyType.SINGLE_FAMILY,
            zoning_type=ZoningType.RESIDENTIAL,
            bedrooms=3,
            bathrooms=Decimal("2"),
            sqft=2000,
            lot_sqft=7500,
            year_built=2005,
            features=["pool"],
        )
        score = scorer.overall_score(prop, Decimal("500000"))
        assert 0 <= score <= 100
