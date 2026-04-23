"""
Tests for the contact management system.
"""

import pytest

from thomas.marketplace.crm._exceptions import ContactNotFoundError, DuplicateContactError
from thomas.marketplace.crm._types import ActivityType
from thomas.marketplace.crm.contacts import ContactManager


@pytest.fixture
def contact_manager() -> ContactManager:
    """Create a contact manager instance."""
    return ContactManager()


class TestContactCRUD:
    """Test basic CRUD operations on contacts."""

    def test_create_contact(self, contact_manager: ContactManager) -> None:
        """Test creating a contact."""
        contact = contact_manager.create_contact(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
            phone="555-1234",
            company="Acme Corp",
            title="Sales Manager",
        )

        assert contact.id is not None
        assert contact.first_name == "John"
        assert contact.last_name == "Doe"
        assert contact.email == "john@example.com"
        assert contact.phone == "555-1234"
        assert contact.company == "Acme Corp"
        assert contact.title == "Sales Manager"

    def test_get_contact(self, contact_manager: ContactManager) -> None:
        """Test getting a contact by ID."""
        created = contact_manager.create_contact(
            first_name="Jane",
            last_name="Smith",
            email="jane@example.com",
        )

        retrieved = contact_manager.get_contact(created.id)

        assert retrieved.id == created.id
        assert retrieved.email == "jane@example.com"

    def test_get_nonexistent_contact(self, contact_manager: ContactManager) -> None:
        """Test getting a non-existent contact raises error."""
        with pytest.raises(ContactNotFoundError):
            contact_manager.get_contact("nonexistent-id")

    def test_update_contact(self, contact_manager: ContactManager) -> None:
        """Test updating a contact."""
        contact = contact_manager.create_contact(
            first_name="Bob",
            last_name="Jones",
            email="bob@example.com",
        )

        updated = contact_manager.update_contact(
            contact.id,
            title="Director",
            phone="555-9999",
        )

        assert updated.title == "Director"
        assert updated.phone == "555-9999"

    def test_delete_contact(self, contact_manager: ContactManager) -> None:
        """Test deleting a contact."""
        contact = contact_manager.create_contact(
            first_name="Alice",
            last_name="Brown",
            email="alice@example.com",
        )

        contact_manager.delete_contact(contact.id)

        with pytest.raises(ContactNotFoundError):
            contact_manager.get_contact(contact.id)

    def test_list_contacts(self, contact_manager: ContactManager) -> None:
        """Test listing all contacts."""
        contact_manager.create_contact(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
        )
        contact_manager.create_contact(
            first_name="Jane",
            last_name="Smith",
            email="jane@example.com",
        )

        contacts = contact_manager.list_contacts()

        assert len(contacts) == 2


class TestContactSearch:
    """Test contact search functionality."""

    def test_search_by_name(self, contact_manager: ContactManager) -> None:
        """Test searching contacts by name."""
        contact_manager.create_contact(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
        )
        contact_manager.create_contact(
            first_name="Jane",
            last_name="Smith",
            email="jane@example.com",
        )

        results = contact_manager.search_contacts(name="John")

        assert len(results) == 1
        assert results[0].first_name == "John"

    def test_search_by_email(self, contact_manager: ContactManager) -> None:
        """Test searching contacts by email."""
        contact_manager.create_contact(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
        )

        results = contact_manager.search_contacts(email="john@example.com")

        assert len(results) == 1

    def test_search_by_company(self, contact_manager: ContactManager) -> None:
        """Test searching contacts by company."""
        contact_manager.create_contact(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
            company="Acme Corp",
        )
        contact_manager.create_contact(
            first_name="Jane",
            last_name="Smith",
            email="jane@example.com",
            company="Tech Inc",
        )

        results = contact_manager.search_contacts(company="Acme")

        assert len(results) == 1

    def test_search_by_tags(self, contact_manager: ContactManager) -> None:
        """Test searching contacts by tags."""
        contact_manager.create_contact(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
            tags=["hot", "sales"],
        )
        contact_manager.create_contact(
            first_name="Jane",
            last_name="Smith",
            email="jane@example.com",
            tags=["cold"],
        )

        results = contact_manager.search_contacts(tags=["hot"])

        assert len(results) == 1


class TestContactDeduplication:
    """Test contact deduplication."""

    def test_exact_email_duplicate(self, contact_manager: ContactManager) -> None:
        """Test detecting exact email duplicates."""
        contact_manager.create_contact(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
        )

        with pytest.raises(DuplicateContactError):
            contact_manager.create_contact(
                first_name="John",
                last_name="Doe",
                email="john@example.com",
            )

    def test_fuzzy_name_match(self, contact_manager: ContactManager) -> None:
        """Test fuzzy name matching for duplicates."""
        contact_manager.create_contact(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
        )

        # Very similar name and email should trigger duplicate
        with pytest.raises(DuplicateContactError):
            contact_manager.create_contact(
                first_name="Jon",
                last_name="Doe",
                email="jon@example.com",
            )

    def test_find_duplicates(self, contact_manager: ContactManager) -> None:
        """Test finding duplicate contacts."""
        contact_manager.create_contact(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
        )

        duplicates = contact_manager.find_duplicates("John", "Doe", "john@example.com")

        assert len(duplicates) == 1


class TestContactMerge:
    """Test contact merging."""

    def test_merge_contacts(self, contact_manager: ContactManager) -> None:
        """Test merging two contacts."""
        contact1 = contact_manager.create_contact(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
            tags=["hot"],
        )

        contact2 = contact_manager.create_contact(
            first_name="John",
            last_name="Doe",
            email="john2@example.com",
            tags=["sales"],
        )

        merged = contact_manager.merge_contacts(contact1.id, contact2.id)

        assert merged.id == contact1.id
        assert len(merged.tags) == 2
        assert "hot" in merged.tags
        assert "sales" in merged.tags

        with pytest.raises(ContactNotFoundError):
            contact_manager.get_contact(contact2.id)


class TestActivityTracking:
    """Test activity tracking for contacts."""

    def test_add_activity(self, contact_manager: ContactManager) -> None:
        """Test adding an activity to a contact."""
        contact = contact_manager.create_contact(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
        )

        contact_manager.add_activity(
            contact.id,
            ActivityType.CALL,
            "Discussed pricing options",
            duration=30,
        )

        history = contact_manager.get_activity_history(contact.id)

        assert len(history) == 1
        assert history[0]["type"] == ActivityType.CALL.value

    def test_get_activity_history(self, contact_manager: ContactManager) -> None:
        """Test getting activity history."""
        contact = contact_manager.create_contact(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
        )

        contact_manager.add_activity(
            contact.id,
            ActivityType.EMAIL,
            "Sent proposal",
        )
        contact_manager.add_activity(
            contact.id,
            ActivityType.CALL,
            "Follow-up call",
        )

        history = contact_manager.get_activity_history(contact.id)

        assert len(history) == 2


class TestContactLifecycle:
    """Test contact lifecycle tracking."""

    def test_subscriber_lifecycle(self, contact_manager: ContactManager) -> None:
        """Test subscriber lifecycle stage."""
        contact = contact_manager.create_contact(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
        )

        stage = contact_manager.get_lifecycle_stage(contact.id)

        assert stage == "Subscriber"

    def test_lead_lifecycle(self, contact_manager: ContactManager) -> None:
        """Test lead lifecycle stage."""
        contact = contact_manager.create_contact(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
        )

        contact_manager.add_activity(
            contact.id,
            ActivityType.EMAIL,
            "Opened email",
        )

        stage = contact_manager.get_lifecycle_stage(contact.id)

        assert stage == "Lead"

    def test_sql_lifecycle(self, contact_manager: ContactManager) -> None:
        """Test SQL lifecycle stage."""
        contact = contact_manager.create_contact(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
        )

        contact_manager.add_activity(
            contact.id,
            ActivityType.MEETING,
            "Sales meeting",
        )

        stage = contact_manager.get_lifecycle_stage(contact.id)

        assert stage == "SQL"


class TestBatchOperations:
    """Test batch operations on contacts."""

    def test_batch_update_tags(self, contact_manager: ContactManager) -> None:
        """Test updating tags for multiple contacts."""
        contact1 = contact_manager.create_contact(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
            tags=["existing"],
        )

        contact2 = contact_manager.create_contact(
            first_name="Jane",
            last_name="Smith",
            email="jane@example.com",
        )

        contact_manager.batch_update_tags(
            [contact1.id, contact2.id],
            ["new_tag"],
            append=True,
        )

        updated1 = contact_manager.get_contact(contact1.id)
        updated2 = contact_manager.get_contact(contact2.id)

        assert "new_tag" in updated1.tags
        assert "new_tag" in updated2.tags


class TestContactEnrichment:
    """Test contact enrichment."""

    def test_enrich_contact(self, contact_manager: ContactManager) -> None:
        """Test enriching a contact with additional data."""
        contact = contact_manager.create_contact(
            first_name="John",
            last_name="Doe",
            email="john@example.com",
        )

        enriched = contact_manager.enrich_contact(
            contact.id,
            {
                "linkedin_url": "https://linkedin.com/in/johndoe",
                "company_size": 500,
            },
        )

        assert enriched.custom_fields["linkedin_url"] == "https://linkedin.com/in/johndoe"
        assert enriched.custom_fields["company_size"] == 500
