"""
Data types for CRM system.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class ActivityType(str, Enum):
    """Types of activities that can be logged."""

    CALL = "call"
    EMAIL = "email"
    MEETING = "meeting"
    NOTE = "note"
    TASK = "task"
    DEMO = "demo"
    PROPOSAL = "proposal"
    PRESENTATION = "presentation"


@dataclass
class Contact:
    """Represents a contact in the CRM system.

    Attributes:
        id: Unique contact identifier
        first_name: Contact's first name
        last_name: Contact's last name
        email: Primary email address
        phone: Phone number
        company: Associated company name
        title: Job title
        tags: List of tags for categorization
        created_at: Creation timestamp
        custom_fields: Additional custom fields
    """

    id: str
    first_name: str
    last_name: str
    email: str
    phone: str | None = None
    company: str | None = None
    title: str | None = None
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    custom_fields: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate contact data."""
        if not self.first_name or not self.last_name:
            raise ValueError("first_name and last_name are required")
        if not self.email:
            raise ValueError("email is required")

    @property
    def full_name(self) -> str:
        """Return the full name of the contact."""
        return f"{self.first_name} {self.last_name}"

    def to_dict(self) -> dict[str, Any]:
        """Convert contact to dictionary."""
        return {
            "id": self.id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "email": self.email,
            "phone": self.phone,
            "company": self.company,
            "title": self.title,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "custom_fields": self.custom_fields,
        }


@dataclass
class Company:
    """Represents a company in the CRM system.

    Attributes:
        id: Unique company identifier
        name: Company name
        domain: Company website domain
        industry: Industry classification
        size: Number of employees
        revenue: Annual revenue
        contacts: List of associated contact IDs
        created_at: Creation timestamp
    """

    id: str
    name: str
    domain: str | None = None
    industry: str | None = None
    size: int | None = None
    revenue: Decimal | None = None
    contacts: list[str] = field(default_factory=list)
    parent_company_id: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert company to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "domain": self.domain,
            "industry": self.industry,
            "size": self.size,
            "revenue": str(self.revenue) if self.revenue else None,
            "contacts": self.contacts,
            "parent_company_id": self.parent_company_id,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class Stage:
    """Represents a stage in a sales pipeline.

    Attributes:
        id: Unique stage identifier
        name: Stage name
        order: Position in pipeline
        is_closed_won: Whether this stage represents a closed-won deal
        is_closed_lost: Whether this stage represents a closed-lost deal
    """

    id: str
    name: str
    order: int
    is_closed_won: bool = False
    is_closed_lost: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert stage to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "order": self.order,
            "is_closed_won": self.is_closed_won,
            "is_closed_lost": self.is_closed_lost,
        }


@dataclass
class Pipeline:
    """Represents a sales pipeline.

    Attributes:
        id: Unique pipeline identifier
        name: Pipeline name
        stages: List of stages in the pipeline
        created_at: Creation timestamp
    """

    id: str
    name: str
    stages: list[Stage] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def get_stage_by_id(self, stage_id: str) -> Stage | None:
        """Get a stage by its ID."""
        return next((s for s in self.stages if s.id == stage_id), None)

    def to_dict(self) -> dict[str, Any]:
        """Convert pipeline to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "stages": [s.to_dict() for s in self.stages],
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class Deal:
    """Represents a sales deal in the CRM system.

    Attributes:
        id: Unique deal identifier
        name: Deal name
        company_id: Associated company ID
        contact_id: Primary contact ID
        stage_id: Current pipeline stage ID
        value: Deal value
        probability: Win probability (0-100)
        expected_close: Expected close date
        owner: Sales rep/owner name
        created_at: Creation timestamp
        products: List of products/line items
        custom_fields: Additional custom fields
    """

    id: str
    name: str
    company_id: str
    contact_id: str
    stage_id: str
    value: Decimal
    probability: int
    expected_close: datetime
    owner: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    products: list[dict[str, Any]] = field(default_factory=list)
    custom_fields: dict[str, Any] = field(default_factory=dict)
    stage_entered_at: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self) -> None:
        """Validate deal data."""
        if not 0 <= self.probability <= 100:
            raise ValueError("probability must be between 0 and 100")
        if self.value < 0:
            raise ValueError("value must be non-negative")

    @property
    def weighted_value(self) -> Decimal:
        """Calculate weighted value based on probability."""
        return self.value * Decimal(self.probability) / Decimal(100)

    def to_dict(self) -> dict[str, Any]:
        """Convert deal to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "company_id": self.company_id,
            "contact_id": self.contact_id,
            "stage_id": self.stage_id,
            "value": str(self.value),
            "probability": self.probability,
            "expected_close": self.expected_close.isoformat(),
            "owner": self.owner,
            "created_at": self.created_at.isoformat(),
            "products": self.products,
            "custom_fields": self.custom_fields,
            "stage_entered_at": self.stage_entered_at.isoformat(),
        }


@dataclass
class Activity:
    """Represents an activity in the CRM system.

    Attributes:
        id: Unique activity identifier
        type: Activity type
        contact_id: Associated contact ID
        deal_id: Associated deal ID (optional)
        timestamp: When the activity occurred
        notes: Activity notes/description
        duration: Duration in minutes
        created_at: Creation timestamp
        user: User who logged the activity
    """

    id: str
    type: ActivityType
    contact_id: str
    deal_id: str | None
    timestamp: datetime
    notes: str
    duration: int | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    user: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert activity to dictionary."""
        return {
            "id": self.id,
            "type": self.type.value,
            "contact_id": self.contact_id,
            "deal_id": self.deal_id,
            "timestamp": self.timestamp.isoformat(),
            "notes": self.notes,
            "duration": self.duration,
            "created_at": self.created_at.isoformat(),
            "user": self.user,
        }


@dataclass
class LeadScore:
    """Represents a lead scoring record.

    Attributes:
        contact_id: Contact being scored
        total_score: Total score (0-100)
        demographic_score: Demographic component (0-100)
        behavioral_score: Behavioral component (0-100)
        predictive_score: Predictive component (0-100)
        grade: Letter grade (A, B, C, D, F)
        last_updated: Last update timestamp
        explanation: Detailed scoring explanation
    """

    contact_id: str
    total_score: int
    demographic_score: int
    behavioral_score: int
    predictive_score: int
    grade: str
    last_updated: datetime = field(default_factory=datetime.utcnow)
    explanation: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert lead score to dictionary."""
        return {
            "contact_id": self.contact_id,
            "total_score": self.total_score,
            "demographic_score": self.demographic_score,
            "behavioral_score": self.behavioral_score,
            "predictive_score": self.predictive_score,
            "grade": self.grade,
            "last_updated": self.last_updated.isoformat(),
            "explanation": self.explanation,
        }


@dataclass
class DealForecast:
    """Represents a deal forecast for a period.

    Attributes:
        period: Time period identifier
        total_pipeline: Total pipeline value
        weighted_forecast: Weighted forecast based on probabilities
        confidence: Forecast confidence level
        by_stage: Breakdown by stage
        by_owner: Breakdown by owner
    """

    period: str
    total_pipeline: Decimal
    weighted_forecast: Decimal
    confidence: float
    by_stage: dict[str, Decimal] = field(default_factory=dict)
    by_owner: dict[str, Decimal] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert forecast to dictionary."""
        return {
            "period": self.period,
            "total_pipeline": str(self.total_pipeline),
            "weighted_forecast": str(self.weighted_forecast),
            "confidence": self.confidence,
            "by_stage": {k: str(v) for k, v in self.by_stage.items()},
            "by_owner": {k: str(v) for k, v in self.by_owner.items()},
        }
