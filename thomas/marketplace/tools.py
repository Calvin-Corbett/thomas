"""Tools for Marketplace system - exposes vendor management, listings, orders, and payments."""

from decimal import Decimal
from typing import Any

from thomas.tools.base import Tool, ToolResult


class MarketplaceRegisterVendorTool(Tool):
    """Register a new vendor on the marketplace."""

    name = "marketplace.register_vendor"
    category = "marketplace"
    description = "Register a new vendor with business information and banking details"
    parameters = {
        "type": "object",
        "properties": {
            "business_name": {"type": "string", "description": "Business name"},
            "email": {"type": "string", "description": "Business email"},
            "phone": {"type": "string", "description": "Contact phone"},
            "country": {"type": "string", "description": "Country of operation"},
            "tax_id": {"type": "string", "description": "Tax or VAT ID"},
            "bank_account": {"type": "string", "description": "Bank account for payouts"},
        },
        "required": ["business_name", "email", "phone", "country"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.vendors import VendorManager

        vm = VendorManager()
        try:
            vendor = vm.register_vendor(
                business_name=args["business_name"],
                email=args["email"],
                phone=args["phone"],
                country=args["country"],
                tax_id=args.get("tax_id", ""),
                bank_account=args.get("bank_account", ""),
            )
            return ToolResult(
                ok=True,
                data={
                    "vendor_id": vendor.vendor_id,
                    "business_name": vendor.business_name,
                    "status": vendor.status.name if hasattr(vendor.status, "name") else str(vendor.status),
                    "email": vendor.email,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class MarketplaceGetVendorTool(Tool):
    """Get vendor information and metrics."""

    name = "marketplace.get_vendor"
    category = "marketplace"
    description = "Retrieve vendor profile including ratings, performance metrics, and commission tier"
    parameters = {
        "type": "object",
        "properties": {
            "vendor_id": {"type": "string", "description": "Vendor ID"},
        },
        "required": ["vendor_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.vendors import VendorManager

        vm = VendorManager()
        try:
            vendor = vm.get_vendor(args["vendor_id"])
            return ToolResult(
                ok=True,
                data={
                    "vendor_id": vendor.vendor_id,
                    "business_name": vendor.business_name,
                    "email": vendor.email,
                    "status": vendor.status.name if hasattr(vendor.status, "name") else str(vendor.status),
                    "average_rating": float(vendor.average_rating) if vendor.average_rating else None,
                    "total_sales": str(vendor.total_sales) if vendor.total_sales else "0",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class MarketplaceCreateListingTool(Tool):
    """Create a new product listing."""

    name = "marketplace.create_listing"
    category = "marketplace"
    description = "Create a new product listing with title, description, price, and inventory"
    parameters = {
        "type": "object",
        "properties": {
            "vendor_id": {"type": "string", "description": "Vendor ID"},
            "title": {"type": "string", "description": "Product title"},
            "description": {"type": "string", "description": "Product description"},
            "category_id": {"type": "string", "description": "Category ID"},
            "price": {"type": "number", "description": "Price per unit"},
            "quantity_available": {"type": "integer", "description": "Available quantity"},
            "sku": {"type": "string", "description": "Stock keeping unit (optional)"},
        },
        "required": ["vendor_id", "title", "description", "category_id", "price", "quantity_available"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.listings import ListingManager

        lm = ListingManager()
        try:
            listing = lm.create_listing(
                vendor_id=args["vendor_id"],
                title=args["title"],
                description=args["description"],
                category_id=args["category_id"],
                price=Decimal(str(args["price"])),
                quantity_available=args["quantity_available"],
                sku=args.get("sku", ""),
            )
            return ToolResult(
                ok=True,
                data={
                    "listing_id": listing.listing_id,
                    "title": listing.title,
                    "price": str(listing.price),
                    "quantity": listing.quantity_available,
                    "status": listing.status.name if hasattr(listing.status, "name") else str(listing.status),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class MarketplaceGetListingTool(Tool):
    """Get product listing details."""

    name = "marketplace.get_listing"
    category = "marketplace"
    description = "Retrieve product listing details including description, price, and reviews"
    parameters = {
        "type": "object",
        "properties": {
            "listing_id": {"type": "string", "description": "Listing ID"},
        },
        "required": ["listing_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.listings import ListingManager

        lm = ListingManager()
        try:
            listing = lm.get_listing(args["listing_id"])
            return ToolResult(
                ok=True,
                data={
                    "listing_id": listing.listing_id,
                    "vendor_id": listing.vendor_id,
                    "title": listing.title,
                    "description": listing.description[:200],
                    "price": str(listing.price),
                    "quantity": listing.quantity_available,
                    "status": listing.status.name if hasattr(listing.status, "name") else str(listing.status),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class MarketplacePublishListingTool(Tool):
    """Publish a product listing to make it visible."""

    name = "marketplace.publish_listing"
    category = "marketplace"
    description = "Publish a draft listing to make it visible to buyers"
    parameters = {
        "type": "object",
        "properties": {
            "listing_id": {"type": "string", "description": "Listing ID"},
        },
        "required": ["listing_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.listings import ListingManager

        lm = ListingManager()
        try:
            listing = lm.publish_listing(args["listing_id"])
            return ToolResult(
                ok=True,
                data={
                    "listing_id": listing.listing_id,
                    "status": listing.status.name if hasattr(listing.status, "name") else str(listing.status),
                    "published_at": str(listing.published_at) if hasattr(listing, "published_at") else None,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class MarketplaceCreateOrderTool(Tool):
    """Create a new order."""

    name = "marketplace.create_order"
    category = "marketplace"
    description = "Create a new order with listings and buyer information"
    parameters = {
        "type": "object",
        "properties": {
            "buyer_id": {"type": "string", "description": "Buyer user ID"},
            "listing_id": {"type": "string", "description": "Listing ID"},
            "quantity": {"type": "integer", "description": "Quantity to purchase"},
            "shipping_address": {"type": "string", "description": "Shipping address"},
        },
        "required": ["buyer_id", "listing_id", "quantity", "shipping_address"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.orders import OrderManager

        om = OrderManager()
        try:
            order = om.create_order(
                buyer_id=args["buyer_id"],
                listing_id=args["listing_id"],
                quantity=args["quantity"],
                shipping_address=args["shipping_address"],
            )
            return ToolResult(
                ok=True,
                data={
                    "order_id": order.order_id,
                    "buyer_id": order.buyer_id,
                    "listing_id": order.listing_id,
                    "quantity": order.quantity,
                    "total_amount": str(order.total_amount) if hasattr(order, "total_amount") else "0",
                    "status": order.status.name if hasattr(order.status, "name") else str(order.status),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class MarketplaceGetOrderTool(Tool):
    """Get order details."""

    name = "marketplace.get_order"
    category = "marketplace"
    description = "Retrieve order details including status, items, and payment info"
    parameters = {
        "type": "object",
        "properties": {
            "order_id": {"type": "string", "description": "Order ID"},
        },
        "required": ["order_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.orders import OrderManager

        om = OrderManager()
        try:
            order = om.get_order(args["order_id"])
            return ToolResult(
                ok=True,
                data={
                    "order_id": order.order_id,
                    "buyer_id": order.buyer_id,
                    "listing_id": order.listing_id,
                    "quantity": order.quantity,
                    "status": order.status.name if hasattr(order.status, "name") else str(order.status),
                    "created_at": str(order.created_at) if hasattr(order, "created_at") else None,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class MarketplaceCreateReviewTool(Tool):
    """Create a product review."""

    name = "marketplace.create_review"
    category = "marketplace"
    description = "Create a review for a purchased product with rating and feedback"
    parameters = {
        "type": "object",
        "properties": {
            "listing_id": {"type": "string", "description": "Listing ID"},
            "buyer_id": {"type": "string", "description": "Buyer user ID"},
            "rating": {"type": "integer", "minimum": 1, "maximum": 5, "description": "Rating (1-5)"},
            "comment": {"type": "string", "description": "Review comment"},
        },
        "required": ["listing_id", "buyer_id", "rating"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.reviews import ReviewManager

        rm = ReviewManager()
        try:
            review = rm.create_review(
                listing_id=args["listing_id"],
                buyer_id=args["buyer_id"],
                rating=args["rating"],
                comment=args.get("comment", ""),
            )
            return ToolResult(
                ok=True,
                data={
                    "review_id": review.review_id if hasattr(review, "review_id") else None,
                    "listing_id": review.listing_id,
                    "rating": review.rating,
                    "comment": review.comment[:100] if review.comment else None,
                    "created_at": str(review.created_at) if hasattr(review, "created_at") else None,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class MarketplaceSearchListingsTool(Tool):
    """Search for listings on the marketplace."""

    name = "marketplace.search_listings"
    category = "marketplace"
    description = "Search for product listings by keyword, category, or price range"
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "category_id": {"type": "string", "description": "Category filter (optional)"},
            "min_price": {"type": "number", "description": "Minimum price filter (optional)"},
            "max_price": {"type": "number", "description": "Maximum price filter (optional)"},
            "limit": {"type": "integer", "description": "Result limit (default 20)"},
        },
        "required": ["query"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        from thomas.marketplace.search import SearchEngine

        se = SearchEngine()
        try:
            results = se.search(
                query=args["query"],
                category_id=args.get("category_id"),
                min_price=Decimal(str(args["min_price"])) if args.get("min_price") else None,
                max_price=Decimal(str(args["max_price"])) if args.get("max_price") else None,
                limit=args.get("limit", 20),
            )
            return ToolResult(
                ok=True,
                data=[
                    {
                        "listing_id": r.listing_id if hasattr(r, "listing_id") else None,
                        "title": r.title if hasattr(r, "title") else str(r),
                        "price": str(r.price) if hasattr(r, "price") else None,
                        "vendor_id": r.vendor_id if hasattr(r, "vendor_id") else None,
                    }
                    for r in results
                ],
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_marketplace_tools(registry, sandbox=None):
    """Register all marketplace tools."""
    registry.register(MarketplaceRegisterVendorTool())
    registry.register(MarketplaceGetVendorTool())
    registry.register(MarketplaceCreateListingTool())
    registry.register(MarketplaceGetListingTool())
    registry.register(MarketplacePublishListingTool())
    registry.register(MarketplaceCreateOrderTool())
    registry.register(MarketplaceGetOrderTool())
    registry.register(MarketplaceCreateReviewTool())
    registry.register(MarketplaceSearchListingsTool())
