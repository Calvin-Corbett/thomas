"""Tests for legal case management module."""

from datetime import timedelta
from decimal import Decimal

import pytest

from thomas.marketplace.legal._exceptions import InvalidCaseStateError
from thomas.marketplace.legal._types import (
    CaseOutcome,
    CaseStatus,
    CaseType,
    Jurisdiction,
    Statute,
)
from thomas.marketplace.legal.cases import CaseManager


class TestCaseManager:
    """Test suite for CaseManager."""

    @pytest.fixture
    def manager(self) -> CaseManager:
        """Create a CaseManager instance for testing."""
        return CaseManager()

    @pytest.fixture
    def sample_jurisdiction(self) -> Jurisdiction:
        """Create a sample jurisdiction."""
        return Jurisdiction(code="CA", name="California", court_type="state", region="west")

    @pytest.fixture
    def sample_statute(self, sample_jurisdiction: Jurisdiction) -> Statute:
        """Create a sample statute of limitations."""
        return Statute(
            statute_id="sol_001",
            title="Contract Statute of Limitations",
            code="California Code of Civil Procedure § 337",
            jurisdiction=sample_jurisdiction,
            years=4,
            description="Standard contract statute of limitations",
            case_types=[CaseType.CIVIL, CaseType.CORPORATE],
        )

    def test_create_case(self, manager: CaseManager) -> None:
        """Test creating a new case."""
        case = manager.create_case(
            case_name="Smith v. Jones",
            case_type=CaseType.CIVIL,
            client_id="client_001",
            assigned_attorney_id="attorney_001",
            description="Personal injury case",
        )

        assert case.case_id in manager.cases
        assert case.case_name == "Smith v. Jones"
        assert case.case_type == CaseType.CIVIL
        assert case.status == CaseStatus.INTAKE
        assert "CIV" in case.matter_number

    def test_matter_numbering(self, manager: CaseManager) -> None:
        """Test matter number generation."""
        case1 = manager.create_case(
            case_name="Case 1",
            case_type=CaseType.CIVIL,
            client_id="client_001",
            assigned_attorney_id="attorney_001",
        )

        case2 = manager.create_case(
            case_name="Case 2",
            case_type=CaseType.CIVIL,
            client_id="client_001",
            assigned_attorney_id="attorney_001",
        )

        # Extract sequence numbers
        seq1 = int(case1.matter_number.split("-")[-1])
        seq2 = int(case2.matter_number.split("-")[-1])

        assert seq2 > seq1

    def test_case_state_transitions(self, manager: CaseManager) -> None:
        """Test valid and invalid case state transitions."""
        case = manager.create_case(
            case_name="Test Case",
            case_type=CaseType.CIVIL,
            client_id="client_001",
            assigned_attorney_id="attorney_001",
        )

        # Valid: INTAKE -> OPEN
        updated = manager.transition_case(case.case_id, CaseStatus.OPEN)
        assert updated.status == CaseStatus.OPEN
        assert updated.opened_date is not None

        # Valid: OPEN -> DISCOVERY
        updated = manager.transition_case(case.case_id, CaseStatus.DISCOVERY)
        assert updated.status == CaseStatus.DISCOVERY

        # Invalid: DISCOVERY -> INTAKE (not in transitions)
        with pytest.raises(InvalidCaseStateError):
            manager.transition_case(case.case_id, CaseStatus.INTAKE)

    def test_case_assignment_workload(self, manager: CaseManager) -> None:
        """Test case assignment and workload tracking."""
        case = manager.create_case(
            case_name="Test Case",
            case_type=CaseType.CIVIL,
            client_id="client_001",
            assigned_attorney_id="attorney_001",
            hourly_budget=Decimal("100.00"),
        )

        assert manager.get_attorney_workload("attorney_001") == Decimal("100.00")

        # Reassign to different attorney
        manager.assign_case(case.case_id, "attorney_002")
        assert manager.get_attorney_workload("attorney_001") == Decimal("0.00")
        assert manager.get_attorney_workload("attorney_002") == Decimal("100.00")

    def test_least_loaded_attorney(self, manager: CaseManager) -> None:
        """Test finding least loaded attorney."""
        manager.create_case(
            case_name="Case 1",
            case_type=CaseType.CIVIL,
            client_id="client_001",
            assigned_attorney_id="attorney_001",
            hourly_budget=Decimal("50.00"),
        )

        manager.create_case(
            case_name="Case 2",
            case_type=CaseType.CIVIL,
            client_id="client_001",
            assigned_attorney_id="attorney_002",
            hourly_budget=Decimal("30.00"),
        )

        least_loaded = manager.find_least_loaded_attorney(["attorney_001", "attorney_002"])
        assert least_loaded == "attorney_002"

    def test_link_related_cases(self, manager: CaseManager) -> None:
        """Test linking related cases."""
        case1 = manager.create_case(
            case_name="Case 1",
            case_type=CaseType.CIVIL,
            client_id="client_001",
            assigned_attorney_id="attorney_001",
        )

        case2 = manager.create_case(
            case_name="Case 2 (Appeal)",
            case_type=CaseType.CIVIL,
            client_id="client_001",
            assigned_attorney_id="attorney_001",
        )

        manager.link_related_cases(case1.case_id, case2.case_id)

        related1 = manager.get_related_cases(case1.case_id)
        related2 = manager.get_related_cases(case2.case_id)

        assert len(related1) == 1
        assert related1[0].case_id == case2.case_id
        assert len(related2) == 1
        assert related2[0].case_id == case1.case_id

    def test_set_case_outcome(self, manager: CaseManager) -> None:
        """Test setting case outcome."""
        case = manager.create_case(
            case_name="Test Case",
            case_type=CaseType.CIVIL,
            client_id="client_001",
            assigned_attorney_id="attorney_001",
        )

        # Transition to closed first
        manager.transition_case(case.case_id, CaseStatus.OPEN)
        manager.transition_case(case.case_id, CaseStatus.CLOSED)

        # Now set outcome
        updated = manager.set_case_outcome(case.case_id, CaseOutcome.SETTLED, metadata={"settlement_amount": "50000"})

        assert updated.case_outcome == CaseOutcome.SETTLED
        assert updated.metadata["settlement_amount"] == "50000"

    def test_calculate_statute_of_limitations(
        self,
        manager: CaseManager,
        sample_statute: Statute,
    ) -> None:
        """Test statute of limitations calculation."""
        case = manager.create_case(
            case_name="Contract Dispute",
            case_type=CaseType.CIVIL,
            client_id="client_001",
            assigned_attorney_id="attorney_001",
        )

        updated = manager.calculate_statute_of_limitations(
            case.case_id,
            sample_statute,
        )

        expected_date = case.intake_date.date() + timedelta(days=4 * 365)

        assert updated.statute_of_limitations == sample_statute
        assert updated.sol_expiration_date is not None
        # Allow 1 day variance for leap years
        assert abs((updated.sol_expiration_date - expected_date).days) <= 1

    def test_case_timeline(self, manager: CaseManager) -> None:
        """Test retrieving case timeline."""
        case = manager.create_case(
            case_name="Test Case",
            case_type=CaseType.CIVIL,
            client_id="client_001",
            assigned_attorney_id="attorney_001",
        )

        manager.transition_case(case.case_id, CaseStatus.OPEN)
        manager.transition_case(case.case_id, CaseStatus.CLOSED)

        timeline = manager.get_case_timeline(case.case_id)

        assert timeline["intake"] is not None
        assert timeline["opened"] is not None
        assert timeline["closed"] is not None
        assert timeline["archived"] is None

    def test_search_cases(self, manager: CaseManager) -> None:
        """Test case searching with filters."""
        case1 = manager.create_case(
            case_name="Smith v. Jones",
            case_type=CaseType.CIVIL,
            client_id="client_001",
            assigned_attorney_id="attorney_001",
        )

        case2 = manager.create_case(
            case_name="Doe Employment Case",
            case_type=CaseType.EMPLOYMENT,
            client_id="client_002",
            assigned_attorney_id="attorney_002",
        )

        # Search by name
        results = manager.search_cases(case_name="Smith")
        assert len(results) == 1
        assert results[0].case_id == case1.case_id

        # Search by case type
        results = manager.search_cases(case_type=CaseType.EMPLOYMENT)
        assert len(results) == 1
        assert results[0].case_id == case2.case_id

        # Search by attorney
        results = manager.search_cases(attorney_id="attorney_001")
        assert len(results) == 1
        assert results[0].case_id == case1.case_id

    def test_get_cases_by_status(self, manager: CaseManager) -> None:
        """Test retrieving cases by status."""
        case1 = manager.create_case(
            case_name="Case 1",
            case_type=CaseType.CIVIL,
            client_id="client_001",
            assigned_attorney_id="attorney_001",
        )

        manager.create_case(
            case_name="Case 2",
            case_type=CaseType.CIVIL,
            client_id="client_001",
            assigned_attorney_id="attorney_001",
        )

        # Both start in INTAKE
        intake_cases = manager.get_cases_by_status(CaseStatus.INTAKE)
        assert len(intake_cases) == 2

        # Transition one
        manager.transition_case(case1.case_id, CaseStatus.OPEN)

        intake_cases = manager.get_cases_by_status(CaseStatus.INTAKE)
        open_cases = manager.get_cases_by_status(CaseStatus.OPEN)

        assert len(intake_cases) == 1
        assert len(open_cases) == 1

    def test_case_type_abbreviations(self) -> None:
        """Test case type abbreviation generation."""
        test_cases = [
            (CaseType.CIVIL, "CIV"),
            (CaseType.CRIMINAL, "CRM"),
            (CaseType.FAMILY, "FAM"),
            (CaseType.CORPORATE, "COR"),
            (CaseType.INTELLECTUAL_PROPERTY, "IP"),
            (CaseType.EMPLOYMENT, "EMP"),
            (CaseType.BANKRUPTCY, "BNK"),
            (CaseType.TAX, "TAX"),
        ]

        for case_type, expected_abbrev in test_cases:
            abbrev = CaseManager._get_case_type_abbrev(case_type)
            assert abbrev == expected_abbrev

    def test_get_cases_by_client(self, manager: CaseManager) -> None:
        """Test retrieving cases by client."""
        manager.create_case(
            case_name="Case 1",
            case_type=CaseType.CIVIL,
            client_id="client_001",
            assigned_attorney_id="attorney_001",
        )

        manager.create_case(
            case_name="Case 2",
            case_type=CaseType.CIVIL,
            client_id="client_001",
            assigned_attorney_id="attorney_001",
        )

        manager.create_case(
            case_name="Case 3",
            case_type=CaseType.CIVIL,
            client_id="client_002",
            assigned_attorney_id="attorney_001",
        )

        client_001_cases = manager.get_cases_by_client("client_001")
        assert len(client_001_cases) == 2

        client_002_cases = manager.get_cases_by_client("client_002")
        assert len(client_002_cases) == 1
