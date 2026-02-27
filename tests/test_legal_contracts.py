"""Tests for legal contract management module."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from thomas.legal._exceptions import InvalidContractStateError
from thomas.legal._types import ContractStatus
from thomas.legal.contracts import (
    ClauseLibrary,
    ContractManager,
)


class TestClauseLibrary:
    """Test suite for ClauseLibrary."""

    @pytest.fixture
    def library(self) -> ClauseLibrary:
        """Create a ClauseLibrary instance."""
        return ClauseLibrary()

    def test_add_clause(self, library: ClauseLibrary) -> None:
        """Test adding a clause to the library."""
        clause = library.add_clause(
            title="Indemnification",
            content="Each party shall indemnify the other...",
            category="indemnification",
        )

        assert clause.clause_id in library.clauses
        assert clause.version == 1
        assert clause.is_current

    def test_update_clause(self, library: ClauseLibrary) -> None:
        """Test updating a clause (creates new version)."""
        clause1 = library.add_clause(
            title="Limitation of Liability",
            content="In no event shall liability exceed...",
            category="limitation_of_liability",
        )

        clause2 = library.update_clause(
            clause1.clause_id,
            content="In no event shall liability exceed $1,000,000...",
        )

        assert clause2.version == 2
        assert not clause1.is_current
        assert clause2.is_current

    def test_get_clause_by_version(self, library: ClauseLibrary) -> None:
        """Test retrieving specific clause versions."""
        clause1 = library.add_clause(
            title="Test Clause",
            content="Version 1",
            category="test",
        )

        library.update_clause(clause1.clause_id, "Version 2")

        retrieved_v1 = library.get_clause(clause1.clause_id, version=1)
        retrieved_v2 = library.get_clause(clause1.clause_id, version=2)

        assert retrieved_v1.content == "Version 1"
        assert retrieved_v2.content == "Version 2"

    def test_get_clauses_by_category(self, library: ClauseLibrary) -> None:
        """Test retrieving clauses by category."""
        library.add_clause(
            title="Indem 1",
            content="Content 1",
            category="indemnification",
        )

        library.add_clause(
            title="Indem 2",
            content="Content 2",
            category="indemnification",
        )

        library.add_clause(
            title="Limitation",
            content="Content 3",
            category="limitation_of_liability",
        )

        indem_clauses = library.get_clauses_by_category("indemnification")
        assert len(indem_clauses) == 2

    def test_search_clauses(self, library: ClauseLibrary) -> None:
        """Test searching clauses by keyword."""
        library.add_clause(
            title="Payment Terms",
            content="Payment due within 30 days",
            category="payment",
        )

        library.add_clause(
            title="Delivery Terms",
            content="Delivery within 15 business days",
            category="delivery",
        )

        results = library.search_clauses("payment")
        assert len(results) == 1
        assert "Payment" in results[0].title

    def test_clause_history(self, library: ClauseLibrary) -> None:
        """Test retrieving clause version history."""
        clause = library.add_clause(
            title="Test",
            content="v1",
            category="test",
        )

        library.update_clause(clause.clause_id, "v2")
        library.update_clause(clause.clause_id, "v3")

        history = library.get_clause_history(clause.clause_id)
        assert len(history) == 3
        assert history[0].version == 1
        assert history[2].version == 3


class TestContractManager:
    """Test suite for ContractManager."""

    @pytest.fixture
    def library(self) -> ClauseLibrary:
        """Create a ClauseLibrary instance."""
        return ClauseLibrary()

    @pytest.fixture
    def manager(self, library: ClauseLibrary) -> ContractManager:
        """Create a ContractManager instance."""
        return ContractManager(library)

    def test_create_contract(self, manager: ContractManager) -> None:
        """Test creating a new contract."""
        contract = manager.create_contract(
            title="Service Agreement",
            client_id="client_001",
            counterparty="Vendor Inc.",
            value=Decimal("50000.00"),
        )

        assert contract.contract_id in manager.contracts
        assert contract.status == ContractStatus.DRAFT
        assert contract.title == "Service Agreement"

    def test_contract_state_transitions(self, manager: ContractManager) -> None:
        """Test contract state transitions."""
        contract = manager.create_contract(
            title="Test Contract",
            client_id="client_001",
            counterparty="Other Party",
        )

        # Valid: DRAFT -> REVIEW
        updated = manager.transition_contract(
            contract.contract_id,
            ContractStatus.REVIEW,
        )
        assert updated.status == ContractStatus.REVIEW

        # Valid: REVIEW -> NEGOTIATION
        updated = manager.transition_contract(
            contract.contract_id,
            ContractStatus.NEGOTIATION,
        )
        assert updated.status == ContractStatus.NEGOTIATION

        # Valid: NEGOTIATION -> EXECUTED
        updated = manager.transition_contract(
            contract.contract_id,
            ContractStatus.EXECUTED,
        )
        assert updated.status == ContractStatus.EXECUTED
        assert updated.execution_date is not None

        # Invalid: EXECUTED -> DRAFT
        with pytest.raises(InvalidContractStateError):
            manager.transition_contract(
                contract.contract_id,
                ContractStatus.DRAFT,
            )

    def test_assemble_contract(
        self,
        manager: ContractManager,
        library: ClauseLibrary,
    ) -> None:
        """Test assembling contract from clauses."""
        clause1 = library.add_clause(
            title="Indemnification",
            content="Indemnify content...",
            category="indemnification",
        )

        clause2 = library.add_clause(
            title="Limitation of Liability",
            content="Limit liability to...",
            category="limitation",
        )

        contract = manager.create_contract(
            title="Master Service Agreement",
            client_id="client_001",
            counterparty="Vendor",
        )

        updated = manager.assemble_contract(
            contract.contract_id,
            [clause1.clause_id, clause2.clause_id],
        )

        assert len(updated.clauses) == 2
        assert clause1.clause_id in updated.clauses

    def test_set_contract_dates(self, manager: ContractManager) -> None:
        """Test setting contract dates."""
        contract = manager.create_contract(
            title="Test Contract",
            client_id="client_001",
            counterparty="Other Party",
        )

        effective = date(2024, 1, 1)
        expiration = date(2025, 1, 1)

        updated = manager.set_contract_dates(
            contract.contract_id,
            effective_date=effective,
            expiration_date=expiration,
        )

        assert updated.effective_date == effective
        assert updated.expiration_date == expiration

    def test_compare_contracts(
        self,
        manager: ContractManager,
        library: ClauseLibrary,
    ) -> None:
        """Test contract comparison."""
        clause1 = library.add_clause(
            title="Payment",
            content="Payment terms original",
            category="payment",
        )

        contract = manager.create_contract(
            title="Contract V1",
            client_id="client_001",
            counterparty="Vendor",
        )

        manager.assemble_contract(contract.contract_id, [clause1.clause_id])

        # Create second version
        contract2 = manager.create_contract(
            title="Contract V2",
            client_id="client_001",
            counterparty="Vendor",
        )

        # Assemble with updated clause
        clause2 = library.update_clause(
            clause1.clause_id,
            "Payment terms updated",
        )

        manager.assemble_contract(contract2.contract_id, [clause2.clause_id])

        comparison = manager.compare_contracts(
            contract.contract_id,
            contract2.contract_id,
        )

        assert comparison["contract_1"] == contract.contract_id
        assert comparison["contract_2"] == contract2.contract_id
        assert comparison["additions"] >= 0
        assert comparison["deletions"] >= 0
        assert 0 <= comparison["similarity"] <= 100

    def test_extract_obligations(
        self,
        manager: ContractManager,
        library: ClauseLibrary,
    ) -> None:
        """Test extracting obligations from contract."""
        clause = library.add_clause(
            title="Delivery",
            content=(
                "Vendor shall deliver goods within 30 days of order. "
                "Payment of $50,000 due by December 31, 2024. "
                "Deliverable: monthly reports within 5 days of month end."
            ),
            category="delivery",
        )

        contract = manager.create_contract(
            title="Vendor Agreement",
            client_id="client_001",
            counterparty="Vendor",
        )

        manager.assemble_contract(contract.contract_id, [clause.clause_id])

        obligations = manager.extract_obligations(contract.contract_id)

        assert "deadlines" in obligations
        assert "payments" in obligations
        assert "deliverables" in obligations
        assert len(obligations["deadlines"]) > 0
        assert len(obligations["payments"]) > 0

    def test_add_amendment(self, manager: ContractManager) -> None:
        """Test adding amendments to contract."""
        contract = manager.create_contract(
            title="Test Contract",
            client_id="client_001",
            counterparty="Vendor",
        )

        updated = manager.add_amendment(
            contract.contract_id,
            "Increase price by 10%",
            {"price_increase": "10%"},
        )

        assert len(updated.amendments) == 1
        assert updated.amendments[0]["description"] == "Increase price by 10%"

    def test_check_renewal_status(self, manager: ContractManager) -> None:
        """Test renewal status checking."""
        contract = manager.create_contract(
            title="Annual Contract",
            client_id="client_001",
            counterparty="Vendor",
        )

        # Set expiration 60 days from now
        expiration = date.today() + timedelta(days=60)
        manager.set_contract_dates(
            contract.contract_id,
            expiration_date=expiration,
        )

        status = manager.check_renewal_status(contract.contract_id)

        assert status["needs_renewal"] is True
        assert 50 <= status["days_until_expiration"] <= 60

    def test_get_expiring_contracts(self, manager: ContractManager) -> None:
        """Test retrieving contracts approaching expiration."""
        contract1 = manager.create_contract(
            title="Expiring Soon",
            client_id="client_001",
            counterparty="Vendor A",
        )

        contract2 = manager.create_contract(
            title="Not Expiring",
            client_id="client_001",
            counterparty="Vendor B",
        )

        # Set contract1 to expire in 60 days
        expiration1 = date.today() + timedelta(days=60)
        manager.set_contract_dates(
            contract1.contract_id,
            expiration_date=expiration1,
        )
        manager.transition_contract(contract1.contract_id, ContractStatus.ACTIVE)

        # Set contract2 to expire in 200 days
        expiration2 = date.today() + timedelta(days=200)
        manager.set_contract_dates(
            contract2.contract_id,
            expiration_date=expiration2,
        )
        manager.transition_contract(contract2.contract_id, ContractStatus.ACTIVE)

        # Get expiring within 90 days
        expiring = manager.get_expiring_contracts(days_threshold=90)

        assert len(expiring) == 1
        assert expiring[0].contract_id == contract1.contract_id
