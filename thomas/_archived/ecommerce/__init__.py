"""E-commerce system public API."""

# Types
# Exceptions
from ._exceptions import (
    EcommerceError,
    InvalidCouponError,
    InventoryError,
    OrderError,
    OutOfStockError,
    PaymentError,
    PricingError,
)
from ._types import (
    Address,
    Cart,
    CartItem,
    Coupon,
    Order,
    OrderItem,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    PriceRule,
    Product,
    ProductStatus,
    ProductVariant,
    ShippingMethod,
    TaxRule,
)

# Modules
from .cart import ShoppingCart
from .catalog import CategoryTree, ProductCatalog
from .checkout import CheckoutProcessor, CheckoutSession
from .inventory import InventoryManager, StockMovement, StockMovementType, StockReservation
from .pricing import PricingEngine
from .promotions import PromotionEngine
from .reviews import Review, ReviewManager, ReviewStatus
from .shipping import Package, ShipmentTracker, ShippingCalculator, ShippingRate, ShippingStatus
from .tax import TaxCalculator

__all__ = [
    # Types
    "Address",
    "Cart",
    "CartItem",
    "Coupon",
    "Order",
    "OrderItem",
    "OrderStatus",
    "PaymentMethod",
    "PaymentStatus",
    "PriceRule",
    "Product",
    "ProductStatus",
    "ProductVariant",
    "ShippingMethod",
    "TaxRule",
    # Exceptions
    "EcommerceError",
    "InventoryError",
    "InvalidCouponError",
    "OrderError",
    "OutOfStockError",
    "PaymentError",
    "PricingError",
    # Managers and Engines
    "CategoryTree",
    "CheckoutProcessor",
    "CheckoutSession",
    "InventoryManager",
    "Package",
    "PricingEngine",
    "ProductCatalog",
    "PromotionEngine",
    "Review",
    "ReviewManager",
    "ReviewStatus",
    "ShippingCalculator",
    "ShippingRate",
    "ShippingStatus",
    "ShipmentTracker",
    "ShoppingCart",
    "StockMovement",
    "StockMovementType",
    "StockReservation",
    "TaxCalculator",
]
