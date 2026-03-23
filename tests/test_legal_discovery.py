"""Tests for e-discovery and litigation hold module."""

import pytest

from thomas.marketplace.legal.discovery import DiscoveryManager, HoldStatus, ReviewCoding


class TestDiscoveryManager:
    """Test suite for DiscoveryManager."""

    @pytest.fixture
    def manager(self) -> DiscoveryManager:
        """Create a DiscoveryManager instance."""
        return DiscoveryManager()

    def test_issue_legal_hold(self, manager: DiscoveryManager) -> None:
        """Test issuing a legal hold."""
        hold = manager.issue_legal_hold(
            case_id="case_001",
            case_name="Smith v. Jones",
            custodians=["employee_001", "employee_002", "employee_003"],
        )

        assert hold.hold_id in manager.holds
        assert hold.status == HoldStatus.ACTIVE
        assert len(hold.custodians) == 3

    def test_acknowledge_hold(self, manager: DiscoveryManager) -> None:
        """Test custodian acknowledgment of hold."""
        hold = manager.issue_legal_hold(
            case_id="case_001",
            case_name="Smith v. Jones",
            custodians=["employee_001", "employee_002"],
        )

        updated = manager.acknowledge_hold(hold.hold_id, "employee_001")
        assert "employee_001" in updated.custodian_acks

    def test_hold_compliance_status(self, manager: DiscoveryManager) -> None:
        """Test calculating hold compliance."""
        hold = manager.issue_legal_hold(
            case_id="case_001",
            case_name="Smith v. Jones",
            custodians=["emp_001", "emp_002", "emp_003"],
        )

        manager.acknowledge_hold(hold.hold_id, "emp_001")
        manager.acknowledge_hold(hold.hold_id, "emp_002")

        compliance = manager.get_hold_compliance(hold.hold_id)

        assert compliance["total_custodians"] == 3
        assert compliance["acknowledged"] == 2
        assert compliance["pending"] == 1
        assert len(compliance["pending_custodians"]) == 1

    def test_release_hold(self, manager: DiscoveryManager) -> None:
        """Test releasing a legal hold."""
        hold = manager.issue_legal_hold(
            case_id="case_001",
            case_name="Smith v. Jones",
            custodians=["emp_001"],
        )

        updated = manager.release_hold(hold.hold_id)

        assert updated.status == HoldStatus.RELEASED
        assert updated.released_date is not None

    def test_add_data_source(self, manager: DiscoveryManager) -> None:
        """Test adding a data source for collection."""
        source = manager.add_data_source(
            source_name="John Smith Email",
            source_type="email",
            custodian="john_smith",
            location="john.smith@company.com",
        )

        assert source.source_id in manager.data_sources
        assert source.source_type == "email"

    def test_log_collection(self, manager: DiscoveryManager) -> None:
        """Test logging data collection."""
        source = manager.add_data_source(
            source_name="File Server",
            source_type="fileserver",
            custodian="dept_legal",
            location="\\\\server\\legal",
        )

        entry = manager.log_collection(
            source.source_id,
            document_count=1500,
            method="forensic_image",
        )

        assert entry["document_count"] == 1500
        assert source.document_count == 1500
        assert source.collected_date is not None

    def test_create_review_queue(self, manager: DiscoveryManager) -> None:
        """Test creating a document review queue."""
        doc_ids = [f"doc_{i}" for i in range(10)]

        manager.create_review_queue("case_001", doc_ids)

        assert len(manager.review_queue) == 10
        assert len(manager.reviews) == 10

    def test_assign_review(self, manager: DiscoveryManager) -> None:
        """Test assigning documents for review."""
        doc_ids = [f"doc_{i}" for i in range(5)]
        manager.create_review_queue("case_001", doc_ids)

        review_id = manager.review_queue[0]
        updated = manager.assign_review(review_id, "reviewer_001")

        assert updated.reviewer_id == "reviewer_001"
        assert review_id not in manager.review_queue

    def test_code_document(self, manager: DiscoveryManager) -> None:
        """Test coding documents during review."""
        doc_ids = ["doc_001"]
        manager.create_review_queue("case_001", doc_ids)

        review_id = manager.review_queue[0]
        manager.assign_review(review_id, "reviewer_001")

        updated = manager.code_document(
            review_id,
            ReviewCoding.RELEVANT,
            notes="Contains email about contract",
        )

        assert updated.coding == ReviewCoding.RELEVANT
        assert updated.review_date is not None

    def test_search_documents(self, manager: DiscoveryManager) -> None:
        """Test document keyword search."""
        results = manager.search_documents(
            case_id="case_001",
            keywords=["contract", "payment"],
        )

        assert isinstance(results, list)
        assert len(results) > 0

    def test_apply_tar(self, manager: DiscoveryManager) -> None:
        """Test Technology Assisted Review."""
        # Create some search results first
        manager.search_results["case_001"] = [f"doc_{i}" for i in range(100)]

        tar_result = manager.apply_tar(
            case_id="case_001",
            seed_set=[f"doc_{i}" for i in range(10)],
            training_iterations=3,
        )

        assert tar_result["case_id"] == "case_001"
        assert tar_result["seed_set_size"] == 10
        assert tar_result["training_iterations"] == 3
        assert 0 < tar_result["estimated_accuracy"] < 1
        assert len(tar_result["prioritized_queue"]) > 0

    def test_create_production(self, manager: DiscoveryManager) -> None:
        """Test creating a production batch."""
        doc_ids = [f"doc_{i}" for i in range(5)]

        batch = manager.create_production(
            case_id="case_001",
            case_name="Smith v. Jones",
            recipient="opposing_counsel@example.com",
            document_ids=doc_ids,
        )

        assert batch.batch_id in manager.productions
        assert len(batch.documents) == 5
        assert batch.bates_start == 10000
        assert batch.bates_end == 10004

    def test_finalize_production(self, manager: DiscoveryManager) -> None:
        """Test finalizing a production batch."""
        batch = manager.create_production(
            case_id="case_001",
            case_name="Smith v. Jones",
            recipient="opposing_counsel@example.com",
            document_ids=["doc_001", "doc_002"],
        )

        updated = manager.finalize_production(batch.batch_id)

        assert updated.production_date is not None

    def test_get_review_metrics(self, manager: DiscoveryManager) -> None:
        """Test calculating review metrics."""
        doc_ids = [f"doc_{i}" for i in range(10)]
        manager.create_review_queue("case_001", doc_ids)

        # Code some documents
        for i in range(5):
            review_id = manager.reviews[next(iter(manager.reviews))].review_id
            review = manager.reviews.get(review_id)
            if review:
                manager.code_document(
                    review_id,
                    ReviewCoding.RELEVANT,
                )

        metrics = manager.get_review_metrics("case_001")

        assert metrics["total_documents"] == 10
        assert metrics["reviewed"] >= 0
        assert 0 <= metrics["completion_rate"] <= 1

    def test_bates_number_assignment(self, manager: DiscoveryManager) -> None:
        """Test Bates number assignment in production."""
        batch = manager.create_production(
            case_id="case_001",
            case_name="Test Case",
            recipient="opponent@example.com",
            document_ids=[f"doc_{i}" for i in range(3)],
        )

        # Verify sequential Bates numbers
        for i, doc in enumerate(batch.documents):
            expected_bates = f"{10000 + i:06d}"
            assert doc["bates_number"] == expected_bates
