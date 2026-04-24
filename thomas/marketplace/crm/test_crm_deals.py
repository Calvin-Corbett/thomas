"""
Tests for the deal management system.
"""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from thomas.marketplace.crm._exceptions import DealNotFoundError
from thomas.marketplace.crm.deals import DealManager


@pytest.fixture
def deal_manager() -> DealManager:
    """Create a deal manager instance."""
    return DealManager()


class TestDealCRUD:
    """Test basic CRUD operations on deals."""

    def test_create_deal(self, deal_manager: DealManager) -> None:
        """Test creating a deal."""
        deal = deal_manager.create_deal(
            name="Enterprise Deal",
            company_id="company-1",
            contact_id="contact-1",
            stage_id="stage-1",
            value=Decimal("50000"),
            probability=60,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="John",
        )

        assert deal.id is not None
        assert deal.name == "Enterprise Deal"
        assert deal.value == Decimal("50000")
        assert deal.probability == 60

    def test_get_deal(self, deal_manager: DealManager) -> None:
        """Test getting a deal by ID."""
        created = deal_manager.create_deal(
            name="Test Deal",
            company_id="company-1",
            contact_id="contact-1",
            stage_id="stage-1",
            value=Decimal("25000"),
            probability=50,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="John",
        )

        retrieved = deal_manager.get_deal(created.id)

        assert retrieved.id == created.id
        assert retrieved.name == "Test Deal"

    def test_get_nonexistent_deal(self, deal_manager: DealManager) -> None:
        """Test getting a non-existent deal raises error."""
        with pytest.raises(DealNotFoundError):
            deal_manager.get_deal("nonexistent-id")

    def test_update_deal(self, deal_manager: DealManager) -> None:
        """Test updating a deal."""
        deal = deal_manager.create_deal(
            name="Test Deal",
            company_id="company-1",
            contact_id="contact-1",
            stage_id="stage-1",
            value=Decimal("25000"),
            probability=50,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="John",
        )

        updated = deal_manager.update_deal(
            deal.id,
            probability=75,
            value=Decimal("35000"),
        )

        assert updated.probability == 75
        assert updated.value == Decimal("35000")

    def test_delete_deal(self, deal_manager: DealManager) -> None:
        """Test deleting a deal."""
        deal = deal_manager.create_deal(
            name="Test Deal",
            company_id="company-1",
            contact_id="contact-1",
            stage_id="stage-1",
            value=Decimal("25000"),
            probability=50,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="John",
        )

        deal_manager.delete_deal(deal.id)

        with pytest.raises(DealNotFoundError):
            deal_manager.get_deal(deal.id)

    def test_list_deals(self, deal_manager: DealManager) -> None:
        """Test listing all deals."""
        deal_manager.create_deal(
            name="Deal 1",
            company_id="company-1",
            contact_id="contact-1",
            stage_id="stage-1",
            value=Decimal("25000"),
            probability=50,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="John",
        )
        deal_manager.create_deal(
            name="Deal 2",
            company_id="company-2",
            contact_id="contact-2",
            stage_id="stage-2",
            value=Decimal("50000"),
            probability=75,
            expected_close=datetime.utcnow() + timedelta(days=45),
            owner="Jane",
        )

        deals = deal_manager.list_deals()

        assert len(deals) == 2


class TestDealSearch:
    """Test deal search functionality."""

    def test_search_by_name(self, deal_manager: DealManager) -> None:
        """Test searching deals by name."""
        deal_manager.create_deal(
            name="Enterprise Deal",
            company_id="company-1",
            contact_id="contact-1",
            stage_id="stage-1",
            value=Decimal("50000"),
            probability=60,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="John",
        )

        results = deal_manager.search_deals(name="Enterprise")

        assert len(results) == 1

    def test_search_by_owner(self, deal_manager: DealManager) -> None:
        """Test searching deals by owner."""
        deal_manager.create_deal(
            name="Deal 1",
            company_id="company-1",
            contact_id="contact-1",
            stage_id="stage-1",
            value=Decimal("25000"),
            probability=50,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="John",
        )

        results = deal_manager.search_deals(owner="John")

        assert len(results) == 1


class TestDealScoring:
    """Test deal scoring."""

    def test_calculate_deal_score(self, deal_manager: DealManager) -> None:
        """Test calculating a deal score."""
        deal = deal_manager.create_deal(
            name="Test Deal",
            company_id="company-1",
            contact_id="contact-1",
            stage_id="stage-1",
            value=Decimal("50000"),
            probability=80,
            expected_close=datetime.utcnow() + timedelta(days=15),
            owner="John",
        )

        score = deal_manager.calculate_deal_score(deal.id)

        assert 0 <= score <= 100

    def test_get_deal_score(self, deal_manager: DealManager) -> None:
        """Test getting a deal score."""
        deal = deal_manager.create_deal(
            name="Test Deal",
            company_id="company-1",
            contact_id="contact-1",
            stage_id="stage-1",
            value=Decimal("50000"),
            probability=80,
            expected_close=datetime.utcnow() + timedelta(days=15),
            owner="John",
        )

        deal_manager.calculate_deal_score(deal.id)
        score = deal_manager.get_deal_score(deal.id)

        assert score >= 0


class TestDealAging:
    """Test deal aging alerts."""

    def test_get_aging_deals(self, deal_manager: DealManager) -> None:
        """Test getting aging deals."""
        # Create a deal with past expected close
        deal = deal_manager.create_deal(
            name="Old Deal",
            company_id="company-1",
            contact_id="contact-1",
            stage_id="stage-1",
            value=Decimal("25000"),
            probability=50,
            expected_close=datetime.utcnow() - timedelta(days=10),
            owner="John",
        )

        aging = deal_manager.get_aging_deals()

        assert len(aging) == 1
        assert aging[0]["deal_id"] == deal.id


class TestProducts:
    """Test product/line item management."""

    def test_add_product(self, deal_manager: DealManager) -> None:
        """Test adding a product to a deal."""
        deal = deal_manager.create_deal(
            name="Test Deal",
            company_id="company-1",
            contact_id="contact-1",
            stage_id="stage-1",
            value=Decimal("50000"),
            probability=60,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="John",
        )

        deal_manager.add_product_to_deal(
            deal.id,
            "Product A",
            quantity=10,
            unit_price=Decimal("1000"),
        )

        updated_deal = deal_manager.get_deal(deal.id)

        assert len(updated_deal.products) == 1
        assert updated_deal.products[0]["name"] == "Product A"

    def test_remove_product(self, deal_manager: DealManager) -> None:
        """Test removing a product from a deal."""
        deal = deal_manager.create_deal(
            name="Test Deal",
            company_id="company-1",
            contact_id="contact-1",
            stage_id="stage-1",
            value=Decimal("50000"),
            probability=60,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="John",
        )

        deal_manager.add_product_to_deal(
            deal.id,
            "Product A",
            quantity=10,
            unit_price=Decimal("1000"),
        )

        deal = deal_manager.get_deal(deal.id)
        product_id = deal.products[0]["id"]

        deal_manager.remove_product_from_deal(deal.id, product_id)

        updated_deal = deal_manager.get_deal(deal.id)

        assert len(updated_deal.products) == 0


class TestAlternativeVendors:
    """Test alternative vendor tracking."""

    def test_add_alternative_vendor(self, deal_manager: DealManager) -> None:
        """Test adding an alternative vendor to a deal."""
        deal = deal_manager.create_deal(
            name="Test Deal",
            company_id="company-1",
            contact_id="contact-1",
            stage_id="stage-1",
            value=Decimal("50000"),
            probability=60,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="John",
        )

        deal_manager.add_alternative_vendor(deal.id, "Vendor A")

        alternative_vendors = deal_manager.get_alternative_vendors(deal.id)

        assert len(alternative_vendors) == 1
        assert "Vendor A" in alternative_vendors


class TestDealCloning:
    """Test deal cloning."""

    def test_clone_deal(self, deal_manager: DealManager) -> None:
        """Test cloning a deal."""
        original = deal_manager.create_deal(
            name="Original Deal",
            company_id="company-1",
            contact_id="contact-1",
            stage_id="stage-1",
            value=Decimal("50000"),
            probability=60,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="John",
        )

        deal_manager.add_product_to_deal(
            original.id,
            "Product A",
            quantity=5,
            unit_price=Decimal("1000"),
        )

        cloned = deal_manager.clone_deal(
            original.id,
            "Cloned Deal",
        )

        assert cloned.id != original.id
        assert cloned.name == "Cloned Deal"
        assert cloned.value == original.value
        assert len(cloned.products) == 1


class TestWinLossAnalysis:
    """Test win/loss analysis."""

    def test_analyze_win_loss(self, deal_manager: DealManager) -> None:
        """Test win/loss analysis."""
        won_deal = deal_manager.create_deal(
            name="Won Deal",
            company_id="company-1",
            contact_id="contact-1",
            stage_id="stage-won",
            value=Decimal("50000"),
            probability=100,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="John",
        )

        lost_deal = deal_manager.create_deal(
            name="Lost Deal",
            company_id="company-2",
            contact_id="contact-2",
            stage_id="stage-lost",
            value=Decimal("25000"),
            probability=0,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="Jane",
        )

        analysis = deal_manager.analyze_win_loss(
            [won_deal.id],
            [lost_deal.id],
        )

        assert analysis["total_deals"] == 2
        assert analysis["won_deals"] == 1
        assert analysis["lost_deals"] == 1
        assert analysis["win_rate"] == 50.0


class TestDealsByOwner:
    """Test filtering deals by owner."""

    def test_get_deals_by_owner(self, deal_manager: DealManager) -> None:
        """Test getting deals for a specific owner."""
        deal_manager.create_deal(
            name="Deal 1",
            company_id="company-1",
            contact_id="contact-1",
            stage_id="stage-1",
            value=Decimal("25000"),
            probability=50,
            expected_close=datetime.utcnow() + timedelta(days=30),
            owner="John",
        )

        deal_manager.create_deal(
            name="Deal 2",
            company_id="company-2",
            contact_id="contact-2",
            stage_id="stage-1",
            value=Decimal("50000"),
            probability=75,
            expected_close=datetime.utcnow() + timedelta(days=45),
            owner="Jane",
        )

        johns_deals = deal_manager.get_deals_by_owner("John")

        assert len(johns_deals) == 1
        assert johns_deals[0].owner == "John"
