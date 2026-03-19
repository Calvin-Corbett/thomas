"""E-discovery and litigation hold management module."""

import logging
import random
from datetime import datetime
from enum import Enum
from uuid import uuid4

from thomas.legal._exceptions import LegalHoldError

logger = logging.getLogger(__name__)


class HoldStatus(Enum):
    """Enumeration of legal hold statuses."""

    ACTIVE = "active"
    RELEASED = "released"
    SUSPENDED = "suspended"


class ReviewCoding(Enum):
    """Enumeration of document review codes."""

    RELEVANT = "relevant"
    NOT_RELEVANT = "not_relevant"
    PRIVILEGED = "privileged"
    WORK_PRODUCT = "work_product"
    RESPONSIVE = "responsive"
    NOT_RESPONSIVE = "not_responsive"


class LegalHold:
    """Represents a litigation hold notification."""

    def __init__(
        self,
        hold_id: str,
        case_id: str,
        case_name: str,
        custodians: list[str],
    ) -> None:
        """Initialize a legal hold."""
        self.hold_id = hold_id
        self.case_id = case_id
        self.case_name = case_name
        self.custodians = custodians
        self.status = HoldStatus.ACTIVE
        self.created_at = datetime.now()
        self.custodian_acks: dict[str, datetime] = {}
        self.released_date: datetime | None = None

    def acknowledge(self, custodian_id: str) -> None:
        """Record custodian acknowledgment of hold."""
        self.custodian_acks[custodian_id] = datetime.now()


class DataSource:
    """Represents a data source for collection."""

    def __init__(
        self,
        source_id: str,
        source_name: str,
        source_type: str,
        custodian: str,
        location: str,
    ) -> None:
        """Initialize a data source."""
        self.source_id = source_id
        self.source_name = source_name
        self.source_type = source_type  # email, fileserver, cloud, etc.
        self.custodian = custodian
        self.location = location
        self.collected_date: datetime | None = None
        self.document_count: int = 0


class DocumentReview:
    """Represents a document review task."""

    def __init__(
        self,
        review_id: str,
        document_id: str,
        case_id: str,
    ) -> None:
        """Initialize a document review."""
        self.review_id = review_id
        self.document_id = document_id
        self.case_id = case_id
        self.coding: ReviewCoding | None = None
        self.reviewer_id: str | None = None
        self.review_date: datetime | None = None
        self.notes: str = ""
        self.privilege_log_entry: bool = False


class ProductionBatch:
    """Represents a batch of documents for production."""

    def __init__(
        self,
        batch_id: str,
        case_id: str,
        case_name: str,
        recipient: str,
    ) -> None:
        """Initialize a production batch."""
        self.batch_id = batch_id
        self.case_id = case_id
        self.case_name = case_name
        self.recipient = recipient
        self.documents: list[dict] = []
        self.created_at = datetime.now()
        self.bates_start: int | None = None
        self.bates_end: int | None = None
        self.production_date: datetime | None = None


class DiscoveryManager:
    """Manages litigation holds, document collection, review, and production."""

    def __init__(self) -> None:
        """Initialize the discovery manager."""
        self.holds: dict[str, LegalHold] = {}
        self.data_sources: dict[str, DataSource] = {}
        self.collection_log: list[dict] = []
        self.reviews: dict[str, DocumentReview] = {}
        self.review_queue: list[str] = []
        self.productions: dict[str, ProductionBatch] = {}
        self.search_results: dict[str, list[str]] = {}
        self.tar_classifiers: dict[str, object] = {}  # case_id -> classifier

    def issue_legal_hold(
        self,
        case_id: str,
        case_name: str,
        custodians: list[str],
    ) -> LegalHold:
        """Issue a legal hold notice."""
        hold_id = str(uuid4())
        hold = LegalHold(
            hold_id=hold_id,
            case_id=case_id,
            case_name=case_name,
            custodians=custodians,
        )

        self.holds[hold_id] = hold
        logger.info(f"Issued legal hold {hold_id} for case {case_name}")
        return hold

    def acknowledge_hold(self, hold_id: str, custodian_id: str) -> LegalHold:
        """Record custodian acknowledgment of legal hold."""
        if hold_id not in self.holds:
            raise LegalHoldError(f"Hold {hold_id} not found")

        hold = self.holds[hold_id]
        if custodian_id not in hold.custodians:
            raise ValueError(f"Custodian {custodian_id} not in hold list")

        hold.acknowledge(custodian_id)
        logger.info(f"Hold {hold_id} acknowledged by {custodian_id}")
        return hold

    def get_hold_compliance(self, hold_id: str) -> dict:
        """Get compliance status for a hold."""
        if hold_id not in self.holds:
            raise LegalHoldError(f"Hold {hold_id} not found")

        hold = self.holds[hold_id]
        total = len(hold.custodians)
        acknowledged = len(hold.custodian_acks)

        return {
            "hold_id": hold_id,
            "status": hold.status.value,
            "total_custodians": total,
            "acknowledged": acknowledged,
            "pending": total - acknowledged,
            "compliance_rate": acknowledged / total if total > 0 else 0,
            "pending_custodians": [c for c in hold.custodians if c not in hold.custodian_acks],
        }

    def release_hold(self, hold_id: str) -> LegalHold:
        """Release a legal hold."""
        if hold_id not in self.holds:
            raise LegalHoldError(f"Hold {hold_id} not found")

        hold = self.holds[hold_id]
        hold.status = HoldStatus.RELEASED
        hold.released_date = datetime.now()

        logger.info(f"Released legal hold {hold_id}")
        return hold

    def add_data_source(
        self,
        source_name: str,
        source_type: str,
        custodian: str,
        location: str,
    ) -> DataSource:
        """Add a data source for collection."""
        source_id = str(uuid4())
        source = DataSource(
            source_id=source_id,
            source_name=source_name,
            source_type=source_type,
            custodian=custodian,
            location=location,
        )

        self.data_sources[source_id] = source
        self.collection_log.append(
            {
                "action": "source_added",
                "source_id": source_id,
                "timestamp": datetime.now(),
            }
        )

        logger.info(f"Added data source {source_id}: {source_name}")
        return source

    def log_collection(
        self,
        source_id: str,
        document_count: int,
        method: str,
    ) -> dict:
        """Log data collection from a source."""
        if source_id not in self.data_sources:
            raise ValueError(f"Source {source_id} not found")

        source = self.data_sources[source_id]
        source.collected_date = datetime.now()
        source.document_count = document_count

        entry = {
            "source_id": source_id,
            "document_count": document_count,
            "collection_method": method,
            "collected_at": datetime.now(),
        }

        self.collection_log.append(entry)
        logger.info(f"Collected {document_count} documents from {source_id}")
        return entry

    def create_review_queue(
        self,
        case_id: str,
        document_ids: list[str],
    ) -> None:
        """Create review queue from list of documents."""
        for doc_id in document_ids:
            review_id = str(uuid4())
            review = DocumentReview(
                review_id=review_id,
                document_id=doc_id,
                case_id=case_id,
            )
            self.reviews[review_id] = review
            self.review_queue.append(review_id)

        logger.info(f"Created review queue with {len(document_ids)} documents")

    def assign_review(self, review_id: str, reviewer_id: str) -> DocumentReview:
        """Assign a document for review."""
        if review_id not in self.reviews:
            raise ValueError(f"Review {review_id} not found")

        review = self.reviews[review_id]
        review.reviewer_id = reviewer_id

        if review_id in self.review_queue:
            self.review_queue.remove(review_id)

        logger.info(f"Assigned review {review_id} to {reviewer_id}")
        return review

    def code_document(
        self,
        review_id: str,
        coding: ReviewCoding,
        notes: str = "",
        privilege_log: bool = False,
    ) -> DocumentReview:
        """Code a document during review."""
        if review_id not in self.reviews:
            raise ValueError(f"Review {review_id} not found")

        review = self.reviews[review_id]
        review.coding = coding
        review.review_date = datetime.now()
        review.notes = notes
        review.privilege_log_entry = privilege_log

        logger.info(f"Coded review {review_id} as {coding.value}")
        return review

    def search_documents(
        self,
        case_id: str,
        keywords: list[str],
        exclude_keywords: list[str] | None = None,
    ) -> list[str]:
        """Search documents by keywords (mock implementation)."""
        search_id = str(uuid4())
        results = []

        # Mock: simulate finding documents matching keywords
        for i in range(random.randint(5, 20)):
            results.append(f"doc_{i}_{case_id}")

        self.search_results[search_id] = results
        logger.info(f"Search {search_id} found {len(results)} documents " f"matching {keywords}")

        return results

    def apply_tar(
        self,
        case_id: str,
        seed_set: list[str],
        training_iterations: int = 3,
    ) -> dict:
        """Apply Technology Assisted Review (TAR) using iterative training.

        Simulates: seed set -> train classifier -> prioritize queue ->
        review -> retrain.
        """
        # Simulate classifier training
        classifier_accuracy = 0.5 + (training_iterations * 0.15)
        classifier_accuracy = min(0.95, classifier_accuracy)

        # Simulate ranked results
        ranked_results = sorted(
            self.search_results.get(case_id, []),
            key=lambda x: random.random(),
        )

        tar_result = {
            "case_id": case_id,
            "seed_set_size": len(seed_set),
            "training_iterations": training_iterations,
            "estimated_accuracy": classifier_accuracy,
            "prioritized_queue": ranked_results[:50],
            "estimated_richness": 0.45 + (training_iterations * 0.12),
        }

        self.tar_classifiers[case_id] = classifier_accuracy
        logger.info(f"Applied TAR to case {case_id}")
        return tar_result

    def create_production(
        self,
        case_id: str,
        case_name: str,
        recipient: str,
        document_ids: list[str],
    ) -> ProductionBatch:
        """Create a batch for production to opposing counsel."""
        batch_id = str(uuid4())
        batch = ProductionBatch(
            batch_id=batch_id,
            case_id=case_id,
            case_name=case_name,
            recipient=recipient,
        )

        # Add documents with Bates numbers
        bates_start = 10000
        for i, doc_id in enumerate(document_ids):
            batch.documents.append(
                {
                    "document_id": doc_id,
                    "bates_number": f"{bates_start + i:06d}",
                    "redactions": [],
                    "produced_date": datetime.now(),
                }
            )

        batch.bates_start = bates_start
        batch.bates_end = bates_start + len(document_ids) - 1

        self.productions[batch_id] = batch
        logger.info(f"Created production batch {batch_id} with " f"{len(document_ids)} documents")

        return batch

    def finalize_production(
        self,
        batch_id: str,
    ) -> ProductionBatch:
        """Finalize a production batch for delivery."""
        if batch_id not in self.productions:
            raise ValueError(f"Production {batch_id} not found")

        batch = self.productions[batch_id]
        batch.production_date = datetime.now()

        logger.info(f"Finalized production batch {batch_id}")
        return batch

    def get_review_metrics(self, case_id: str) -> dict:
        """Calculate review metrics for a case."""
        case_reviews = [r for r in self.reviews.values() if r.case_id == case_id]

        total = len(case_reviews)
        completed = sum(1 for r in case_reviews if r.coding)
        relevant = sum(1 for r in case_reviews if r.coding == ReviewCoding.RELEVANT)
        privileged = sum(1 for r in case_reviews if r.coding in [ReviewCoding.PRIVILEGED, ReviewCoding.WORK_PRODUCT])

        richness = relevant / total if total > 0 else 0
        privilege_rate = privileged / total if total > 0 else 0

        return {
            "case_id": case_id,
            "total_documents": total,
            "reviewed": completed,
            "relevant": relevant,
            "privileged": privileged,
            "completion_rate": completed / total if total > 0 else 0,
            "richness": richness,
            "privilege_rate": privilege_rate,
            "pending_review": total - completed,
        }
