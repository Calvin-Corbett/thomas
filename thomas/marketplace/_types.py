"""Core data types for the marketplace platform."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class VendorStatus(Enum):
    """Vendor account lifecycle states."""

    APPLIED = "applied"
    VERIFIED = "verified"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class VerificationLevel(Enum):
    """Vendor verification levels."""

    UNVERIFIED = "unverified"
    BASIC = "basic"
    STANDARD = "standard"
    PREMIUM = "premium"


class ListingState(Enum):
    """Product listing lifecycle states."""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    DELISTED = "delisted"


class OrderStatus(Enum):
    """Order lifecycle states."""

    PLACED = "placed"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentStatus(Enum):
    """Payment processing states."""

    PENDING = "pending"
    PROCESSING = "processing"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    FAILED = "failed"
    REFUNDED = "refunded"
    DISPUTED = "disputed"


class DisputeStatus(Enum):
    """Dispute resolution lifecycle."""

    OPENED = "opened"
    EVIDENCE_REVIEW = "evidence_review"
    DECISION = "decision"
    APPEAL = "appeal"
    CLOSED = "closed"


class DisputeType(Enum):
    """Categories of disputes."""

    ITEM_NOT_RECEIVED = "item_not_received"
    ITEM_NOT_DESCRIBED = "item_not_described"
    UNAUTHORIZED_CHARGE = "unauthorized_charge"
    QUALITY_ISSUE = "quality_issue"
    OTHER = "other"


class CommissionTier(Enum):
    """Volume-based commission tiers."""

    TIER_1 = "tier_1"  # 0-50k monthly GMV
    TIER_2 = "tier_2"  # 50k-200k monthly GMV
    TIER_3 = "tier_3"  # 200k-1m monthly GMV
    TIER_4 = "tier_4"  # 1m+ monthly GMV


@dataclass
class Badge:
    """Vendor badge for achievements and recognition."""

    id: str
    name: str
    description: str
    icon_url: str
    earned_at: datetime
    category: str

    def __str__(self) -> str:
        return f"{self.name} ({self.category})"


@dataclass
class Vendor:
    """Vendor account with performance tracking and verification."""

    id: str
    name: str
    email: str
    status: VendorStatus
    verification_level: VerificationLevel
    created_at: datetime
    verified_at: datetime | None
    description: str
    logo_url: str
    phone: str
    address: str
    bank_account: str
    tax_id: str
    response_time_hours: float
    order_fulfillment_rate: Decimal
    review_score: Decimal
    badges: list[Badge] = field(default_factory=list)
    commission_tier: CommissionTier = CommissionTier.TIER_1
    is_active: bool = True

    def __post_init__(self) -> None:
        """Validate vendor data."""
        if not 0 <= float(self.order_fulfillment_rate) <= 100:
            raise ValueError("Order fulfillment rate must be 0-100")
        if not 0 <= float(self.review_score) <= 5:
            raise ValueError("Review score must be 0-5")

    @property
    def can_list_products(self) -> bool:
        """Check if vendor can list products."""
        return self.status == VendorStatus.ACTIVE and self.is_active


@dataclass
class Category:
    """Hierarchical product category with breadcrumb path."""

    id: str
    name: str
    parent_id: str | None
    description: str
    icon_url: str
    breadcrumb: list[str] = field(default_factory=list)
    attribute_keys: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return " > ".join(self.breadcrumb) if self.breadcrumb else self.name


@dataclass
class Product:
    """Core product information."""

    id: str
    name: str
    sku: str
    category_id: str
    price: Decimal
    currency: str
    description: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate product data."""
        if self.price < 0:
            raise ValueError("Price cannot be negative")


@dataclass
class Listing:
    """Product listing with state and quality scoring."""

    id: str
    vendor_id: str
    product_id: str
    state: ListingState
    title: str
    description: str
    price: Decimal
    quantity: int
    category_id: str
    images: list[str]
    attributes: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    quality_score: Decimal = Decimal("0")
    is_duplicate: bool = False
    duplicate_of: str | None = None
    view_count: int = 0

    def __post_init__(self) -> None:
        """Validate listing data."""
        if self.quantity < 0:
            raise ValueError("Quantity cannot be negative")
        if self.price < 0:
            raise ValueError("Price cannot be negative")


@dataclass
class Rating:
    """Star rating without text review."""

    id: str
    listing_id: str
    buyer_id: str
    rating: int
    created_at: datetime

    def __post_init__(self) -> None:
        """Validate rating."""
        if not 1 <= self.rating <= 5:
            raise ValueError("Rating must be between 1 and 5")


@dataclass
class Review:
    """Text review with authenticity scoring."""

    id: str
    listing_id: str
    vendor_id: str
    buyer_id: str
    rating: int
    title: str
    text: str
    created_at: datetime
    updated_at: datetime
    is_verified_purchase: bool
    authenticity_score: Decimal = Decimal("0")
    helpfulness_votes: int = 0
    vendor_response: str | None = None
    vendor_response_at: datetime | None = None
    sentiment_score: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        """Validate review."""
        if not 1 <= self.rating <= 5:
            raise ValueError("Rating must be between 1 and 5")


@dataclass
class Payment:
    """Payment transaction with escrow and split payment tracking."""

    id: str
    order_id: str
    amount: Decimal
    currency: str
    status: PaymentStatus
    gateway_id: str
    created_at: datetime
    updated_at: datetime
    platform_fee: Decimal = Decimal("0")
    vendor_amount: Decimal = Decimal("0")
    is_escrow: bool = False
    escrow_released_at: datetime | None = None
    refund_amount: Decimal = Decimal("0")
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate payment."""
        if self.amount < 0:
            raise ValueError("Payment amount cannot be negative")


@dataclass
class Commission:
    """Commission calculation with tier-based rates."""

    id: str
    vendor_id: str
    tier: CommissionTier
    percentage_rate: Decimal
    fixed_fee: Decimal
    min_commission: Decimal
    max_commission: Decimal | None
    effective_from: datetime
    effective_to: datetime | None
    created_at: datetime

    def calculate(self, amount: Decimal) -> Decimal:
        """Calculate commission for given amount."""
        commission = (amount * self.percentage_rate / Decimal("100")) + self.fixed_fee
        commission = max(commission, self.min_commission)
        if self.max_commission:
            commission = min(commission, self.max_commission)
        return commission


@dataclass
class Order:
    """Multi-vendor order with item-level tracking."""

    id: str
    buyer_id: str
    status: OrderStatus
    created_at: datetime
    updated_at: datetime
    items: list[dict[str, Any]] = field(default_factory=list)
    shipping_address: str = ""
    billing_address: str = ""
    shipping_method: str = ""
    total_amount: Decimal = Decimal("0")
    subtotal: Decimal = Decimal("0")
    shipping_cost: Decimal = Decimal("0")
    tax_amount: Decimal = Decimal("0")
    currency: str = "USD"
    tracking_numbers: dict[str, str] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self) -> None:
        """Validate order."""
        if self.total_amount < 0:
            raise ValueError("Order total cannot be negative")


@dataclass
class Dispute:
    """Dispute resolution with evidence tracking."""

    id: str
    order_id: str
    buyer_id: str
    vendor_id: str
    dispute_type: DisputeType
    status: DisputeStatus
    title: str
    description: str
    created_at: datetime
    updated_at: datetime
    buyer_evidence: list[dict[str, str]] = field(default_factory=list)
    seller_evidence: list[dict[str, str]] = field(default_factory=list)
    resolution: str | None = None
    resolved_at: datetime | None = None
    fairness_score: Decimal = Decimal("0")
    appeal_count: int = 0


@dataclass
class SearchQuery:
    """User search query with facets and filters."""

    q: str
    category_id: str | None = None
    price_min: Decimal | None = None
    price_max: Decimal | None = None
    vendor_id: str | None = None
    rating_min: Decimal | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    sort_by: str = "relevance"
    page: int = 1
    limit: int = 20
    include_sponsored: bool = True


@dataclass
class SearchResult:
    """Search result with ranking metadata."""

    listing_id: str
    vendor_id: str
    title: str
    price: Decimal
    rating: Decimal
    review_count: int
    relevance_score: Decimal
    vendor_score: Decimal
    listing_quality: Decimal
    is_sponsored: bool
    rank_position: int


@dataclass
class PricingTier:
    """Subscription tier for vendor premium features."""

    id: str
    name: str
    price_per_month: Decimal
    features: list[str]
    max_listings: int
    commission_discount: Decimal
    created_at: datetime


@dataclass
class Subscription:
    """Vendor subscription to premium features."""

    id: str
    vendor_id: str
    tier_id: str
    status: str
    started_at: datetime
    renewal_at: datetime
    cancelled_at: datetime | None = None
    auto_renew: bool = True
    payment_method_id: str = ""


@dataclass
class Analytics:
    """Marketplace and vendor analytics."""

    period_start: datetime
    period_end: datetime
    gmv: Decimal
    take_rate: Decimal
    total_orders: int
    total_items_sold: int
    avg_order_value: Decimal
    buyer_retention_rate: Decimal
    conversion_rate: Decimal
    avg_response_time: float
    top_categories: list[tuple[str, int]] = field(default_factory=list)
    top_vendors: list[tuple[str, Decimal]] = field(default_factory=list)
