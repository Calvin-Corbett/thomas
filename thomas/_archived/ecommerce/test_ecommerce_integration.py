"""Integration tests for complete e-commerce flow."""

from decimal import Decimal

from thomas.ecommerce._types import (
    Address,
    Coupon,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    PriceRule,
    Product,
    ProductStatus,
    ShippingMethod,
    TaxRule,
)
from thomas.ecommerce.cart import ShoppingCart
from thomas.ecommerce.catalog import ProductCatalog
from thomas.ecommerce.checkout import CheckoutProcessor
from thomas.ecommerce.inventory import InventoryManager
from thomas.ecommerce.pricing import PricingEngine
from thomas.ecommerce.promotions import PromotionEngine
from thomas.ecommerce.reviews import ReviewManager
from thomas.ecommerce.tax import TaxCalculator


class TestEcommerceIntegration:
    """Integration tests for complete workflows."""

    def setup_method(self) -> None:
        """Setup all e-commerce components."""
        self.catalog = ProductCatalog()
        self.cart_manager = ShoppingCart()
        self.checkout = CheckoutProcessor()
        self.inventory = InventoryManager()
        self.pricing = PricingEngine()
        self.promotions = PromotionEngine()
        self.tax = TaxCalculator()
        self.reviews = ReviewManager()

        # Setup catalog
        self.catalog.add_category("electronics", "Electronics")

        # Create products
        self.laptop = Product(
            id="laptop",
            name="Gaming Laptop",
            sku="LAP001",
            price=Decimal("1299.99"),
            cost=Decimal("800.00"),
            category="electronics",
            inventory_count=10,
            status=ProductStatus.ACTIVE,
            description="High-performance gaming laptop",
        )

        self.mouse = Product(
            id="mouse",
            name="Gaming Mouse",
            sku="MOUSE001",
            price=Decimal("79.99"),
            cost=Decimal("30.00"),
            category="electronics",
            inventory_count=50,
            status=ProductStatus.ACTIVE,
        )

        self.catalog.add_product(self.laptop)
        self.catalog.add_product(self.mouse)

        # Setup inventory
        self.inventory.set_stock_level("laptop", 10)
        self.inventory.set_stock_level("mouse", 50)

        # Setup tax
        tax_rule = TaxRule(
            id="tax1",
            country="US",
            state="CA",
            rate=Decimal("0.0875"),
            tax_category="standard",
        )
        self.tax.add_tax_rule(tax_rule)

    def test_browse_and_search(self) -> None:
        """Test browsing and searching products."""
        results, total = self.catalog.search(category="electronics")
        assert total == 2

        results, total = self.catalog.search(query="gaming")
        assert total == 2

        results, total = self.catalog.search(query="laptop")
        assert total == 1

    def test_add_to_cart(self) -> None:
        """Test adding products to cart."""
        cart = self.cart_manager.create_cart("cart1", "user1")

        self.cart_manager.add_item("cart1", self.laptop, 1)
        self.cart_manager.add_item("cart1", self.mouse, 2)

        items = self.cart_manager.get_items("cart1")
        assert len(items) == 2

        subtotal = self.cart_manager.get_subtotal("cart1")
        expected = Decimal("1299.99") + (Decimal("79.99") * 2)
        assert subtotal == expected

    def test_apply_pricing_rules(self) -> None:
        """Test applying pricing rules during shopping."""
        # Add discount rule for electronics
        from datetime import datetime

        rule = PriceRule(
            id="electronics_discount",
            name="Electronics Special",
            conditions={"categories": ["electronics"]},
            action="discount_percentage",
            action_value=Decimal("10"),
            active=True,
            start_date=datetime.utcnow(),
        )
        self.pricing.add_price_rule(rule)

        # Get discounted price
        discounted_price = self.pricing.get_product_price(self.laptop)
        expected = Decimal("1299.99") * (1 - Decimal("10") / Decimal("100"))
        assert discounted_price == expected

    def test_apply_coupon_to_cart(self) -> None:
        """Test applying coupon to cart."""
        # Create and add coupon
        coupon = Coupon(
            code="SUMMER2025",
            coupon_type="percentage",
            value=Decimal("15"),
            active=True,
        )
        self.promotions.add_coupon(coupon)

        # Add items to cart
        cart = self.cart_manager.create_cart("cart1", "user1")
        self.cart_manager.add_item("cart1", self.laptop, 1)

        # Apply coupon
        cart_total = self.cart_manager.get_subtotal("cart1")
        discount = self.promotions.apply_coupon("SUMMER2025", cart, "user1")

        expected_discount = cart_total * Decimal("15") / Decimal("100")
        assert discount == expected_discount

    def test_calculate_shipping_and_tax(self) -> None:
        """Test calculating shipping and tax."""
        # Setup shipping (flat rate)
        from shipping import ShippingCalculator

        shipping = ShippingCalculator()

        # Cart total
        cart = self.cart_manager.create_cart("cart1", "user1")
        self.cart_manager.add_item("cart1", self.laptop, 1)
        cart_total = self.cart_manager.get_subtotal("cart1")

        # Calculate shipping
        shipping_cost = shipping.calculate_flat_rate(ShippingMethod.STANDARD)

        # Calculate tax
        items = [
            {
                "product_id": "laptop",
                "unit_price": Decimal("1299.99"),
                "quantity": 1,
                "tax_category": "standard",
            }
        ]
        tax_amount = self.tax.calculate_order_tax(items, "US", "CA")

        # Verify calculations
        assert shipping_cost >= 0
        assert tax_amount > 0
        total = cart_total + shipping_cost + tax_amount
        assert total > cart_total

    def test_complete_checkout(self) -> None:
        """Test complete checkout flow."""
        # Browse and add to cart
        cart = self.cart_manager.create_cart("cart1", "user1")
        self.cart_manager.add_item("cart1", self.laptop, 1)
        self.cart_manager.add_item("cart1", self.mouse, 1)

        # Start checkout
        session = self.checkout.start_checkout(cart)

        # Set addresses
        address = Address(
            street_line_1="123 Tech Street",
            street_line_2=None,
            city="San Francisco",
            state="CA",
            postal_code="94105",
            country="US",
        )
        self.checkout.set_shipping_address(session.session_id, address)
        self.checkout.set_billing_address(session.session_id, same_as_shipping=True)

        # Select shipping and payment
        self.checkout.set_shipping_method(session.session_id, ShippingMethod.STANDARD)
        self.checkout.set_payment_method(session.session_id, PaymentMethod.CREDIT_CARD)

        # Create order
        order = self.checkout.create_order(session.session_id, "user1")

        # Calculate totals
        items = [
            {
                "product_id": "laptop",
                "unit_price": Decimal("1299.99"),
                "quantity": 1,
                "tax_category": "standard",
            },
            {
                "product_id": "mouse",
                "unit_price": Decimal("79.99"),
                "quantity": 1,
                "tax_category": "standard",
            },
        ]
        tax = self.tax.calculate_order_tax(items, "US", "CA")

        self.checkout.calculate_order_totals(
            order,
            shipping_cost=Decimal("15.00"),
            tax_cost=tax,
        )

        # Process payment
        payment_details = {"amount": order.total, "card_number": "4111111111111111"}
        self.checkout.process_payment(order, payment_details)

        # Verify order state
        assert order.status == OrderStatus.PROCESSING
        assert order.payment_status == PaymentStatus.COMPLETED
        assert order.total > 0
        assert len(order.items) == 2

    def test_product_reviews(self) -> None:
        """Test submitting and managing reviews."""
        # Submit reviews
        review1 = self.reviews.submit_review(
            product_id="laptop",
            reviewer_id="user1",
            rating=5,
            title="Excellent laptop!",
            text="Great performance and build quality",
            verified_purchase=True,
        )

        review2 = self.reviews.submit_review(
            product_id="laptop",
            reviewer_id="user2",
            rating=4,
            title="Very good",
            text="A bit expensive but worth it",
            verified_purchase=True,
        )

        # Approve reviews
        self.reviews.approve_review(review1.id)
        self.reviews.approve_review(review2.id)

        # Get product reviews
        reviews = self.reviews.get_product_reviews("laptop")
        assert len(reviews) == 2

        # Check rating
        average = self.reviews.get_average_rating("laptop")
        assert average == Decimal("4.50")

    def test_inventory_reservation(self) -> None:
        """Test inventory reservation during checkout."""
        initial_stock = self.inventory.get_stock_level("laptop")

        # Reserve stock for order
        reservation = self.inventory.reserve_stock(
            product_id="laptop",
            variant_id=None,
            quantity=2,
            order_id="order1",
            reservation_id="res1",
        )

        # Available stock should decrease
        available = self.inventory.get_available_stock("laptop")
        assert available == initial_stock - 2

        # Confirm reservation
        self.inventory.confirm_reservation("res1")

        # Stock should be decremented
        final_stock = self.inventory.get_stock_level("laptop")
        assert final_stock == initial_stock - 2

    def test_loyalty_points_on_order(self) -> None:
        """Test loyalty points earning and redemption."""
        # Complete an order
        cart = self.cart_manager.create_cart("cart1", "user1")
        self.cart_manager.add_item("cart1", self.laptop, 1)
        session = self.checkout.start_checkout(cart)

        address = Address(
            street_line_1="123 Tech Street",
            street_line_2=None,
            city="San Francisco",
            state="CA",
            postal_code="94105",
            country="US",
        )
        self.checkout.set_shipping_address(session.session_id, address)
        self.checkout.set_billing_address(session.session_id, same_as_shipping=True)
        self.checkout.set_shipping_method(session.session_id, ShippingMethod.STANDARD)
        self.checkout.set_payment_method(session.session_id, PaymentMethod.CREDIT_CARD)

        order = self.checkout.create_order(session.session_id, "user1")
        self.checkout.calculate_order_totals(order, Decimal("15.00"), Decimal("100.00"))

        # Earn loyalty points
        points_earned = self.promotions.calculate_loyalty_points_earned(order.total)
        self.promotions.add_loyalty_points("user1", points_earned)

        balance = self.promotions.get_loyalty_balance("user1")
        assert balance == points_earned

        # Redeem points
        success = self.promotions.redeem_loyalty_points("user1", points_earned // 2)
        assert success is True

    def test_multi_item_checkout(self) -> None:
        """Test checkout with multiple items and calculations."""
        # Create cart with multiple items
        cart = self.cart_manager.create_cart("cart1", "user1")
        self.cart_manager.add_item("cart1", self.laptop, 1)
        self.cart_manager.add_item("cart1", self.mouse, 3)

        # Verify subtotal
        subtotal = self.cart_manager.get_subtotal("cart1")
        expected_subtotal = Decimal("1299.99") + (Decimal("79.99") * 3)
        assert subtotal == expected_subtotal

        # Start checkout
        session = self.checkout.start_checkout(cart)

        # Complete checkout steps
        address = Address(
            street_line_1="123 Main St",
            street_line_2=None,
            city="New York",
            state="NY",
            postal_code="10001",
            country="US",
        )
        self.checkout.set_shipping_address(session.session_id, address)
        self.checkout.set_billing_address(session.session_id, same_as_shipping=True)
        self.checkout.set_shipping_method(session.session_id, ShippingMethod.EXPRESS)
        self.checkout.set_payment_method(session.session_id, PaymentMethod.PAYPAL)

        # Create order
        order = self.checkout.create_order(session.session_id, "user1")

        # Verify items
        assert len(order.items) == 2
        assert order.items[0].quantity == 1
        assert order.items[1].quantity == 3
