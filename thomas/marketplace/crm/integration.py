"""
Integration layer for the CRM system.
"""

import json
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from thomas.marketplace.crm._exceptions import IntegrationError


class IntegrationManager:
    """Manages integrations and data exchange with external systems.

    Handles email integration, calendar sync, webhooks, API data formatting,
    field mapping, and bulk data import with validation.
    """

    def __init__(self) -> None:
        """Initialize the integration manager."""
        self._integrations: dict[str, dict[str, Any]] = {}
        self._field_mappings: dict[str, dict[str, str]] = {}
        self._webhook_handlers: dict[str, Callable] = {}
        self._import_history: list[dict[str, Any]] = []

    def register_integration(
        self,
        integration_name: str,
        config: dict[str, Any],
    ) -> str:
        """Register a new integration.

        Args:
            integration_name: Name of the integration
            config: Integration configuration

        Returns:
            Integration ID
        """
        integration_id = str(uuid.uuid4())

        integration = {
            "id": integration_id,
            "name": integration_name,
            "config": config,
            "created_at": datetime.utcnow().isoformat(),
            "enabled": True,
            "last_sync": None,
        }

        self._integrations[integration_id] = integration
        return integration_id

    def get_integration(self, integration_id: str) -> dict[str, Any] | None:
        """Get an integration by ID.

        Args:
            integration_id: Integration ID

        Returns:
            Integration dictionary or None
        """
        return self._integrations.get(integration_id)

    def list_integrations(self) -> list[dict[str, Any]]:
        """Get all integrations.

        Returns:
            List of integration dictionaries
        """
        return list(self._integrations.values())

    def enable_integration(self, integration_id: str) -> None:
        """Enable an integration.

        Args:
            integration_id: Integration ID
        """
        integration = self.get_integration(integration_id)
        if integration:
            integration["enabled"] = True

    def disable_integration(self, integration_id: str) -> None:
        """Disable an integration.

        Args:
            integration_id: Integration ID
        """
        integration = self.get_integration(integration_id)
        if integration:
            integration["enabled"] = False

    def log_email_activity(
        self,
        contact_id: str,
        email_type: str,
        email_address: str,
        subject: str,
        timestamp: datetime | None = None,
        deal_id: str | None = None,
    ) -> dict[str, Any]:
        """Log an email activity from external integration.

        Args:
            contact_id: Contact ID
            email_type: "sent" or "received"
            email_address: Email address involved
            subject: Email subject
            timestamp: When the email was sent/received
            deal_id: Associated deal ID

        Returns:
            Activity record
        """
        activity = {
            "id": str(uuid.uuid4()),
            "type": "email",
            "contact_id": contact_id,
            "email_type": email_type,
            "email_address": email_address,
            "subject": subject,
            "timestamp": (timestamp or datetime.utcnow()).isoformat(),
            "deal_id": deal_id,
            "logged_at": datetime.utcnow().isoformat(),
        }

        return activity

    def log_meeting_activity(
        self,
        contact_id: str,
        meeting_title: str,
        start_time: datetime,
        end_time: datetime,
        attendees: list[str],
        deal_id: str | None = None,
    ) -> dict[str, Any]:
        """Log a meeting activity from calendar integration.

        Args:
            contact_id: Contact ID
            meeting_title: Title of the meeting
            start_time: Meeting start time
            end_time: Meeting end time
            attendees: List of attendees
            deal_id: Associated deal ID

        Returns:
            Activity record
        """
        duration = int((end_time - start_time).total_seconds() / 60)

        activity = {
            "id": str(uuid.uuid4()),
            "type": "meeting",
            "contact_id": contact_id,
            "title": meeting_title,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_minutes": duration,
            "attendees": attendees,
            "deal_id": deal_id,
            "logged_at": datetime.utcnow().isoformat(),
        }

        return activity

    def register_webhook(
        self,
        event_type: str,
        handler: Callable,
    ) -> None:
        """Register a webhook handler for an event type.

        Args:
            event_type: Type of event to handle
            handler: Callable to handle the webhook
        """
        self._webhook_handlers[event_type] = handler

    def trigger_webhook(
        self,
        event_type: str,
        event_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Trigger a webhook event.

        Args:
            event_type: Type of event
            event_data: Event data

        Returns:
            Webhook result

        Raises:
            IntegrationError: If webhook handler fails
        """
        if event_type not in self._webhook_handlers:
            raise IntegrationError(f"No handler for event type: {event_type}")

        handler = self._webhook_handlers[event_type]

        try:
            result = handler(event_data)
            return {
                "event_type": event_type,
                "status": "success",
                "result": result,
            }
        except Exception as e:
            raise IntegrationError(f"Webhook handler failed: {str(e)}")

    def create_field_mapping(
        self,
        system_name: str,
        crm_field: str,
        external_field: str,
        transformation: Callable | None = None,
    ) -> None:
        """Create a field mapping between CRM and external system.

        Args:
            system_name: Name of external system
            crm_field: CRM field name
            external_field: External system field name
            transformation: Optional transformation function
        """
        if system_name not in self._field_mappings:
            self._field_mappings[system_name] = {}

        self._field_mappings[system_name][crm_field] = external_field

    def get_field_mappings(self, system_name: str) -> dict[str, str]:
        """Get field mappings for a system.

        Args:
            system_name: Name of external system

        Returns:
            Dictionary of CRM field to external field mappings
        """
        return self._field_mappings.get(system_name, {})

    def export_to_json(
        self,
        crm_objects: list[dict[str, Any]],
    ) -> str:
        """Export CRM objects to JSON.

        Args:
            crm_objects: List of CRM object dictionaries

        Returns:
            JSON string
        """
        return json.dumps(crm_objects, indent=2, default=str)

    def import_from_json(
        self,
        json_data: str,
        object_type: str,
    ) -> list[dict[str, Any]]:
        """Import CRM objects from JSON.

        Args:
            json_data: JSON string
            object_type: Type of objects being imported

        Returns:
            List of imported objects

        Raises:
            IntegrationError: If JSON is invalid
        """
        try:
            objects = json.loads(json_data)

            if not isinstance(objects, list):
                objects = [objects]

            return objects
        except json.JSONDecodeError as e:
            raise IntegrationError(f"Invalid JSON: {str(e)}")

    def validate_import_data(
        self,
        data: list[dict[str, Any]],
        required_fields: list[str],
    ) -> dict[str, Any]:
        """Validate data before import.

        Args:
            data: List of data objects
            required_fields: List of required field names

        Returns:
            Validation result with issues
        """
        validation_result = {
            "total_rows": len(data),
            "valid_rows": 0,
            "invalid_rows": 0,
            "issues": [],
        }

        for idx, row in enumerate(data):
            row_issues = []

            # Check required fields
            for field in required_fields:
                if field not in row or not row[field]:
                    row_issues.append(f"Missing required field: {field}")

            # Check for empty rows
            if not any(row.values()):
                row_issues.append("Empty row")

            if row_issues:
                validation_result["invalid_rows"] += 1
                validation_result["issues"].append(
                    {
                        "row": idx + 1,
                        "issues": row_issues,
                    }
                )
            else:
                validation_result["valid_rows"] += 1

        return validation_result

    def bulk_import(
        self,
        data: list[dict[str, Any]],
        object_type: str,
        transform_function: Callable | None = None,
    ) -> dict[str, Any]:
        """Perform a bulk import of objects.

        Args:
            data: List of objects to import
            object_type: Type of objects
            transform_function: Optional function to transform each object

        Returns:
            Import result with statistics
        """
        import_id = str(uuid.uuid4())

        result = {
            "import_id": import_id,
            "object_type": object_type,
            "started_at": datetime.utcnow().isoformat(),
            "total_rows": len(data),
            "imported": 0,
            "failed": 0,
            "errors": [],
        }

        for idx, obj in enumerate(data):
            try:
                # Apply transformation if provided
                if transform_function:
                    obj = transform_function(obj)

                # Simulate import (in real system, would persist to DB)
                result["imported"] += 1

            except Exception as e:
                result["failed"] += 1
                result["errors"].append(
                    {
                        "row": idx + 1,
                        "error": str(e),
                    }
                )

        result["completed_at"] = datetime.utcnow().isoformat()

        # Record in history
        self._import_history.append(result)

        return result

    def get_import_history(
        self,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get import history.

        Args:
            limit: Maximum number of entries to return

        Returns:
            List of import records
        """
        return sorted(self._import_history, key=lambda x: x["started_at"], reverse=True)[:limit]

    def sync_salesforce_format(
        self,
        crm_object: dict[str, Any],
        object_type: str,
    ) -> dict[str, Any]:
        """Convert CRM object to Salesforce format.

        Args:
            crm_object: CRM object
            object_type: Type of object (Contact, Account, Opportunity)

        Returns:
            Salesforce-formatted object
        """
        mappings = {
            "Contact": {
                "id": "Id",
                "first_name": "FirstName",
                "last_name": "LastName",
                "email": "Email",
                "phone": "Phone",
                "title": "Title",
                "company_id": "AccountId",
            },
            "Account": {
                "id": "Id",
                "name": "Name",
                "domain": "Website",
                "industry": "Industry",
                "size": "NumberOfEmployees",
                "revenue": "AnnualRevenue",
            },
            "Opportunity": {
                "id": "Id",
                "name": "Name",
                "value": "Amount",
                "probability": "Probability",
                "stage_id": "StageName",
                "expected_close": "CloseDate",
                "owner": "OwnerId",
            },
        }

        if object_type not in mappings:
            return crm_object

        mapping = mappings[object_type]
        sf_object = {}

        for crm_field, sf_field in mapping.items():
            if crm_field in crm_object:
                sf_object[sf_field] = crm_object[crm_field]

        return sf_object

    def get_integration_status(self, integration_id: str) -> dict[str, Any]:
        """Get the status of an integration.

        Args:
            integration_id: Integration ID

        Returns:
            Status dictionary
        """
        integration = self.get_integration(integration_id)

        if not integration:
            return None

        return {
            "id": integration_id,
            "name": integration["name"],
            "enabled": integration["enabled"],
            "created_at": integration["created_at"],
            "last_sync": integration["last_sync"],
        }
