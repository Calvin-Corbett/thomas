"""Core data types for the legal practice management system."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class CaseStatus(Enum):
    """Enumeration of case statuses through the case lifecycle."""

    INTAKE = "intake"
    OPEN = "open"
    DISCOVERY = "discovery"
    TRIAL = "trial"
    CLOSED = "closed"
    ARCHIVED = "archived"


class CaseType(Enum):
    """Enumeration of legal case types."""

    CIVIL = "civil"
    CRIMINAL = "criminal"
    FAMILY = "family"
    CORPORATE = "corporate"
    INTELLECTUAL_PROPERTY = "ip"
    EMPLOYMENT = "employment"
    BANKRUPTCY = "bankruptcy"
    TAX = "tax"


class CaseOutcome(Enum):
    """Enumeration of case outcomes."""

    WON = "won"
    LOST = "lost"
    SETTLED = "settled"
    DISMISSED = "dismissed"
    ARBITRATION = "arbitration"
    MEDIATION = "mediation"


class ContractStatus(Enum):
    """Enumeration of contract statuses through lifecycle."""

    DRAFT = "draft"
    REVIEW = "review"
    NEGOTIATION = "negotiation"
    EXECUTED = "executed"
    ACTIVE = "active"
    EXPIRED = "expired"
    TERMINATED = "terminated"
    ARCHIVED = "archived"


class BillingStatus(Enum):
    """Enumeration of invoice billing statuses."""

    DRAFT = "draft"
    SENT = "sent"
    PAID = "paid"
    OVERDUE = "overdue"
    WRITTEN_OFF = "written_off"
    DISPUTED = "disputed"


class DocumentType(Enum):
    """Enumeration of document types."""

    CONTRACT = "contract"
    BRIEF = "brief"
    MOTION = "motion"
    CORRESPONDENCE = "correspondence"
    EVIDENCE = "evidence"
    FILING = "filing"
    MEMO = "memo"
    DEPOSITION = "deposition"


@dataclass(frozen=True)
class Jurisdiction:
    """Represents a legal jurisdiction (state, federal, international)."""

    code: str
    name: str
    court_type: str
    region: str


@dataclass(frozen=True)
class Statute:
    """Represents a statute of limitations or relevant statute."""

    statute_id: str
    title: str
    code: str
    jurisdiction: Jurisdiction
    years: int
    description: str
    case_types: list[CaseType]


@dataclass(frozen=True)
class Court:
    """Represents a court for case filing."""

    court_id: str
    name: str
    jurisdiction: Jurisdiction
    court_level: str  # district, appellate, supreme, etc.
    location: str
    phone: str | None = None
    website: str | None = None


@dataclass
class Client:
    """Represents a legal client."""

    client_id: str
    name: str
    type: str  # individual, corporation, partnership, etc.
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    billing_address: str | None = None
    contact_person: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Attorney:
    """Represents an attorney in the firm."""

    attorney_id: str
    name: str
    bar_number: str
    jurisdiction: Jurisdiction
    email: str
    phone: str
    practice_areas: list[str]
    seniority_level: str  # partner, counsel, associate, paralegal, etc.
    billable_rate: Decimal  # hourly rate in dollars
    status: str  # active, inactive, counsel, etc.
    admitted_date: date
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class TimeEntry:
    """Represents a time entry for billing (6-minute increments)."""

    entry_id: str
    attorney_id: str
    case_id: str
    date: date
    hours: Decimal  # in 0.1 hour increments (6 minutes)
    description: str
    activity_type: str  # research, drafting, meeting, review, etc.
    billable: bool = True
    created_at: datetime = field(default_factory=datetime.now)

    def validate_increment(self) -> bool:
        """Validate that hours are in 6-minute increments (0.1 hours)."""
        remainder = (self.hours * 10) % 1
        return remainder == 0


@dataclass
class Clause:
    """Represents a reusable contract clause with versioning."""

    clause_id: str
    title: str
    content: str
    category: str  # indemnification, limitation_of_liability, etc.
    version: int
    effective_date: date
    jurisdiction: Jurisdiction | None = None
    is_current: bool = True
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Contract:
    """Represents a legal contract."""

    contract_id: str
    title: str
    client_id: str
    counterparty: str
    status: ContractStatus
    execution_date: date | None = None
    effective_date: date | None = None
    expiration_date: date | None = None
    value: Decimal | None = None
    description: str = ""
    clauses: list[str] = field(default_factory=list)  # clause IDs
    related_documents: list[str] = field(default_factory=list)  # document IDs
    amendments: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    modified_at: datetime = field(default_factory=datetime.now)
    created_by: str | None = None


@dataclass
class Document:
    """Represents a legal document with versioning and metadata."""

    document_id: str
    title: str
    document_type: DocumentType
    case_id: str | None = None
    contract_id: str | None = None
    file_path: str | None = None
    author: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    modified_at: datetime = field(default_factory=datetime.now)
    version: int = 1
    is_privileged: bool = False
    privilege_holder: str | None = None
    bates_number_start: int | None = None
    bates_number_end: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    checked_out_by: str | None = None
    checked_out_at: datetime | None = None
    full_text: str = ""


@dataclass
class Filing:
    """Represents a court filing."""

    filing_id: str
    case_id: str
    court_id: str
    document_id: str
    filing_date: date
    filing_type: str  # complaint, answer, motion, etc.
    description: str
    docket_number: str | None = None
    received_date: date | None = None
    attorney_id: str = ""
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Deadline:
    """Represents a legal deadline."""

    deadline_id: str
    case_id: str
    description: str
    due_date: date
    deadline_type: str  # filing, response, trial, etc.
    importance: int  # 1-5, higher is more critical
    triggering_event: str | None = None
    dependent_deadline_ids: list[str] = field(default_factory=list)
    reminded: bool = False
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Invoice:
    """Represents a legal billing invoice."""

    invoice_id: str
    client_id: str
    status: BillingStatus
    invoice_date: date
    due_date: date
    amount_due: Decimal
    case_id: str | None = None
    amount_paid: Decimal = Decimal("0.00")
    line_items: list[dict[str, Any]] = field(default_factory=list)
    trust_account_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    notes: str = ""


@dataclass
class Trust:
    """Represents a trust/IOLTA account for client funds."""

    trust_id: str
    firm_id: str
    account_number: str
    bank_name: str
    balance: Decimal = Decimal("0.00")
    created_at: datetime = field(default_factory=datetime.now)
    transactions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Conflict:
    """Represents a potential conflict of interest."""

    conflict_id: str
    party_name: str
    conflict_type: str
    case_id: str | None = None
    related_parties: list[str] = field(default_factory=list)
    identified_date: datetime = field(default_factory=datetime.now)
    waived: bool = False
    waiver_details: dict[str, Any] | None = None
    description: str = ""


@dataclass
class Case:
    """Represents a legal case from intake to archival."""

    case_id: str
    matter_number: str
    case_name: str
    case_type: CaseType
    status: CaseStatus
    client_id: str
    assigned_attorney_id: str
    court_id: str | None = None
    opposing_counsel: list[str] = field(default_factory=list)
    description: str = ""
    case_outcome: CaseOutcome | None = None
    statute_of_limitations: Statute | None = None
    sol_expiration_date: date | None = None
    intake_date: datetime = field(default_factory=datetime.now)
    opened_date: datetime | None = None
    closed_date: datetime | None = None
    archived_date: datetime | None = None
    related_cases: list[str] = field(default_factory=list)
    hourly_budget: Decimal | None = None
    estimated_duration_months: int | None = None
    documents: list[str] = field(default_factory=list)  # document IDs
    filings: list[str] = field(default_factory=list)  # filing IDs
    deadlines: list[str] = field(default_factory=list)  # deadline IDs
    time_entries: list[str] = field(default_factory=list)  # time entry IDs
    metadata: dict[str, Any] = field(default_factory=dict)
