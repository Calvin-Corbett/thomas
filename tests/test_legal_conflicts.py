"""Tests for conflict of interest checking module."""

import pytest

from thomas.marketplace.legal.conflicts import ConflictChecker


class TestConflictChecker:
    """Test suite for ConflictChecker."""

    @pytest.fixture
    def checker(self) -> ConflictChecker:
        """Create a ConflictChecker instance."""
        return ConflictChecker()

    def test_check_party_conflict(self, checker: ConflictChecker) -> None:
        """Test detecting direct adverse conflicts."""
        # Add a party to the index
        checker.parties_index["acme corporation"] = {"case_001"}

        # Check for conflict with similar name
        conflict = checker.check_party_conflict("ACME Corp", "case_002")

        assert conflict is not None
        assert conflict.conflict_type == "direct_adverse"

    def test_fuzzy_matching(self) -> None:
        """Test fuzzy string matching."""
        # Perfect match
        score = ConflictChecker._fuzzy_match("acme", "acme")
        assert score == 1.0

        # Close match
        score = ConflictChecker._fuzzy_match("acme corporation", "acme corp")
        assert score > 0.8

        # No match
        score = ConflictChecker._fuzzy_match("acme", "xyz")
        assert score < 0.5

    def test_material_limitation_conflict(self, checker: ConflictChecker) -> None:
        """Test detecting material limitation conflicts."""
        attorney_id = "attorney_001"

        # Add prior matter for attorney
        checker.add_prior_matter(
            attorney_id=attorney_id,
            party_name="Defendant Corp",
            case_name="Case 1",
            is_adverse=True,
        )

        # Check for conflict with similar adverse party
        conflict = checker.check_material_limitation(
            attorney_id,
            "Defendant Corporation",  # Similar name
            "case_002",
        )

        assert conflict is not None
        assert conflict.conflict_type == "material_limitation"

    def test_business_transaction_conflict(self, checker: ConflictChecker) -> None:
        """Test detecting business transaction conflicts."""
        attorney_id = "attorney_001"

        checker.add_prior_matter(
            attorney_id=attorney_id,
            party_name="XYZ Inc",
            case_name="Prior Matter",
            is_adverse=True,
        )

        conflict = checker.check_business_transaction_conflict(
            attorney_id,
            "client_001",
            ["XYZ Inc", "ABC Corp"],
        )

        assert conflict is not None
        assert conflict.conflict_type == "business_transaction"

    def test_screen_new_matter_intake(self, checker: ConflictChecker) -> None:
        """Test screening new matter at intake."""
        # Set up prior matter
        checker.add_prior_matter(
            attorney_id="attorney_001",
            party_name="Smith Corp",
            case_name="Prior Case",
            is_adverse=True,
        )

        # Screen new matter with adverse party
        is_clear, conflicts = checker.screen_new_matter_intake(
            case_id="case_002",
            client_id="client_001",
            opposing_parties=["Smith Corporation"],
            assigned_attorney_id="attorney_001",
        )

        assert is_clear is False
        assert len(conflicts) > 0

    def test_screen_new_matter_clear(self, checker: ConflictChecker) -> None:
        """Test screening new matter with no conflicts."""
        is_clear, conflicts = checker.screen_new_matter_intake(
            case_id="case_001",
            client_id="client_001",
            opposing_parties=["Defendant Inc"],
            assigned_attorney_id="attorney_001",
        )

        assert is_clear is True
        assert len(conflicts) == 0

    def test_lateral_hire_conflict(self, checker: ConflictChecker) -> None:
        """Test detecting lateral hire conflicts."""
        attorney_id = "attorney_new"

        # Add prior matters from previous firm
        checker.add_prior_matter(
            attorney_id=attorney_id,
            party_name="Acme Corp",
            case_name="Case 1",
            is_adverse=True,
        )

        checker.add_prior_matter(
            attorney_id=attorney_id,
            party_name="XYZ Inc",
            case_name="Case 2",
            is_adverse=False,
        )

        # Check new matters at current firm
        new_matters = [
            {
                "case_id": "new_case_1",
                "party_name": "ACME Corporation",  # Adverse from prior
            },
            {
                "case_id": "new_case_2",
                "party_name": "XYZ Inc",  # Not adverse
            },
        ]

        conflicts = checker.check_lateral_hire(attorney_id, new_matters)

        # Should find conflict only for adverse party
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == "lateral_hire"

    def test_waive_conflict(self, checker: ConflictChecker) -> None:
        """Test recording conflict waiver."""
        # Create a conflict
        checker.conflicts["conflict_001"] = type(
            "Conflict",
            (),
            {
                "conflict_id": "conflict_001",
                "waived": False,
                "waiver_details": None,
            },
        )()

        waived = checker.waive_conflict(
            "conflict_001",
            informed_client="client_001",
            informed_opposing="opposing_counsel@example.com",
            waiver_details={"acknowledged": True},
        )

        assert waived.waived is True
        assert waived.waiver_details is not None

    def test_get_waived_conflicts(self, checker: ConflictChecker) -> None:
        """Test retrieving waived conflicts."""
        # Create multiple conflicts
        conflict_data = [
            {
                "conflict_id": "c001",
                "case_id": "case_001",
                "waived": True,
            },
            {
                "conflict_id": "c002",
                "case_id": "case_001",
                "waived": False,
            },
            {
                "conflict_id": "c003",
                "case_id": "case_002",
                "waived": True,
            },
        ]

        for data in conflict_data:
            conflict = type("Conflict", (), data)()
            checker.conflicts[data["conflict_id"]] = conflict

        waived = checker.get_waived_conflicts("case_001")
        assert len(waived) == 1
        assert waived[0].conflict_id == "c001"

    def test_add_prior_matter(self, checker: ConflictChecker) -> None:
        """Test adding prior matter to attorney history."""
        attorney_id = "attorney_001"

        checker.add_prior_matter(
            attorney_id=attorney_id,
            party_name="Smith v. Jones",
            case_name="Contract Dispute",
            is_adverse=True,
            jurisdiction="California",
        )

        assert attorney_id in checker.prior_matters
        assert len(checker.prior_matters[attorney_id]) == 1

        matter = checker.prior_matters[attorney_id][0]
        assert matter["party_name"] == "Smith v. Jones"
        assert matter["is_adverse"] is True

    def test_conflict_report_generation(self, checker: ConflictChecker) -> None:
        """Test generating conflict report."""
        # Add some test conflicts
        conflict_data = [
            {
                "conflict_id": "c001",
                "party_name": "Acme",
                "conflict_type": "direct_adverse",
                "waived": False,
            },
            {
                "conflict_id": "c002",
                "party_name": "Smith",
                "conflict_type": "material_limitation",
                "waived": True,
            },
        ]

        for data in conflict_data:
            conflict = type("Conflict", (), data)()
            checker.conflicts[data["conflict_id"]] = conflict

        report = checker.generate_conflict_report()

        assert report["total_conflicts"] == 2
        assert report["unwaived"] == 1
        assert report["waived"] == 1
        assert "direct_adverse" in report["by_type"]
