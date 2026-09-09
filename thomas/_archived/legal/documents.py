"""Document management module for legal practice operations."""

import logging
import re
from datetime import datetime
from uuid import uuid4

from thomas.legal._exceptions import DocumentNotFoundError, PrivilegeClaimError
from thomas.legal._types import (
    Document,
    DocumentType,
)

logger = logging.getLogger(__name__)


class DocumentManager:
    """Manages document versioning, metadata, and access control."""

    def __init__(self) -> None:
        """Initialize the document manager."""
        self.documents: dict[str, Document] = {}
        self.document_versions: dict[str, list[Document]] = {}
        self.privilege_log: list[dict] = []
        self.bates_counter: int = 1000

    def create_document(
        self,
        title: str,
        document_type: DocumentType,
        case_id: str | None = None,
        contract_id: str | None = None,
        author: str | None = None,
        content: str = "",
        is_privileged: bool = False,
        privilege_holder: str | None = None,
    ) -> Document:
        """Create a new document."""
        document_id = str(uuid4())
        doc = Document(
            document_id=document_id,
            title=title,
            document_type=document_type,
            case_id=case_id,
            contract_id=contract_id,
            author=author,
            version=1,
            is_privileged=is_privileged,
            privilege_holder=privilege_holder,
            full_text=content,
        )

        self.documents[document_id] = doc
        self.document_versions[document_id] = [doc]

        if is_privileged:
            self._log_privilege_claim(document_id, privilege_holder or "")

        logger.info(f"Created document {document_id}: {title}")
        return doc

    def update_document(
        self,
        document_id: str,
        content: str,
        author: str | None = None,
    ) -> Document:
        """Update document content, creating a new version."""
        if document_id not in self.documents:
            raise DocumentNotFoundError(f"Document {document_id} not found")

        old_doc = self.documents[document_id]

        # Create new version
        new_version = old_doc.version + 1
        new_doc = Document(
            document_id=document_id,
            title=old_doc.title,
            document_type=old_doc.document_type,
            case_id=old_doc.case_id,
            contract_id=old_doc.contract_id,
            author=author or old_doc.author,
            version=new_version,
            is_privileged=old_doc.is_privileged,
            privilege_holder=old_doc.privilege_holder,
            full_text=content,
            bates_number_start=old_doc.bates_number_start,
            bates_number_end=old_doc.bates_number_end,
        )

        self.documents[document_id] = new_doc
        self.document_versions[document_id].append(new_doc)

        logger.info(f"Updated document {document_id} to version {new_version}")
        return new_doc

    def checkout_document(
        self,
        document_id: str,
        user_id: str,
    ) -> Document:
        """Check out a document for editing."""
        if document_id not in self.documents:
            raise DocumentNotFoundError(f"Document {document_id} not found")

        doc = self.documents[document_id]
        if doc.checked_out_by and doc.checked_out_by != user_id:
            raise ValueError(f"Document checked out by {doc.checked_out_by}")

        doc.checked_out_by = user_id
        doc.checked_out_at = datetime.now()

        logger.info(f"Checked out document {document_id} to {user_id}")
        return doc

    def checkin_document(
        self,
        document_id: str,
        user_id: str,
        new_content: str,
    ) -> Document:
        """Check in a document after editing."""
        if document_id not in self.documents:
            raise DocumentNotFoundError(f"Document {document_id} not found")

        doc = self.documents[document_id]
        if doc.checked_out_by != user_id:
            raise ValueError(f"Document checked out by {doc.checked_out_by}, not {user_id}")

        # Create new version
        result = self.update_document(document_id, new_content, user_id)
        result.checked_out_by = None
        result.checked_out_at = None

        logger.info(f"Checked in document {document_id} from {user_id}")
        return result

    def assign_bates_numbers(
        self,
        document_ids: list[str],
        start_number: int | None = None,
    ) -> dict[str, tuple[int, int]]:
        """Assign sequential Bates numbers to documents for production.

        Returns mapping of document_id -> (start, end) Bates numbers.
        """
        if start_number is None:
            start_number = self.bates_counter

        result: dict[str, tuple[int, int]] = {}
        current = start_number

        for doc_id in document_ids:
            if doc_id not in self.documents:
                raise DocumentNotFoundError(f"Document {doc_id} not found")

            doc = self.documents[doc_id]

            # Estimate page count (rough: ~4000 chars per page)
            pages = max(1, len(doc.full_text) // 4000)

            bates_start = current
            bates_end = current + pages - 1

            doc.bates_number_start = bates_start
            doc.bates_number_end = bates_end

            result[doc_id] = (bates_start, bates_end)
            current = bates_end + 1

        self.bates_counter = current
        logger.info(f"Assigned Bates numbers to {len(document_ids)} documents")
        return result

    def search_full_text(
        self,
        query: str,
        case_id: str | None = None,
        document_type: DocumentType | None = None,
    ) -> list[Document]:
        """Search documents by full text content."""
        results = []
        query_lower = query.lower()

        for doc in self.documents.values():
            if case_id and doc.case_id != case_id:
                continue
            if document_type and doc.document_type != document_type:
                continue

            if query_lower in doc.full_text.lower():
                results.append(doc)

        return results

    def search_by_keyword_pattern(
        self,
        pattern: str,
        case_id: str | None = None,
    ) -> list[tuple[Document, list[str]]]:
        """Search documents using regex pattern.

        Returns (document, matching_lines) tuples.
        """
        results: list[tuple[Document, list[str]]] = []

        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"Invalid regex pattern: {e}")

        for doc in self.documents.values():
            if case_id and doc.case_id != case_id:
                continue

            matches = regex.findall(doc.full_text)
            if matches:
                results.append((doc, matches))

        return results

    def generate_privilege_log(
        self,
        case_id: str | None = None,
    ) -> list[dict]:
        """Generate privilege log for discovery."""
        log_entries = []

        for entry in self.privilege_log:
            if case_id and entry.get("case_id") != case_id:
                continue

            log_entries.append(
                {
                    "document_id": entry["document_id"],
                    "date_created": entry.get("created_at"),
                    "title": entry.get("title"),
                    "privilege_holder": entry.get("privilege_holder"),
                    "privilege_type": entry.get("privilege_type"),
                    "description": entry.get("description"),
                }
            )

        return log_entries

    def claim_privilege(
        self,
        document_id: str,
        privilege_type: str,
        privilege_holder: str,
        description: str = "",
    ) -> Document:
        """Claim privilege over a document."""
        if document_id not in self.documents:
            raise DocumentNotFoundError(f"Document {document_id} not found")

        doc = self.documents[document_id]

        if not doc.is_privileged:
            doc.is_privileged = True
            doc.privilege_holder = privilege_holder

        # Log privilege claim
        entry = {
            "document_id": document_id,
            "title": doc.title,
            "privilege_type": privilege_type,
            "privilege_holder": privilege_holder,
            "description": description,
            "created_at": datetime.now(),
            "case_id": doc.case_id,
        }

        self.privilege_log.append(entry)
        logger.info(f"Claimed {privilege_type} privilege on document {document_id}")
        return doc

    def access_document(
        self,
        document_id: str,
        user_id: str,
        is_privileged_user: bool = False,
    ) -> Document:
        """Access a document, checking privilege restrictions."""
        if document_id not in self.documents:
            raise DocumentNotFoundError(f"Document {document_id} not found")

        doc = self.documents[document_id]

        if doc.is_privileged and not is_privileged_user:
            raise PrivilegeClaimError(f"Access denied to privileged document {document_id}")

        logger.info(f"User {user_id} accessed document {document_id}")
        return doc

    def get_document(self, document_id: str) -> Document:
        """Retrieve a document."""
        if document_id not in self.documents:
            raise DocumentNotFoundError(f"Document {document_id} not found")
        return self.documents[document_id]

    def get_document_version(
        self,
        document_id: str,
        version: int,
    ) -> Document:
        """Retrieve a specific version of a document."""
        if document_id not in self.document_versions:
            raise DocumentNotFoundError(f"Document {document_id} not found")

        versions = self.document_versions[document_id]
        matching = [v for v in versions if v.version == version]

        if not matching:
            raise DocumentNotFoundError(f"Document {document_id} version {version} not found")

        return matching[0]

    def get_document_history(self, document_id: str) -> list[Document]:
        """Get version history for a document."""
        if document_id not in self.document_versions:
            raise DocumentNotFoundError(f"Document {document_id} not found")
        return self.document_versions[document_id]

    def get_documents_by_case(self, case_id: str) -> list[Document]:
        """Get all documents for a case."""
        return [d for d in self.documents.values() if d.case_id == case_id]

    def get_documents_by_type(
        self,
        document_type: DocumentType,
    ) -> list[Document]:
        """Get all documents of a specific type."""
        return [d for d in self.documents.values() if d.document_type == document_type]

    def get_privileged_documents(self) -> list[Document]:
        """Get all privileged documents."""
        return [d for d in self.documents.values() if d.is_privileged]

    def export_document(
        self,
        document_id: str,
        format: str = "text",
    ) -> str:
        """Export document in specified format."""
        if document_id not in self.documents:
            raise DocumentNotFoundError(f"Document {document_id} not found")

        doc = self.documents[document_id]

        if format == "text":
            return doc.full_text
        elif format == "metadata":
            return str(
                {
                    "title": doc.title,
                    "type": doc.document_type.value,
                    "author": doc.author,
                    "created": doc.created_at,
                    "version": doc.version,
                    "privileged": doc.is_privileged,
                }
            )
        elif format == "bates":
            if doc.bates_number_start:
                return f"BATES: {doc.bates_number_start:06d} - {doc.bates_number_end:06d}"
            return "No Bates numbers assigned"
        else:
            raise ValueError(f"Unsupported format: {format}")

    def _log_privilege_claim(
        self,
        document_id: str,
        privilege_holder: str,
    ) -> None:
        """Internal: log privilege claim for new document."""
        if document_id in self.documents:
            doc = self.documents[document_id]
            self.privilege_log.append(
                {
                    "document_id": document_id,
                    "title": doc.title,
                    "privilege_type": "attorney-client",
                    "privilege_holder": privilege_holder,
                    "created_at": datetime.now(),
                    "case_id": doc.case_id,
                }
            )
