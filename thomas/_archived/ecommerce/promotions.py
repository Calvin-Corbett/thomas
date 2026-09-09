"""Promotions and coupon management."""

from decimal import Decimal
from typing import Any

from ._exceptions import InvalidCouponError
from ._types import Cart, CartItem, Coupon


class PromotionEngine:
    """Manage promotions, coupons, and loyalty."""

    def __init__(self) -> None:
        """Initialize promotion engine."""
        self.coupons: dict[str, Coupon] = {}
        self.user_coupon_usage: dict[str, dict[str, int]] = {}
        self.loyalty_points_balance: dict[str, int] = {}
        self.bogo_rules: dict[str, dict[str, Any]] = {}
        self.cart_rules: list[dict[str, Any]] = []

    def add_coupon(self, coupon: Coupon) -> None:
        """Add coupon to system.

        Args:
            coupon: Coupon to add
        """
        self.coupons[coupon.code] = coupon

    def get_coupon(self, code: str) -> Coupon | None:
        """Get coupon by code.

        Args:
            code: Coupon code

        Returns:
            Coupon or None if not found
        """
        return self.coupons.get(code.upper())

    def validate_coupon(self, code: str, user_id: str | None = None, cart_total: Decimal | None = None) -> Coupon:
        """Validate coupon for use.

        Args:
            code: Coupon code
            user_id: User applying coupon
            cart_total: Cart total for minimum threshold check

        Returns:
            Valid coupon

        Raises:
            InvalidCouponError: If coupon is invalid
        """
        coupon = self.get_coupon(code)
        if not coupon:
            raise InvalidCouponError(code, "Coupon not found")

        if not coupon.is_valid():
            raise InvalidCouponError(code, "Coupon expired or inactive")

        # Check minimum order total
        if coupon.minimum_order_total and cart_total and cart_total < coupon.minimum_order_total:
            raise InvalidCouponError(
                code,
                f"Minimum order total {coupon.minimum_order_total} required",
            )

        # Check usage limits per user
        if user_id and coupon.usage_limit_per_user:
            usage = self.user_coupon_usage.get(user_id, {}).get(code, 0)
            if usage >= coupon.usage_limit_per_user:
                raise InvalidCouponError(code, "Usage limit exceeded for user")

        return coupon

    def apply_coupon(
        self,
        code: str,
        cart: Cart,
        user_id: str | None = None,
    ) -> Decimal:
        """Apply coupon to cart and calculate discount.

        Args:
            code: Coupon code
            cart: Shopping cart
            user_id: User applying coupon

        Returns:
            Discount amount

        Raises:
            InvalidCouponError: If coupon invalid
        """
        cart_total = sum(item.unit_price * item.quantity for item in cart.items)
        coupon = self.validate_coupon(code, user_id, cart_total)

        # Check product/category restrictions
        if coupon.product_ids or coupon.category_ids:
            applicable_items = self._get_applicable_items(cart, coupon)
            if not applicable_items:
                raise InvalidCouponError(code, "No applicable items in cart")

        cart.coupon_code = code
        return self._calculate_coupon_discount(coupon, cart)

    def _get_applicable_items(self, cart: Cart, coupon: Coupon) -> list[CartItem]:
        """Get items applicable to coupon.

        Args:
            cart: Shopping cart
            coupon: Coupon with restrictions

        Returns:
            List of applicable items
        """
        applicable = []
        for item in cart.items:
            if coupon.product_ids and item.product_id in coupon.product_ids or coupon.category_ids:
                applicable.append(item)
        return applicable if coupon.product_ids or coupon.category_ids else cart.items

    def _calculate_coupon_discount(self, coupon: Coupon, cart: Cart) -> Decimal:
        """Calculate discount amount for coupon.

        Args:
            coupon: Coupon to apply
            cart: Shopping cart

        Returns:
            Discount amount
        """
        cart_total = sum(item.unit_price * item.quantity for item in cart.items)

        if coupon.coupon_type == "flat":
            return min(coupon.value, cart_total)
        elif coupon.coupon_type == "percentage":
            return (cart_total * coupon.value) / Decimal("100")
        elif coupon.coupon_type == "free_shipping":
            return coupon.value

        return Decimal("0")

    def record_coupon_usage(self, code: str, user_id: str | None = None) -> None:
        """Record coupon usage.

        Args:
            code: Coupon code
            user_id: User who used coupon
        """
        coupon = self.get_coupon(code)
        if coupon:
            coupon.usage_count += 1

        if user_id:
            if user_id not in self.user_coupon_usage:
                self.user_coupon_usage[user_id] = {}
            self.user_coupon_usage[user_id][code] = self.user_coupon_usage[user_id].get(code, 0) + 1

    def add_bogo(
        self,
        bogo_id: str,
        trigger_product_id: str,
        reward_product_id: str,
        reward_type: str = "free",
        reward_value: Decimal | None = None,
        min_quantity: int = 1,
        max_uses: int | None = None,
    ) -> None:
        """Add buy-one-get-one promotion.

        Args:
            bogo_id: Unique BOGO ID
            trigger_product_id: Product that triggers BOGO
            reward_product_id: Product given as reward
            reward_type: "free", "discount_percentage", "discount_fixed"
            reward_value: Value for discount rewards
            min_quantity: Minimum quantity to trigger
            max_uses: Maximum uses per user
        """
        self.bogo_rules[bogo_id] = {
            "trigger_product_id": trigger_product_id,
            "reward_product_id": reward_product_id,
            "reward_type": reward_type,
            "reward_value": reward_value,
            "min_quantity": min_quantity,
            "max_uses": max_uses,
        }

    def apply_bogo(self, bogo_id: str, cart: Cart) -> Decimal:
        """Apply BOGO promotion to cart.

        Args:
            bogo_id: BOGO rule ID
            cart: Shopping cart

        Returns:
            Discount amount

        Raises:
            ValueError: If BOGO not found
        """
        bogo = self.bogo_rules.get(bogo_id)
        if not bogo:
            raise ValueError(f"BOGO {bogo_id} not found")

        # Find trigger item
        trigger_item = next(
            (i for i in cart.items if i.product_id == bogo["trigger_product_id"]),
            None,
        )
        if not trigger_item or trigger_item.quantity < bogo["min_quantity"]:
            return Decimal("0")

        # Find reward item
        reward_item = next(
            (i for i in cart.items if i.product_id == bogo["reward_product_id"]),
            None,
        )
        if not reward_item:
            return Decimal("0")

        # Calculate discount
        if bogo["reward_type"] == "free":
            return reward_item.unit_price
        elif bogo["reward_type"] == "discount_percentage":
            return (reward_item.unit_price * bogo["reward_value"]) / Decimal("100")
        elif bogo["reward_type"] == "discount_fixed":
            return bogo["reward_value"]

        return Decimal("0")

    def add_cart_rule(
        self,
        rule_id: str,
        condition: dict[str, Any],
        action: dict[str, Any],
    ) -> None:
        """Add automatic cart rule.

        Args:
            rule_id: Unique rule ID
            condition: Condition dict with trigger logic
            action: Action dict with discount logic
        """
        self.cart_rules.append(
            {
                "id": rule_id,
                "condition": condition,
                "action": action,
            }
        )

    def apply_cart_rules(self, cart: Cart) -> Decimal:
        """Apply automatic cart rules.

        Args:
            cart: Shopping cart

        Returns:
            Total discount from rules
        """
        total_discount = Decimal("0")
        cart_total = sum(item.unit_price * item.quantity for item in cart.items)

        for rule in self.cart_rules:
            condition = rule["condition"]

            # Check minimum cart total
            if "min_cart_total" in condition:
                if cart_total < condition["min_cart_total"]:
                    continue

            # Check item count
            if "min_item_count" in condition:
                if len(cart.items) < condition["min_item_count"]:
                    continue

            # Apply action
            action = rule["action"]
            if action["type"] == "discount_percentage":
                discount = (cart_total * action["value"]) / Decimal("100")
                total_discount += discount
            elif action["type"] == "discount_fixed" or action["type"] == "free_shipping":
                total_discount += action["value"]

        return total_discount

    def add_loyalty_points(self, user_id: str, points: int) -> None:
        """Add loyalty points to user.

        Args:
            user_id: User ID
            points: Points to add
        """
        if user_id not in self.loyalty_points_balance:
            self.loyalty_points_balance[user_id] = 0
        self.loyalty_points_balance[user_id] += points

    def redeem_loyalty_points(self, user_id: str, points: int) -> bool:
        """Redeem loyalty points.

        Args:
            user_id: User ID
            points: Points to redeem

        Returns:
            True if redeemed successfully
        """
        balance = self.loyalty_points_balance.get(user_id, 0)
        if balance < points:
            return False

        self.loyalty_points_balance[user_id] -= points
        return True

    def get_loyalty_balance(self, user_id: str) -> int:
        """Get user loyalty points balance.

        Args:
            user_id: User ID

        Returns:
            Points balance
        """
        return self.loyalty_points_balance.get(user_id, 0)

    def calculate_loyalty_points_earned(
        self,
        order_total: Decimal,
        points_per_dollar: Decimal = Decimal("1"),
    ) -> int:
        """Calculate loyalty points earned on order.

        Args:
            order_total: Order total amount
            points_per_dollar: Points per dollar spent

        Returns:
            Points earned
        """
        return int(order_total * points_per_dollar)

    def loyalty_points_to_discount(
        self,
        points: int,
        value_per_point: Decimal = Decimal("0.01"),
    ) -> Decimal:
        """Convert loyalty points to discount.

        Args:
            points: Number of points
            value_per_point: Monetary value per point

        Returns:
            Discount amount
        """
        return Decimal(points) * value_per_point

    def get_coupon_usage_for_user(self, user_id: str, code: str) -> int:
        """Get coupon usage count for user.

        Args:
            user_id: User ID
            code: Coupon code

        Returns:
            Usage count
        """
        return self.user_coupon_usage.get(user_id, {}).get(code, 0)
