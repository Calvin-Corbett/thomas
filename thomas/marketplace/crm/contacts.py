"""
Contact management system for the CRM.
"""

import csv
import uuid
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Any

from thomas.marketplace.crm._exceptions import ContactNotFoundError, DuplicateContactError
from thomas.marketplace.crm._types import ActivityType, Contact


class ContactManager:
    """Manages contacts in the CRM system.

    Handles CRUD operations, search, deduplication, enrichment, segmentation,
    activity tracking, lifecycle management, and import/export.
    """

    def __init__(self) -> None:
        """Initialize the contact manager."""
        self._contacts: dict[str, Contact] = {}
        self._activity_history: dict[str, list[dict[str, Any]]] = {}

    def create_contact(
        self,
        first_name: str,
        last_name: str,
        email: str,
        phone: str | None = None,
        company: str | None = None,
        title: str | None = None,
        tags: list[str] | None = None,
        custom_fields: dict[str, Any] | None = None,
    ) -> Contact:
        """Create a new contact.

        Args:
            first_name: Contact's first name
            last_name: Contact's last name
            email: Email address
            phone: Phone number
            company: Company name
            title: Job title
            tags: List of tags
            custom_fields: Custom field values

        Returns:
            Created Contact object

        Raises:
            DuplicateContactError: If a duplicate contact is detected
        """
        # Check for duplicates
        duplicates = self.find_duplicates(first_name, last_name, email)
        if duplicates:
            raise DuplicateContactError(f"Duplicate contact detected: {duplicates}")

        contact_id = str(uuid.uuid4())
        contact = Contact(
            id=contact_id,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            company=company,
            title=title,
            tags=tags or [],
            custom_fields=custom_fields or {},
        )

        self._contacts[contact_id] = contact
        self._activity_history[contact_id] = []
        return contact

    def get_contact(self, contact_id: str) -> Contact:
        """Get a contact by ID.

        Args:
            contact_id: Contact identifier

        Returns:
            Contact object

        Raises:
            ContactNotFoundError: If contact not found
        """
        if contact_id not in self._contacts:
            raise ContactNotFoundError(f"Contact {contact_id} not found")
        return self._contacts[contact_id]

    def update_contact(self, contact_id: str, **kwargs: Any) -> Contact:
        """Update a contact's information.

        Args:
            contact_id: Contact identifier
            **kwargs: Fields to update

        Returns:
            Updated Contact object

        Raises:
            ContactNotFoundError: If contact not found
        """
        contact = self.get_contact(contact_id)

        for key, value in kwargs.items():
            if hasattr(contact, key):
                setattr(contact, key, value)

        return contact

    def delete_contact(self, contact_id: str) -> None:
        """Delete a contact.

        Args:
            contact_id: Contact identifier

        Raises:
            ContactNotFoundError: If contact not found
        """
        if contact_id not in self._contacts:
            raise ContactNotFoundError(f"Contact {contact_id} not found")
        del self._contacts[contact_id]
        if contact_id in self._activity_history:
            del self._activity_history[contact_id]

    def list_contacts(self) -> list[Contact]:
        """Get all contacts.

        Returns:
            List of Contact objects
        """
        return list(self._contacts.values())

    def search_contacts(
        self,
        name: str | None = None,
        email: str | None = None,
        company: str | None = None,
        tags: list[str] | None = None,
        title: str | None = None,
    ) -> list[Contact]:
        """Search for contacts using various criteria.

        Args:
            name: Full name or partial name
            email: Email address
            company: Company name
            tags: List of tags (match all)
            title: Job title

        Returns:
            List of matching Contact objects
        """
        results = list(self._contacts.values())

        if name:
            name_lower = name.lower()
            results = [c for c in results if name_lower in c.full_name.lower()]

        if email:
            email_lower = email.lower()
            results = [c for c in results if c.email and email_lower in c.email.lower()]

        if company:
            company_lower = company.lower()
            results = [c for c in results if c.company and company_lower in c.company.lower()]

        if title:
            title_lower = title.lower()
            results = [c for c in results if c.title and title_lower in c.title.lower()]

        if tags:
            results = [c for c in results if all(tag in c.tags for tag in tags)]

        return results

    def find_duplicates(
        self,
        first_name: str,
        last_name: str,
        email: str,
        similarity_threshold: float = 0.85,
    ) -> list[Contact]:
        """Find potential duplicate contacts using fuzzy matching.

        Compares name and email similarity to detect duplicates.

        Args:
            first_name: First name to check
            last_name: Last name to check
            email: Email to check
            similarity_threshold: Minimum similarity score (0-1)

        Returns:
            List of potential duplicate Contact objects
        """
        duplicates = []

        for contact in self._contacts.values():
            # Exact email match
            if contact.email.lower() == email.lower():
                duplicates.append(contact)
                continue

            # Fuzzy name matching
            full_name = f"{first_name} {last_name}".lower()
            contact_full_name = contact.full_name.lower()

            name_similarity = SequenceMatcher(None, full_name, contact_full_name).ratio()

            if name_similarity >= similarity_threshold:
                duplicates.append(contact)

        return duplicates

    def merge_contacts(
        self,
        primary_id: str,
        secondary_id: str,
        keep_primary_values: bool = True,
    ) -> Contact:
        """Merge two contacts, keeping the primary contact.

        Args:
            primary_id: Primary contact ID (kept)
            secondary_id: Secondary contact ID (merged into primary)
            keep_primary_values: Whether to keep primary values for conflicts

        Returns:
            Merged Contact object

        Raises:
            ContactNotFoundError: If either contact not found
        """
        primary = self.get_contact(primary_id)
        secondary = self.get_contact(secondary_id)

        # Merge tags
        merged_tags = list(set(primary.tags + secondary.tags))
        primary.tags = merged_tags

        # Merge custom fields
        if not keep_primary_values:
            for key, value in secondary.custom_fields.items():
                if key not in primary.custom_fields:
                    primary.custom_fields[key] = value

        # Merge phone if primary doesn't have it
        if not primary.phone and secondary.phone:
            primary.phone = secondary.phone

        # Merge title if primary doesn't have it
        if not primary.title and secondary.title:
            primary.title = secondary.title

        # Merge activity history
        if secondary_id in self._activity_history:
            if primary_id not in self._activity_history:
                self._activity_history[primary_id] = []
            self._activity_history[primary_id].extend(self._activity_history[secondary_id])

        # Delete secondary contact
        self.delete_contact(secondary_id)

        return primary

    def enrich_contact(
        self,
        contact_id: str,
        enrichment_data: dict[str, Any],
    ) -> Contact:
        """Enrich a contact with additional data.

        Args:
            contact_id: Contact identifier
            enrichment_data: Data to add to the contact

        Returns:
            Enriched Contact object

        Raises:
            ContactNotFoundError: If contact not found
        """
        contact = self.get_contact(contact_id)

        # Merge enrichment data into custom fields
        contact.custom_fields.update(enrichment_data)

        return contact

    def segment_contacts(
        self,
        attribute: str,
        value: Any,
    ) -> list[Contact]:
        """Segment contacts based on an attribute.

        Args:
            attribute: Contact attribute to filter by
            value: Value to match

        Returns:
            List of matching Contact objects
        """
        results = []

        for contact in self._contacts.values():
            if hasattr(contact, attribute):
                if getattr(contact, attribute) == value:
                    results.append(contact)
            elif attribute in contact.custom_fields:
                if contact.custom_fields[attribute] == value:
                    results.append(contact)

        return results

    def add_activity(
        self,
        contact_id: str,
        activity_type: ActivityType,
        notes: str,
        duration: int | None = None,
        deal_id: str | None = None,
        user: str | None = None,
    ) -> None:
        """Log an activity for a contact.

        Args:
            contact_id: Contact identifier
            activity_type: Type of activity
            notes: Activity notes
            duration: Duration in minutes
            deal_id: Associated deal ID
            user: User who logged the activity

        Raises:
            ContactNotFoundError: If contact not found
        """
        self.get_contact(contact_id)  # Verify contact exists

        if contact_id not in self._activity_history:
            self._activity_history[contact_id] = []

        activity = {
            "id": str(uuid.uuid4()),
            "type": activity_type.value,
            "timestamp": datetime.utcnow().isoformat(),
            "notes": notes,
            "duration": duration,
            "deal_id": deal_id,
            "user": user,
        }

        self._activity_history[contact_id].append(activity)

    def get_activity_history(self, contact_id: str) -> list[dict[str, Any]]:
        """Get activity history for a contact.

        Args:
            contact_id: Contact identifier

        Returns:
            List of activities, sorted by timestamp

        Raises:
            ContactNotFoundError: If contact not found
        """
        self.get_contact(contact_id)

        history = self._activity_history.get(contact_id, [])
        return sorted(history, key=lambda x: x["timestamp"], reverse=True)

    def get_lifecycle_stage(self, contact_id: str) -> str:
        """Determine the lifecycle stage of a contact.

        Stages: Subscriber → Lead → MQL → SQL → Customer → Advocate

        Args:
            contact_id: Contact identifier

        Returns:
            Lifecycle stage name

        Raises:
            ContactNotFoundError: If contact not found
        """
        contact = self.get_contact(contact_id)
        history = self.get_activity_history(contact_id)

        if not history:
            return "Subscriber"

        activity_types = {a["type"] for a in history}
        recent_activities = [
            a for a in history if datetime.fromisoformat(a["timestamp"]) > datetime.utcnow() - timedelta(days=30)
        ]

        # Heuristic-based lifecycle determination
        if "meeting" in activity_types:
            return "SQL"  # Sales Qualified Lead
        elif "demo" in activity_types or "proposal" in activity_types:
            return "MQL"  # Marketing Qualified Lead
        elif recent_activities:
            return "Lead"
        else:
            return "Subscriber"

    def export_to_csv(self, filepath: str) -> None:
        """Export all contacts to a CSV file.

        Args:
            filepath: Path to write CSV file
        """
        contacts = list(self._contacts.values())

        if not contacts:
            return

        fieldnames = ["id", "first_name", "last_name", "email", "phone", "company", "title", "tags", "created_at"]

        with open(filepath, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for contact in contacts:
                row = {
                    "id": contact.id,
                    "first_name": contact.first_name,
                    "last_name": contact.last_name,
                    "email": contact.email,
                    "phone": contact.phone or "",
                    "company": contact.company or "",
                    "title": contact.title or "",
                    "tags": ";".join(contact.tags),
                    "created_at": contact.created_at.isoformat(),
                }
                writer.writerow(row)

    def import_from_csv(self, filepath: str) -> list[Contact]:
        """Import contacts from a CSV file.

        Args:
            filepath: Path to CSV file

        Returns:
            List of imported Contact objects
        """
        imported = []

        with open(filepath) as f:
            reader = csv.DictReader(f)

            for row in reader:
                try:
                    contact = self.create_contact(
                        first_name=row["first_name"],
                        last_name=row["last_name"],
                        email=row["email"],
                        phone=row.get("phone") or None,
                        company=row.get("company") or None,
                        title=row.get("title") or None,
                        tags=row.get("tags", "").split(";") if row.get("tags") else [],
                    )
                    imported.append(contact)
                except (ValueError, DuplicateContactError):
                    # Skip invalid or duplicate rows
                    continue

        return imported

    def batch_update_tags(
        self,
        contact_ids: list[str],
        tags: list[str],
        append: bool = True,
    ) -> None:
        """Update tags for multiple contacts.

        Args:
            contact_ids: List of contact IDs
            tags: Tags to add or replace
            append: If True, append tags; if False, replace tags
        """
        for contact_id in contact_ids:
            contact = self.get_contact(contact_id)

            if append:
                contact.tags = list(set(contact.tags + tags))
            else:
                contact.tags = tags
