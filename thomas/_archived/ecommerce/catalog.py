"""Product catalog management."""

import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Any

from ._exceptions import EcommerceError
from ._types import Product, ProductStatus, ProductVariant


class CategoryTree:
    """Hierarchical product category tree."""

    def __init__(self) -> None:
        """Initialize category tree."""
        self.categories: dict[str, dict[str, Any]] = {}
        self.parent_map: dict[str, str | None] = {}

    def add_category(self, category_id: str, name: str, parent_id: str | None = None) -> None:
        """Add category to tree.

        Args:
            category_id: Unique category identifier
            name: Category name
            parent_id: Parent category ID for hierarchy

        Raises:
            EcommerceError: If parent category doesn't exist
        """
        if parent_id and parent_id not in self.categories:
            raise EcommerceError(f"Parent category {parent_id} not found")

        self.categories[category_id] = {
            "id": category_id,
            "name": name,
            "parent_id": parent_id,
            "children": [],
        }
        self.parent_map[category_id] = parent_id

        if parent_id:
            self.categories[parent_id]["children"].append(category_id)

    def get_path(self, category_id: str) -> list[str]:
        """Get full path from root to category.

        Args:
            category_id: Category ID

        Returns:
            List of category IDs from root to target
        """
        path = []
        current = category_id
        while current:
            path.append(current)
            current = self.parent_map.get(current)
        return list(reversed(path))

    def get_subcategories(self, category_id: str) -> list[str]:
        """Get all subcategories recursively.

        Args:
            category_id: Category ID

        Returns:
            List of all subcategory IDs
        """
        if category_id not in self.categories:
            return []

        result = []
        to_process = [category_id]
        while to_process:
            current = to_process.pop(0)
            result.append(current)
            to_process.extend(self.categories[current]["children"])
        return result[1:]  # Exclude the root category itself


class ProductCatalog:
    """Product catalog with CRUD operations and search."""

    def __init__(self) -> None:
        """Initialize product catalog."""
        self.products: dict[str, Product] = {}
        self.variants: dict[str, ProductVariant] = {}
        self.category_tree = CategoryTree()
        self.sku_index: dict[str, str] = {}
        self.category_index: dict[str, set[str]] = defaultdict(set)

    def add_category(self, category_id: str, name: str, parent_id: str | None = None) -> None:
        """Add category to catalog.

        Args:
            category_id: Unique category identifier
            name: Category name
            parent_id: Parent category ID for hierarchy
        """
        self.category_tree.add_category(category_id, name, parent_id)

    def add_product(self, product: Product) -> None:
        """Add product to catalog.

        Args:
            product: Product to add

        Raises:
            EcommerceError: If product ID or SKU already exists
        """
        if product.id in self.products:
            raise EcommerceError(f"Product {product.id} already exists")
        if product.sku in self.sku_index:
            raise EcommerceError(f"SKU {product.sku} already exists")

        self.products[product.id] = product
        self.sku_index[product.sku] = product.id
        self.category_index[product.category].add(product.id)

    def update_product(self, product: Product) -> None:
        """Update existing product.

        Args:
            product: Updated product

        Raises:
            EcommerceError: If product doesn't exist
        """
        if product.id not in self.products:
            raise EcommerceError(f"Product {product.id} not found")

        old_product = self.products[product.id]
        if product.sku != old_product.sku and product.sku in self.sku_index:
            raise EcommerceError(f"SKU {product.sku} already exists")

        if product.category != old_product.category:
            self.category_index[old_product.category].discard(product.id)
            self.category_index[product.category].add(product.id)

        if product.sku != old_product.sku:
            del self.sku_index[old_product.sku]
            self.sku_index[product.sku] = product.id

        product.updated_at = datetime.utcnow()
        self.products[product.id] = product

    def delete_product(self, product_id: str) -> None:
        """Delete product from catalog.

        Args:
            product_id: ID of product to delete

        Raises:
            EcommerceError: If product doesn't exist
        """
        if product_id not in self.products:
            raise EcommerceError(f"Product {product_id} not found")

        product = self.products[product_id]
        del self.products[product_id]
        del self.sku_index[product.sku]
        self.category_index[product.category].discard(product_id)

        # Delete variants
        variant_ids = [vid for vid in self.variants if self.variants[vid].product_id == product_id]
        for vid in variant_ids:
            del self.variants[vid]

    def get_product(self, product_id: str) -> Product | None:
        """Get product by ID.

        Args:
            product_id: Product ID

        Returns:
            Product or None if not found
        """
        return self.products.get(product_id)

    def get_product_by_sku(self, sku: str) -> Product | None:
        """Get product by SKU.

        Args:
            sku: Product SKU

        Returns:
            Product or None if not found
        """
        product_id = self.sku_index.get(sku)
        return self.products.get(product_id) if product_id else None

    def add_variant(self, variant: ProductVariant) -> None:
        """Add product variant.

        Args:
            variant: Product variant to add

        Raises:
            EcommerceError: If variant ID exists or product not found
        """
        if variant.id in self.variants:
            raise EcommerceError(f"Variant {variant.id} already exists")
        if variant.product_id not in self.products:
            raise EcommerceError(f"Product {variant.product_id} not found")

        self.variants[variant.id] = variant

    def get_variants(self, product_id: str) -> list[ProductVariant]:
        """Get all variants for a product.

        Args:
            product_id: Product ID

        Returns:
            List of product variants
        """
        return [v for v in self.variants.values() if v.product_id == product_id]

    def search(
        self,
        query: str | None = None,
        category: str | None = None,
        status: ProductStatus | None = None,
        min_price: Decimal | None = None,
        max_price: Decimal | None = None,
        in_stock_only: bool = False,
        attributes: dict[str, Any] | None = None,
        sort_by: str = "name",
        sort_order: str = "asc",
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Product], int]:
        """Search products with filters.

        Args:
            query: Text search query
            category: Category ID (includes subcategories)
            status: Product status filter
            min_price: Minimum price filter
            max_price: Maximum price filter
            in_stock_only: Only return in-stock products
            attributes: Attribute filters
            sort_by: Field to sort by (name, price, rating, popularity)
            sort_order: Sort order (asc, desc)
            page: Page number (1-indexed)
            page_size: Results per page

        Returns:
            Tuple of (products, total_count)
        """
        results = list(self.products.values())

        # Text search
        if query:
            query_lower = query.lower()
            query_pattern = re.compile(re.escape(query_lower))
            results = [
                p
                for p in results
                if (
                    query_pattern.search(p.name.lower())
                    or query_pattern.search(p.description.lower())
                    or query_pattern.search(p.sku.lower())
                )
            ]

        # Category filter
        if category:
            category_ids = {category} | set(self.category_tree.get_subcategories(category))
            results = [p for p in results if p.category in category_ids]

        # Status filter
        if status:
            results = [p for p in results if p.status == status]

        # Price range
        if min_price is not None:
            results = [p for p in results if p.price >= min_price]
        if max_price is not None:
            results = [p for p in results if p.price <= max_price]

        # Stock filter
        if in_stock_only:
            results = [p for p in results if p.inventory_count > 0]

        # Attribute filters
        if attributes:
            for attr_key, attr_val in attributes.items():
                results = [p for p in results if p.attributes.get(attr_key) == attr_val]

        # Sorting
        reverse = sort_order == "desc"
        if sort_by == "price":
            results.sort(key=lambda p: p.price, reverse=reverse)
        elif sort_by == "rating":
            results.sort(key=lambda p: p.rating, reverse=reverse)
        elif sort_by == "popularity":
            results.sort(key=lambda p: p.review_count, reverse=reverse)
        else:  # name
            results.sort(key=lambda p: p.name, reverse=reverse)

        # Pagination
        total = len(results)
        start = (page - 1) * page_size
        end = start + page_size
        return results[start:end], total

    def get_by_category(self, category_id: str) -> list[Product]:
        """Get all products in category.

        Args:
            category_id: Category ID

        Returns:
            List of products in category
        """
        if category_id not in self.category_tree.categories:
            return []
        return [self.products[pid] for pid in self.category_index[category_id]]

    def update_inventory(self, product_id: str, quantity: int) -> None:
        """Update product inventory count.

        Args:
            product_id: Product ID
            quantity: New inventory count

        Raises:
            EcommerceError: If product not found
        """
        if product_id not in self.products:
            raise EcommerceError(f"Product {product_id} not found")

        self.products[product_id].inventory_count = max(0, quantity)
        self.products[product_id].updated_at = datetime.utcnow()

    def update_variant_inventory(self, variant_id: str, quantity: int) -> None:
        """Update variant inventory count.

        Args:
            variant_id: Variant ID
            quantity: New inventory count

        Raises:
            EcommerceError: If variant not found
        """
        if variant_id not in self.variants:
            raise EcommerceError(f"Variant {variant_id} not found")

        self.variants[variant_id].inventory_count = max(0, quantity)

    def get_low_stock_products(self, threshold: int = 10) -> list[Product]:
        """Get products below stock threshold.

        Args:
            threshold: Stock level threshold

        Returns:
            List of low-stock products
        """
        return [p for p in self.products.values() if p.inventory_count <= threshold]

    def get_stock_value(self) -> Decimal:
        """Calculate total inventory value.

        Returns:
            Total value of inventory (cost-based)
        """
        return sum(p.cost * p.inventory_count for p in self.products.values())

    def get_product_popularity(self, product_id: str) -> int:
        """Get product popularity score.

        Args:
            product_id: Product ID

        Returns:
            Popularity score (review count * rating)
        """
        product = self.products.get(product_id)
        if not product:
            return 0
        return int(product.review_count * float(product.rating))
