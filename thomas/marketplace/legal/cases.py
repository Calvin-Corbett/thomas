"""Case management module for legal practice operations."""

import logging
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from thomas.marketplace.legal._exceptions import InvalidCaseStateError
from thomas.marketplace.legal._types import (
    Case,
    CaseOutcome,
    CaseStatus,
    CaseType,
    Statute,
)

logger = logging.getLogger(__name__)


class CaseManager:
    """Manages case lifecycle, assignment, and tracking."""

    # Valid state transitions
    VALID_TRANSITIONS: dict[CaseStatus, list[CaseStatus]] = {
        CaseStatus.INTAKE: [CaseStatus.OPEN, CaseStatus.ARCHIVED],
        CaseStatus.OPEN: [CaseStatus.DISCOVERY, CaseStatus.CLOSED, CaseStatus.ARCHIVED],
        CaseStatus.DISCOVERY: [CaseStatus.TRIAL, CaseStatus.CLOSED, CaseStatus.ARCHIVED],
        CaseStatus.TRIAL: [CaseStatus.CLOSED, CaseStatus.ARCHIVED],
        CaseStatus.CLOSED: [CaseStatus.ARCHIVED],
        CaseStatus.ARCHIVED: [],
    }

    def __init__(self) -> None:
        """Initialize the case manager."""
        self.cases: dict[str, Case] = {}
        self.matter_counter: dict[CaseType, int] = {case_type: 0 for case_type in CaseType}
        self.attorney_workload: dict[str, Decimal] = {}

    def create_case(
        self,
        case_name: str,
        case_type: CaseType,
        client_id: str,
        assigned_attorney_id: str,
        description: str = "",
        court_id: str | None = None,
        opposing_counsel: list[str] | None = None,
        hourly_budget: Decimal | None = None,
        estimated_duration_months: int | None = None,
    ) -> Case:
        """Create a new case with auto-generated matter number.

        Matter numbering format: CCYY-TYPE-XXXX
        CC = century, YY = year, TYPE = case type abbreviation, XXXX = sequence
        """
        case_id = str(uuid4())
        year = datetime.now().year
        century = year // 100
        year_short = year % 100

        # Generate matter number with type abbreviation
        type_abbrev = self._get_case_type_abbrev(case_type)
        sequence = self.matter_counter[case_type] + 1
        self.matter_counter[case_type] = sequence
        matter_number = f"{century}{year_short:02d}-{type_abbrev}-{sequence:04d}"

        case = Case(
            case_id=case_id,
            matter_number=matter_number,
            case_name=case_name,
            case_type=case_type,
            status=CaseStatus.INTAKE,
            client_id=client_id,
            assigned_attorney_id=assigned_attorney_id,
            court_id=court_id,
            opposing_counsel=opposing_counsel or [],
            description=description,
            hourly_budget=hourly_budget,
            estimated_duration_months=estimated_duration_months,
        )

        self.cases[case_id] = case
        if assigned_attorney_id not in self.attorney_workload:
            self.attorney_workload[assigned_attorney_id] = Decimal("0.00")
        if hourly_budget is not None:
            self.attorney_workload[assigned_attorney_id] += hourly_budget

        logger.info(f"Created case {matter_number} for client {client_id}")
        return case

    def transition_case(self, case_id: str, new_status: CaseStatus) -> Case:
        """Transition a case to a new status with validation.

        Validates that the transition is allowed per the VALID_TRANSITIONS map.
        """
        if case_id not in self.cases:
            raise ValueError(f"Case {case_id} not found")

        case = self.cases[case_id]
        current_status = case.status

        if new_status not in self.VALID_TRANSITIONS.get(current_status, []):
            raise InvalidCaseStateError(f"Cannot transition from {current_status.value} to {new_status.value}")

        # Update timestamps based on transition
        case.status = new_status
        if new_status == CaseStatus.OPEN:
            case.opened_date = datetime.now()
        elif new_status == CaseStatus.CLOSED:
            case.closed_date = datetime.now()
        elif new_status == CaseStatus.ARCHIVED:
            case.archived_date = datetime.now()

        logger.info(f"Case {case.matter_number} transitioned to {new_status.value}")
        return case

    def assign_case(self, case_id: str, attorney_id: str, reason: str = "") -> Case:
        """Assign or reassign a case to an attorney using workload balancing.

        Considers current workload when assigning.
        """
        if case_id not in self.cases:
            raise ValueError(f"Case {case_id} not found")

        case = self.cases[case_id]
        old_attorney = case.assigned_attorney_id
        case.assigned_attorney_id = attorney_id

        # Update workload tracking
        old_budget = case.hourly_budget or Decimal("0.00")
        if old_attorney in self.attorney_workload:
            self.attorney_workload[old_attorney] = max(
                Decimal("0.00"),
                self.attorney_workload[old_attorney] - old_budget,
            )

        if attorney_id not in self.attorney_workload:
            self.attorney_workload[attorney_id] = Decimal("0.00")
        self.attorney_workload[attorney_id] += old_budget

        logger.info(f"Case {case.matter_number} reassigned from {old_attorney} to {attorney_id}")
        return case

    def get_attorney_workload(self, attorney_id: str) -> Decimal:
        """Get current workload (estimated hours) for an attorney."""
        return self.attorney_workload.get(attorney_id, Decimal("0.00"))

    def find_least_loaded_attorney(self, attorney_ids: list[str]) -> str:
        """Find the attorney with the least workload from a list."""
        return min(attorney_ids, key=lambda aid: self.attorney_workload.get(aid, Decimal("0.00")))

    def link_related_cases(self, case_id_1: str, case_id_2: str) -> tuple[Case, Case]:
        """Link two cases as related (e.g., parallel or appeal)."""
        if case_id_1 not in self.cases:
            raise ValueError(f"Case {case_id_1} not found")
        if case_id_2 not in self.cases:
            raise ValueError(f"Case {case_id_2} not found")

        case1 = self.cases[case_id_1]
        case2 = self.cases[case_id_2]

        if case_id_2 not in case1.related_cases:
            case1.related_cases.append(case_id_2)
        if case_id_1 not in case2.related_cases:
            case2.related_cases.append(case_id_1)

        logger.info(f"Linked cases {case1.matter_number} and {case2.matter_number}")
        return case1, case2

    def set_case_outcome(
        self,
        case_id: str,
        outcome: CaseOutcome,
        metadata: dict | None = None,
    ) -> Case:
        """Set the outcome of a closed case."""
        if case_id not in self.cases:
            raise ValueError(f"Case {case_id} not found")

        case = self.cases[case_id]
        if case.status != CaseStatus.CLOSED:
            raise InvalidCaseStateError(f"Cannot set outcome on {case.status.value} case")

        case.case_outcome = outcome
        if metadata:
            case.metadata.update(metadata)

        logger.info(f"Case {case.matter_number} outcome set to {outcome.value}")
        return case

    def calculate_statute_of_limitations(
        self,
        case_id: str,
        statute: Statute,
    ) -> Case:
        """Calculate and set statute of limitations expiration date.

        Formula: intake_date + statute.years
        """
        if case_id not in self.cases:
            raise ValueError(f"Case {case_id} not found")

        case = self.cases[case_id]
        case.statute_of_limitations = statute

        # Calculate SOL expiration
        intake_date = case.intake_date.date() if isinstance(case.intake_date, datetime) else case.intake_date
        sol_expiration = intake_date + timedelta(days=statute.years * 365)

        case.sol_expiration_date = sol_expiration

        logger.info(f"Case {case.matter_number} SOL expiration set to {sol_expiration}")
        return case

    def get_case_timeline(self, case_id: str) -> dict[str, datetime | None]:
        """Get timeline milestones for a case."""
        if case_id not in self.cases:
            raise ValueError(f"Case {case_id} not found")

        case = self.cases[case_id]
        return {
            "intake": case.intake_date,
            "opened": case.opened_date,
            "closed": case.closed_date,
            "archived": case.archived_date,
            "sol_expiration": case.sol_expiration_date,
        }

    def get_case_by_id(self, case_id: str) -> Case:
        """Retrieve a case by ID."""
        if case_id not in self.cases:
            raise ValueError(f"Case {case_id} not found")
        return self.cases[case_id]

    def get_case_by_matter_number(self, matter_number: str) -> Case | None:
        """Retrieve a case by matter number."""
        for case in self.cases.values():
            if case.matter_number == matter_number:
                return case
        return None

    def get_cases_by_attorney(self, attorney_id: str) -> list[Case]:
        """Get all active cases assigned to an attorney."""
        return [
            case
            for case in self.cases.values()
            if case.assigned_attorney_id == attorney_id and case.status != CaseStatus.ARCHIVED
        ]

    def get_cases_by_client(self, client_id: str) -> list[Case]:
        """Get all cases for a client."""
        return [case for case in self.cases.values() if case.client_id == client_id]

    def get_cases_by_status(self, status: CaseStatus) -> list[Case]:
        """Get all cases with a specific status."""
        return [case for case in self.cases.values() if case.status == status]

    def get_cases_by_type(self, case_type: CaseType) -> list[Case]:
        """Get all cases of a specific type."""
        return [case for case in self.cases.values() if case.case_type == case_type]

    def get_cases_by_court(self, court_id: str) -> list[Case]:
        """Get all cases in a specific court."""
        return [case for case in self.cases.values() if case.court_id == court_id]

    def search_cases(
        self,
        case_name: str | None = None,
        client_id: str | None = None,
        attorney_id: str | None = None,
        status: CaseStatus | None = None,
        case_type: CaseType | None = None,
    ) -> list[Case]:
        """Search cases with multiple filters."""
        results = list(self.cases.values())

        if case_name:
            results = [c for c in results if case_name.lower() in c.case_name.lower()]
        if client_id:
            results = [c for c in results if c.client_id == client_id]
        if attorney_id:
            results = [c for c in results if c.assigned_attorney_id == attorney_id]
        if status:
            results = [c for c in results if c.status == status]
        if case_type:
            results = [c for c in results if c.case_type == case_type]

        return results

    def get_related_cases(self, case_id: str) -> list[Case]:
        """Get all cases related to a given case."""
        if case_id not in self.cases:
            raise ValueError(f"Case {case_id} not found")

        case = self.cases[case_id]
        return [self.cases[related_id] for related_id in case.related_cases if related_id in self.cases]

    @staticmethod
    def _get_case_type_abbrev(case_type: CaseType) -> str:
        """Get 3-letter abbreviation for case type."""
        abbrevs = {
            CaseType.CIVIL: "CIV",
            CaseType.CRIMINAL: "CRM",
            CaseType.FAMILY: "FAM",
            CaseType.CORPORATE: "COR",
            CaseType.INTELLECTUAL_PROPERTY: "IP",
            CaseType.EMPLOYMENT: "EMP",
            CaseType.BANKRUPTCY: "BNK",
            CaseType.TAX: "TAX",
        }
        return abbrevs.get(case_type, "OTH")
