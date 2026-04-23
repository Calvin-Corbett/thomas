"""
Tests for the integration layer.
"""

import json
from datetime import datetime, timedelta

import pytest

from thomas.marketplace.crm._exceptions import IntegrationError
from thomas.marketplace.crm.integration import IntegrationManager


@pytest.fixture
def integration_manager() -> IntegrationManager:
    """Create an integration manager instance."""
    return IntegrationManager()


class TestIntegrationRegistration:
    """Test integration registration and management."""

    def test_register_integration(self, integration_manager: IntegrationManager) -> None:
        """Test registering a new integration."""
        integration_id = integration_manager.register_integration(
            "Gmail",
            {
                "api_key": "test-key",
                "api_secret": "test-secret",
            },
        )

        assert integration_id is not None
        assert integration_manager.get_integration(integration_id) is not None

    def test_get_integration(self, integration_manager: IntegrationManager) -> None:
        """Test getting an integration."""
        integration_id = integration_manager.register_integration(
            "Outlook",
            {"endpoint": "https://outlook.com"},
        )

        integration = integration_manager.get_integration(integration_id)

        assert integration["name"] == "Outlook"
        assert integration["enabled"] is True

    def test_list_integrations(self, integration_manager: IntegrationManager) -> None:
        """Test listing all integrations."""
        integration_manager.register_integration("Gmail", {})
        integration_manager.register_integration("Outlook", {})

        integrations = integration_manager.list_integrations()

        assert len(integrations) == 2

    def test_enable_disable_integration(self, integration_manager: IntegrationManager) -> None:
        """Test enabling and disabling integrations."""
        integration_id = integration_manager.register_integration(
            "Gmail",
            {},
        )

        integration_manager.disable_integration(integration_id)
        integration = integration_manager.get_integration(integration_id)

        assert integration["enabled"] is False

        integration_manager.enable_integration(integration_id)
        integration = integration_manager.get_integration(integration_id)

        assert integration["enabled"] is True


class TestEmailIntegration:
    """Test email integration."""

    def test_log_email_activity(self, integration_manager: IntegrationManager) -> None:
        """Test logging an email activity."""
        activity = integration_manager.log_email_activity(
            contact_id="contact-1",
            email_type="sent",
            email_address="john@example.com",
            subject="Follow-up",
        )

        assert activity["type"] == "email"
        assert activity["email_type"] == "sent"
        assert activity["contact_id"] == "contact-1"

    def test_log_received_email(self, integration_manager: IntegrationManager) -> None:
        """Test logging a received email."""
        activity = integration_manager.log_email_activity(
            contact_id="contact-1",
            email_type="received",
            email_address="john@example.com",
            subject="Re: Follow-up",
            deal_id="deal-1",
        )

        assert activity["email_type"] == "received"
        assert activity["deal_id"] == "deal-1"


class TestMeetingIntegration:
    """Test calendar/meeting integration."""

    def test_log_meeting_activity(self, integration_manager: IntegrationManager) -> None:
        """Test logging a meeting from calendar."""
        start_time = datetime.utcnow()
        end_time = start_time + timedelta(hours=1)

        activity = integration_manager.log_meeting_activity(
            contact_id="contact-1",
            meeting_title="Sales Call",
            start_time=start_time,
            end_time=end_time,
            attendees=["john@example.com", "jane@example.com"],
        )

        assert activity["type"] == "meeting"
        assert activity["title"] == "Sales Call"
        assert activity["duration_minutes"] == 60

    def test_meeting_with_deal(self, integration_manager: IntegrationManager) -> None:
        """Test logging a meeting with associated deal."""
        start_time = datetime.utcnow()
        end_time = start_time + timedelta(minutes=30)

        activity = integration_manager.log_meeting_activity(
            contact_id="contact-1",
            meeting_title="Product Demo",
            start_time=start_time,
            end_time=end_time,
            attendees=["contact@example.com"],
            deal_id="deal-1",
        )

        assert activity["deal_id"] == "deal-1"
        assert activity["duration_minutes"] == 30


class TestWebhooks:
    """Test webhook functionality."""

    def test_register_webhook(self, integration_manager: IntegrationManager) -> None:
        """Test registering a webhook handler."""

        def handler(data):
            return {"processed": True}

        integration_manager.register_webhook("deal_won", handler)

        # Verify handler is registered
        assert "deal_won" in integration_manager._webhook_handlers

    def test_trigger_webhook(self, integration_manager: IntegrationManager) -> None:
        """Test triggering a webhook."""

        def handler(data):
            return {"deal_id": data["deal_id"], "processed": True}

        integration_manager.register_webhook("deal_won", handler)

        result = integration_manager.trigger_webhook(
            "deal_won",
            {"deal_id": "deal-1", "value": 50000},
        )

        assert result["status"] == "success"
        assert result["result"]["processed"] is True

    def test_trigger_unregistered_webhook(self, integration_manager: IntegrationManager) -> None:
        """Test triggering an unregistered webhook raises error."""
        with pytest.raises(IntegrationError):
            integration_manager.trigger_webhook(
                "unknown_event",
                {},
            )


class TestFieldMapping:
    """Test field mapping functionality."""

    def test_create_field_mapping(self, integration_manager: IntegrationManager) -> None:
        """Test creating field mappings."""
        integration_manager.create_field_mapping(
            "Salesforce",
            "first_name",
            "FirstName",
        )

        mappings = integration_manager.get_field_mappings("Salesforce")

        assert mappings["first_name"] == "FirstName"

    def test_multiple_mappings(self, integration_manager: IntegrationManager) -> None:
        """Test creating multiple mappings."""
        integration_manager.create_field_mapping("Salesforce", "first_name", "FirstName")
        integration_manager.create_field_mapping("Salesforce", "last_name", "LastName")
        integration_manager.create_field_mapping("Salesforce", "email", "Email")

        mappings = integration_manager.get_field_mappings("Salesforce")

        assert len(mappings) == 3


class TestJSONImportExport:
    """Test JSON import/export functionality."""

    def test_export_to_json(self, integration_manager: IntegrationManager) -> None:
        """Test exporting objects to JSON."""
        objects = [
            {
                "id": "contact-1",
                "first_name": "John",
                "last_name": "Doe",
                "email": "john@example.com",
            },
        ]

        json_str = integration_manager.export_to_json(objects)

        assert isinstance(json_str, str)
        assert "John" in json_str

    def test_import_from_json(self, integration_manager: IntegrationManager) -> None:
        """Test importing objects from JSON."""
        json_str = json.dumps(
            [
                {
                    "id": "contact-1",
                    "first_name": "John",
                    "last_name": "Doe",
                    "email": "john@example.com",
                },
            ]
        )

        objects = integration_manager.import_from_json(json_str, "Contact")

        assert len(objects) == 1
        assert objects[0]["first_name"] == "John"

    def test_import_invalid_json(self, integration_manager: IntegrationManager) -> None:
        """Test importing invalid JSON raises error."""
        with pytest.raises(IntegrationError):
            integration_manager.import_from_json("invalid json", "Contact")


class TestDataValidation:
    """Test data validation for import."""

    def test_validate_import_data(self, integration_manager: IntegrationManager) -> None:
        """Test validating import data."""
        data = [
            {
                "first_name": "John",
                "last_name": "Doe",
                "email": "john@example.com",
            },
            {
                "first_name": "Jane",
                "last_name": "Smith",
            },  # Missing email
        ]

        result = integration_manager.validate_import_data(
            data,
            required_fields=["first_name", "last_name", "email"],
        )

        assert result["total_rows"] == 2
        assert result["valid_rows"] == 1
        assert result["invalid_rows"] == 1

    def test_validation_report(self, integration_manager: IntegrationManager) -> None:
        """Test validation includes error details."""
        data = [
            {"first_name": "John"},  # Missing required fields
        ]

        result = integration_manager.validate_import_data(
            data,
            required_fields=["first_name", "last_name"],
        )

        assert len(result["issues"]) > 0
        assert "Missing required field" in result["issues"][0]["issues"][0]


class TestBulkImport:
    """Test bulk import functionality."""

    def test_bulk_import(self, integration_manager: IntegrationManager) -> None:
        """Test bulk importing data."""
        data = [
            {
                "id": "contact-1",
                "first_name": "John",
                "last_name": "Doe",
            },
            {
                "id": "contact-2",
                "first_name": "Jane",
                "last_name": "Smith",
            },
        ]

        result = integration_manager.bulk_import(data, "Contact")

        assert result["total_rows"] == 2
        assert result["imported"] == 2
        assert result["failed"] == 0

    def test_bulk_import_with_errors(self, integration_manager: IntegrationManager) -> None:
        """Test bulk import tracks errors."""

        def transform(obj):
            if obj.get("id") == "bad":
                raise ValueError("Bad ID")
            return obj

        data = [
            {"id": "good", "name": "Good"},
            {"id": "bad", "name": "Bad"},
        ]

        result = integration_manager.bulk_import(data, "Contact", transform)

        assert result["imported"] == 1
        assert result["failed"] == 1

    def test_import_history(self, integration_manager: IntegrationManager) -> None:
        """Test import history is tracked."""
        data = [{"id": "test"}]

        integration_manager.bulk_import(data, "Test")

        history = integration_manager.get_import_history()

        assert len(history) > 0
        assert history[0]["object_type"] == "Test"


class TestSalesforceSync:
    """Test Salesforce format conversion."""

    def test_sync_contact_format(self, integration_manager: IntegrationManager) -> None:
        """Test converting contact to Salesforce format."""
        crm_contact = {
            "id": "contact-1",
            "first_name": "John",
            "last_name": "Doe",
            "email": "john@example.com",
            "title": "Sales Manager",
            "company_id": "company-1",
        }

        sf_contact = integration_manager.sync_salesforce_format(crm_contact, "Contact")

        assert sf_contact["Id"] == "contact-1"
        assert sf_contact["FirstName"] == "John"
        assert sf_contact["Email"] == "john@example.com"

    def test_sync_account_format(self, integration_manager: IntegrationManager) -> None:
        """Test converting account to Salesforce format."""
        crm_account = {
            "id": "company-1",
            "name": "Acme Corp",
            "domain": "acme.com",
            "industry": "Technology",
            "size": 500,
        }

        sf_account = integration_manager.sync_salesforce_format(crm_account, "Account")

        assert sf_account["Id"] == "company-1"
        assert sf_account["Name"] == "Acme Corp"
        assert sf_account["Website"] == "acme.com"

    def test_sync_opportunity_format(self, integration_manager: IntegrationManager) -> None:
        """Test converting opportunity to Salesforce format."""
        crm_deal = {
            "id": "deal-1",
            "name": "Enterprise Deal",
            "value": 50000,
            "probability": 75,
            "stage_id": "proposal",
            "owner": "John",
        }

        sf_opportunity = integration_manager.sync_salesforce_format(
            crm_deal,
            "Opportunity",
        )

        assert sf_opportunity["Id"] == "deal-1"
        assert sf_opportunity["Name"] == "Enterprise Deal"


class TestIntegrationStatus:
    """Test integration status checking."""

    def test_get_integration_status(self, integration_manager: IntegrationManager) -> None:
        """Test getting integration status."""
        integration_id = integration_manager.register_integration("Gmail", {})

        status = integration_manager.get_integration_status(integration_id)

        assert status["name"] == "Gmail"
        assert status["enabled"] is True
        assert "created_at" in status
