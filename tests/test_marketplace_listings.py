"""Tests for listings module."""

from datetime import datetime
from decimal import Decimal

import pytest

from thomas.marketplace._exceptions import (
    ListingNotFoundError,
)
from thomas.marketplace._types import (
    Listing,
    ListingState,
)
from thomas.marketplace.listings import (
    CategoryTree,
    DuplicateDetector,
    ListingQualityScorer,
    ListingRegistry,
    ListingStateManager,
)


class TestListingStateManager:
    """Test listing state machine."""

    def test_valid_transition_draft_to_published(self) -> None:
        """Test transition from DRAFT to PUBLISHED."""
        assert ListingStateManager.can_transition(ListingState.DRAFT, ListingState.PUBLISHED)

    def test_valid_transition_published_to_archived(self) -> None:
        """Test transition from PUBLISHED to ARCHIVED."""
        assert ListingStateManager.can_transition(ListingState.PUBLISHED, ListingState.ARCHIVED)

    def test_invalid_transition_draft_to_delisted(self) -> None:
        """Test invalid transition from DRAFT to DELISTED."""
        assert not ListingStateManager.can_transition(ListingState.DRAFT, ListingState.DELISTED)

    def test_invalid_transition_archived_to_published(self) -> None:
        """Test valid transition from ARCHIVED to PUBLISHED."""
        assert ListingStateManager.can_transition(ListingState.ARCHIVED, ListingState.PUBLISHED)


class TestListingQualityScorer:
    """Test listing quality scoring."""

    def test_quality_score_complete_listing(self) -> None:
        """Test quality score for complete listing."""
        listing = Listing(
            id="list_1",
            vendor_id="vendor_1",
            product_id="prod_1",
            state=ListingState.DRAFT,
            title="Amazing Product with Great Features",
            description="This is a detailed description that exceeds the minimum length requirement for quality.",
            price=Decimal("99.99"),
            quantity=10,
            category_id="cat_1",
            images=["img1.jpg", "img2.jpg", "img3.jpg"],
            attributes={"color": "blue", "size": "large", "brand": "TestBrand"},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        score = ListingQualityScorer.calculate_quality_score(listing)
        assert score > Decimal("50")

    def test_quality_score_minimal_listing(self) -> None:
        """Test quality score for minimal listing."""
        listing = Listing(
            id="list_2",
            vendor_id="vendor_1",
            product_id="prod_2",
            state=ListingState.DRAFT,
            title="Item",
            description="Bad",
            price=Decimal("0"),
            quantity=10,
            category_id="cat_1",
            images=[],
            attributes={},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

        score = ListingQualityScorer.calculate_quality_score(listing)
        assert score < Decimal("30")


class TestDuplicateDetector:
    """Test duplicate listing detection."""

    def test_identical_titles_are_duplicates(self) -> None:
        """Test identical titles detected as duplicates."""
        is_dup, score = DuplicateDetector.is_duplicate(
            "iPhone 13 Pro Max",
            "iPhone 13 Pro Max",
            {},
            {},
        )

        assert is_dup
        assert score > Decimal("0.9")

    def test_similar_titles_are_duplicates(self) -> None:
        """Test similar titles detected as duplicates."""
        is_dup, score = DuplicateDetector.is_duplicate(
            "iPhone 13 Pro Max 256GB",
            "iPhone 13 Pro Max 512GB",
            {},
            {},
        )

        assert is_dup
        assert score > Decimal("0.8")

    def test_different_titles_not_duplicates(self) -> None:
        """Test different titles not flagged as duplicates."""
        is_dup, score = DuplicateDetector.is_duplicate(
            "Samsung Galaxy S21",
            "iPhone 13 Pro",
            {},
            {},
        )

        assert not is_dup
        assert score < Decimal("0.7")


class TestCategoryTree:
    """Test hierarchical category management."""

    def test_add_root_category(self) -> None:
        """Test adding root category."""
        tree = CategoryTree()

        cat = tree.add_category(
            name="Electronics",
            description="Electronic devices",
            icon_url="http://example.com/electronics.png",
        )

        assert cat.name == "Electronics"
        assert cat.parent_id is None
        assert cat.breadcrumb == ["Electronics"]

    def test_add_subcategory(self) -> None:
        """Test adding subcategory."""
        tree = CategoryTree()

        electronics = tree.add_category(
            name="Electronics",
            description="Electronic devices",
            icon_url="http://example.com/electronics.png",
        )

        phones = tree.add_category(
            name="Phones",
            description="Mobile phones",
            icon_url="http://example.com/phones.png",
            parent_id=electronics.id,
        )

        assert phones.parent_id == electronics.id
        assert phones.breadcrumb == ["Electronics", "Phones"]

    def test_get_breadcrumb(self) -> None:
        """Test getting category breadcrumb."""
        tree = CategoryTree()

        electronics = tree.add_category(
            name="Electronics",
            description="Electronic devices",
            icon_url="http://example.com/electronics.png",
        )

        phones = tree.add_category(
            name="Phones",
            description="Mobile phones",
            icon_url="http://example.com/phones.png",
            parent_id=electronics.id,
        )

        breadcrumb = tree.get_breadcrumb(phones.id)
        assert breadcrumb == ["Electronics", "Phones"]

    def test_list_subcategories(self) -> None:
        """Test listing subcategories."""
        tree = CategoryTree()

        electronics = tree.add_category(
            name="Electronics",
            description="Electronic devices",
            icon_url="http://example.com/electronics.png",
        )

        tree.add_category(
            name="Phones",
            description="Mobile phones",
            icon_url="http://example.com/phones.png",
            parent_id=electronics.id,
        )

        tree.add_category(
            name="Laptops",
            description="Computers",
            icon_url="http://example.com/laptops.png",
            parent_id=electronics.id,
        )

        subcats = tree.list_categories(parent_id=electronics.id)
        assert len(subcats) == 2


class TestListingRegistry:
    """Test listing registry operations."""

    def test_create_listing(self) -> None:
        """Test creating listing."""
        registry = ListingRegistry()

        listing = registry.create_listing(
            vendor_id="vendor_1",
            product_id="prod_1",
            title="Great Product",
            description="A detailed product description",
            price=Decimal("99.99"),
            quantity=10,
            category_id="cat_1",
            images=["img1.jpg"],
            attributes={"color": "blue"},
        )

        assert listing.state == ListingState.DRAFT
        assert listing.title == "Great Product"
        assert listing.quality_score > Decimal("0")

    def test_publish_listing(self) -> None:
        """Test publishing listing."""
        registry = ListingRegistry()

        listing = registry.create_listing(
            vendor_id="vendor_1",
            product_id="prod_1",
            title="Great Product",
            description="A detailed product description",
            price=Decimal("99.99"),
            quantity=10,
            category_id="cat_1",
            images=["img1.jpg"],
            attributes={"color": "blue"},
        )

        published = registry.publish_listing(listing.id)
        assert published.state == ListingState.PUBLISHED

    def test_archive_listing(self) -> None:
        """Test archiving listing."""
        registry = ListingRegistry()

        listing = registry.create_listing(
            vendor_id="vendor_1",
            product_id="prod_1",
            title="Great Product",
            description="A detailed product description",
            price=Decimal("99.99"),
            quantity=10,
            category_id="cat_1",
            images=["img1.jpg"],
            attributes={"color": "blue"},
        )

        published = registry.publish_listing(listing.id)
        archived = registry.archive_listing(published.id)

        assert archived.state == ListingState.ARCHIVED

    def test_get_listing(self) -> None:
        """Test retrieving listing."""
        registry = ListingRegistry()

        listing = registry.create_listing(
            vendor_id="vendor_1",
            product_id="prod_1",
            title="Great Product",
            description="A detailed product description",
            price=Decimal("99.99"),
            quantity=10,
            category_id="cat_1",
            images=["img1.jpg"],
            attributes={"color": "blue"},
        )

        retrieved = registry.get_listing(listing.id)
        assert retrieved.id == listing.id
        assert retrieved.title == "Great Product"

    def test_get_nonexistent_listing(self) -> None:
        """Test getting nonexistent listing."""
        registry = ListingRegistry()

        with pytest.raises(ListingNotFoundError):
            registry.get_listing("listing_nonexistent")

    def test_list_vendor_listings(self) -> None:
        """Test listing vendor's listings."""
        registry = ListingRegistry()

        registry.create_listing(
            vendor_id="vendor_1",
            product_id="prod_1",
            title="Product 1",
            description="Description 1",
            price=Decimal("99.99"),
            quantity=10,
            category_id="cat_1",
            images=["img1.jpg"],
            attributes={},
        )

        registry.create_listing(
            vendor_id="vendor_1",
            product_id="prod_2",
            title="Product 2",
            description="Description 2",
            price=Decimal("49.99"),
            quantity=5,
            category_id="cat_1",
            images=["img2.jpg"],
            attributes={},
        )

        registry.create_listing(
            vendor_id="vendor_2",
            product_id="prod_3",
            title="Product 3",
            description="Description 3",
            price=Decimal("199.99"),
            quantity=20,
            category_id="cat_1",
            images=["img3.jpg"],
            attributes={},
        )

        vendor1_listings = registry.list_vendor_listings("vendor_1")
        assert len(vendor1_listings) == 2

        vendor2_listings = registry.list_vendor_listings("vendor_2")
        assert len(vendor2_listings) == 1

    def test_record_view(self) -> None:
        """Test recording listing view."""
        registry = ListingRegistry()

        listing = registry.create_listing(
            vendor_id="vendor_1",
            product_id="prod_1",
            title="Great Product",
            description="A detailed product description",
            price=Decimal("99.99"),
            quantity=10,
            category_id="cat_1",
            images=["img1.jpg"],
            attributes={},
        )

        count1 = registry.record_view(listing.id)
        count2 = registry.record_view(listing.id)

        assert count1 == 1
        assert count2 == 2

    def test_get_recommended_listings(self) -> None:
        """Test getting recommended listings."""
        registry = ListingRegistry()

        listing1 = registry.create_listing(
            vendor_id="vendor_1",
            product_id="prod_1",
            title="iPhone Case",
            description="Protective case",
            price=Decimal("29.99"),
            quantity=50,
            category_id="cat_accessories",
            images=["img1.jpg"],
            attributes={"type": "case"},
        )

        listing2 = registry.create_listing(
            vendor_id="vendor_1",
            product_id="prod_2",
            title="Screen Protector",
            description="Protective protector",
            price=Decimal("9.99"),
            quantity=100,
            category_id="cat_accessories",
            images=["img2.jpg"],
            attributes={"type": "protector"},
        )

        registry.publish_listing(listing1.id)
        registry.publish_listing(listing2.id)

        recommendations = registry.get_recommended_listings(listing1.id)
        assert len(recommendations) > 0
