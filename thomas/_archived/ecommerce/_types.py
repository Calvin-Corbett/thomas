"""Type definitions for the e-commerce system."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class OrderStatus(str, Enum):
    """Order status enumeration."""

    PENDING = "pending"
    PROCESSING = "processing"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentStatus(str, Enum):
    """Payment status enumeration."""

    PENDING = "pending"
    AUTHORIZED = "authorized"
    COMPLETED = "completed"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentMethod(str, Enum):
    """Payment method enumeration."""

    CREDIT_CARD = "credit_card"
    DEBIT_CARD = "debit_card"
    PAYPAL = "paypal"
    BANK_TRANSFER = "bank_transfer"
    CRYPTOCURRENCY = "cryptocurrency"


class ProductStatus(str, Enum):
    """Product status enumeration."""

    ACTIVE = "active"
    DRAFT = "draft"
    ARCHIVED = "archived"


class ShippingMethod(str, Enum):
    """Shipping method enumeration."""

    STANDARD = "standard"
    EXPRESS = "express"
    OVERNIGHT = "overnight"
    PICKUP = "pickup"


@dataclass
class Address:
    """Physical address."""

    street_line_1: str
    street_line_2: str | None
    city: str
    state: str
    postal_code: str
    country: str

    def is_valid(self) -> bool:
        """Validate address has required fields."""
        return all(
            [
                self.street_line_1.strip(),
                self.city.strip(),
                self.state.strip(),
                self.postal_code.strip(),
                self.country.strip(),
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "street_line_1": self.street_line_1,
            "street_line_2": self.street_line_2,
            "city": self.city,
            "state": self.state,
            "postal_code": self.postal_code,
            "country": self.country,
        }


@dataclass
class Product:
    """Product in the catalog."""

    id: str
    name: str
    sku: str
    price: Decimal
    cost: Decimal
    category: str
    attributes: dict[str, Any] = field(default_factory=dict)
    inventory_count: int = 0
    status: ProductStatus = ProductStatus.DRAFT
    description: str = ""
    images: list[str] = field(default_factory=list)
    rating: Decimal = Decimal("0.00")
    review_count: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "sku": self.sku,
            "price": str(self.price),
            "cost": str(self.cost),
            "category": self.category,
            "attributes": self.attributes,
            "inventory_count": self.inventory_count,
            "status": self.status.value,
            "description": self.description,
            "images": self.images,
            "rating": str(self.rating),
            "review_count": self.review_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class ProductVariant:
    """Product variant (size, color, etc.)."""

    id: str
    product_id: str
    sku: str
    attributes: dict[str, str]
    price_delta: Decimal = Decimal("0.00")
    inventory_count: int = 0
    status: ProductStatus = ProductStatus.ACTIVE

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "product_id": self.product_id,
            "sku": self.sku,
            "attributes": self.attributes,
            "price_delta": str(self.price_delta),
            "inventory_count": self.inventory_count,
            "status": self.status.value,
        }


@dataclass
class CartItem:
    """Item in the shopping cart."""

    product_id: str
    variant_id: str | None
    quantity: int
    unit_price: Decimal
    added_at: datetime = field(default_factory=datetime.utcnow)

    def subtotal(self) -> Decimal:
        """Calculate subtotal for this item."""
        return self.unit_price * self.quantity

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "product_id": self.product_id,
            "variant_id": self.variant_id,
            "quantity": self.quantity,
            "unit_price": str(self.unit_price),
            "added_at": self.added_at.isoformat(),
        }


@dataclass
class Cart:
    """Shopping cart."""

    id: str
    user_id: str | None
    items: list[CartItem] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None
    coupon_code: str | None = None
    saved_items: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "items": [item.to_dict() for item in self.items],
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "coupon_code": self.coupon_code,
            "saved_items": self.saved_items,
        }


@dataclass
class Coupon:
    """Promotional coupon."""

    code: str
    coupon_type: str  # "flat", "percentage", "free_shipping"
    value: Decimal
    minimum_order_total: Decimal | None = None
    product_ids: list[str] | None = None
    category_ids: list[str] | None = None
    usage_limit_per_user: int | None = None
    total_usage_limit: int | None = None
    usage_count: int = 0
    expires_at: datetime | None = None
    stackable: bool = False
    active: bool = True

    def is_valid(self) -> bool:
        """Check if coupon is valid."""
        if not self.active:
            return False
        if self.expires_at and datetime.utcnow() > self.expires_at:
            return False
        if self.total_usage_limit and self.usage_count >= self.total_usage_limit:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "code": self.code,
            "coupon_type": self.coupon_type,
            "value": str(self.value),
            "minimum_order_total": str(self.minimum_order_total) if self.minimum_order_total else None,
            "product_ids": self.product_ids,
            "category_ids": self.category_ids,
            "usage_limit_per_user": self.usage_limit_per_user,
            "total_usage_limit": self.total_usage_limit,
            "usage_count": self.usage_count,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "stackable": self.stackable,
            "active": self.active,
        }


@dataclass
class TaxRule:
    """Tax rule by jurisdiction."""

    id: str
    country: str
    state: str | None
    rate: Decimal
    tax_category: str  # "standard", "reduced", "exempt"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "country": self.country,
            "state": self.state,
            "rate": str(self.rate),
            "tax_category": self.tax_category,
        }


@dataclass
class PriceRule:
    """Dynamic pricing rule."""

    id: str
    name: str
    conditions: dict[str, Any]
    action: str  # "discount_percentage", "discount_fixed", "set_price"
    action_value: Decimal
    priority: int = 0
    active: bool = True
    start_date: datetime | None = None
    end_date: datetime | None = None

    def is_applicable(self) -> bool:
        """Check if rule is currently applicable."""
        if not self.active:
            return False
        now = datetime.utcnow()
        if self.start_date and now < self.start_date:
            return False
        if self.end_date and now > self.end_date:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "conditions": self.conditions,
            "action": self.action,
            "action_value": str(self.action_value),
            "priority": self.priority,
            "active": self.active,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
        }


@dataclass
class OrderItem:
    """Item in an order."""

    product_id: str
    variant_id: str | None
    quantity: int
    unit_price: Decimal
    subtotal: Decimal

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "product_id": self.product_id,
            "variant_id": self.variant_id,
            "quantity": self.quantity,
            "unit_price": str(self.unit_price),
            "subtotal": str(self.subtotal),
        }


@dataclass
class Order:
    """Order in the system."""

    id: str
    user_id: str | None
    items: list[OrderItem]
    status: OrderStatus = OrderStatus.PENDING
    total: Decimal = Decimal("0.00")
    subtotal: Decimal = Decimal("0.00")
    tax: Decimal = Decimal("0.00")
    shipping: Decimal = Decimal("0.00")
    discount: Decimal = Decimal("0.00")
    payment_status: PaymentStatus = PaymentStatus.PENDING
    payment_method: PaymentMethod | None = None
    shipping_method: ShippingMethod = ShippingMethod.STANDARD
    shipping_address: Address | None = None
    billing_address: Address | None = None
    coupon_code: str | None = None
    loyalty_points_used: int = 0
    loyalty_points_earned: int = 0
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "items": [item.to_dict() for item in self.items],
            "status": self.status.value,
            "total": str(self.total),
            "subtotal": str(self.subtotal),
            "tax": str(self.tax),
            "shipping": str(self.shipping),
            "discount": str(self.discount),
            "payment_status": self.payment_status.value,
            "payment_method": self.payment_method.value if self.payment_method else None,
            "shipping_method": self.shipping_method.value,
            "shipping_address": self.shipping_address.to_dict() if self.shipping_address else None,
            "billing_address": self.billing_address.to_dict() if self.billing_address else None,
            "coupon_code": self.coupon_code,
            "loyalty_points_used": self.loyalty_points_used,
            "loyalty_points_earned": self.loyalty_points_earned,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "notes": self.notes,
        }
