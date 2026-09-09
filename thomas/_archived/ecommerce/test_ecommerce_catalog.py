"""Tests for product catalog management."""

from decimal import Decimal

import pytest

from thomas.ecommerce._exceptions import EcommerceError
from thomas.ecommerce._types import Product, ProductStatus, ProductVariant
from thomas.ecommerce.catalog import CategoryTree, ProductCatalog


class TestCategoryTree:
    """Test category tree hierarchy."""

    def test_add_category(self) -> None:
        """Test adding categories."""
        tree = CategoryTree()
        tree.add_category("electronics", "Electronics")
        tree.add_category("phones", "Phones", "electronics")

        assert "electronics" in tree.categories
        assert "phones" in tree.categories
        assert tree.categories["phones"]["parent_id"] == "electronics"

    def test_add_category_invalid_parent(self) -> None:
        """Test adding category with non-existent parent."""
        tree = CategoryTree()

        with pytest.raises(EcommerceError):
            tree.add_category("phones", "Phones", "nonexistent")

    def test_get_path(self) -> None:
        """Test getting category path."""
        tree = CategoryTree()
        tree.add_category("electronics", "Electronics")
        tree.add_category("phones", "Phones", "electronics")
        tree.add_category("smartphones", "Smartphones", "phones")

        path = tree.get_path("smartphones")
        assert path == ["electronics", "phones", "smartphones"]

    def test_get_subcategories(self) -> None:
        """Test getting subcategories."""
        tree = CategoryTree()
        tree.add_category("electronics", "Electronics")
        tree.add_category("phones", "Phones", "electronics")
        tree.add_category("smartphones", "Smartphones", "phones")
        tree.add_category("tablets", "Tablets", "electronics")

        subcats = tree.get_subcategories("electronics")
        assert "phones" in subcats
        assert "tablets" in subcats
        assert "smartphones" in subcats


class TestProductCatalog:
    """Test product catalog operations."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.catalog = ProductCatalog()
        self.catalog.add_category("electronics", "Electronics")

    def test_add_product(self) -> None:
        """Test adding product."""
        product = Product(
            id="p1",
            name="Laptop",
            sku="LAP001",
            price=Decimal("999.99"),
            cost=Decimal("600.00"),
            category="electronics",
            inventory_count=10,
            status=ProductStatus.ACTIVE,
        )
        self.catalog.add_product(product)

        assert self.catalog.get_product("p1") == product

    def test_add_duplicate_product(self) -> None:
        """Test adding duplicate product."""
        product = Product(
            id="p1",
            name="Laptop",
            sku="LAP001",
            price=Decimal("999.99"),
            cost=Decimal("600.00"),
            category="electronics",
        )
        self.catalog.add_product(product)

        with pytest.raises(EcommerceError):
            self.catalog.add_product(product)

    def test_add_duplicate_sku(self) -> None:
        """Test adding product with duplicate SKU."""
        product1 = Product(
            id="p1",
            name="Laptop",
            sku="LAP001",
            price=Decimal("999.99"),
            cost=Decimal("600.00"),
            category="electronics",
        )
        product2 = Product(
            id="p2",
            name="Desktop",
            sku="LAP001",
            price=Decimal("1299.99"),
            cost=Decimal("800.00"),
            category="electronics",
        )
        self.catalog.add_product(product1)

        with pytest.raises(EcommerceError):
            self.catalog.add_product(product2)

    def test_get_product_by_sku(self) -> None:
        """Test getting product by SKU."""
        product = Product(
            id="p1",
            name="Laptop",
            sku="LAP001",
            price=Decimal("999.99"),
            cost=Decimal("600.00"),
            category="electronics",
        )
        self.catalog.add_product(product)

        found = self.catalog.get_product_by_sku("LAP001")
        assert found == product

    def test_update_product(self) -> None:
        """Test updating product."""
        product = Product(
            id="p1",
            name="Laptop",
            sku="LAP001",
            price=Decimal("999.99"),
            cost=Decimal("600.00"),
            category="electronics",
        )
        self.catalog.add_product(product)

        product.price = Decimal("899.99")
        self.catalog.update_product(product)

        updated = self.catalog.get_product("p1")
        assert updated.price == Decimal("899.99")

    def test_delete_product(self) -> None:
        """Test deleting product."""
        product = Product(
            id="p1",
            name="Laptop",
            sku="LAP001",
            price=Decimal("999.99"),
            cost=Decimal("600.00"),
            category="electronics",
        )
        self.catalog.add_product(product)
        self.catalog.delete_product("p1")

        assert self.catalog.get_product("p1") is None

    def test_add_variant(self) -> None:
        """Test adding product variant."""
        product = Product(
            id="p1",
            name="Laptop",
            sku="LAP001",
            price=Decimal("999.99"),
            cost=Decimal("600.00"),
            category="electronics",
        )
        self.catalog.add_product(product)

        variant = ProductVariant(
            id="v1",
            product_id="p1",
            sku="LAP001-BLU",
            attributes={"color": "blue", "size": "15in"},
            price_delta=Decimal("50.00"),
            inventory_count=5,
        )
        self.catalog.add_variant(variant)

        variants = self.catalog.get_variants("p1")
        assert len(variants) == 1
        assert variants[0].id == "v1"

    def test_search_by_text(self) -> None:
        """Test searching products by text."""
        p1 = Product(
            id="p1",
            name="Gaming Laptop",
            sku="LAP001",
            price=Decimal("999.99"),
            cost=Decimal("600.00"),
            category="electronics",
            description="High-performance gaming laptop",
        )
        p2 = Product(
            id="p2",
            name="Office Desk",
            sku="DESK001",
            price=Decimal("299.99"),
            cost=Decimal("150.00"),
            category="furniture",
            description="Standard office desk",
        )
        self.catalog.add_product(p1)
        self.catalog.add_product(p2)

        results, total = self.catalog.search(query="gaming")
        assert total == 1
        assert results[0].id == "p1"

    def test_search_by_price(self) -> None:
        """Test searching by price range."""
        p1 = Product(
            id="p1",
            name="Expensive Laptop",
            sku="LAP001",
            price=Decimal("1999.99"),
            cost=Decimal("1200.00"),
            category="electronics",
        )
        p2 = Product(
            id="p2",
            name="Budget Laptop",
            sku="LAP002",
            price=Decimal("499.99"),
            cost=Decimal("300.00"),
            category="electronics",
        )
        self.catalog.add_product(p1)
        self.catalog.add_product(p2)

        results, total = self.catalog.search(min_price=Decimal("400"), max_price=Decimal("600"))
        assert total == 1
        assert results[0].id == "p2"

    def test_search_in_stock_only(self) -> None:
        """Test searching in-stock only."""
        p1 = Product(
            id="p1",
            name="In Stock",
            sku="LAP001",
            price=Decimal("999.99"),
            cost=Decimal("600.00"),
            category="electronics",
            inventory_count=5,
            status=ProductStatus.ACTIVE,
        )
        p2 = Product(
            id="p2",
            name="Out of Stock",
            sku="LAP002",
            price=Decimal("899.99"),
            cost=Decimal("500.00"),
            category="electronics",
            inventory_count=0,
            status=ProductStatus.ACTIVE,
        )
        self.catalog.add_product(p1)
        self.catalog.add_product(p2)

        results, total = self.catalog.search(in_stock_only=True)
        assert total == 1
        assert results[0].id == "p1"

    def test_search_by_status(self) -> None:
        """Test searching by product status."""
        p1 = Product(
            id="p1",
            name="Active Product",
            sku="LAP001",
            price=Decimal("999.99"),
            cost=Decimal("600.00"),
            category="electronics",
            status=ProductStatus.ACTIVE,
        )
        p2 = Product(
            id="p2",
            name="Draft Product",
            sku="LAP002",
            price=Decimal("899.99"),
            cost=Decimal("500.00"),
            category="electronics",
            status=ProductStatus.DRAFT,
        )
        self.catalog.add_product(p1)
        self.catalog.add_product(p2)

        results, total = self.catalog.search(status=ProductStatus.ACTIVE)
        assert total == 1
        assert results[0].id == "p1"

    def test_search_sorting(self) -> None:
        """Test search result sorting."""
        p1 = Product(
            id="p1",
            name="Zebra",
            sku="P001",
            price=Decimal("999.99"),
            cost=Decimal("600.00"),
            category="electronics",
        )
        p2 = Product(
            id="p2",
            name="Apple",
            sku="P002",
            price=Decimal("899.99"),
            cost=Decimal("500.00"),
            category="electronics",
        )
        self.catalog.add_product(p1)
        self.catalog.add_product(p2)

        results, _ = self.catalog.search(sort_by="name", sort_order="asc")
        assert results[0].name == "Apple"
        assert results[1].name == "Zebra"

    def test_pagination(self) -> None:
        """Test search pagination."""
        for i in range(25):
            product = Product(
                id=f"p{i}",
                name=f"Product {i}",
                sku=f"SKU{i:03d}",
                price=Decimal("99.99"),
                cost=Decimal("50.00"),
                category="electronics",
            )
            self.catalog.add_product(product)

        results, total = self.catalog.search(page=1, page_size=10)
        assert len(results) == 10
        assert total == 25

        results, total = self.catalog.search(page=2, page_size=10)
        assert len(results) == 10

        results, total = self.catalog.search(page=3, page_size=10)
        assert len(results) == 5

    def test_update_inventory(self) -> None:
        """Test updating product inventory."""
        product = Product(
            id="p1",
            name="Laptop",
            sku="LAP001",
            price=Decimal("999.99"),
            cost=Decimal("600.00"),
            category="electronics",
            inventory_count=10,
        )
        self.catalog.add_product(product)

        self.catalog.update_inventory("p1", 20)
        assert self.catalog.get_product("p1").inventory_count == 20

    def test_low_stock_alert(self) -> None:
        """Test low stock detection."""
        p1 = Product(
            id="p1",
            name="Product 1",
            sku="P001",
            price=Decimal("99.99"),
            cost=Decimal("50.00"),
            category="electronics",
            inventory_count=5,
        )
        p2 = Product(
            id="p2",
            name="Product 2",
            sku="P002",
            price=Decimal("99.99"),
            cost=Decimal("50.00"),
            category="electronics",
            inventory_count=20,
        )
        self.catalog.add_product(p1)
        self.catalog.add_product(p2)

        low_stock = self.catalog.get_low_stock_products(threshold=10)
        assert len(low_stock) == 1
        assert low_stock[0].id == "p1"

    def test_stock_value(self) -> None:
        """Test inventory valuation."""
        p1 = Product(
            id="p1",
            name="Product 1",
            sku="P001",
            price=Decimal("99.99"),
            cost=Decimal("50.00"),
            category="electronics",
            inventory_count=10,
        )
        p2 = Product(
            id="p2",
            name="Product 2",
            sku="P002",
            price=Decimal("199.99"),
            cost=Decimal("100.00"),
            category="electronics",
            inventory_count=5,
        )
        self.catalog.add_product(p1)
        self.catalog.add_product(p2)

        total_value = self.catalog.get_stock_value()
        expected = (Decimal("50.00") * 10) + (Decimal("100.00") * 5)
        assert total_value == expected
