"""Contract management module for legal practice operations."""

import difflib
import logging
import re
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from thomas.legal._exceptions import InvalidContractStateError
from thomas.legal._types import (
    Clause,
    Contract,
    ContractStatus,
)

logger = logging.getLogger(__name__)


class ClauseLibrary:
    """Manages a library of reusable contract clauses with versioning."""

    def __init__(self) -> None:
        """Initialize the clause library."""
        self.clauses: dict[str, list[Clause]] = {}  # clause_id -> list of versions

    def add_clause(
        self,
        title: str,
        content: str,
        category: str,
        jurisdiction: object | None = None,
    ) -> Clause:
        """Add a new clause to the library."""
        clause_id = str(uuid4())
        clause = Clause(
            clause_id=clause_id,
            title=title,
            content=content,
            category=category,
            version=1,
            effective_date=date.today(),
            jurisdiction=jurisdiction,
            is_current=True,
        )

        self.clauses[clause_id] = [clause]
        logger.info(f"Added clause {clause_id}: {title}")
        return clause

    def update_clause(
        self,
        clause_id: str,
        content: str,
        title: str | None = None,
    ) -> Clause:
        """Create a new version of an existing clause."""
        if clause_id not in self.clauses:
            raise ValueError(f"Clause {clause_id} not found")

        old_clause = self.clauses[clause_id][-1]
        new_version = old_clause.version + 1

        new_clause = replace(
            old_clause,
            version=new_version,
            content=content,
            title=title or old_clause.title,
            effective_date=date.today(),
            is_current=True,
            created_at=datetime.now(),
        )

        # Mark old version as not current
        old_clause.is_current = False

        self.clauses[clause_id].append(new_clause)
        logger.info(f"Updated clause {clause_id} to version {new_version}")
        return new_clause

    def get_clause(self, clause_id: str, version: int | None = None) -> Clause:
        """Get a clause by ID, optionally specifying version."""
        if clause_id not in self.clauses:
            raise ValueError(f"Clause {clause_id} not found")

        versions = self.clauses[clause_id]
        if version:
            matching = [c for c in versions if c.version == version]
            if not matching:
                raise ValueError(f"Clause {clause_id} version {version} not found")
            return matching[0]

        return versions[-1]  # Return latest version

    def get_clauses_by_category(self, category: str) -> list[Clause]:
        """Get all current clauses in a category."""
        result = []
        for clause_list in self.clauses.values():
            current = next((c for c in clause_list if c.is_current), None)
            if current and current.category == category:
                result.append(current)
        return result

    def search_clauses(self, keyword: str) -> list[Clause]:
        """Search clauses by keyword in title or content."""
        results = []
        keyword_lower = keyword.lower()
        for clause_list in self.clauses.values():
            current = next((c for c in clause_list if c.is_current), None)
            if current and (keyword_lower in current.title.lower() or keyword_lower in current.content.lower()):
                results.append(current)
        return results

    def get_clause_history(self, clause_id: str) -> list[Clause]:
        """Get version history for a clause."""
        if clause_id not in self.clauses:
            raise ValueError(f"Clause {clause_id} not found")
        return self.clauses[clause_id]


class ContractManager:
    """Manages contract lifecycle, assembly, and comparison."""

    VALID_TRANSITIONS: dict[ContractStatus, list[ContractStatus]] = {
        ContractStatus.DRAFT: [
            ContractStatus.REVIEW,
            ContractStatus.ACTIVE,
            ContractStatus.ARCHIVED,
        ],
        ContractStatus.REVIEW: [
            ContractStatus.NEGOTIATION,
            ContractStatus.DRAFT,
            ContractStatus.ARCHIVED,
        ],
        ContractStatus.NEGOTIATION: [
            ContractStatus.EXECUTED,
            ContractStatus.REVIEW,
            ContractStatus.ARCHIVED,
        ],
        ContractStatus.EXECUTED: [ContractStatus.ACTIVE, ContractStatus.ARCHIVED],
        ContractStatus.ACTIVE: [ContractStatus.EXPIRED, ContractStatus.TERMINATED],
        ContractStatus.EXPIRED: [ContractStatus.ARCHIVED],
        ContractStatus.TERMINATED: [ContractStatus.ARCHIVED],
    }

    def __init__(self, clause_library: ClauseLibrary) -> None:
        """Initialize the contract manager."""
        self.contracts: dict[str, Contract] = {}
        self.clause_library = clause_library
        self.contract_versions: dict[str, list[Contract]] = {}

    def create_contract(
        self,
        title: str,
        client_id: str,
        counterparty: str,
        description: str = "",
        value: Decimal | None = None,
        clauses: list[str] | None = None,
    ) -> Contract:
        """Create a new contract."""
        contract_id = str(uuid4())
        contract = Contract(
            contract_id=contract_id,
            title=title,
            client_id=client_id,
            counterparty=counterparty,
            status=ContractStatus.DRAFT,
            description=description,
            value=value,
            clauses=clauses or [],
        )

        self.contracts[contract_id] = contract
        self.contract_versions[contract_id] = [contract]
        logger.info(f"Created contract {contract_id}: {title}")
        return contract

    def assemble_contract(
        self,
        contract_id: str,
        clause_ids: list[str],
    ) -> Contract:
        """Assemble a contract from clauses in the library."""
        if contract_id not in self.contracts:
            raise ValueError(f"Contract {contract_id} not found")

        contract = self.contracts[contract_id]
        if contract.status != ContractStatus.DRAFT:
            raise InvalidContractStateError(f"Cannot assemble {contract.status.value} contract")

        # Validate all clauses exist
        for clause_id in clause_ids:
            self.clause_library.get_clause(clause_id)

        contract.clauses = clause_ids
        contract.modified_at = datetime.now()

        logger.info(f"Assembled contract {contract_id} with {len(clause_ids)} clauses")
        return contract

    def transition_contract(
        self,
        contract_id: str,
        new_status: ContractStatus,
    ) -> Contract:
        """Transition contract to new status with validation."""
        if contract_id not in self.contracts:
            raise ValueError(f"Contract {contract_id} not found")

        contract = self.contracts[contract_id]
        current = contract.status

        if new_status not in self.VALID_TRANSITIONS.get(current, []):
            raise InvalidContractStateError(f"Cannot transition from {current.value} to {new_status.value}")

        contract.status = new_status
        if new_status == ContractStatus.EXECUTED:
            contract.execution_date = date.today()
        contract.modified_at = datetime.now()

        self.contract_versions[contract_id].append(contract)
        logger.info(f"Contract {contract_id} transitioned to {new_status.value}")
        return contract

    def set_contract_dates(
        self,
        contract_id: str,
        effective_date: date | None = None,
        expiration_date: date | None = None,
    ) -> Contract:
        """Set effective and/or expiration dates for a contract."""
        if contract_id not in self.contracts:
            raise ValueError(f"Contract {contract_id} not found")

        contract = self.contracts[contract_id]
        if effective_date:
            contract.effective_date = effective_date
        if expiration_date:
            contract.expiration_date = expiration_date

        contract.modified_at = datetime.now()
        logger.info(f"Updated dates for contract {contract_id}")
        return contract

    def compare_contracts(
        self,
        contract_id_1: str,
        contract_id_2: str,
    ) -> dict[str, object]:
        """Compare two contract versions highlighting changes.

        Uses difflib for line-by-line comparison of clause content.
        """
        if contract_id_1 not in self.contracts:
            raise ValueError(f"Contract {contract_id_1} not found")
        if contract_id_2 not in self.contracts:
            raise ValueError(f"Contract {contract_id_2} not found")

        contract1 = self.contracts[contract_id_1]
        contract2 = self.contracts[contract_id_2]

        # Build full text from clauses
        text1 = self._build_contract_text(contract1)
        text2 = self._build_contract_text(contract2)

        # Generate diff
        diff = list(
            difflib.unified_diff(
                text1.splitlines(keepends=True),
                text2.splitlines(keepends=True),
                fromfile=f"Contract {contract_id_1}",
                tofile=f"Contract {contract_id_2}",
                lineterm="",
            )
        )

        # Count changes
        additions = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
        deletions = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))

        return {
            "contract_1": contract1.contract_id,
            "contract_2": contract2.contract_id,
            "differences": diff,
            "additions": additions,
            "deletions": deletions,
            "similarity": 100 - ((additions + deletions) / max(len(text1), len(text2)) * 100)
            if max(len(text1), len(text2)) > 0
            else 100,
        }

    def extract_obligations(
        self,
        contract_id: str,
    ) -> dict[str, list[dict[str, str]]]:
        """Extract obligations from a contract using keyword patterns.

        Identifies deadlines, payments, and deliverables.
        """
        if contract_id not in self.contracts:
            raise ValueError(f"Contract {contract_id} not found")

        contract = self.contracts[contract_id]
        text = self._build_contract_text(contract)

        obligations = {
            "deadlines": [],
            "payments": [],
            "deliverables": [],
        }

        # Deadline patterns (mentions of dates, periods)
        deadline_patterns = [
            r"(?:within|by|before|after|on)\s+(\d+\s+(?:days?|weeks?|months?|years?))",
            r"(?:deadline|due date).*?(?:is\s+)?(\w+\s+\d{1,2})",
            r"(\d{1,2}\s+(?:days?|weeks?|months?|years?)\s+(?:from|after|before))",
        ]

        for pattern in deadline_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                obligations["deadlines"].append(
                    {
                        "text": match.group(0),
                        "timeframe": match.group(1),
                    }
                )

        # Payment patterns
        payment_patterns = [
            r"\$[\d,]+(?:\.\d{2})?",
            r"(?:payment|fee|cost|price).*?\$[\d,]+",
            r"(?:invoice|billing).*?(?:within|by)\s+(\d+\s+days?)",
        ]

        for pattern in payment_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                obligations["payments"].append({"text": match.group(0)})

        # Deliverable patterns
        deliverable_patterns = [
            r"(?:deliver|provide|submit|prepare|create).*?(?:within|by)\s+(\d+\s+(?:days?|weeks?))",
            r"(?:deliverable|output|work product).*?(?:is|includes?|consists)",
        ]

        for pattern in deliverable_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                obligations["deliverables"].append({"text": match.group(0)})

        return obligations

    def add_amendment(
        self,
        contract_id: str,
        amendment_description: str,
        changes: dict[str, str],
    ) -> Contract:
        """Add an amendment to a contract."""
        if contract_id not in self.contracts:
            raise ValueError(f"Contract {contract_id} not found")

        contract = self.contracts[contract_id]
        amendment = {
            "amendment_id": str(uuid4()),
            "description": amendment_description,
            "created_at": datetime.now(),
            "changes": changes,
        }

        contract.amendments.append(amendment)
        contract.modified_at = datetime.now()

        logger.info(f"Added amendment to contract {contract_id}")
        return contract

    def check_renewal_status(self, contract_id: str) -> dict[str, object]:
        """Check if a contract is approaching renewal."""
        if contract_id not in self.contracts:
            raise ValueError(f"Contract {contract_id} not found")

        contract = self.contracts[contract_id]
        if not contract.expiration_date:
            return {"needs_renewal": False, "days_until_expiration": None}

        today = date.today()
        days_until = (contract.expiration_date - today).days

        return {
            "contract_id": contract_id,
            "expiration_date": contract.expiration_date,
            "days_until_expiration": days_until,
            "needs_renewal": days_until <= 90,
            "renewal_alert_threshold": 90,
        }

    def get_contract(self, contract_id: str) -> Contract:
        """Retrieve a contract by ID."""
        if contract_id not in self.contracts:
            raise ValueError(f"Contract {contract_id} not found")
        return self.contracts[contract_id]

    def get_contracts_by_client(self, client_id: str) -> list[Contract]:
        """Get all contracts for a client."""
        return [c for c in self.contracts.values() if c.client_id == client_id]

    def get_contracts_by_status(self, status: ContractStatus) -> list[Contract]:
        """Get all contracts with a specific status."""
        return [c for c in self.contracts.values() if c.status == status]

    def get_expiring_contracts(self, days_threshold: int = 90) -> list[Contract]:
        """Get contracts expiring within a threshold."""
        today = date.today()
        threshold_date = today + timedelta(days=days_threshold)

        return [
            c
            for c in self.contracts.values()
            if c.expiration_date
            and today <= c.expiration_date <= threshold_date
            and c.status in [ContractStatus.ACTIVE, ContractStatus.EXECUTED]
        ]

    def _build_contract_text(self, contract: Contract) -> str:
        """Build full contract text from clauses."""
        parts = [contract.title, contract.description]

        for clause_id in contract.clauses:
            try:
                clause = self.clause_library.get_clause(clause_id)
                parts.append(f"\n{clause.title}\n")
                parts.append(clause.content)
            except ValueError:
                logger.warning(f"Clause {clause_id} not found in library")

        for amendment in contract.amendments:
            parts.append(f"\nAmendment: {amendment['description']}\n")

        return "\n".join(parts)
