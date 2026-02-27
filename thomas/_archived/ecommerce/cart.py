"""Shopping cart management."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from ._exceptions import EcommerceError, OutOfStockError
from ._types import Cart, CartItem, Product


class ShoppingCart:
    """Shopping cart manager."""

    def __init__(self, default_expiry_days: int = 7) -> None:
        """Initialize shopping cart manager.

        Args:
            default_expiry_days: Days until cart expires
        """
        self.carts: dict[str, Cart] = {}
        self.default_expiry_days = default_expiry_days

    def create_cart(self, cart_id: str, user_id: str | None = None) -> Cart:
        """Create new shopping cart.

        Args:
            cart_id: Unique cart identifier
            user_id: Optional user ID

        Returns:
            Created cart

        Raises:
            EcommerceError: If cart ID already exists
        """
        if cart_id in self.carts:
            raise EcommerceError(f"Cart {cart_id} already exists")

        expires_at = datetime.utcnow() + timedelta(days=self.default_expiry_days)
        cart = Cart(
            id=cart_id,
            user_id=user_id,
            items=[],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            expires_at=expires_at,
        )
        self.carts[cart_id] = cart
        return cart

    def get_cart(self, cart_id: str) -> Cart | None:
        """Get cart by ID.

        Args:
            cart_id: Cart ID

        Returns:
            Cart or None if not found or expired
        """
        if cart_id not in self.carts:
            return None

        cart = self.carts[cart_id]
        if cart.expires_at and datetime.utcnow() > cart.expires_at:
            del self.carts[cart_id]
            return None
        return cart

    def add_item(
        self,
        cart_id: str,
        product: Product,
        quantity: int,
        variant_id: str | None = None,
    ) -> CartItem:
        """Add item to cart.

        Args:
            cart_id: Cart ID
            product: Product to add
            quantity: Quantity to add
            variant_id: Optional variant ID

        Returns:
            Added cart item

        Raises:
            EcommerceError: If cart not found or quantity invalid
            OutOfStockError: If insufficient inventory
        """
        cart = self.get_cart(cart_id)
        if not cart:
            raise EcommerceError(f"Cart {cart_id} not found or expired")

        if quantity <= 0:
            raise EcommerceError("Quantity must be positive")

        if product.inventory_count < quantity:
            raise OutOfStockError(product.id, quantity, product.inventory_count)

        # Check if item already in cart
        for item in cart.items:
            if item.product_id == product.id and item.variant_id == variant_id:
                item.quantity += quantity
                cart.updated_at = datetime.utcnow()
                return item

        # Create new item
        unit_price = product.price
        item = CartItem(
            product_id=product.id,
            variant_id=variant_id,
            quantity=quantity,
            unit_price=unit_price,
            added_at=datetime.utcnow(),
        )
        cart.items.append(item)
        cart.updated_at = datetime.utcnow()
        return item

    def remove_item(self, cart_id: str, product_id: str, variant_id: str | None = None) -> None:
        """Remove item from cart.

        Args:
            cart_id: Cart ID
            product_id: Product ID to remove
            variant_id: Optional variant ID

        Raises:
            EcommerceError: If cart not found
        """
        cart = self.get_cart(cart_id)
        if not cart:
            raise EcommerceError(f"Cart {cart_id} not found or expired")

        cart.items = [
            item for item in cart.items if not (item.product_id == product_id and item.variant_id == variant_id)
        ]
        cart.updated_at = datetime.utcnow()

    def update_item_quantity(
        self,
        cart_id: str,
        product_id: str,
        quantity: int,
        variant_id: str | None = None,
    ) -> None:
        """Update item quantity in cart.

        Args:
            cart_id: Cart ID
            product_id: Product ID
            quantity: New quantity
            variant_id: Optional variant ID

        Raises:
            EcommerceError: If cart or item not found, or quantity invalid
        """
        cart = self.get_cart(cart_id)
        if not cart:
            raise EcommerceError(f"Cart {cart_id} not found or expired")

        if quantity < 0:
            raise EcommerceError("Quantity cannot be negative")

        for item in cart.items:
            if item.product_id == product_id and item.variant_id == variant_id:
                if quantity == 0:
                    self.remove_item(cart_id, product_id, variant_id)
                else:
                    item.quantity = quantity
                cart.updated_at = datetime.utcnow()
                return

        raise EcommerceError(f"Item {product_id} not in cart")

    def get_subtotal(self, cart_id: str) -> Decimal:
        """Calculate cart subtotal.

        Args:
            cart_id: Cart ID

        Returns:
            Subtotal before tax/shipping

        Raises:
            EcommerceError: If cart not found
        """
        cart = self.get_cart(cart_id)
        if not cart:
            raise EcommerceError(f"Cart {cart_id} not found or expired")

        return sum(item.subtotal() for item in cart.items)

    def get_item_count(self, cart_id: str) -> int:
        """Get total items in cart.

        Args:
            cart_id: Cart ID

        Returns:
            Total quantity of items

        Raises:
            EcommerceError: If cart not found
        """
        cart = self.get_cart(cart_id)
        if not cart:
            raise EcommerceError(f"Cart {cart_id} not found or expired")

        return sum(item.quantity for item in cart.items)

    def get_items(self, cart_id: str) -> list[CartItem]:
        """Get all items in cart.

        Args:
            cart_id: Cart ID

        Returns:
            List of cart items

        Raises:
            EcommerceError: If cart not found
        """
        cart = self.get_cart(cart_id)
        if not cart:
            raise EcommerceError(f"Cart {cart_id} not found or expired")

        return cart.items.copy()

    def clear_cart(self, cart_id: str) -> None:
        """Clear all items from cart.

        Args:
            cart_id: Cart ID

        Raises:
            EcommerceError: If cart not found
        """
        cart = self.get_cart(cart_id)
        if not cart:
            raise EcommerceError(f"Cart {cart_id} not found or expired")

        cart.items.clear()
        cart.updated_at = datetime.utcnow()

    def apply_coupon(self, cart_id: str, coupon_code: str) -> None:
        """Apply coupon code to cart.

        Args:
            cart_id: Cart ID
            coupon_code: Coupon code

        Raises:
            EcommerceError: If cart not found
        """
        cart = self.get_cart(cart_id)
        if not cart:
            raise EcommerceError(f"Cart {cart_id} not found or expired")

        cart.coupon_code = coupon_code
        cart.updated_at = datetime.utcnow()

    def remove_coupon(self, cart_id: str) -> None:
        """Remove coupon from cart.

        Args:
            cart_id: Cart ID

        Raises:
            EcommerceError: If cart not found
        """
        cart = self.get_cart(cart_id)
        if not cart:
            raise EcommerceError(f"Cart {cart_id} not found or expired")

        cart.coupon_code = None
        cart.updated_at = datetime.utcnow()

    def save_for_later(self, cart_id: str, product_id: str) -> None:
        """Save item for later (wishlist).

        Args:
            cart_id: Cart ID
            product_id: Product ID to save

        Raises:
            EcommerceError: If cart not found
        """
        cart = self.get_cart(cart_id)
        if not cart:
            raise EcommerceError(f"Cart {cart_id} not found or expired")

        if product_id not in cart.saved_items:
            cart.saved_items.append(product_id)
            cart.updated_at = datetime.utcnow()

    def remove_saved_item(self, cart_id: str, product_id: str) -> None:
        """Remove item from saved items.

        Args:
            cart_id: Cart ID
            product_id: Product ID

        Raises:
            EcommerceError: If cart not found
        """
        cart = self.get_cart(cart_id)
        if not cart:
            raise EcommerceError(f"Cart {cart_id} not found or expired")

        if product_id in cart.saved_items:
            cart.saved_items.remove(product_id)
            cart.updated_at = datetime.utcnow()

    def get_saved_items(self, cart_id: str) -> list[str]:
        """Get saved items (wishlist).

        Args:
            cart_id: Cart ID

        Returns:
            List of saved product IDs

        Raises:
            EcommerceError: If cart not found
        """
        cart = self.get_cart(cart_id)
        if not cart:
            raise EcommerceError(f"Cart {cart_id} not found or expired")

        return cart.saved_items.copy()

    def merge_carts(self, source_cart_id: str, target_cart_id: str, target_user_id: str | None = None) -> Cart:
        """Merge guest cart into authenticated cart.

        Args:
            source_cart_id: Guest cart ID
            target_cart_id: User cart ID
            target_user_id: New user ID for merged cart

        Returns:
            Merged cart

        Raises:
            EcommerceError: If carts not found
        """
        source = self.carts.get(source_cart_id)
        target = self.carts.get(target_cart_id)

        if not source or not target:
            raise EcommerceError("One or both carts not found")

        # Merge items
        for item in source.items:
            existing = next(
                (i for i in target.items if i.product_id == item.product_id and i.variant_id == item.variant_id),
                None,
            )
            if existing:
                existing.quantity += item.quantity
            else:
                target.items.append(item)

        # Merge saved items
        target.saved_items.extend([p for p in source.saved_items if p not in target.saved_items])

        # Update user ID and timestamp
        if target_user_id:
            target.user_id = target_user_id
        target.updated_at = datetime.utcnow()

        # Delete source cart
        del self.carts[source_cart_id]

        return target

    def delete_cart(self, cart_id: str) -> None:
        """Delete cart.

        Args:
            cart_id: Cart ID
        """
        if cart_id in self.carts:
            del self.carts[cart_id]

    def cleanup_expired_carts(self) -> int:
        """Remove expired carts.

        Returns:
            Number of carts removed
        """
        now = datetime.utcnow()
        expired = [cid for cid, cart in self.carts.items() if cart.expires_at and now > cart.expires_at]
        for cid in expired:
            del self.carts[cid]
        return len(expired)

    def export_cart(self, cart_id: str) -> dict[str, Any]:
        """Export cart to dictionary.

        Args:
            cart_id: Cart ID

        Returns:
            Cart as dictionary

        Raises:
            EcommerceError: If cart not found
        """
        cart = self.get_cart(cart_id)
        if not cart:
            raise EcommerceError(f"Cart {cart_id} not found")

        return cart.to_dict()
